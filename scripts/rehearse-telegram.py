#!/usr/bin/env python3
"""Rehearse Telegram commands in one disposable, fictional event."""

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wedding_ops.agent import Assistant
from wedding_ops.auth import Auth
from wedding_ops.clock import DemoClock
from wedding_ops.config import Settings
from wedding_ops.db import Database
from wedding_ops.models import Member, Notification
from wedding_ops.operations import Operations
from wedding_ops.policy import Actor
from wedding_ops.seed import DEMO_TIME, seed_demo
from wedding_ops.telegram import TelegramIngress
from wedding_ops.views import Queries


def main() -> None:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--as", dest="steps", action="append", nargs=2, required=True,
                         metavar=("MEMBER", "MESSAGE"), help="Repeat for each fictional role and command.")
    args = command.parse_args()

    with TemporaryDirectory(prefix="loveoncue-rehearsal-") as directory:
        # No deployed settings, provider tokens, or notification transport enter this rehearsal.
        config = Settings(mode="test", database_url=f"sqlite:///{directory}/rehearsal.db",
                          telegram_webhook_secret="local-telegram-rehearsal-fixture")
        db = Database(config.database_url)
        try:
            db.create_schema()
            seed_demo(db, config.wedding_id)
            clock = DemoClock(DEMO_TIME)
            auth = Auth(db, config)
            coordinator = Actor(config.wedding_id, "coordinator")
            queries = Queries(db, config.wedding_id, clock)
            operations = Operations(db, config.wedding_id, clock)
            ingress = TelegramIngress(db, config, clock, auth, Assistant(queries, operations), operations)
            with db.sessions() as session:
                members = set(session.scalars(select(Member.id).where(Member.active)))
            senders: dict[str, int] = {}
            print("Fictional local rehearsal. Replies are stored locally.")
            for number, (member, message) in enumerate(args.steps, start=1):
                if member not in members:
                    command.error("Choose a seeded fixture: " + ", ".join(sorted(members)))
                if member not in senders:
                    sender = len(senders) + 1
                    invitation = auth.issue_invite(coordinator, member)
                    auth.redeem(invitation["token"], str(sender))
                    senders[member] = sender
                sender = senders[member]
                ingress.accept(config.telegram_webhook_secret, {
                    "update_id": number,
                    "message": {"from": {"id": sender}, "chat": {"id": sender, "type": "private"}, "text": message},
                })
                ingress.process_one()
                with db.sessions() as session:
                    reply = session.scalar(select(Notification.message).where(
                        Notification.wedding_id == config.wedding_id,
                        Notification.dedupe_key == f"telegram-reply:{number}:{member}",
                    ))
                print(f"\n[{member}] {message}\n{reply or 'No bot reply queued.'}")
        finally:
            db.close()


if __name__ == "__main__":
    main()
