"""Authenticated Telegram DM ingress. One bot/token belongs to one wedding cell."""
from __future__ import annotations

import hmac
import re
from collections.abc import Callable
from datetime import timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import or_, select

from .agent import Assistant
from .auth import Auth
from .clock import Clock, parse_time
from .config import Settings
from .db import Database
from .errors import OpsError, denied
from .models import InboundUpdate, new_id
from .operations import Operations, audit, notify
from .schemas import PhotoReview
from .telegram_photo import MAX_PHOTO_BYTES, download_photo, render_photo
from .telegram_ui import NAVIGATION, acknowledged_reply, attendance_label, names_list, render_brief
from .views import row


def private_sender(sender: object, chat: object) -> str | None:
    if not isinstance(sender, dict) or not isinstance(chat, dict):
        return None
    ident = sender.get("id")
    if (type(ident) is not int or not 0 < ident <= 2**52 or sender.get("is_bot")
            or chat.get("type") != "private" or type(chat.get("id")) is not int or chat["id"] != ident):
        return None
    return str(ident)


def private_message(update: dict) -> tuple[str, str] | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    sender = private_sender(message.get("from"), message.get("chat"))
    text = message.get("text")
    if not sender or not isinstance(text, str) or not 1 <= len(text) <= 2000:
        return None
    return sender, text


def private_photo(update: dict) -> dict[str, str] | None:
    message = update.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("photo"), list):
        return None
    sender = private_sender(message.get("from"), message.get("chat"))
    if sender is None:
        return None
    caption = message.get("caption", "")
    caption = caption[:1000] if isinstance(caption, str) else ""
    for size in reversed(message["photo"]):
        if not isinstance(size, dict):
            continue
        file_id, size_bytes = size.get("file_id"), size.get("file_size")
        if (isinstance(file_id, str) and 1 <= len(file_id) <= 512
                and (size_bytes is None or type(size_bytes) is int and 0 < size_bytes <= MAX_PHOTO_BYTES)):
            return {"sender": sender, "photo_id": file_id, "caption": caption}
    return {"sender": sender, "photo_id": "", "caption": ""}


def private_callback(update: dict, token: str) -> tuple[str, str | None, str] | None:
    callback = update.get("callback_query")
    if not isinstance(callback, dict) or not isinstance(callback.get("message"), dict):
        return None
    original = callback["message"]
    sender = private_sender(callback.get("from"), original.get("chat"))
    author = original.get("from")
    callback_id, data = callback.get("id"), callback.get("data")
    bot_id = token.partition(":")[0]
    if (not sender or not isinstance(author, dict) or not author.get("is_bot")
            or (bot_id.isdecimal() and str(author.get("id")) != bot_id)
            or not isinstance(callback_id, str) or not 1 <= len(callback_id) <= 128):
        return None
    command = None
    if isinstance(data, str) and len(data) <= 64:
        confirmation = re.fullmatch(r"(confirm|ack|approve|reject|taskack):([A-Za-z0-9_-]{1,56})", data)
        command = f"/{confirmation[1]} {confirmation[2]}" if confirmation else NAVIGATION.get(data)
    return sender, command, callback_id


HELP = ("Just message me like you would a teammate. Ask what you should be doing, where something "
        "is, or when something happens. Tell me about delays or problems in your own words and I will "
        "pass them on once you confirm. Photo reviews are read-only when enabled. "
        "Reports need confirmation. "
        "Schedule changes need human approval in LoveOnCue.")


def local_time(value: str | None, zone_name: str | None) -> str:
    """Show a stored UTC time as the wedding's local HH:MM."""
    if not value:
        return "no time set"
    return parse_time(value).astimezone(ZoneInfo(zone_name or "UTC")).strftime("%H:%M")


def render_reply(result: dict) -> str:
    message = result["message"]
    zone = result.get("timezone")
    if result.get("degraded"):
        message = "Model unavailable; using deterministic commands.\n" + message
    if (result.get("draft") or {}).get("light"):
        # A question button: the reply already says what the tap sends.
        return message[:3900]
    if result.get("draft"):
        draft = result["draft"]
        note = ("\nTimeline changes still need the coordinator's approval."
                if draft.get("command_type") == "propose_delay" else "")
        if draft.get("command_type") == "change_item":
            note = ""  # The preview itself says who approves the change.
        return f"{message}\n\n{draft['summary']}\n\nTap the button below within five minutes to send it.{note}"
    for item in result.get("data", [])[:8]:
        if result["kind"] == "tasks":
            message += f"\n• {item['title']} · due {local_time(item['due_at'], zone)} · {item['state']}"
            if item.get("where"):
                message += f"\n  Where: {item['where']['name']}. {item['where']['directions']}"
            if item.get("instructions"):
                message += f"\n  What: {item['instructions']}"
            if item.get("blocked_by"):
                message += " · blocked by " + ", ".join(item["blocked_by"])
        elif result["kind"] == "schedule":
            moved = "" if item["current_start"] == item["planned_start"] else \
                f" (moved from {local_time(item['planned_start'], zone)})"
            message += f"\n• {item['title']} · {local_time(item['current_start'], zone)}{moved}"
        elif result["kind"] == "my_reports":
            note = f" — {item['note']}" if item.get("note") else ""
            message += f"\n• {item['title']}: {item['status']}{note}"
        elif result["kind"] == "guests":
            message += f"\n• {item['name']}: Table {item['table'] or 'unassigned'}; {attendance_label(item['attendance'])}"
        elif result["kind"] == "family":
            message += f"\n• {item['name']}: {attendance_label(item['attendance'])}"
        elif result["kind"] == "knowledge":
            message += f"\n\n{item['excerpt']}\nSource: {item['source']}, revision {item['revision']}, line {item['line']}"
        elif result["kind"] == "vendors":
            message += f"\n• {item['name']}: {item['contact_name']} · {item['contact_phone']}"
        else:
            message += "\n• " + str(item.get("name") or f"Table {item.get('label', '')}") + ": " + str(item.get("directions") or item.get("location_id", ""))
    return message[:3900]


def confirmation_reply(result: dict) -> str:
    """Tell the reporter what their confirmed report did, in plain words."""
    if result.get("replayed"):
        return "Already recorded\nThis report was confirmed earlier. No new change was made."
    kind = result.get("command_type")
    if kind in {"propose_delay", "change_item"} and result.get("status") == "approved":
        # Say how many were told: an approved change can reach nobody (no team affected).
        told = result.get("told", 0)
        return (f"Run sheet updated\nVersion {result['timeline_version']}. "
                + (f"{told} {'person is' if told == 1 else 'people are'} told, with an Acknowledge button."
                   if told else "Nobody else needed telling."))
    if kind in {"propose_delay", "change_item"}:
        return ("Report confirmed\nProposal awaiting approval from the coordinator. The run sheet does not change until "
                "they approve it. I will tell you their decision.")
    question = result.get("kind") == "question"
    if kind == "report_incident" and result.get("status") == "updated":
        return ("Added to your question\nThe coordinator will see it with your earlier message." if question else
                "Update added\nThe coordinator will see it with your earlier report.")
    if kind == "report_incident" and question:
        return "Question sent\nThe coordinator has your message. Their answer will come to this chat. Tap Undo to take it back."
    if kind == "report_incident" and result.get("kind") == "note":
        return "Note sent\nThe coordinator has it, for their information."
    if kind == "report_incident":
        # Say exactly who received it: the operation reports the teams it told.
        teams = result.get("teams") or []
        also = f" The {', '.join(teams)} team{'s' if len(teams) > 1 else ''} also got it." if teams else ""
        return f"Report sent\nThe coordinator has it.{also}"
    if kind == "arrival":
        # Only family arrivals are announced, and only to the roles that act on them.
        told = result.get("told") or []
        return "Arrival recorded\n" + (f"{names_list(told)} {'has' if len(told) == 1 else 'have'} been told."
                                        if told else "It is in the records. Nobody else is notified.")
    if kind == "set_deputy_enabled":
        return ("Check-ins are on. I will chase unacknowledged tasks again." if result["status"] == "on" else
                "Check-ins are paused for everyone. Helpers get the plain reminders instead.")
    if kind == "broadcast":
        count = result.get("recipients", 0)
        return (f"Message sent\n{count} {'person gets' if count == 1 else 'people get'} it with an Acknowledge "
                "button. Ask me who has not acknowledged yet.")
    if kind == "task_action":
        return "Marked done\nThe coordinator can see it."
    if kind == "withdraw_report":
        noun, told = result.get("noun", "report"), result.get("told") or []
        lines = [f"Withdrawn\nYour {noun} ({result['title']}) is taken back."]
        if result.get("coordinator_told", True):
            lines.append("The coordinator sees this in their next update.")
        if told:
            lines.append(f"{names_list(told)} {'is' if len(told) == 1 else 'are'} told to ignore it.")
        return " ".join(lines)
    return "Report confirmed."


class TelegramIngress:
    def __init__(self, db: Database, settings: Settings, clock: Clock, auth: Auth,
                 assistant: Assistant, operations: Operations, *,
                 photo_reviewer: Callable[[bytes, str], PhotoReview] | None = None,
                 photo_transport: httpx.BaseTransport | None = None):
        self.db, self.settings, self.clock, self.auth = db, settings, clock, auth
        # Set to a Deputy to answer free-form messages conversationally (ADR 0003).
        self.deputy = None
        self.assistant, self.operations, self.wid = assistant, operations, settings.wedding_id
        self.photo_reviewer = photo_reviewer
        self.photo_transport = photo_transport

    def _photo_reply(self, payload: dict) -> str:
        if self.photo_reviewer is None:
            return "Photo review is off for this event. Send a text report to record an issue or arrival."
        if not payload["photo_id"]:
            return "Photo is too large or unavailable. Send it as a smaller Telegram photo, or send a text report."
        try:
            image = download_photo(self.settings.telegram_bot_token, payload["photo_id"], self.photo_transport)
            review = self.photo_reviewer(image, payload["caption"])
            return render_photo(review)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, IndexError):
            # Exceptions from Telegram may include the bot token in a request URL.
            return "I couldn't review this photo. Send a text report for any issue or arrival."

    def _explain_denial(self, member_id: str, error: OpsError) -> str:
        """Say which role was refused and who can help, instead of a bare refusal."""
        roles, coordinators = self.assistant.queries.help_contact(member_id)
        contact = f"{' or '.join(coordinators)} (coordinator)" if coordinators else "the coordinator"
        if error.message == "Your role does not permit this action":
            return f"Your role ({', '.join(roles)}) does not permit this action. Ask {contact} if you need it."
        return f"{error.message}. Ask {contact} if you need help."

    def _deputy_command(self, actor, command: str) -> str:
        """Opt-out, the coordinator's on/off switch, and the On it button on a deputy ping."""
        if command.startswith("taskack"):
            task_id = command.split()[1]
            version = next(t["version"] for t in self.assistant.queries.snapshot(actor)["tasks"] if t["id"] == task_id)
            self.operations.execute(actor, {"type": "task_action", "task_id": task_id, "action": "acknowledge",
                                            "expected_version": version}, f"taskack:{task_id}:{version}")
            from .deputy import Heartbeat
            Heartbeat(self.db, self.wid, self.clock).record_answer(actor.member_id, "On it", acknowledged=True, task_id=task_id)
            return "Thanks, marked as acknowledged. The coordinator can see it."
        if command in {"quiet", "unquiet"}:
            self.operations.set_deputy_quiet(actor, command == "quiet")
            return ("Okay, I won't message you unprompted for the rest of the event, except urgent items. "
                    "Tell me when you want check-ins again." if command == "quiet" else "Okay, I may check in with you again.")
        enabled = command.endswith("on")
        self.operations.set_deputy_enabled(actor, enabled)
        return ("Deputy on. I will chase unacknowledged tasks and keep you posted." if enabled else
                "Paused. I will not check in with anyone; the plain reminders are back. Tell me to resume when you want.")

    def _decide(self, actor, decision: str, approval_id: str, note: str) -> str:
        """A coordinator's explicit Approve or Reject from Telegram. The model is not involved."""
        outcome = self.operations.execute(
            actor, {"type": "decide_approval", "approval_id": approval_id, "decision": decision,
                    "note": note[:1000] or f"{decision.capitalize()}d in Telegram."},
            f"telegram-decision:{approval_id}")
        if decision == "approve":
            return (f"Approved\nTimeline version {outcome['timeline_version']}. "
                    "Affected teams are being told, and the reporter knows.")
        return "Rejected\nThe run sheet is unchanged. The reporter has been told."

    def _announce(self, actor, message: str) -> tuple[str, str | None]:
        """Draft a coordinator announcement to every team. Nothing is sent until confirmed."""
        if len(message) < 3:
            return "What should I tell everyone? For example: tell everyone the ceremony moves to the ballroom.", None
        team_ids = [team["id"] for team in self.assistant.queries.snapshot(actor)["teams"]]
        draft = self.operations.draft(actor, {"type": "broadcast", "team_ids": team_ids, "message": message[:1500]},
                                      f"Send this announcement to everyone on the team:\n{message[:1500]}")
        reply = render_reply({"kind": "confirmation", "message": "Check this announcement before I send it.",
                              "draft": draft, "data": []})
        return reply, draft["id"]

    def accept(self, supplied_secret: str | None, update: dict) -> dict:
        expected = self.settings.telegram_webhook_secret
        if len(expected) < 24 or not supplied_secret or not hmac.compare_digest(expected, supplied_secret):
            raise denied("Invalid webhook authentication")
        ident = update.get("update_id")
        if type(ident) is not int or ident < 0:
            raise OpsError("invalid_update", "A numeric update_id is required")
        callback = private_callback(update, self.settings.telegram_bot_token)
        acknowledgment = None
        if callback:
            sender, text, callback_id = callback
            # Telegram can acknowledge the tap from the webhook response. Process the command durably.
            acknowledgment = {"method": "answerCallbackQuery", "callback_query_id": callback_id}
            if text is None:
                return acknowledgment
            payload = {"sender": sender, "text": text}
        else:
            message = private_message(update)
            if message:
                sender, text = message
                payload = {"sender": sender, "text": text}
            else:
                photo = private_photo(update)
                if photo is None:
                    return {"ok": True, "ignored": True}
                payload = photo
        # Persist only the fields needed by the worker.
        with self.db.transaction(self.wid, write=True) as (s, w):
            duplicate = s.scalar(select(InboundUpdate.id).where(
                InboundUpdate.wedding_id == self.wid, InboundUpdate.provider_update_id == str(ident)
            ))
            if duplicate:
                return acknowledgment or {"ok": True, "duplicate": True}
            s.add(InboundUpdate(
                wedding_id=self.wid, provider_update_id=str(ident), payload=payload,
                state="queued", attempts=0, created_at=self.clock.now(), next_attempt_at=self.clock.now(),
            ))
        return acknowledgment or {"ok": True, "queued": True}

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
        member_id, result, permission, draft_id = None, None, None, None
        chase = False  # whether the deputy may chase this person right after its reply
        try:
            text = payload.get("text", "").strip()
            match = re.fullmatch(r"/start\s+([A-Za-z0-9_-]{20,64})", text)
            if "photo_id" in payload:
                actor = self.auth.telegram_actor(payload["sender"], require_open_event=True)
                member_id = actor.member_id
                result = self._photo_reply(payload)
            elif match:
                # A crash after redemption but before acknowledgment may cause a retry.
                # Recover only the same already-linked sender; never consume a different invitation.
                try:
                    enrollment = self.auth.redeem(match[1], payload["sender"])
                    member_id = enrollment["member_id"]
                except OpsError:
                    member_id = self.auth.telegram_actor(payload["sender"]).member_id
                result = "You're in! Ask me \u201cwhat should I do?\u201d any time, or tap My tasks."
            else:
                actor = self.auth.telegram_actor(payload["sender"])
                member_id = actor.member_id
                confirmation = re.fullmatch(r"/confirm\s+([a-zA-Z0-9_-]{1,64})", text)
                if confirmation:
                    outcome = self.operations.confirm(actor, confirmation[1])
                    result = confirmation_reply(outcome)
                    if (outcome.get("kind") == "question" and outcome.get("status") == "open"
                            and not outcome.get("replayed")):
                        # A question just sent can be taken back with one tap.
                        draft_id = self.operations.draft(
                            actor, {"type": "withdraw_report", "request_id": f"draft:{confirmation[1]}"},
                            "Take back your question.", offer="undo")["id"]
                elif decision := re.fullmatch(r"/(approve|reject)\s+([A-Za-z0-9_-]{1,64})(?:\s+(.+))?", text, re.S):
                    result = self._decide(actor, decision[1], decision[2], (decision[3] or "").strip())
                elif deputy_command := re.fullmatch(r"/(quiet|unquiet|deputy\s+(?:on|off)|taskack\s+[A-Za-z0-9_-]{1,64})", text):
                    result = self._deputy_command(actor, deputy_command[1])
                elif text.startswith("/announce"):
                    result, draft_id = self._announce(actor, text[len("/announce"):].strip())
                elif re.fullmatch(r"/ack(\s+[A-Za-z0-9_-]{1,64})?", text):
                    notice = self.operations.acknowledge_latest(actor, text[len("/ack"):].strip() or None)
                    result = (acknowledged_reply(notice) if notice else
                              "Nothing to acknowledge. You have no update waiting for acknowledgement.")
                elif text in {"/brief", "/brief_more"}:
                    brief = self.assistant.queries.coordinator_brief(actor)
                    result = render_brief(brief, expanded=text == "/brief_more")
                    permission = "timeline:approve"
                elif text == "/guest":
                    self.assistant.queries.guests(actor, "")
                    result = "Find a guest\nWho are you looking for? Send me their name."
                    permission = "guests:seating"
                elif text in {"/start", "/help"}:
                    result = HELP
                else:
                    responder = self.deputy if self.deputy is not None else self.assistant
                    response = responder.ask(actor, text)
                    result = render_reply(response)
                    if response.get("draft"):
                        draft_id = response["draft"]["id"]
                    # Beside a draft, a second button would compete with the one the preview is for.
                    chase = self.deputy is not None and draft_id is None
                    permission = {"guests": "guests:seating", "family": "family:status",
                                  "knowledge": "knowledge:read"}.get(response["kind"])
            failure, retry = None, False
        except OpsError as exc:
            failure, retry = exc.code, False
            if member_id:
                result = self._explain_denial(member_id, exc) if exc.code == "forbidden" else exc.message
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
                    notify(s, self.wid, member_id, "bot_reply", result, f"telegram-reply:{provider_id}", self.clock.now(),
                           permission=permission, telegram_draft_id=draft_id)
                w.state_version += 1
                audit(s,w,"system","telegram_processed",item.id,{"status":item.state,"error_code":failure},self.clock.now())
            item.last_error, item.lease_token, item.lease_until = failure, None, None
        if chase and result and failure is None:
            # What still waits for them (an unacknowledged update, a task due) follows the reply.
            from .deputy import Heartbeat
            Heartbeat(self.db, self.wid, self.clock).run(active=member_id)
        return True
