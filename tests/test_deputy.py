"""The deputy: conversational replies grounded in the person's own context, with safe actions."""

import httpx
import pytest
from sqlalchemy import select
from test_core_loop import Chat

from wedding_ops.deputy import Deputy, DeputyPlan
from wedding_ops.models import ConversationTurn


class StubPlanner:
    """Stands in for the model. Records what it was shown and returns scripted plans."""

    def __init__(self, plans: dict[str, DeputyPlan] | None = None, fail: bool = False):
        self.plans, self.fail, self.calls = plans or {}, fail, []

    def plan(self, messages: list[dict]) -> DeputyPlan:
        self.calls.append(messages)
        if self.fail:
            raise httpx.ConnectError("model offline")
        text = messages[-1]["content"]
        return self.plans.get(text, DeputyPlan(reply="Sorry, I am not sure. Please ask Alex Morgan (coordinator)."))


@pytest.fixture
def deputy_chat(db, settings, clock, queries, ops):
    def build(planner: StubPlanner) -> Chat:
        chat = Chat(db, settings, clock, queries, ops)
        chat.ingress.deputy = Deputy(queries, ops, chat.ingress.assistant, planner, db, clock)
        return chat
    return build


def test_free_form_question_is_answered_in_the_deputys_own_words(deputy_chat):
    planner = StubPlanner({"eh wat time dinner ah": DeputyPlan(reply="Dinner service starts at 19:00 in the Cedar Ballroom.")})
    reply = deputy_chat(planner).send("usher", "eh wat time dinner ah")
    assert reply.message == "Dinner service starts at 19:00 in the Cedar Ballroom."
    context = planner.calls[0][0]["content"] + planner.calls[0][1]["content"]
    assert "Dinner service" in context and "19:00" in context


def test_a_reply_with_a_time_not_in_the_context_falls_back(deputy_chat):
    planner = StubPlanner({"when is dinner": DeputyPlan(reply="Dinner is at 21:30.")})
    reply = deputy_chat(planner).send("usher", "when is dinner").message
    assert "21:30" not in reply


def test_an_action_creates_the_usual_draft_for_the_person_to_confirm(deputy_chat, db):
    planner = StubPlanner({"kitchen jialat, dinner need 15 more min": DeputyPlan(
        reply="Got it, I will ask the coordinator to approve a 15-minute delay.", action="draft_delay",
        text="dinner", minutes=15)})
    reply = deputy_chat(planner).send("banquet", "kitchen jialat, dinner need 15 more min")
    assert reply.telegram_draft_id and "Dinner service" in reply.message
    assert reply.message.startswith("Got it")


def test_conversation_memory_carries_the_last_turns(deputy_chat):
    planner = StubPlanner()
    chat = deputy_chat(planner)
    chat.send("mc", "hi im the mc")
    chat.send("mc", "what did i just say")
    second_call = planner.calls[1]
    assert any(m["content"] == "hi im the mc" and m["role"] == "user" for m in second_call)


def test_memory_is_capped_and_expires(deputy_chat, db, clock):
    chat = deputy_chat(StubPlanner())
    for number in range(8):
        chat.send("mc", f"message {number}")
    with db.sessions() as s:
        assert len(s.scalars(select(ConversationTurn).where(ConversationTurn.member_id == "mc")).all()) <= 10
    clock.advance(13 * 60)
    chat.send("mc", "later")
    with db.sessions() as s:
        texts = [t.text for t in s.scalars(select(ConversationTurn).where(ConversationTurn.member_id == "mc"))]
    assert "message 0" not in texts and "later" in texts


def test_model_outage_falls_back_to_commands(deputy_chat):
    chat = deputy_chat(StubPlanner(fail=True))
    assert "Confirm dinner readiness" in chat.send("banquet", "/now").message
    assert chat.send("banquet", "what do i do").message  # The intent path still answers.


def test_slash_commands_do_not_go_to_the_model(deputy_chat):
    planner = StubPlanner()
    deputy_chat(planner).send("banquet", "/schedule")
    assert planner.calls == []


def test_context_respects_the_role(deputy_chat):
    planner = StubPlanner()
    chat = deputy_chat(planner)
    chat.send("usher", "anything for me")
    usher_context = " ".join(m["content"] for m in planner.calls[0])
    assert "Coordinator brief" not in usher_context
    chat.send("coordinator", "what needs attention")
    coordinator_context = " ".join(m["content"] for m in planner.calls[1])
    assert "Coordinator brief" in coordinator_context
