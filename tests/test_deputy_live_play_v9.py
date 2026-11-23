"""Fixes for the causes found in live play v9 (docs/plans/2026-11-22-deputy-claim-check.md)."""
from sqlalchemy import select
from test_deputy import StubPlanner, deputy_chat  # noqa: F401  (fixture)

from wedding_ops.deputy import DeputyPlan
from wedding_ops.models import Incident
from wedding_ops.policy import Actor

WEDDING = "demo-wedding"


def test_acknowledge_is_offered_only_for_a_confirmation(deputy_chat):  # noqa: F811
    planner = StubPlanner()
    chat = deputy_chat(planner)
    chat.send("driver", "help car spoil!!")
    assert "acknowledge" not in planner.actions[-1]  # before: it acknowledged the driver's task
    chat.send("driver", "ok noted")
    assert "acknowledge" in planner.actions[-1]


def test_the_time_is_said_once(deputy_chat):  # noqa: F811
    planner = StubPlanner({"what time now": DeputyPlan(answer="It's 17:45 now, so dinner is in over an hour.",
                                                       say_time=True)})
    reply = deputy_chat(planner).send("usher", "what time now")
    assert reply.message.count("17:45") == 1


def test_a_question_title_skips_a_leading_confirmation(deputy_chat, db):  # noqa: F811
    text = "ok thanks. i stand at entrance b till seating announce then i go where"
    chat = deputy_chat(StubPlanner({text: DeputyPlan(answer="The run sheet doesn't say.")}))
    chat.send("usher", text)
    chat.tap("usher", f"confirm:{chat.tap('usher', 'nav:ask').telegram_draft_id}")
    with db.sessions() as s:
        question = s.scalars(select(Incident)).one()
    assert question.title.startswith("i stand at entrance b") and question.details == text


def test_only_roles_that_look_up_seats_are_offered_the_lookup(deputy_chat):  # noqa: F811
    planner = StubPlanner()
    chat = deputy_chat(planner)
    chat.send("family-liaison", "are the parents here")
    assert planner.lookups is False and "cannot look up guest seats" in planner.calls[-1][1]["content"]
    chat.send("usher", "where amelia tan sit")
    assert planner.lookups is True and "can look up guest seats" in planner.calls[-1][1]["content"]


def test_a_reply_from_before_a_run_sheet_change_is_marked(deputy_chat, ops):  # noqa: F811
    planner = StubPlanner({"where is the ceremony": DeputyPlan(answer="The garden ceremony is at 18:30.")})
    chat = deputy_chat(planner)
    chat.send("usher", "where is the ceremony")
    ops.execute(Actor(WEDDING, "coordinator", "telegram"), {
        "type": "change_item", "item_id": "ceremony", "shift_minutes": 10, "location_id": "ballroom",
        "reason": "Rain"}, "v9-rain")
    chat.send("usher", "where is the ceremony")
    earlier = [m["content"] for m in planner.calls[-1] if m["role"] == "assistant"]
    assert "written before the run sheet changed" in earlier[-1]


def test_a_decision_stated_as_a_predicate_is_removed(deputy_chat):  # noqa: F811
    planner = StubPlanner({"approved or not": DeputyPlan(
        answer="The run sheet still shows dinner service at 19:00, so tell the kitchen it's not approved.")})
    reply = deputy_chat(planner).send("banquet", "approved or not")
    assert "not approved" not in reply.message


def test_a_task_is_marked_done_only_when_the_person_says_so(deputy_chat):  # noqa: F811
    from wedding_ops.claims import asks
    assert asks("ok got it. where's the Acknowledge thing") and asks("so the ceremony is inside now right")
    assert not asks("ok noted ah") and not asks("ok all right")
    got_it = "ok got it 👍 cedar ballroom. wait so the ceremony is inside now right"
    planner = StubPlanner({got_it: DeputyPlan(action="complete_task", text="position"),
                           "entrance b done": DeputyPlan(action="complete_task", text="position")})
    chat = deputy_chat(planner)
    # Replay v9: with no acknowledge to choose, the model drafted "Mark your task done" for this.
    assert not chat.send("usher", got_it).telegram_draft_id
    assert "Mark your task done" in chat.send("usher", "entrance b done").message


# Live play v10 ---------------------------------------------------------------------------------------

def test_an_earlier_time_supports_only_a_sentence_about_the_change():
    from wedding_ops.claims import Support, check_answer
    support = Support("- 19:10 Dinner service at Cedar Ballroom (moved from 19:00).\n"
                      "- [record] • Dinner service 18:50 → 19:00\n- [record] • Dinner service 19:00 → 19:10", set())
    assert support.missing("Dinner service is still 19:00.", set()) == ["19:00"]
    assert support.missing("Dinner moved from 19:00 to 19:10.", set()) == []
    assert support.missing("Dinner was at 18:50.", set()) == []
    # A sentence split by a line break is checked whole, so no half of it is left.
    assert check_answer("I don't have a seat listed for\n“auntie sarah” at 21:30.", support, set()).text == ""


def test_a_lateness_report_needs_the_person_to_say_late(deputy_chat):  # noqa: F811
    planner = StubPlanner({"not yet lol going there now": DeputyPlan(action="report_late"),
                           "stuck in jam, 20 min late": DeputyPlan(action="report_late", minutes=20)})
    chat = deputy_chat(planner)
    assert not chat.send("usher", "not yet lol going there now").telegram_draft_id
    assert chat.send("usher", "stuck in jam, 20 min late").telegram_draft_id


def test_a_question_title_is_the_sentence_that_asks(deputy_chat, db):  # noqa: F811
    text = "Ok, saw the coordinator's message. Who is covering the welcome speech?"
    chat = deputy_chat(StubPlanner({text: DeputyPlan(answer="The records don't say.")}))
    chat.send("mc", text)
    chat.tap("mc", f"confirm:{chat.tap('mc', 'nav:ask').telegram_draft_id}")
    with db.sessions() as s:
        assert s.scalars(select(Incident)).one().title.startswith("Who is covering the welcome")


def test_a_replaced_draft_and_a_left_out_person_are_named(deputy_chat):  # noqa: F811
    both = "tell Chris: delay approved. tell Taylor: announce at 7.15"
    chat = deputy_chat(StubPlanner({
        "tell asha speeches stay after dinner": DeputyPlan(action="send_message", to="Asha",
                                                           message="Speeches stay after dinner."),
        both: DeputyPlan(action="send_message", to="Chris", message="Delay approved.")}))
    chat.send("coordinator", "tell asha speeches stay after dinner")
    reply = chat.send("coordinator", both)
    assert "This message is not to Taylor Ng." in reply.message
    assert "This replaces your unsent draft: Message to Asha Tan:" in reply.message


def test_a_helpers_delay_reads_as_a_report(deputy_chat):  # noqa: F811
    planner = StubPlanner({"kitchen behind, dinner 20 min late": DeputyPlan(action="run_sheet_change", text="dinner",
                                                                           minutes=20)})
    reply = deputy_chat(planner).send("banquet", "kitchen behind, dinner 20 min late")
    assert "Report to the coordinator: Dinner service starts 20 minutes late.\nIf they approve, the run sheet becomes:" \
        in reply.message


def test_a_lookup_states_the_seat_and_the_answer_does_not_guess_it(deputy_chat):  # noqa: F811
    planner = StubPlanner({"Lucas Tan table?": DeputyPlan(
        answer="Lucas Tan isn't on the guest list I can see, so please refer him to Alex.", find_guests=["Lucas Tan"])})
    reply = deputy_chat(planner).send("registration-a", "Lucas Tan table?")
    assert "isn't on the guest list" not in reply.message and "Lucas Tan: Table" in reply.message
    assert not reply.telegram_draft_id  # the lookup answered it; no question button


def test_a_question_about_an_arrival_never_records_one(deputy_chat):  # noqa: F811
    planner = StubPlanner({"what is Grace Tan status now? arrived or not": DeputyPlan(action="draft_arrival",
                                                                                     text="Grace Tan")})
    assert not deputy_chat(planner).send("registration-a", "what is Grace Tan status now? arrived or not").telegram_draft_id


def test_advice_and_a_pending_task_are_not_report_statuses():
    from wedding_ops.claims import states_report_status
    assert not states_report_status("Moving the speeches needs to be approved by the coordinator.")
    assert not states_report_status("Your task is still pending, due 17:50.")
    assert states_report_status("So tell the kitchen it's not approved.")


def test_a_status_word_counts_only_when_said_of_something():
    from wedding_ops.claims import states_report_status
    # Replay v10: a verb "change" and the adjective "approved" removed the couple's whole answer.
    assert not states_report_status("I can't change the run sheet, and the approved sheet has speeches at 19:45.")
    assert states_report_status("Your report was sent.") and states_report_status("R1 approved.")
