#!/usr/bin/env python3
"""Run a persistent, fictional wedding that several simulated users share.

Each command is one action by one fixture member, as if they used the
Telegram bot. The world (database, simulated clock, who has read what) lives
in --dir, so separate processes, such as one per simulated user, can act on
the same wedding. Nothing leaves this machine except optional intent-parsing
calls to the model provider when a key file is present.

    simulate.py --dir D init                 Create the wedding and enroll everyone.
    simulate.py --dir D members              List members and their roles.
    simulate.py --dir D send --as usher "text"
    simulate.py --dir D tap --as usher "My tasks"
    simulate.py --dir D inbox --as usher     Show messages not yet read.
    simulate.py --dir D clock                Show the simulated time.
    simulate.py --dir D metrics              Fallback rate, pings, coordinator load (for the gate).
    simulate.py --dir D advance 10           Move the clock and run reminders.
    simulate.py --dir D realtime             From now on, the simulated clock runs at real speed.
    simulate.py --dir D records --as usher   The true records a rater scores against (after playing).
    simulate.py --dir D transcript --as usher   What this member saw, in order.
    simulate.py --dir D desk view            Coordinator web desk: approvals, incidents.
    simulate.py --dir D desk approve ID [--note TEXT]
    simulate.py --dir D desk reject ID [--note TEXT]
    simulate.py --dir D desk resolve INCIDENT_ID [--note TEXT]

Put a model API key in D/model.key (mode 600) to parse free-form messages with
the configured model, as staging does. Without it, only commands are parsed.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

# WEDDING_OPS_SRC runs another version of the code (scripts/ab.py compares two versions).
sys.path.insert(0, os.environ.get("WEDDING_OPS_SRC") or str(Path(__file__).resolve().parents[1] / "src"))
from wedding_ops.agent import Assistant, MistralParser
from wedding_ops.auth import Auth
from wedding_ops.clock import DemoClock, iso, parse_time
from wedding_ops.config import DEFAULT_MISTRAL_MODEL, Settings
from wedding_ops.db import Database
from wedding_ops.deputy import Deputy
from wedding_ops.models import Approval, Member, Notification, Person
from wedding_ops.operations import Operations
from wedding_ops.policy import Actor, load_access
from wedding_ops.seed import DEMO_TIME, seed_demo
from wedding_ops.telegram import TelegramIngress
from wedding_ops.telegram_ui import (
    DRAFT_BUTTONS,
    approval_markup,
    attendance_label,
    notice_markup,
    reply_markup,
)
from wedding_ops.views import Queries
from wedding_ops.worker import Worker, deputy_ping_markup, draft_type

WEDDING_ID = "demo-wedding"
COORDINATOR_ID = "coordinator"
# The callback check compares the message author with the bot ID in the token.
SIMULATED_BOT_ID = 900001
SIMULATED_BOT_TOKEN = f"{SIMULATED_BOT_ID}:simulated-token"
WEBHOOK_SECRET = "local-simulation-webhook-secret"
# Fictional Telegram user IDs start here, one per member.
FIRST_SENDER_ID = 700001
# Fictional, but written like a real contact: raters read the seeded placeholder as a defect.
SIMULATED_EMERGENCY_CONTACT = "Venue duty manager Lee, +65 6555 0142"


class World:
    """The shared wedding state in one directory. Use only inside `locked`."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.state_file = directory / "state.json"
        self.state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        key_file = directory / "model.key"
        key = key_file.read_text().strip() if key_file.exists() else ""
        self.settings = Settings(
            mode="test", database_url=f"sqlite:///{directory / 'wedding.db'}", wedding_id=WEDDING_ID,
            telegram_bot_token=SIMULATED_BOT_TOKEN, telegram_webhook_secret=WEBHOOK_SECRET,
            agent_mode="mistral" if key else "deterministic", mistral_api_key=key,
            mistral_model=DEFAULT_MISTRAL_MODEL, deputy=bool(self.state.get("deputy")) and bool(key),
        )
        self.db = Database(self.settings.database_url)
        self.clock = DemoClock(self.simulated_now())
        self.queries = Queries(self.db, WEDDING_ID, self.clock)
        self.operations = Operations(self.db, WEDDING_ID, self.clock)
        self.auth = Auth(self.db, self.settings)
        self.parser = MistralParser(self.settings) if key else None

    def simulated_now(self) -> datetime:
        """The stored time, or with `realtime`, the anchor time plus the real time since then.

        Gate raters play in real time. A clock that ticks on its own schedule drifts away from
        the time their persona states, and raters then report the clock as wrong.
        """
        anchor = self.state.get("realtime")
        if anchor:
            return parse_time(anchor["simulated"]) + (datetime.now(UTC) - parse_time(anchor["real"]))
        return parse_time(self.state["now"]) if "now" in self.state else DEMO_TIME

    def close(self) -> None:
        if self.parser is not None:
            self.parser.close()
        self.db.close()

    def save(self) -> None:
        self.state["now"] = iso(self.clock.now())
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def ingress(self) -> TelegramIngress:
        assistant = Assistant(self.queries, self.operations, self.parser)
        ingress = TelegramIngress(self.db, self.settings, self.clock, self.auth, assistant, self.operations)
        if self.parser is not None and self.state.get("deputy"):
            ingress.deputy = Deputy(self.queries, self.operations, assistant, self.parser, self.db, self.clock)
        return ingress

    def next_update_id(self) -> int:
        self.state["update_id"] = self.state.get("update_id", 0) + 1
        return self.state["update_id"]

    def log(self, member_id: str, update_id: int, text: str) -> None:
        """Keep what the member sent, by update, for `transcript`. Telegram payloads are deleted
        once processed, and the deputy's memory keeps only its last 10 turns."""
        self.state.setdefault("log", {}).setdefault(member_id, {})[str(update_id)] = text

    def sender(self, member_id: str) -> int:
        senders = self.state.get("senders", {})
        if member_id not in senders:
            raise SystemExit(f"Unknown member {member_id!r}. Choose one of: {', '.join(sorted(senders))}")
        return senders[member_id]

    def run_background_work(self) -> None:
        """Process queued Telegram updates, then reminders and deliveries."""
        ingress = self.ingress()
        while ingress.process_one():
            pass
        Worker(self.db, self.settings, self.clock).tick()

    def unread(self, member_id: str) -> list[Notification]:
        seen = set(self.state.setdefault("seen", {}).setdefault(member_id, []))
        with self.db.sessions() as s:
            rows = s.scalars(select(Notification).where(
                Notification.wedding_id == WEDDING_ID, Notification.recipient_id == member_id,
                Notification.state.in_(("sent", "simulated")),
            ).order_by(Notification.created_at, Notification.id)).all()
        fresh = [n for n in rows if n.id not in seen]
        self.state["seen"][member_id].extend(n.id for n in fresh)
        return fresh

    def buttons(self, member_id: str, notification: Notification) -> list[str]:
        """The buttons Telegram would show under this message, chosen as the worker does."""
        if notification.topic == "bot_reply":
            with self.db.transaction(WEDDING_ID) as (s, _):
                access = load_access(s, Actor(WEDDING_ID, member_id), WEDDING_ID)
                markup = reply_markup(coordinator=access.coordinator, guest_lookup=access.permits("guests:seating"),
                                      draft_id=notification.telegram_draft_id, app_url=self.settings.public_url,
                                      draft_type=draft_type(s, WEDDING_ID, notification.telegram_draft_id))
        elif notification.topic == "approval_requested":
            with self.db.sessions() as s:
                approval = s.scalar(select(Approval).where(Approval.id == notification.dedupe_key.split(":")[1]))
            if approval is None or approval.status != "pending":
                return []
            markup = approval_markup(approval.id, blocked=bool(approval.blockers))
        elif notification.topic == "deputy_ping":
            with self.db.sessions() as s:
                markup = deputy_ping_markup(s, WEDDING_ID, notification)
        else:
            markup = notice_markup(notification.topic, notification.id)
        if markup is None:
            return []
        callbacks = {b["text"]: b["callback_data"] for row in markup["inline_keyboard"] for b in row
                     if "callback_data" in b}
        # Remember them so `tap` can press a button from the newest message that has it.
        self.state.setdefault("buttons", {}).setdefault(member_id, {}).update(callbacks)
        return list(callbacks)

    def print_unread(self, member_id: str, *, quiet: bool = False) -> None:
        messages = self.unread(member_id)
        if not messages and not quiet:
            print("(no new messages)")
        for notification in messages:
            label = "bot" if notification.topic == "bot_reply" else f"notice:{notification.topic}"
            print(f"[{label}] {notification.message}")
            labels = self.buttons(member_id, notification)
            if labels:
                print("    buttons: " + " | ".join(f"[{label}]" for label in labels))


def command_init(world: World, deputy: bool = False) -> None:
    if world.state:
        raise SystemExit(f"{world.directory} already holds a wedding. Use a new --dir.")
    world.db.create_schema()
    seed_demo(world.db, WEDDING_ID)
    coordinator = Actor(WEDDING_ID, COORDINATOR_ID)
    senders = {}
    with world.db.sessions() as s:
        member_ids = sorted(s.scalars(select(Member.id).where(Member.active)))
    for offset, member_id in enumerate(member_ids):
        invitation = world.auth.issue_invite(coordinator, member_id)
        senders[member_id] = FIRST_SENDER_ID + offset
        world.auth.redeem(invitation["token"], str(senders[member_id]))
    world.operations.execute(coordinator, {"type": "set_emergency_contact", "contact": SIMULATED_EMERGENCY_CONTACT},
                             "sim-emergency-contact")
    world.state = {"senders": senders, "seen": {}, "update_id": 0, "deputy": deputy}
    print(f"Created a fictional wedding with {len(senders)} enrolled members at {iso(world.clock.now())}.")
    print("Model parsing: " + ("on" if world.parser else "off (commands only)") + ("; deputy on" if deputy else ""))


def command_members(world: World) -> None:
    with world.db.sessions() as s:
        rows = s.execute(select(Member.id, Member.roles, Person.name).join(
            Person, (Person.id == Member.person_id) & (Person.wedding_id == Member.wedding_id)
        ).where(Member.wedding_id == WEDDING_ID, Member.active).order_by(Member.id)).all()
    for member_id, roles, name in rows:
        print(f"{member_id:16} {name:24} {', '.join(roles)}")


def message_update(world: World, member_id: str, text: str) -> dict:
    sender = world.sender(member_id)
    return {"update_id": world.next_update_id(),
            "message": {"from": {"id": sender}, "chat": {"id": sender, "type": "private"}, "text": text}}


def command_send(world: World, member_id: str, text: str) -> None:
    # Messages pushed since the user last looked appear first, as they would in the chat.
    world.print_unread(member_id, quiet=True)
    update = message_update(world, member_id, text)
    world.log(member_id, update["update_id"], text)
    world.ingress().accept(WEBHOOK_SECRET, update)
    world.run_background_work()
    world.print_unread(member_id)


def command_tap(world: World, member_id: str, label: str) -> None:
    callbacks = world.state.get("buttons", {}).get(member_id, {})
    match = next((data for text, data in callbacks.items() if text.casefold() == label.strip().casefold()), None)
    if match is None:
        raise SystemExit(f"No [{label}] button on your latest message. Buttons: {', '.join(callbacks) or 'none'}")
    sender = world.sender(member_id)
    update = {"update_id": world.next_update_id(), "callback_query": {
        "id": f"sim-{world.state['update_id']}", "data": match, "from": {"id": sender},
        "message": {"chat": {"id": sender, "type": "private"}, "from": {"id": SIMULATED_BOT_ID, "is_bot": True}}}}
    world.log(member_id, update["update_id"], f"(taps {label.strip()})")
    world.print_unread(member_id, quiet=True)
    world.ingress().accept(WEBHOOK_SECRET, update)
    world.run_background_work()
    world.print_unread(member_id)


def command_advance(world: World, minutes: int) -> None:
    if not 0 < minutes <= 240:
        raise SystemExit("Advance between 1 and 240 minutes at a time.")
    world.clock = DemoClock(world.clock.now() + timedelta(minutes=minutes))
    if "realtime" in world.state:
        anchor = world.state["realtime"]
        anchor["simulated"] = iso(parse_time(anchor["simulated"]) + timedelta(minutes=minutes))
    world.queries.clock = world.operations.clock = world.clock
    world.run_background_work()
    print(f"Simulated time is now {iso(world.clock.now())}.")


def command_realtime(world: World) -> None:
    world.state["realtime"] = {"real": iso(datetime.now(UTC)), "simulated": iso(world.clock.now())}
    print(f"The simulated clock now runs at real speed from {iso(world.clock.now())}.")


def chat_turns(world: World, member_id: str) -> list[tuple[str, str]]:
    """The member's chat with the deputy as (role, text), in order. Telegram payloads are
    redacted once processed, so the deputy's short-lived conversation memory is the record."""
    from wedding_ops.models import ConversationTurn
    with world.db.sessions() as s:
        turns = s.scalars(select(ConversationTurn).where(
            ConversationTurn.wedding_id == WEDDING_ID, ConversationTurn.member_id == member_id
        ).order_by(text("conversation_turns.rowid"))).all()
    return [(turn.role, turn.text) for turn in turns]


def command_transcript(world: World, member_id: str) -> None:
    """What the member saw, in the order they saw it: each message, then its reply, and any notices."""
    turns = chat_turns(world, member_id)
    sent = world.state.get("log", {}).get(member_id, {})
    zone = ZoneInfo(world.queries.snapshot(Actor(WEDDING_ID, member_id))["wedding"]["timezone"])
    with world.db.sessions() as s:
        # Rows are numbered in the order they were written, which is the order the member saw them.
        rows = s.scalars(select(Notification).where(
            Notification.wedding_id == WEDDING_ID, Notification.recipient_id == member_id
        ).order_by(text("notifications.rowid"))).all()
    for notification in rows:
        at = notification.created_at.astimezone(zone).strftime("%H:%M")
        if notification.topic != "bot_reply":
            print(f"\n[{at}] notice ({notification.topic}): {notification.message}")
            print_action_button(world, notification)
            continue
        # A reply's key names the update it answers ("telegram-reply:<update>:<member>").
        update_id = notification.dedupe_key.split(":")[1]
        if update_id in sent:
            print(f"\n[{at}] {member_id}: {sent[update_id]}")
            print(f"[{at}] bot: {notification.message}")
            print_action_button(world, notification)
            continue
        # Worlds made before the log: a reply that starts with the deputy's next answer answers
        # the user turn just before it, when the deputy kept it. Any other reply answers a tap.
        answer = next((i for i, (role, _) in enumerate(turns) if role == "assistant"), None)
        if answer is not None and notification.message.startswith(turns[answer][1][:60]):
            message = turns[answer - 1][1] if answer and turns[answer - 1][0] == "user" else "(message not kept)"
            print(f"\n[{at}] {member_id}: {message}")
            turns = turns[answer + 1:]
        else:
            print(f"\n[{at}] {member_id}: (taps a button)")
        print(f"[{at}] bot: {notification.message}")
        print_action_button(world, notification)


def print_action_button(world: World, notification: Notification) -> None:
    """The button that acts (a draft's, Acknowledge, On it), as the member saw it. Menu buttons are left out."""
    with world.db.sessions() as s:
        if notification.topic == "bot_reply":
            kind = draft_type(s, WEDDING_ID, notification.telegram_draft_id)
            label = DRAFT_BUTTONS.get(kind, "Confirm") if notification.telegram_draft_id else None
        elif notification.topic == "deputy_ping":
            markup = deputy_ping_markup(s, WEDDING_ID, notification)
            label = markup["inline_keyboard"][0][0]["text"] if markup else None
        else:
            markup = notice_markup(notification.topic, notification.id)
            label = markup["inline_keyboard"][0][0]["text"] if markup else None
    if label:
        print(f"    [button: {label}]")


def command_records(world: World, member_id: str) -> None:
    """The records a rater checks the bot against, after the chat: run sheet, places, tasks, what reached
    the coordinator, and guests the member asked about. Raters see this only when they have finished."""
    from wedding_ops.models import Incident, Person, Task
    snapshot = world.queries.snapshot(Actor(WEDDING_ID, COORDINATOR_ID))
    zone = ZoneInfo(snapshot["wedding"]["timezone"])
    places = {place["id"]: place for place in snapshot["locations"]}
    names = {member["id"]: member["name"] for member in snapshot["members"]}

    def local(value) -> str:
        if value is None:
            return "-"
        moment = parse_time(value) if isinstance(value, str) else value
        return moment.astimezone(zone).strftime("%H:%M")

    print(f"Records at {local(snapshot['now'])}.")
    print("\nRun sheet (approved):")
    for item in snapshot["timeline"]:
        place = places.get(item["location_id"], {}).get("name", "-")
        moved = "" if item["current_start"] == item["planned_start"] else f" (planned {local(item['planned_start'])})"
        print(f"  {local(item['current_start'])} {item['title']} at {place}{moved}")
    print("\nPlaces:")
    for place in snapshot["locations"]:
        print(f"  {place['name']}: {place['directions']}")
    print(f"\nEmergency contact: {snapshot['wedding']['emergency_contact']}")
    with world.db.sessions() as s:
        tasks = s.scalars(select(Task).where(Task.wedding_id == WEDDING_ID, Task.owner_id == member_id)).all()
        incidents = s.scalars(select(Incident).where(Incident.wedding_id == WEDDING_ID)).all()
        people = s.scalars(select(Person).where(Person.wedding_id == WEDDING_ID)).all()
    guests = [p for p in people if p.is_guest]
    tables = {table["id"]: table["label"] for table in snapshot["tables"]}
    if tasks:
        print(f"\nTasks of {names[member_id]}:")
        for task in sorted(tasks, key=lambda t: t.due_at):
            seen = "acknowledged" if task.acknowledged_at else "not acknowledged"
            print(f"  due {local(task.due_at)} {task.title} ({task.state}, {seen}): {task.instructions}")
    is_coordinator = member_id == COORDINATOR_ID
    reports = [i for i in incidents if is_coordinator or i.reported_by == member_id]
    requests = [a for a in snapshot["approvals"] if is_coordinator or a["proposed_by"] == member_id]
    print("\nWhat reached the coordinator" + ("" if is_coordinator else f" from {names[member_id]}") + ":")
    teams = {team["id"]: team["name"] for team in snapshot["teams"]}
    for incident in sorted(reports, key=lambda i: i.created_at):
        shared = ", ".join(teams.get(t, t) for t in incident.audience_team_ids)
        # Raters read "also shown to: Banquet" as "only Banquet"; every item here reached the coordinator.
        audience = f"the coordinator and the {shared} team" if shared else "the coordinator only"
        print(f"  {local(incident.created_at)} {incident.severity} {incident.kind} from {names.get(incident.reported_by)}: "
              f"“{incident.title}” — {incident.status}; seen by {audience}. Details: {incident.details[:600]}")
    for request in requests:
        note = f" ({request['decision_note']})" if request.get("decision_note") else ""
        print(f"  {local(request['created_at'])} run-sheet request from {names.get(request['proposed_by'])}: "
              f"“{request['title']}” — {request['status']}{note}")
    if not reports and not requests:
        print("  nothing")
    if not is_coordinator:
        with world.db.sessions() as s:
            received = s.scalars(select(Notification).where(
                Notification.wedding_id == WEDDING_ID, Notification.recipient_id == member_id,
                Notification.topic.in_(("timeline_updated", "coordinator_message")))).all()
        if received:
            print(f"\nUpdates and messages to {names[member_id]}, and whether the coordinator sees them acknowledged:")
            for notice in sorted(received, key=lambda n: n.created_at):
                seen = f"acknowledged at {local(notice.acknowledged_at)}" if notice.acknowledged_at else "not acknowledged"
                print(f"  {local(notice.created_at)} {notice.topic} “{notice.message[:80]}”: {seen}")
    if is_coordinator:
        print("\nAcknowledgements of updates and messages (latest first):")
        with world.db.sessions() as s:
            notices = s.scalars(select(Notification).where(
                Notification.wedding_id == WEDDING_ID,
                Notification.topic.in_(("timeline_updated", "coordinator_message")))).all()
        by_key: dict[str, list[Notification]] = {}
        for notice in notices:
            by_key.setdefault(notice.dedupe_key.rsplit(":", 1)[0], []).append(notice)
        for group in sorted(by_key.values(), key=lambda g: g[0].created_at, reverse=True):
            done = [names.get(n.recipient_id, n.recipient_id) for n in group if n.acknowledged_at]
            waiting = [names.get(n.recipient_id, n.recipient_id) for n in group if not n.acknowledged_at]
            sides = ([f"acknowledged by {', '.join(done)}"] if done else []) + \
                    ([f"not acknowledged by {', '.join(waiting)}"] if waiting else [])
            print(f"  {local(group[0].created_at)} {group[0].topic} “{group[0].message[:80]}”: {'; '.join(sides)}")
    logged = world.state.get("log", {}).get(member_id, {}).values()
    words = " ".join([*logged, *(text for role, text in chat_turns(world, member_id) if role == "user")]).casefold()
    asked = [g for g in guests if g.name.casefold() in words or re.search(rf"\b{g.name.split()[0].casefold()}\b", words)]
    if asked:
        print("\nGuests named in your messages (full name or first name):")
        for guest in sorted(asked, key=lambda g: g.name)[:15]:
            table = f"Table {tables[guest.table_id]}" if guest.table_id in tables else "no table"
            print(f"  {guest.name}: {table}, {attendance_label(guest.attendance)}")
        print("Guests named only by surname or title (\"Mr Lee\") are not matched here.")
    family = [p for p in people if p.relationship and p.name.casefold() in words]
    if family:
        print("\nFamily named in your messages:")
        for person in sorted(family, key=lambda p: p.name):
            print(f"  {person.name} ({person.relationship}): {attendance_label(person.attendance)}")


def command_desk(world: World, action: str, target: str | None, note: str) -> None:
    actor = Actor(WEDDING_ID, COORDINATOR_ID)
    if action == "view":
        snapshot = world.queries.snapshot(actor)
        zone = ZoneInfo(snapshot["wedding"]["timezone"])

        def local(value: str | None) -> str:
            return parse_time(value).astimezone(zone).strftime("%H:%M") if value else "-"

        print(f"Time {local(snapshot['now'])} · timeline version {snapshot['wedding']['timeline_version']}")
        pending = [a for a in snapshot["approvals"] if a.get("status") == "pending"]
        print(f"Pending approvals: {len(pending)}")
        for approval in pending:
            print(f"  {approval['id']}  {approval.get('title')}  review by {local(approval.get('expires_at'))}")
            # The web desk shows the reason and any blockers on each approval card.
            print(f"      reason: {approval.get('reason')}")
            for blocker in approval.get("blockers") or []:
                print(f"      blocked: {blocker}")
        open_incidents = [i for i in snapshot["incidents"] if i.get("status") == "open"]
        print(f"Open incidents: {len(open_incidents)}")
        for incident in open_incidents:
            print(f"  {incident['id']}  [{incident.get('severity')}] {incident.get('title')}")
        print("Timeline:")
        for item in snapshot["timeline"]:
            # current_start holds the approved time; planned_start is the original plan.
            moved = "" if item["current_start"] == item["planned_start"] else f" (planned {local(item['planned_start'])})"
            print(f"  {local(item['current_start'])}  {item['title']}{moved}")
        return
    if not target:
        raise SystemExit(f"desk {action} needs an ID.")
    request_id = f"sim-desk-{world.next_update_id()}"
    if action in {"approve", "reject"}:
        command = {"type": "decide_approval", "approval_id": target, "decision": action, "note": note}
    else:
        command = {"type": "resolve_incident", "incident_id": target, "note": note or "Resolved by coordinator"}
    result = world.operations.execute(actor, command, request_id)
    world.run_background_work()
    print(json.dumps(result, default=str)[:1500])


def command_metrics(world: World) -> None:
    """Objective measures for the gate, computed from the database."""
    from collections import Counter

    from wedding_ops.models import Approval, DeputyPing, InboundUpdate

    with world.db.sessions() as s:
        replies = s.scalars(select(Notification).where(Notification.topic == "bot_reply")).all()
        notices = s.scalars(select(Notification).where(Notification.topic != "bot_reply")).all()
        pings = s.scalars(select(DeputyPing)).all()
        inbound = s.scalars(select(InboundUpdate)).all()
        approvals = s.scalars(select(Approval)).all()
    if not inbound:
        print("No messages yet.")
        return
    started = min(u.created_at for u in inbound)
    hours = max((world.clock.now() - started).total_seconds() / 3600, 0.25)
    # The help menu is what a person gets when nothing understood them.
    fallback = sum(r.message.startswith(("Sorry, I didn't catch that", "I didn't understand")) for r in replies)
    print(f"Messages from users: {len(inbound)} · bot replies: {len(replies)} · "
          f"fallback replies: {fallback} ({100 * fallback / max(len(replies), 1):.0f}%)")
    per_person = Counter(p.recipient_id for p in pings)
    print(f"Deputy pings: {len(pings)} · answered: {sum(p.answered_at is not None for p in pings)} · "
          f"most to one person: {max(per_person.values(), default=0)} over {hours:.2f} simulated hours")
    to_coordinator = [n for n in notices if n.recipient_id == COORDINATOR_ID]
    print(f"Unprompted notices to the coordinator: {len(to_coordinator)} ({len(to_coordinator) / hours:.1f} per hour)"
          f" · by topic: {dict(Counter(n.topic for n in to_coordinator))}")
    live = Counter(a.changes[0]["item_id"] for a in approvals if a.status == "pending" and a.changes)
    print(f"Pending proposals per item (max): {max(live.values(), default=0)}")
    claim_checks(world.directory / "app.log")


def claim_checks(log: Path) -> None:
    """Counts from the deputy's claim check (docs/plans/2026-11-22-deputy-claim-check.md)."""
    pattern = re.compile(r"Claim check: sentences=(\d+) removed=(\d+) status=(\d+) self_acts=(\d+)")
    rows = [tuple(map(int, m.groups())) for m in pattern.finditer(log.read_text())] if log.exists() else []
    if not rows:
        print("Claim check: no deputy answers logged.")
        return
    replies = len(rows)
    with_removal = sum(1 for _, removed, _, _ in rows if removed)
    print(f"Claim check over {replies} answers: sentences {sum(r[0] for r in rows)}, removed {sum(r[1] for r in rows)} "
          f"(in {with_removal} answers, {100 * with_removal / replies:.0f}%), status sentences stated by code instead "
          f"{sum(r[2] for r in rows)}, first-person acts {sum(r[3] for r in rows)} "
          f"(in {sum(1 for r in rows if r[3])} answers)")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shared fictional wedding for simulated users.")
    parser.add_argument("--dir", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--deputy", action="store_true", help="Answer free-form chat with the deputy (ADR 0003)")
    sub.add_parser("members")
    sub.add_parser("clock")
    sub.add_parser("metrics")
    sub.add_parser("realtime")
    for name in ("records", "transcript"):
        sub.add_parser(name).add_argument("--as", dest="member", required=True)
    for name in ("send", "tap"):
        action = sub.add_parser(name)
        action.add_argument("--as", dest="member", required=True)
        action.add_argument("text")
    inbox = sub.add_parser("inbox")
    inbox.add_argument("--as", dest="member", required=True)
    advance = sub.add_parser("advance")
    advance.add_argument("minutes", type=int)
    desk = sub.add_parser("desk")
    desk.add_argument("action", choices=["view", "approve", "reject", "resolve"])
    desk.add_argument("target", nargs="?")
    desk.add_argument("--note", default="")
    return parser.parse_args(argv)


def main(argv: list[str]) -> None:
    import logging
    args = parse_args(argv)
    args.dir.mkdir(parents=True, exist_ok=True)
    # Simulated users see only chat output. The app's warnings, including the claim check's
    # counts, go to a log file in the world's folder, which `metrics` reads.
    handler = logging.FileHandler(args.dir / "app.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.WARNING, handlers=[handler])
    logging.getLogger("httpx").setLevel(logging.ERROR)
    logging.getLogger("wedding_ops.deputy").setLevel(logging.INFO)  # the claim check counts
    logging.getLogger("wedding_ops.deputy.removed").setLevel(logging.DEBUG)  # why a sentence went
    # One lock per world: simulated users act one at a time, like a real queue.
    with open(args.dir / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        world = World(args.dir)
        try:
            if args.command == "init":
                command_init(world, args.deputy)
            elif args.command == "members":
                command_members(world)
            elif args.command == "metrics":
                command_metrics(world)
            elif args.command == "realtime":
                command_realtime(world)
            elif args.command == "records":
                command_records(world, args.member)
            elif args.command == "transcript":
                command_transcript(world, args.member)
            elif args.command == "clock":
                print(iso(world.clock.now()))
            elif args.command == "send":
                command_send(world, args.member, args.text)
            elif args.command == "tap":
                command_tap(world, args.member, args.text)
            elif args.command == "inbox":
                world.run_background_work()
                world.print_unread(args.member)
            elif args.command == "advance":
                command_advance(world, args.minutes)
            else:
                command_desk(world, args.action, args.target, args.note)
            world.save()
        finally:
            world.close()


if __name__ == "__main__":
    main(sys.argv[1:])
