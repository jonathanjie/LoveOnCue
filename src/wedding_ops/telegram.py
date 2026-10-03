"""Authenticated Telegram DM ingress. One bot/token belongs to one wedding cell."""
from __future__ import annotations

import hmac
import re
from datetime import timedelta

from sqlalchemy import or_, select

from .agent import Assistant
from .auth import Auth
from .clock import Clock
from .config import Settings
from .db import Database
from .errors import OpsError, denied
from .models import InboundUpdate, new_id
from .operations import Operations, audit, notify
from .views import row


def private_message(update: dict) -> tuple[str, str] | None:
    """Reject groups, channels, edited posts, bots and spoofed sender/chat combinations."""
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    sender, chat = message.get("from", {}), message.get("chat", {})
    ident = sender.get("id")
    if (type(ident) is not int or ident <= 0 or ident > 2**52 or sender.get("is_bot")
        or chat.get("type") != "private" or chat.get("id") != ident):
        return None
    text = message.get("text")
    if not isinstance(text, str) or not 1 <= len(text) <= 2000:
        return None
    return str(ident), text


def render_reply(result: dict) -> str:
    message = result["message"]
    if result.get("degraded"):
        message = "Model unavailable; using deterministic commands.\n" + message
    if result.get("draft"):
        draft = result["draft"]
        return f"{message}\n\n{draft['summary']}\n\nTo confirm this interpretation, send:\n/confirm {draft['id']}\n\nExpires in five minutes. Timeline proposals still need coordinator approval in the application."
    for item in result.get("data", [])[:8]:
        if result["kind"] == "tasks":
            message += f"\n• {item['title']} · due {item['due_at']} · {item['state']}"
            if item.get("blocked_by"):
                message += " · blocked by " + ", ".join(item["blocked_by"])
        elif result["kind"] == "guests":
            message += f"\n• {item['name']}: Table {item['table'] or 'unassigned'}; {item['attendance']}"
        elif result["kind"] == "family":
            message += f"\n• {item['name']}: {item['attendance']}"
        elif result["kind"] == "knowledge":
            message += f"\n\n{item['excerpt']}\nSource: {item['source']}, revision {item['revision']}, line {item['line']}"
        elif result["kind"] == "vendors":
            message += f"\n• {item['name']}: {item['contact_name']} · {item['contact_phone']}"
        else:
            message += "\n• " + str(item.get("name") or f"Table {item.get('label', '')}") + ": " + str(item.get("directions") or item.get("location_id", ""))
    return message[:3900]


class TelegramIngress:
    def __init__(self, db: Database, settings: Settings, clock: Clock, auth: Auth, assistant: Assistant, operations: Operations):
        self.db, self.settings, self.clock, self.auth = db, settings, clock, auth
        self.assistant, self.operations, self.wid = assistant, operations, settings.wedding_id

    def accept(self, supplied_secret: str | None, update: dict) -> dict:
        expected = self.settings.telegram_webhook_secret
        if len(expected) < 24 or not supplied_secret or not hmac.compare_digest(expected, supplied_secret):
            raise denied("Invalid webhook authentication")
        ident = update.get("update_id")
        if type(ident) is not int or ident < 0:
            raise OpsError("invalid_update", "A numeric update_id is required")
        message = private_message(update)
        if not message:
            return {"ok": True, "ignored": True}
        # Persist only the required fields; do not retain unrelated Telegram profile metadata.
        sender, text = message
        with self.db.transaction(self.wid, write=True) as (s,w):
            duplicate = s.scalar(select(InboundUpdate.id).where(InboundUpdate.wedding_id == self.wid, InboundUpdate.provider_update_id == str(ident)))
            if duplicate:
                return {"ok": True, "duplicate": True}
            s.add(InboundUpdate(wedding_id=self.wid, provider_update_id=str(ident), payload={"sender": sender, "text": text},
                                state="queued", attempts=0, created_at=self.clock.now(), next_attempt_at=self.clock.now()))
        return {"ok": True, "queued": True}

    def process_one(self) -> bool:
        now = self.clock.now()
        with self.db.transaction(self.wid, write=True) as (s,w):
            item = s.scalar(select(InboundUpdate).where(InboundUpdate.wedding_id == self.wid,
                            or_((InboundUpdate.state == "queued") & (InboundUpdate.next_attempt_at <= now),
                                (InboundUpdate.state == "processing") & (InboundUpdate.lease_until <= now)))
                            .order_by(InboundUpdate.created_at, InboundUpdate.id).limit(1))
            if item is None:
                return False
            item.state, item.lease_token, item.lease_until = "processing", new_id(), now + timedelta(seconds=45)
            item.attempts += 1
            ident, lease, payload, provider_id = item.id, item.lease_token, item.payload, item.provider_update_id
        member_id, result, permission = None, None, None
        try:
            text = payload["text"]
            match = re.fullmatch(r"/start\s+([A-Za-z0-9_-]{20,64})", text)
            if match:
                # A crash after redemption but before acknowledgment may cause a retry.
                # Recover only the same already-linked sender; never consume a different invitation.
                try:
                    enrollment = self.auth.redeem(match[1], payload["sender"])
                    member_id = enrollment["member_id"]
                except OpsError:
                    member_id = self.auth.telegram_actor(payload["sender"]).member_id
                result = "You are enrolled in this wedding. Send /now to see your assignment or open the coordinator's Mini App link."
            else:
                actor = self.auth.telegram_actor(payload["sender"])
                member_id = actor.member_id
                confirmation = re.fullmatch(r"/confirm\s+([a-zA-Z0-9_-]{1,64})", text)
                if confirmation:
                    command_result = self.operations.confirm(actor, confirmation[1])
                    result = f"Recorded: {command_result['status']}. Timeline version {command_result['timeline_version']}."
                else:
                    response = self.assistant.ask(actor, text)
                    result = render_reply(response)
                    permission = {"guests":"guests:seating","family":"family:status","knowledge":"knowledge:read"}.get(response["kind"])
            failure, retry = None, False
        except OpsError as exc:
            failure, retry = exc.code, False
            if member_id:
                result = exc.message
        except Exception:
            failure, retry = "processing_error", True
        with self.db.transaction(self.wid, write=True) as (s,w):
            item = row(s, InboundUpdate, self.wid, ident)
            if item.lease_token != lease:
                return True
            if retry and item.attempts < 3:
                item.state, item.next_attempt_at = "queued", self.clock.now() + timedelta(seconds=15 * item.attempts)
            else:
                item.state = "done" if result is not None else "failed"
                item.payload = {}  # Minimize retention of raw messages and enrollment tokens.
                if member_id and result:
                    notify(s, self.wid, member_id, "bot_reply", result, f"telegram-reply:{provider_id}", self.clock.now(), permission=permission)
                w.state_version += 1
                audit(s,w,"system","telegram_processed",item.id,{"status":item.state,"error_code":failure},self.clock.now())
            item.last_error, item.lease_token, item.lease_until = failure, None, None
        return True
