"""The person, not the model, decides when to ask the coordinator (docs/plans/2026-11-22-deputy-claim-check.md).

Replay v11: the model offered the question button beside complete answers in 47 of 53 misses.
Only the person knows whether an answer was enough, so every helper reply has an Ask the
coordinator button, which sends the message that reply answered in one tap (live play v12). The model may still class a message as a question for the coordinator
(ask_coordinator), but that draws nothing: without the class, the model filed the same
questions as notes and problem reports (paired replay, 41 false full drafts in 6 runs).
"""
from sqlalchemy import select
from test_deputy import StubPlanner, deputy_chat  # noqa: F401  (fixture)

from wedding_ops.deputy import ASK_POINTER, DeputyPlan, allowed_actions
from wedding_ops.models import Incident
from wedding_ops.policy import Actor
from wedding_ops.telegram_ui import DRAFT_BUTTONS, reply_markup
from wedding_ops.worker import draft_type

WEDDING = "demo-wedding"


def labels(markup: dict) -> list[str]:
    return [button["text"] for row in markup["inline_keyboard"] for button in row]


def test_a_question_for_the_coordinator_draws_nothing(deputy_chat, queries):  # noqa: F811
    assert "ask_coordinator" in allowed_actions(queries.snapshot(Actor(WEDDING, "usher"))["me"])
    assert "ask_coordinator" not in allowed_actions(queries.snapshot(Actor(WEDDING, "coordinator"))["me"])
    text = "how to pronounce the groom's family name ah?"
    reply = deputy_chat(StubPlanner({text: DeputyPlan(answer="The records don't give the pronunciation.",
                                                      action="ask_coordinator")})).send("mc", text)
    assert reply.message == "The records don't give the pronunciation." and not reply.telegram_draft_id
    assert reply.ask_draft_id


def test_a_helpers_reply_offers_to_ask_but_never_beside_a_draft(deputy_chat, db):  # noqa: F811
    chat = deputy_chat(StubPlanner({"car flat tyre": DeputyPlan(action="tell_coordinator", level="urgent",
                                                                text="Bridal car flat tyre")}))
    helper = chat.send("usher", "where i stand")
    beside_draft = chat.send("driver", "car flat tyre")
    coordinator = chat.send("coordinator", "who never ack yet")
    with db.sessions() as s:
        assert DRAFT_BUTTONS[draft_type(s, WEDDING, helper.ask_draft_id)] == "Ask the coordinator"
    markup = reply_markup(coordinator=False, guest_lookup=False, draft_id=helper.ask_draft_id, app_url="",
                          draft_type="question")
    assert labels(markup)[0] == "Ask the coordinator"
    assert beside_draft.telegram_draft_id and not beside_draft.ask_draft_id
    assert not coordinator.ask_draft_id and not coordinator.telegram_draft_id


def test_a_complete_answer_comes_without_a_draft(deputy_chat):  # noqa: F811
    text = "sorry that was a guest lol. where i put ppl now??"
    reply = deputy_chat(StubPlanner({text: DeputyPlan(answer="Hi.")})).send("usher", text)
    assert not reply.telegram_draft_id


def test_one_tap_sends_the_message_the_reply_answered(deputy_chat, db):  # noqa: F811
    # Live play v12: the first tap only showed the message, and a second tap sent it. One player
    # read the first tap as a failure; 2 of 4 questions never arrived.
    chat = deputy_chat(StubPlanner({"how to say groom surname ah": DeputyPlan(answer="The records don't say.")}))
    reply = chat.send("mc", "how to say groom surname ah")
    sent = chat.tap("mc", f"confirm:{reply.ask_draft_id}")
    assert sent.message.startswith("Question sent: “how to say groom surname ah”\nThe coordinator has it.")
    with db.sessions() as s:
        question = s.scalars(select(Incident)).one()
    assert (question.kind, question.title, question.details) == ("question", "how to say groom surname ah",
                                                                 "how to say groom surname ah")


def test_a_tap_under_an_older_reply_sends_that_replys_message(deputy_chat, db):  # noqa: F811
    # Live play v12: a tap under the reply to "What did I miss?" offered the latest message instead.
    chat = deputy_chat(StubPlanner())
    first = chat.send("mc", "can someone cover the welcome for me")
    chat.send("mc", "what did i miss")
    chat.tap("mc", f"confirm:{first.ask_draft_id}")
    with db.sessions() as s:
        assert s.scalars(select(Incident)).one().details == "can someone cover the welcome for me"


def test_a_second_tap_sends_nothing_new(deputy_chat, db):  # noqa: F811
    chat = deputy_chat(StubPlanner())
    reply = chat.send("banquet", "plate at 7 or wait")
    chat.tap("banquet", f"confirm:{reply.ask_draft_id}")
    again = chat.tap("banquet", f"confirm:{reply.ask_draft_id}")
    assert again.message.startswith("Already sent")
    with db.sessions() as s:
        assert len(s.scalars(select(Incident)).all()) == 1


def test_the_ask_button_leaves_an_unsent_draft_waiting(deputy_chat, db):  # noqa: F811
    chat = deputy_chat(StubPlanner({"car flat tyre": DeputyPlan(action="tell_coordinator", level="urgent",
                                                                text="Bridal car flat tyre")}))
    draft = chat.send("driver", "car flat tyre").telegram_draft_id
    chat.send("driver", "where do i wait")
    assert "Report sent" in chat.tap("driver", f"confirm:{draft}").message


def test_typed_ask_sends_their_latest_message(deputy_chat, db):  # noqa: F811
    chat = deputy_chat(StubPlanner())
    chat.send("mc", "speech order how")
    assert chat.tap("mc", "nav:ask").message.startswith("Question sent")
    with db.sessions() as s:
        assert s.scalars(select(Incident)).one().details == "speech order how"


def test_the_ask_button_titles_the_question_by_the_sentence_that_asks(deputy_chat, db):  # noqa: F811
    text = "ok thanks. i stand at entrance b till seating announce then i go where"
    chat = deputy_chat(StubPlanner({text: DeputyPlan(answer="The run sheet doesn't say.")}))
    chat.tap("usher", f"confirm:{chat.send('usher', text).ask_draft_id}")
    with db.sessions() as s:
        question = s.scalars(select(Incident)).one()
    assert question.title.startswith("i stand at entrance b") and question.details == text


def test_the_ask_button_with_nothing_to_send(deputy_chat):  # noqa: F811
    reply = deputy_chat(StubPlanner()).tap("usher", "nav:ask")
    assert not reply.telegram_draft_id and "Send me your question" in reply.message


def test_the_coordinator_is_not_offered_a_question_to_themself(deputy_chat):  # noqa: F811
    chat = deputy_chat(StubPlanner())
    chat.send("coordinator", "where is the backup car")
    reply = chat.tap("coordinator", "nav:ask")
    assert not reply.telegram_draft_id and "Alex" not in reply.message


def test_a_sentence_about_a_button_the_reply_shows_stays(deputy_chat):  # noqa: F811
    # Live play v12: "got need to do anything else?" got only "I didn't make a draft for that".
    text = "wait the task say pending ah? got need to do anything else?"
    answer = "Tap Send below to tell them. Tap My tasks to see your task."
    reply = deputy_chat(StubPlanner({text: DeputyPlan(answer=answer)})).send("usher", text)
    assert reply.message == "Tap My tasks to see your task."


def test_a_note_made_only_of_questions_is_answered_without_a_draft(deputy_chat):  # noqa: F811
    text = "the coordinator got my message or not? Did you tell them already?"
    planner = StubPlanner({text: DeputyPlan(answer="I can't see that.", action="tell_coordinator", level="fyi",
                                            text="Did the coordinator get my message")})
    reply = deputy_chat(planner).send("family-liaison", text)
    assert not reply.telegram_draft_id and "for their information" not in reply.message


def test_a_task_sentence_naming_a_place_the_run_sheet_moved_away_from_is_left_out(deputy_chat, ops):  # noqa: F811
    # Replay v11: "Your task note still says garden terrace, and it hasn't been updated" led the
    # model to hedge beside a complete answer. Marked as outdated, the sentence was still repeated.
    planner = StubPlanner()
    chat = deputy_chat(planner)
    chat.send("usher", "where i put ppl now")
    assert "Direct guests to the garden terrace" in planner.records()
    ops.execute(Actor(WEDDING, "coordinator", "telegram"), {
        "type": "change_item", "item_id": "ceremony", "shift_minutes": 10, "location_id": "ballroom",
        "reason": "Rain"}, "ask-rain")
    chat.send("usher", "where i put ppl now?")
    context = planner.records()
    assert "garden terrace until seating" not in context
    assert "- Take position at Ballroom Entrance B, due 17:50" in context


def test_a_note_from_a_message_that_asks_has_no_draft_but_a_problem_does(deputy_chat):  # noqa: F811
    asking = "its raining. where do I send arriving guests"
    tyre = "car flat tyre, can someone come help?"
    chat = deputy_chat(StubPlanner({
        asking: DeputyPlan(answer="The ceremony is in Cedar Ballroom.", action="tell_coordinator", level="fyi",
                           text="Rain at registration"),
        tyre: DeputyPlan(action="tell_coordinator", level="problem", text="Bridal car flat tyre")}))
    assert not chat.send("registration-a", asking).telegram_draft_id
    assert chat.send("driver", tyre).telegram_draft_id


def test_a_problem_about_an_item_with_a_waiting_request_states_the_request(deputy_chat):  # noqa: F811
    request = "kitchen behind, dinner need 15 more min"
    again = "wah still no reply ah. the delay approved or not? should i hold the food or serve first"
    chat = deputy_chat(StubPlanner({
        request: DeputyPlan(action="run_sheet_change", text="Dinner service", minutes=15),
        again: DeputyPlan(answer="That call is the coordinator's.", action="tell_coordinator", level="problem",
                          text="Dinner service delay: approval needed")}))
    chat.tap("banquet", f"confirm:{chat.send('banquet', request).telegram_draft_id}")
    reply = chat.send("banquet", again)
    assert not reply.telegram_draft_id
    assert reply.message.count("run-sheet request \u201cDinner service: +15 minutes") == 1 and "pending" in reply.message


def test_a_follow_up_that_only_asks_states_the_report(deputy_chat):  # noqa: F811
    chat = deputy_chat(StubPlanner({
        "car flat tyre": DeputyPlan(action="tell_coordinator", level="urgent", text="Bridal car flat tyre"),
        "any update? got anybody coming?": DeputyPlan(action="tell_coordinator", level="urgent", about="R1",
                                                      text="Bridal car flat tyre")}))
    chat.tap("driver", f"confirm:{chat.send('driver', 'car flat tyre').telegram_draft_id}")
    reply = chat.send("driver", "any update? got anybody coming?")
    assert not reply.telegram_draft_id and "\u201cBridal car flat tyre\u201d: open" in reply.message


def test_a_question_for_the_coordinator_says_how_to_ask(deputy_chat):  # noqa: F811
    # Live play v12: "that's one for the coordinator" with no way named to do it.
    chat = deputy_chat(StubPlanner({
        "speech order how?": DeputyPlan(answer="", action="ask_coordinator"),
        "who covers the welcome": DeputyPlan(answer="That's one for the coordinator.", action="ask_coordinator"),
        "how to say the name": DeputyPlan(answer="The records don't say.", action="ask_coordinator")}))
    empty = chat.send("mc", "speech order how?")
    assert empty.message == "I can't confirm that from the records.\n" + ASK_POINTER and empty.ask_draft_id
    assert chat.send("mc", "who covers the welcome").message.endswith(ASK_POINTER)
    assert ASK_POINTER not in chat.send("mc", "how to say the name").message
