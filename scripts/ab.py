#!/usr/bin/env python3
"""Replay a gate persona's exact chat through one version of the code, for paired comparison.

    WEDDING_OPS_SRC=<src folder> ab.py --scripts S.json --key K --out OUT [--only key,key]

S.json maps "world:member" to the steps the rater took: ["send", text], ["tap", label] or
["inbox", ""]. Each script runs in a fresh stage world (scripts/replay.py: r1 for round 1; for
round 2, r2 for the coordinator, who makes the rain change, and r2-moved for everyone else).
The same steps run against each version, so two transcripts differ only by the code.

Taps keep the rater's intent, not the button's text, because versions label buttons
differently: a draft button ("Send", "Send message", ...) taps the newest draft in that
version; Acknowledge and On it tap the newest notice that has them; menu buttons tap by label.
The clock moves one minute after each message. Output per script: OUT/<key>/transcript.txt
(what the member saw, with each action button) and OUT/<key>/records.txt.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import simulate
from replay import build_stages
from sqlalchemy import select, text

from wedding_ops.models import Notification

MENU_BUTTONS = {"My tasks", "Find a guest", "Help", "Coordinator brief", "More details", "Open LoveOnCue"}
NOTICE_BUTTONS = {"Acknowledge", "On it"}


def stage_for(key: str) -> str:
    world, member = key.split(":")
    if "-r1" in world:
        return "r1"
    return "r2" if member == "coordinator" else "r2-moved"


class Script:
    def __init__(self, world: simulate.World, member: str):
        self.world, self.member = world, member
        self.zone = ZoneInfo(world.queries.snapshot(simulate.Actor(simulate.WEDDING_ID, member))["wedding"]["timezone"])
        self.lines: list[str] = []
        self.shown: set[str] = set()

    def _log_new(self) -> None:
        """Write every notification the member has not seen yet, in the order it was created."""
        with self.world.db.sessions() as s:
            rows = s.scalars(select(Notification).where(
                Notification.wedding_id == simulate.WEDDING_ID, Notification.recipient_id == self.member,
            ).order_by(text("notifications.rowid"))).all()
        for notification in rows:
            if notification.id in self.shown:
                continue
            self.shown.add(notification.id)
            at = notification.created_at.astimezone(self.zone).strftime("%H:%M")
            who = "bot" if notification.topic == "bot_reply" else f"notice ({notification.topic})"
            self.lines.append(f"[{at}] {who}: {notification.message}")
            for label in self.world.buttons(self.member, notification):
                if label not in MENU_BUTTONS:
                    self.lines.append(f"    [button: {label}]")
            self.lines.append("")

    def _callback(self, label: str) -> str | None:
        """The callback for the rater's tap in this version, or None if nothing matches."""
        with self.world.db.sessions() as s:
            rows = s.scalars(select(Notification).where(
                Notification.wedding_id == simulate.WEDDING_ID, Notification.recipient_id == self.member,
            ).order_by(text("notifications.rowid desc"))).all()
        if label not in NOTICE_BUTTONS and label not in MENU_BUTTONS:
            draft = next((n.telegram_draft_id for n in rows if n.telegram_draft_id), None)
            return f"confirm:{draft}" if draft else None
        for notification in rows:
            # buttons() also records each label's callback for this member, as simulate's tap does.
            if label in self.world.buttons(self.member, notification):
                return self.world.state["buttons"][self.member][label]
        return None

    def run(self, steps: list[list[str]]) -> None:
        self._log_new()
        for verb, argument in steps:
            if verb == "send":
                self.lines.append(f"[{self.world.clock.now().astimezone(self.zone):%H:%M}] {self.member}: {argument}")
                self.world.ingress().accept(simulate.WEBHOOK_SECRET, simulate.message_update(self.world, self.member, argument))
                self.world.run_background_work()
                self._log_new()
                with contextlib.redirect_stdout(io.StringIO()):
                    simulate.command_advance(self.world, 1)
                self._log_new()
            elif verb == "tap":
                callback = self._callback(argument)
                if callback is None:
                    continue  # this version offered nothing to tap here
                self.lines.append(f"[{self.world.clock.now().astimezone(self.zone):%H:%M}] {self.member}: "
                                  f"(taps {argument if argument in NOTICE_BUTTONS | MENU_BUTTONS else 'the draft button'})")
                sender = self.world.sender(self.member)
                self.world.ingress().accept(simulate.WEBHOOK_SECRET, {
                    "update_id": self.world.next_update_id(), "callback_query": {
                        "id": f"ab-{self.world.state['update_id']}", "data": callback, "from": {"id": sender},
                        "message": {"chat": {"id": sender, "type": "private"},
                                    "from": {"id": simulate.SIMULATED_BOT_ID, "is_bot": True}}}})
                self.world.run_background_work()
                self._log_new()


def run_script(key: str, steps: list, stage: Path, out: Path) -> str:
    folder = out / key.replace(":", "-")
    if folder.exists():
        shutil.rmtree(folder)
    shutil.copytree(stage, folder / "world")
    world = simulate.World(folder / "world")
    member = key.split(":")[1]
    try:
        script = Script(world, member)
        script.run(steps)
        (folder / "transcript.txt").write_text("\n".join(script.lines))
        records = io.StringIO()
        with contextlib.redirect_stdout(records):
            simulate.command_records(world, member)
        (folder / "records.txt").write_text(records.getvalue())
        return f"{key}: {sum(1 for v, _ in steps if v == 'send')} messages"
    except Exception as error:  # report and go on with the other scripts
        return f"{key}: ERROR {type(error).__name__}: {error}"
    finally:
        world.save()
        world.close()


def main(argv: list[str]) -> None:
    import logging
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--scripts", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.WARNING, handlers=[logging.FileHandler(args.out / "app.log")])
    logging.getLogger("httpx").setLevel(logging.ERROR)
    scripts = json.loads(args.scripts.read_text())
    only = set(filter(None, args.only.split(",")))
    chosen = {key: steps for key, steps in scripts.items() if not only or key in only}
    with contextlib.redirect_stdout(io.StringIO()):
        stages = build_stages(args.out, args.key)
    with ThreadPoolExecutor(6) as pool:
        for line in pool.map(lambda item: run_script(item[0], item[1], stages[stage_for(item[0])], args.out),
                             chosen.items()):
            print(line)


if __name__ == "__main__":
    main(sys.argv[1:])
