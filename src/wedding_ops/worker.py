"""Durable outbox and reminders. Provider delivery is at-least-once, not exactly-once."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, or_, select

from .clock import Clock
from .config import Settings
from .db import Database
from .errors import OpsError
from .models import Approval, Member, Notification, Task, new_id
from .operations import audit, notify, recipients
from .policy import Actor, load_access
from .views import row, rows


@dataclass
class DeliveryError(Exception):
    code: str
    retryable: bool = True
    retry_after: int | None = None


class Transport(Protocol):
    simulated: bool
    def send(self, chat_id: str, text: str) -> str: ...


class SimulatedTransport:
    simulated = True
    def send(self, chat_id: str, text: str) -> str:
        return "simulated-not-delivered"


class TelegramTransport:
    simulated = False
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None):
        self.token, self.transport = token, transport

    def send(self, chat_id: str, text: str) -> str:
        try:
            with httpx.Client(timeout=httpx.Timeout(10, connect=3), follow_redirects=False, transport=self.transport) as client:
                response = client.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                                       json={"chat_id": chat_id, "text": text[:4000], "protect_content": True})
                try:
                    data = response.json()
                except ValueError:
                    raise DeliveryError("invalid_provider_response", retryable=response.status_code >= 500)
                code = data.get("error_code", response.status_code)
                if response.is_error or not data.get("ok"):
                    wait = data.get("parameters", {}).get("retry_after")
                    raise DeliveryError(f"telegram_{code}", retryable=code == 429 or code >= 500,
                                        retry_after=min(max(int(wait), 1), 3600) if wait is not None else None)
                return str(data["result"]["message_id"])
        except httpx.HTTPError as exc:
            # Do not persist the exception string: Telegram URLs contain the bot secret.
            raise DeliveryError("network_error", retryable=True) from exc


class Worker:
    def __init__(self, db: Database, settings: Settings, clock: Clock, transport: Transport | None = None):
        self.db, self.settings, self.wid, self.clock = db, settings, settings.wedding_id, clock
        self.transport = transport or (TelegramTransport(settings.telegram_bot_token) if settings.send_notifications else SimulatedTransport())

    def schedule(self) -> dict:
        with self.db.transaction(self.wid, write=True) as (s, w):
            if w.status != "live":
                return {"queued": 0, "expired": 0}
            now = self.clock.now()
            before_count = s.scalar(select(func.count()).select_from(Notification).where(Notification.wedding_id == self.wid))
            expired = 0
            expired_ids = []
            for task in rows(s, Task, self.wid):
                if task.state in {"done", "cancelled"} or task.acknowledged_at:
                    continue
                owner = row(s, Member, self.wid, task.owner_id)
                if not owner.active:
                    continue
                due = task.due_at.astimezone(ZoneInfo(w.timezone)).strftime("%H:%M")
                if task.due_at - timedelta(minutes=10) <= now <= task.due_at:
                    notify(s, self.wid, owner.id, "task_reminder", f"Due {due}: {task.title}. Open My tasks, review prerequisites and acknowledge the assignment.",
                           f"reminder:{task.id}:{task.version}", now, task=task)
                elif now > task.due_at:
                    notify(s, self.wid, owner.id, "task_overdue", f"Unacknowledged task due {due}: {task.title}. Confirm your status in My tasks.",
                           f"overdue:{task.id}:{task.version}", now, task=task)
                    if now >= task.due_at + timedelta(minutes=5):
                        for m in recipients(s, self.wid):
                            notify(s, self.wid, m.id, "task_escalation", f"Needs follow-up: {task.title} was due {due} and has not been acknowledged. Contact the assigned helper.",
                                   f"escalation:{task.id}:{task.version}", now, task=task)
            for proposal in rows(s, Approval, self.wid):
                if proposal.status == "pending" and proposal.expires_at <= now:
                    proposal.status = "expired"
                    expired += 1
                    expired_ids.append(proposal.id)
            s.flush()
            after_count = s.scalar(select(func.count()).select_from(Notification).where(Notification.wedding_id == self.wid))
            queued = after_count - before_count
            if expired or queued:
                w.state_version += 1
            for ident in expired_ids:
                audit(s, w, "system", "proposal_expired", ident, {}, now)
            return {"queued": queued, "expired": expired}

    def dispatch_one(self) -> bool:
        now = self.clock.now()
        with self.db.transaction(self.wid, write=True) as (s, w):
            n = s.scalar(select(Notification).where(Notification.wedding_id == self.wid,
                         or_((Notification.state == "queued") & (Notification.next_attempt_at <= now),
                             (Notification.state == "sending") & (Notification.lease_until <= now)))
                         .order_by(Notification.created_at, Notification.id).limit(1))
            if n is None:
                return False
            w.state_version += 1
            if w.status == "archived":
                n.state = "cancelled"
                return True
            try:
                a = load_access(s, Actor(self.wid, n.recipient_id, "worker"), self.wid)
                allowed = a.sees_teams(n.audience_team_ids) and (not n.required_permission or a.permits(n.required_permission))
            except OpsError:
                allowed = False
            if not allowed:
                n.state, n.last_error = "cancelled", "recipient_access_changed"
                return True
            if n.timeline_version is not None and n.timeline_version != w.timeline_version:
                n.state = "superseded"
                return True
            if n.task_id:
                task = row(s, Task, self.wid, n.task_id)
                if task.version != n.task_version or task.state in {"done", "cancelled"}:
                    n.state = "superseded"
                    return True
            member = row(s, Member, self.wid, n.recipient_id)
            if not member.telegram_user_id and not self.transport.simulated:
                n.state, n.last_error = "undeliverable", "recipient_not_enrolled_in_telegram"
                return True
            n.lease_token, n.lease_until, n.state = new_id(), now + timedelta(seconds=45), "sending"
            n.attempts += 1
            ident, lease, chat_id, message = n.id, n.lease_token, member.telegram_user_id or "demo", n.message
        # Never hold the wedding lock across a network call.
        try:
            provider_id = self.transport.send(chat_id, message)
            error = None
        except DeliveryError as exc:
            provider_id, error = None, exc
        except Exception:
            provider_id, error = None, DeliveryError("transport_error", retryable=True)
        with self.db.transaction(self.wid, write=True) as (s, w):
            notice = row(s, Notification, self.wid, ident)
            if notice.lease_token != lease:
                return True  # A reclaimed lease owns this row now.
            w.state_version += 1
            if error is None:
                notice.state = "simulated" if self.transport.simulated else "sent"
                notice.provider_message_id, notice.sent_at, notice.last_error = provider_id, self.clock.now(), None
            elif error.retryable and notice.attempts < 5:
                notice.state, notice.last_error = "queued", error.code
                delay = error.retry_after or min(300, 2 ** notice.attempts * 5)
                notice.next_attempt_at = self.clock.now() + timedelta(seconds=delay)
            else:
                notice.state, notice.last_error = "failed", error.code
            notice.lease_until, notice.lease_token = None, None
            audit(s, w, "system", "notification_delivery", notice.id,
                  {"status": notice.state, "attempts": notice.attempts, "error_code": notice.last_error}, self.clock.now())
        return True

    def tick(self, max_deliveries: int = 30) -> dict:
        result = self.schedule()
        dispatched = 0
        for _ in range(max_deliveries):
            if not self.dispatch_one():
                break
            dispatched += 1
        return {**result, "processed": dispatched, "transport": "simulated" if self.transport.simulated else "telegram"}
