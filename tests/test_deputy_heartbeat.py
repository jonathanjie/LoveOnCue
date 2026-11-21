"""The deputy heartbeat: it chases task owners itself, within limits, and keeps the coordinator informed."""
from dataclasses import replace

import pytest
from sqlalchemy import select
from test_core_loop import Chat
from test_deputy import StubPlanner

from wedding_ops.deputy import Deputy
from wedding_ops.models import DeputyPing, Task
from wedding_ops.policy import Actor

WEDDING = "demo-wedding"


@pytest.fixture
def heartbeat_chat(db, settings, clock, queries, ops):
    """A chat with the deputy on. The seed's 17:50 usher task becomes overdue at 17:51."""
    def build() -> Chat:
        chat = Chat(db, replace(settings, deputy=True), clock, queries, ops)
        chat.ingress.deputy = Deputy(queries, ops, chat.ingress.assistant, StubPlanner(), db, clock)
        return chat
    return build


def tick(chat: Chat, minutes: int = 0) -> None:
    if minutes:
        chat.clock.advance(minutes)
    chat.worker.tick()


def test_an_overdue_unacknowledged_task_gets_one_friendly_ping(heartbeat_chat, db):
    chat = heartbeat_chat()
    tick(chat, 6)  # 17:51: the usher task (due 17:50) is overdue and unacknowledged.
    pings = chat.notices("usher", "deputy_ping")
    assert len(pings) == 1 and "Ballroom Entrance B" in pings[0].message
    tick(chat, 2)
    assert len(chat.notices("usher", "deputy_ping")) == 1  # One ping per task.
    assert chat.notices("usher", "task_overdue") == []  # The ping replaces the overdue notice.


def test_on_it_button_acknowledges_the_task(heartbeat_chat, db):
    chat = heartbeat_chat()
    tick(chat, 6)
    with db.sessions() as s:
        task = s.scalars(select(Task).where(Task.id == "usher-ready")).one()
    reply = chat.tap("usher", f"taskack:{task.id}")
    assert reply.message.startswith("Thanks")
    with db.sessions() as s:
        assert s.get(Task, task.id).acknowledged_at is not None
        assert s.scalars(select(DeputyPing).where(DeputyPing.recipient_id == "usher")).one().answered_at is not None


def test_a_reply_is_passed_to_the_coordinator_as_a_quoted_claim(heartbeat_chat):
    chat = heartbeat_chat()
    tick(chat, 6)
    chat.send("usher", "omw!! 2 min")
    update = chat.last("coordinator", "deputy_digest")
    assert "Jamie Lim says" in update.message and "omw!! 2 min" in update.message


def test_silence_is_escalated_to_the_coordinator_once(heartbeat_chat):
    chat = heartbeat_chat()
    tick(chat, 6)
    tick(chat, 6)
    tick(chat, 3)
    escalations = [n for n in chat.notices("coordinator", "deputy_digest") if "No reply from Jamie Lim" in n.message]
    assert len(escalations) == 1 and "Jamie Lim" in escalations[0].message
    assert chat.notices("coordinator", "task_escalation") == [] or all(
        "Jamie" not in n.message for n in chat.notices("coordinator", "task_escalation"))


def test_quiet_members_and_coordinators_are_not_pinged(heartbeat_chat, db):
    chat = heartbeat_chat()
    assert "won't message you" in chat.send("usher", "/quiet").message
    tick(chat, 6)
    assert chat.notices("usher", "deputy_ping") == []
    assert chat.notices("coordinator", "deputy_ping") == []


def test_at_most_one_unprompted_ping_per_person_per_ten_minutes(heartbeat_chat, db, ops):
    chat = heartbeat_chat()
    with db.transaction(WEDDING, write=True) as (s, _):
        # Give the usher a second overdue task.
        first = s.get(Task, "usher-ready")
        s.add(Task(id="usher-second", wedding_id=WEDDING, title="Hand out programmes", instructions="",
                   owner_id="usher", team_id=first.team_id, location_id=first.location_id,
                   timeline_item_id=first.timeline_item_id, offset_minutes=first.offset_minutes,
                   due_at=first.due_at, planned_due=first.planned_due, state="pending", version=1))
    tick(chat, 6)
    assert len(chat.notices("usher", "deputy_ping")) == 1
    tick(chat, 11)
    assert len(chat.notices("usher", "deputy_ping")) == 2


def test_coordinator_can_switch_the_deputy_off(heartbeat_chat):
    chat = heartbeat_chat()
    assert "off" in chat.send("coordinator", "/deputy off").message.lower()
    tick(chat, 6)
    assert chat.notices("usher", "deputy_ping") == []
    assert chat.notices("usher", "task_overdue")  # The plain reminders come back.
    assert "not permit" in chat.send("usher", "/deputy on").message


def test_the_brief_shows_assistant_activity(heartbeat_chat, queries):
    chat = heartbeat_chat()
    tick(chat, 6)
    brief = queries.coordinator_brief(Actor(WEDDING, "coordinator"))
    assert any(title.startswith("Assistant activity") for title, _ in brief["notes"])
