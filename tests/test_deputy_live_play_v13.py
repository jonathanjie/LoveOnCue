"""Fixes for the causes found in live play v13 (docs/plans/2026-11-22-deputy-claim-check.md)."""
from test_deputy import StubPlanner, deputy_chat  # noqa: F401  (fixture)
from test_deputy_live_play_v11 import ReplanningPlanner

from wedding_ops.claims import says_retracted, states_report_status
from wedding_ops.deputy import NOTHING_DONE, DeputyPlan


def test_task_and_attendance_facts_are_not_report_status():
    # Live play v13: these were removed as report status, and "You have no reports on record yet."
    # stood in their place.
    assert not states_report_status("Your task to confirm the parents' arrival is pending.")
    assert not states_report_status("Robert Tan's arrival is not recorded yet.")
    assert states_report_status("Your report was sent.")


def test_an_answer_that_only_points_at_a_missing_button_says_nothing_was_done(deputy_chat):  # noqa: F811
    # Live play v13: "sorry that was a guest lol" got "I didn't make a draft for that".
    text = "sorry that was a guest lol"
    reply = deputy_chat(StubPlanner({text: DeputyPlan(answer="Tap Send to pass it on.")})).send("usher", text)
    assert reply.message == NOTHING_DONE


def test_beside_an_unsent_report_a_statement_about_the_coordinator_is_removed(deputy_chat):  # noqa: F811
    # Live play v13: "The dinner delay and the missing veg meals are both with the coordinator now"
    # above an unsent report.
    text = "two veg meals missing for table 7 leh"
    answer = ("The missing veg meals are with the coordinator now. Dinner service is at 19:00. "
              "Should the coordinator also know which guests?")
    reply = deputy_chat(StubPlanner({text: DeputyPlan(answer=answer, action="tell_coordinator", level="problem",
                                                      text="Two vegetarian meals missing")})).send("banquet", text)
    assert reply.telegram_draft_id
    assert "with the coordinator now" not in reply.message and "Dinner service is at 19:00." in reply.message
    assert "Should the coordinator also know which guests?" in reply.message


def test_a_withdrawal_rests_on_words_that_take_something_back(deputy_chat):  # noqa: F811
    assert says_retracted("cancel the mei one") and says_retracted("please ignore my earlier report")
    assert not says_retracted("sorry that was a guest lol")
    note = "dinner on time actually, kitchen say"
    text = "sorry that was a guest lol"
    planner = ReplanningPlanner({
        note: [DeputyPlan(action="tell_coordinator", level="fyi", text="Kitchen says dinner on time")],
        text: [DeputyPlan(answer="Okay.", action="withdraw_last"), DeputyPlan(answer="")]})
    chat = deputy_chat(planner)
    chat.tap("usher", f"confirm:{chat.send('usher', note).telegram_draft_id}")
    reply = chat.send("usher", text)
    assert planner.actions[-1] == ["none"] and not reply.telegram_draft_id


def test_a_correction_that_names_the_request_may_take_it_back(deputy_chat):  # noqa: F811
    # Paired replay: "chef say only 10 minutes now lah, not 20" has no word that takes something
    # back, but it names the +20 dinner request.
    request = "kitchen 20 minutes behind, dinner 20 late"
    correction = "chef say only 10 minutes now lah, not 20. so dinner 10 min late only"
    chat = deputy_chat(StubPlanner({
        request: DeputyPlan(action="run_sheet_change", text="Dinner service", minutes=20),
        correction: DeputyPlan(action="withdraw_last")}))
    chat.tap("banquet", f"confirm:{chat.send('banquet', request).telegram_draft_id}")
    assert "Take back" in chat.send("banquet", correction).message
