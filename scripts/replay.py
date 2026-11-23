#!/usr/bin/env python3
"""Replay the labelled deputy cases (scripts/replay_cases.py) and score each reply.

    replay.py --key D/model.key --out OUT [--runs 3] [--only id,id] [--workers 6]
    replay.py --score OUT/results.jsonl      Score earlier results again with the current labels.

Each case runs in a fresh copy of its stage world, so runs do not affect each other. The
model is called for real: put the provider key in a file (mode 600) and pass it with --key.
Results go to OUT/results.jsonl (one line per case and run) and a summary is printed.

What is scored, per reply:
    outcome     What the reply drafted: none, question, report, urgent, late, change, message,
                arrival, withdraw, task or control.
    ok          The outcome is one of the case's expected outcomes.
    false draft The case expects an answer only, and the reply drafted something: a full draft,
                or a question button (counted apart, since it is lighter).
    leaks       Internal action names or template lines that a person should never see.
    missing     Words from the case's `must` list that the reply does not contain.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import get_args

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_cases import CASES, Case
from simulate import (
    COORDINATOR_ID,
    WEDDING_ID,
    World,
    command_advance,
    command_init,
)
from sqlalchemy import select

from wedding_ops.deputy import DeputyAction, DeputyPlan
from wedding_ops.models import ActionDraft, Notification
from wedding_ops.policy import Actor

# Words that come from code's own vocabulary and mean nothing to a person at a wedding.
INTERNAL_NAMES = [name for name in [*get_args(DeputyAction), *DeputyPlan.model_fields] if "_" in name]
TEMPLATE_LINES = ["After that, tell me about"]

# Minutes from the seeded start (17:45) to each stage.
ROUND_TWO_MINUTES = 40


def build_stages(root: Path, key: Path) -> dict[str, Path]:
    """One world per stage, made once and copied for every case run."""
    stages = {}
    for name in ("r1", "r2", "r2-moved"):
        directory = root / "stages" / name
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
        shutil.copy(key, directory / "model.key")
        (directory / "model.key").chmod(0o600)
        world = World(directory)
        command_init(world, deputy=True)
        world.save()
        world.close()
        if name != "r1":
            world = World(directory)
            command_advance(world, ROUND_TWO_MINUTES)
            if name == "r2-moved":
                # The coordinator's rain change, as round 2 of the gate makes it: the ceremony moves
                # into the Cedar Ballroom and starts 10 minutes late. A coordinator's change applies now.
                world.operations.execute(Actor(WEDDING_ID, COORDINATOR_ID, "telegram"), {
                    "type": "change_item", "item_id": "ceremony", "shift_minutes": 10, "location_id": "ballroom",
                    "reason": "Rain: the ceremony moves inside."}, "replay-rain-move")
                command_advance(world, 2)
            world.save()
            world.close()
        stages[name] = directory
    return stages


def outcome_of(command: dict | None) -> str:
    """The kind of draft a reply offers, in the labels' vocabulary."""
    if command is None:
        return "none"
    kind = command["type"]
    if kind == "report_incident":
        if command.get("kind") == "question":
            return "question"
        if command.get("severity") == "urgent":
            return "urgent"
        title = command.get("title", "").casefold()
        return "late" if "running" in title and "late" in title else "report"
    return {"propose_delay": "change", "change_item": "change", "broadcast": "message", "arrival": "arrival",
            "withdraw_report": "withdraw", "task_action": "task", "set_deputy_enabled": "control"}.get(kind, kind)


class Chat:
    """One member's chat in a replay world: send, tap the latest draft, read the replies."""

    def __init__(self, world: World):
        self.world = world
        self.drafts: dict[str, str] = {}

    def _replies(self, member: str) -> list[Notification]:
        fresh = self.world.unread(member)
        for notification in fresh:
            if notification.topic == "bot_reply" and notification.telegram_draft_id:
                self.drafts[member] = notification.telegram_draft_id
        return [n for n in fresh if n.topic == "bot_reply"]

    def send(self, member: str, text: str) -> list[Notification]:
        from simulate import WEBHOOK_SECRET, message_update
        self.world.unread(member)  # what arrived before this message is not part of its reply
        self.drafts.pop(member, None)
        self.world.ingress().accept(WEBHOOK_SECRET, message_update(self.world, member, text))
        self.world.run_background_work()
        return self._replies(member)

    def confirm(self, member: str) -> bool:
        from simulate import SIMULATED_BOT_ID, WEBHOOK_SECRET
        draft_id = self.drafts.get(member)
        if draft_id is None:
            return False
        sender = self.world.sender(member)
        self.world.ingress().accept(WEBHOOK_SECRET, {
            "update_id": self.world.next_update_id(), "callback_query": {
                "id": f"replay-{self.world.state['update_id']}", "data": f"confirm:{draft_id}", "from": {"id": sender},
                "message": {"chat": {"id": sender, "type": "private"}, "from": {"id": SIMULATED_BOT_ID, "is_bot": True}}}})
        self.world.run_background_work()
        self._replies(member)
        return True

    def command(self, draft_id: str | None) -> dict | None:
        if not draft_id:
            return None
        with self.world.db.sessions() as s:
            draft = s.scalar(select(ActionDraft).where(ActionDraft.wedding_id == WEDDING_ID, ActionDraft.id == draft_id))
        return draft.command if draft else None


def run_case(case: Case, run: int, stage: Path, root: Path) -> dict:
    directory = root / "runs" / f"{case.id}-{run}"
    if directory.exists():
        shutil.rmtree(directory)
    shutil.copytree(stage, directory)
    world = World(directory)
    result = {"case": case.id, "run": run, "member": case.member, "text": case.text, "expect": sorted(case.expect)}
    try:
        chat = Chat(world)
        for step in case.before:
            if len(step) == 3:
                if not chat.confirm(step[0]):
                    result["setup_failed"] = f"no draft to confirm after {step[0]}'s message"
                    return result
            else:
                chat.send(*step)
        replies = chat.send(case.member, case.text)
        reply = "\n\n".join(n.message for n in replies)
        draft_id = next((n.telegram_draft_id for n in replies if n.telegram_draft_id), None)
        outcome = outcome_of(chat.command(draft_id))
        result |= {
            "reply": reply, "outcome": outcome,
            "ok": outcome in case.expect or (outcome == "none" and "answer" in case.expect),
            "false_draft": case.expect == {"answer"} and outcome != "none",
            "leaks": [word for word in INTERNAL_NAMES + TEMPLATE_LINES if word.casefold() in reply.casefold()],
            "missing": [word for word in case.must if word.casefold() not in reply.casefold()],
        }
    except Exception as error:  # a crash is a result to report, not a reason to stop the other cases
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        world.save()
        world.close()
    return result


def rescore(result: dict) -> dict:
    """A stored result judged against the current label of its case."""
    case = next((c for c in CASES if c.id == result["case"]), None)
    if case is None or "outcome" not in result:
        return result
    outcome = result["outcome"]
    return result | {"expect": sorted(case.expect),
                     "ok": outcome in case.expect or (outcome == "none" and "answer" in case.expect),
                     "false_draft": case.expect == {"answer"} and outcome != "none",
                     "missing": [word for word in case.must if word.casefold() not in result["reply"].casefold()]}


def summarise(results: list[dict]) -> None:
    scored = [r for r in results if "outcome" in r]
    failed = [r for r in results if "outcome" not in r]
    answer_only = [r for r in scored if r["expect"] == ["answer"]]
    question_cases = [r for r in scored if "question" in r["expect"]]
    print(f"Replies scored: {len(scored)} · setup failures or errors: {len(failed)}")
    print(f"Outcome matches the label: {sum(r['ok'] for r in scored)} of {len(scored)}")
    full = sum(r["false_draft"] and r["outcome"] != "question" for r in answer_only)
    buttons = sum(r["false_draft"] and r["outcome"] == "question" for r in answer_only)
    print(f"False drafts in {len(answer_only)} answer-only replies: {full} full drafts, {buttons} question buttons")
    print(f"Question cases that drafted a question: {sum(r['outcome'] == 'question' for r in question_cases)} of "
          f"{len(question_cases)}")
    print(f"Replies with internal names or template lines: {sum(bool(r['leaks']) for r in scored)}")
    print(f"Replies missing a required fact: {sum(bool(r['missing']) for r in scored)}")
    by_case = defaultdict(list)
    for r in scored:
        by_case[r["case"]].append(r)
    print("\nCases with a wrong outcome in any run (case: outcomes per run):")
    for case_id, runs in by_case.items():
        if not all(r["ok"] for r in runs):
            print(f"  {case_id}: {', '.join(r['outcome'] for r in runs)} (expected {'|'.join(runs[0]['expect'])})")
    for r in failed:
        print(f"  {r['case']} run {r['run']}: {r.get('setup_failed') or r.get('error')}")
    print("\nOutcomes: " + ", ".join(f"{k} {v}" for k, v in Counter(r["outcome"] for r in scored).most_common()))


def main(argv: list[str]) -> None:
    import logging
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--key", type=Path, help="File with the model provider key (mode 600)")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--score", type=Path, help="Score an earlier results file with the current labels")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--only", default="", help="Comma-separated case IDs")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    if args.score:
        summarise([rescore(json.loads(line)) for line in args.score.read_text().splitlines()])
        return
    if not (args.key and args.out):
        parser.error("--key and --out are needed to run the cases")
    args.out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.WARNING, handlers=[logging.FileHandler(args.out / "app.log")])
    logging.getLogger("httpx").setLevel(logging.ERROR)
    logging.getLogger("wedding_ops.deputy").setLevel(logging.INFO)
    only = set(filter(None, args.only.split(",")))
    cases = [c for c in CASES if not only or c.id in only]
    stages = build_stages(args.out, args.key)
    jobs = [(case, run) for run in range(args.runs) for case in cases]
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda job: run_case(job[0], job[1], stages[job[0].stage], args.out), jobs))
    with open(args.out / "results.jsonl", "w") as handle:
        handle.writelines(json.dumps(result, ensure_ascii=False) + "\n" for result in results)
    summarise(results)


if __name__ == "__main__":
    main(sys.argv[1:])
