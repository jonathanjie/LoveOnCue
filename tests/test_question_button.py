"""The question button and the code-written lines around it (docs/plans/2026-11-22-deputy-claim-check.md).

When only the coordinator can answer a helper, the model chooses ask_coordinator. Code decides
whether to offer one button that sends the person's own message to the coordinator.
"""
from sqlalchemy import select
from test_deputy import StubPlanner, deputy_chat  # noqa: F401  (fixture)

from wedding_ops.deputy import QUESTION_CAP, DeputyPlan
from wedding_ops.models import Incident
from wedding_ops.policy import Actor
from wedding_ops.telegram_ui import DRAFT_BUTTONS, acknowledged_reply
from wedding_ops.worker import draft_type

WEDDING = "demo-wedding"
UNKNOWN = DeputyPlan(answer="The records don't say.", action="ask_coordinator")


def button(db, reply) -> str:
    with db.sessions() as s:
        return DRAFT_BUTTONS[draft_type(s, WEDDING, reply.telegram_draft_id)]


def test_the_button_sends_the_persons_own_message_and_can_be_undone(deputy_chat, db):  # noqa: F811
    chat = deputy_chat(StubPlanner({"how to say groom surname ah": UNKNOWN}))
    reply = chat.send("mc", "how to say groom surname ah")
    assert button(db, reply) == "Ask the coordinator"
    sent = chat.tap("mc", f"confirm:{reply.telegram_draft_id}")
    assert sent.message.startswith("Question sent\nThe coordinator has your message.")
    with db.sessions() as s:
        question = s.scalars(select(Incident)).one()
    assert (question.kind, question.title, question.details) == ("question", "how to say groom surname ah",
                                                                 "how to say groom surname ah")
    assert button(db, sent) == "Undo"
    chat.tap("mc", f"confirm:{sent.telegram_draft_id}")
    with db.sessions() as s:
        assert s.scalars(select(Incident)).one().status == "resolved"


def test_each_tap_asks_a_new_question_until_the_persons_limit(deputy_chat, db):  # noqa: F811
    from wedding_ops.deputy import QUESTIONS_PER_PERSON
    asks = [f"question {number}?" for number in range(QUESTIONS_PER_PERSON + 1)]
    chat = deputy_chat(StubPlanner({text: UNKNOWN for text in asks}))
    for text in asks[:-1]:
        reply = chat.send("mc", text)
        # Code cannot tell whether two messages are about the same thing, so each is its own question.
        assert button(db, reply) == "Ask the coordinator"
        chat.tap("mc", f"confirm:{reply.telegram_draft_id}")
    reply = chat.send("mc", asks[-1])
    assert button(db, reply) == "Add to my question" and f"You have {QUESTIONS_PER_PERSON} questions open" in reply.message
    chat.tap("mc", f"confirm:{reply.telegram_draft_id}")
    with db.sessions() as s:
        questions = s.scalars(select(Incident).order_by(Incident.created_at)).all()
    assert len(questions) == QUESTIONS_PER_PERSON and questions[-1].details.endswith(f": {asks[-1]}")


def test_a_question_is_never_filed_under_an_open_report(deputy_chat, db):  # noqa: F811
    chat = deputy_chat(StubPlanner({"car flat tyre": DeputyPlan(action="tell_coordinator", level="urgent",
                                                                text="Bridal car flat tyre"),
                                    "bride need the car or not?": UNKNOWN}))
    chat.tap("driver", f"confirm:{chat.send('driver', 'car flat tyre').telegram_draft_id}")
    reply = chat.send("driver", "bride need the car or not?")
    assert button(db, reply) == "Ask the coordinator"


def test_the_next_message_makes_the_button_stale(deputy_chat, db):  # noqa: F811
    chat = deputy_chat(StubPlanner({"speech order how": UNKNOWN}))
    stale = chat.send("mc", "speech order how")
    chat.send("mc", "never mind")
    late = chat.tap("mc", f"confirm:{stale.telegram_draft_id}")
    assert "expired" in late.message
    with db.sessions() as s:
        assert s.scalars(select(Incident)).all() == []


def test_no_button_for_the_coordinator_or_over_a_waiting_draft(deputy_chat):  # noqa: F811
    chat = deputy_chat(StubPlanner({
        "where is the backup car": UNKNOWN,
        "mic spoil": DeputyPlan(action="tell_coordinator", text="Mic broken"),
        "and the brief where": UNKNOWN,
    }))
    assert not chat.send("coordinator", "where is the backup car").telegram_draft_id
    report = chat.send("mc", "mic spoil")
    reply = chat.send("mc", "and the brief where")
    # The waiting report keeps its button; a question button would have replaced it.
    assert not reply.telegram_draft_id and "Your earlier draft is still unsent" in reply.message
    assert report.telegram_draft_id


def test_past_the_cap_no_button_is_offered(deputy_chat, ops):  # noqa: F811
    for number in range(QUESTION_CAP):
        ops.execute(Actor(WEDDING, "usher"), {"type": "report_incident", "kind": "question",
                                              "title": f"Question {number}", "details": "x"}, f"q-{number}")
    reply = deputy_chat(StubPlanner({"speech order how": UNKNOWN})).send("mc", "speech order how")
    assert not reply.telegram_draft_id and "many open questions" in reply.message


def test_the_coordinators_context_names_the_people_they_can_message(deputy_chat):  # noqa: F811
    planner = StubPlanner({"tell asha speeches stay after dinner": DeputyPlan(
        action="send_message", to="Asha", message="Speeches stay after dinner.")})
    chat = deputy_chat(planner)
    draft = chat.send("coordinator", "tell asha speeches stay after dinner")
    context = planner.calls[-1][1]["content"]
    assert "[record] People you can message" in context and "- Asha Tan: couple" in context
    assert "Message to Asha Tan" in draft.message


def test_after_the_tap_the_reply_names_who_got_the_report(deputy_chat):  # noqa: F811
    chat = deputy_chat(StubPlanner({"car flat tyre": DeputyPlan(action="tell_coordinator", text="Bridal car flat tyre"),
                                    "fyi photographer here": DeputyPlan(action="tell_coordinator", level="fyi",
                                                                       text="Photographer arrived")}))
    sent = chat.tap("driver", f"confirm:{chat.send('driver', 'car flat tyre').telegram_draft_id}")
    assert sent.message == "Report sent\nThe coordinator has it."  # the driver is alone in Transport
    note = chat.tap("usher", f"confirm:{chat.send('usher', 'fyi photographer here').telegram_draft_id}")
    assert note.message == "Note sent\nThe coordinator has it, for their information."


def test_an_acknowledgement_names_the_update_without_cutting_a_word():
    notice = ("Message from Alex Morgan:\nDinner is not confirmed yet, so don't stall guests yet. "
              "I'll update you in 5 minutes. Speech order is per the brief.")
    reply = acknowledged_reply(notice)
    assert reply.startswith("Acknowledged\nThe coordinator can see that you saw: “Dinner is not confirmed yet")
    assert reply.endswith("…”") and "Speech o”" not in reply


def test_a_new_report_keeps_the_words_of_the_unsent_one_it_replaces(deputy_chat, db):  # noqa: F811
    planner = StubPlanner({"BRIDAL CAR FLAT TYRE IN CAR PARK": DeputyPlan(action="tell_coordinator", level="urgent",
                                                                         text="Bridal car flat tyre"),
                           "car cannot move": DeputyPlan(action="tell_coordinator", level="urgent",
                                                         text="Bridal car cannot move")})
    chat = deputy_chat(planner)
    chat.send("driver", "BRIDAL CAR FLAT TYRE IN CAR PARK")
    draft = chat.send("driver", "car cannot move")
    assert "Your words:\n\u201cBRIDAL CAR FLAT TYRE IN CAR PARK\u201d\n\u201ccar cannot move\u201d" in draft.message
    chat.tap("driver", f"confirm:{draft.telegram_draft_id}")
    with db.sessions() as s:
        assert s.scalars(select(Incident)).one().details == "BRIDAL CAR FLAT TYRE IN CAR PARK\ncar cannot move"


def test_a_question_never_marks_a_task_done(deputy_chat):  # noqa: F811
    planner = StubPlanner({"what am i supposed to do now ah?": DeputyPlan(action="complete_task", text="route")})
    assert not deputy_chat(planner).send("driver", "what am i supposed to do now ah?").telegram_draft_id
