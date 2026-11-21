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
    simulate.py --dir D advance 10           Move the clock and run reminders.
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
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wedding_ops.agent import Assistant, MistralParser
from wedding_ops.auth import Auth
from wedding_ops.clock import DemoClock, iso, parse_time
from wedding_ops.config import DEFAULT_MISTRAL_MODEL, Settings
from wedding_ops.db import Database
from wedding_ops.models import Member, Notification, Person
from wedding_ops.operations import Operations
from wedding_ops.policy import Actor, load_access
from wedding_ops.seed import DEMO_TIME, seed_demo
from wedding_ops.telegram import TelegramIngress
from wedding_ops.telegram_ui import reply_markup
from wedding_ops.views import Queries
from wedding_ops.worker import Worker

WEDDING_ID = "demo-wedding"
COORDINATOR_ID = "coordinator"
# The callback check compares the message author with the bot ID in the token.
SIMULATED_BOT_ID = 900001
SIMULATED_BOT_TOKEN = f"{SIMULATED_BOT_ID}:simulated-token"
WEBHOOK_SECRET = "local-simulation-webhook-secret"
# Fictional Telegram user IDs start here, one per member.
FIRST_SENDER_ID = 700001


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
            mistral_model=DEFAULT_MISTRAL_MODEL,
        )
        self.db = Database(self.settings.database_url)
        self.clock = DemoClock(parse_time(self.state["now"]) if "now" in self.state else DEMO_TIME)
        self.queries = Queries(self.db, WEDDING_ID, self.clock)
        self.operations = Operations(self.db, WEDDING_ID, self.clock)
        self.auth = Auth(self.db, self.settings)
        self.parser = MistralParser(self.settings) if key else None

    def close(self) -> None:
        if self.parser is not None:
            self.parser.close()
        self.db.close()

    def save(self) -> None:
        self.state["now"] = iso(self.clock.now())
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def ingress(self) -> TelegramIngress:
        assistant = Assistant(self.queries, self.operations, self.parser)
        return TelegramIngress(self.db, self.settings, self.clock, self.auth, assistant, self.operations)

    def next_update_id(self) -> int:
        self.state["update_id"] = self.state.get("update_id", 0) + 1
        return self.state["update_id"]

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
        if notification.topic != "bot_reply":
            return []
        with self.db.transaction(WEDDING_ID) as (s, _):
            access = load_access(s, Actor(WEDDING_ID, member_id), WEDDING_ID)
            markup = reply_markup(coordinator=access.coordinator, guest_lookup=access.permits("guests:seating"),
                                  draft_id=notification.telegram_draft_id, app_url=self.settings.public_url)
        # Store the callback data so `tap` can press a button from the latest message.
        callbacks = {b["text"]: b["callback_data"] for row in markup["inline_keyboard"] for b in row
                     if "callback_data" in b}
        self.state.setdefault("buttons", {})[member_id] = callbacks
        return list(callbacks)

    def print_unread(self, member_id: str) -> None:
        messages = self.unread(member_id)
        if not messages:
            print("(no new messages)")
        for notification in messages:
            label = "bot" if notification.topic == "bot_reply" else f"notice:{notification.topic}"
            print(f"[{label}] {notification.message}")
            labels = self.buttons(member_id, notification)
            if labels:
                print("    buttons: " + " | ".join(f"[{label}]" for label in labels))


def command_init(world: World) -> None:
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
    world.state = {"senders": senders, "seen": {}, "update_id": 0}
    print(f"Created a fictional wedding with {len(senders)} enrolled members at {iso(world.clock.now())}.")
    print("Model parsing: " + ("on" if world.parser else "off (commands only)"))


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
    world.unread(member_id)  # Older messages count as read once the user writes again.
    world.ingress().accept(WEBHOOK_SECRET, message_update(world, member_id, text))
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
    world.unread(member_id)
    world.ingress().accept(WEBHOOK_SECRET, update)
    world.run_background_work()
    world.print_unread(member_id)


def command_advance(world: World, minutes: int) -> None:
    if not 0 < minutes <= 240:
        raise SystemExit("Advance between 1 and 240 minutes at a time.")
    world.clock = DemoClock(world.clock.now() + timedelta(minutes=minutes))
    world.queries.clock = world.operations.clock = world.clock
    world.run_background_work()
    print(f"Simulated time is now {iso(world.clock.now())}.")


def command_desk(world: World, action: str, target: str | None, note: str) -> None:
    actor = Actor(WEDDING_ID, COORDINATOR_ID)
    if action == "view":
        snapshot = world.queries.snapshot(actor)
        print(f"Time {snapshot['now']} · timeline version {snapshot['wedding']['timeline_version']}")
        pending = [a for a in snapshot["approvals"] if a.get("status") == "pending"]
        print(f"Pending approvals: {len(pending)}")
        for approval in pending:
            print(f"  {approval['id']}  {approval.get('title')}  expires {approval.get('expires_at')}")
            # The web desk shows the reason on each approval card.
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
            moved = "" if item.get("current_start") == item.get("planned_start") else f" (planned {item.get('planned_start')})"
            print(f"  {item.get('current_start')}  {item['title']}{moved}")
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shared fictional wedding for simulated users.")
    parser.add_argument("--dir", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("members")
    sub.add_parser("clock")
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
    args = parse_args(argv)
    args.dir.mkdir(parents=True, exist_ok=True)
    # One lock per world: simulated users act one at a time, like a real queue.
    with open(args.dir / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        world = World(args.dir)
        try:
            if args.command == "init":
                command_init(world)
            elif args.command == "members":
                command_members(world)
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
