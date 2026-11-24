"""Fixes for the causes found in live play v12 (docs/plans/2026-11-22-deputy-claim-check.md)."""
from test_deputy import StubPlanner, deputy_chat  # noqa: F401  (fixture)
from test_deputy_live_play_v11 import ReplanningPlanner

from wedding_ops.deputy import DeputyPlan
from wedding_ops.policy import Actor

WEDDING = "demo-wedding"


def test_an_action_code_cannot_draft_is_planned_again_with_what_happened(deputy_chat):  # noqa: F811
    # Live play v12, both casts: "Logging Grace Tay's arrival now." above "I could not tell which
    # guest or family member you mean. Send me their full name." Grace Tay is on no list.
    text = "Grace Tay arrived, regular guest, please log her arrival"
    planner = ReplanningPlanner({text: [
        DeputyPlan(answer="Logging Grace Tay's arrival now.", action="draft_arrival", text="Grace Tay"),
        DeputyPlan(answer="")]})
    reply = deputy_chat(planner).send("registration-a", text)
    assert planner.actions[-1] == ["none"] and len(planner.actions) == 2
    told = planner.calls[-1][-2]["content"]
    assert "nothing was recorded or sent" in told and "Grace Tay: not on the guest list" in told
    assert reply.message.startswith("Nothing was recorded. Grace Tay: not on the guest list. Check the spelling.")
    assert "Logging" not in reply.message and not reply.telegram_draft_id


def test_a_name_that_matches_nobody_and_one_that_matches_several_are_told_apart(deputy_chat):  # noqa: F811
    planner = StubPlanner({
        "Nobody Here arrived": DeputyPlan(action="draft_arrival", text="Nobody Here"),
        "Tan arrived": DeputyPlan(action="draft_arrival", text="Tan")})
    chat = deputy_chat(planner)
    assert "Nobody Here: not on the guest list" in chat.send("registration-a", "Nobody Here arrived").message
    several = chat.send("registration-a", "Tan arrived").message
    assert "guests match; send me the full name" in several and "not on the" not in several


def test_the_coordinator_sees_who_reported_what_and_their_words(deputy_chat, ops):  # noqa: F811
    # Live play v12: "The records only show an open incident titled “Bridal car flat tyre in car
    # park” — no details on the car's condition", though Jordan wrote that it cannot move.
    ops.execute(Actor(WEDDING, "driver", "telegram"), {
        "type": "report_incident", "kind": "other", "severity": "urgent", "title": "Bridal car flat tyre in car park",
        "details": "CAR PANCIT LIAO!! flat tyre, the bridal car cannot move"}, "v12-tyre")
    text = "what happened with the car"
    planner = StubPlanner({text: DeputyPlan(answer="", status_of=["P1"])})
    reply = deputy_chat(planner).send("coordinator", text)
    records = planner.records()
    assert "- P1 [urgent problem report from Jordan Tay at 17:45, open] “Bridal car flat tyre in car park”" in records
    assert "the bridal car cannot move" in records and "Review this open" not in records
    assert reply.message.startswith("Urgent problem report from Jordan Tay at 17:45, open: “Bridal car flat tyre")
    assert "cannot move" in reply.message


def test_the_coordinator_sees_pending_requests_and_their_own_change_is_not_a_report(deputy_chat, ops):  # noqa: F811
    ops.execute(Actor(WEDDING, "coordinator", "telegram"), {
        "type": "change_item", "item_id": "ceremony", "shift_minutes": 10, "location_id": "ballroom",
        "reason": "Rain"}, "v12-rain")
    ops.execute(Actor(WEDDING, "banquet", "telegram"), {
        "type": "propose_delay", "item_id": "dinner", "minutes": 20, "reason": "Kitchen 20 minutes behind lah"},
        "v12-dinner")
    planner = StubPlanner()
    deputy_chat(planner).send("coordinator", "any approvals or reports I must handle?")
    records = planner.records()
    assert "- A1 [run-sheet request from Chris Wong at 17:45, pending" in records
    assert "Kitchen 20 minutes behind lah" in records
    assert "Their reports" not in records  # the rain change is the coordinator's own decision


def test_a_status_chosen_by_code_and_by_the_model_is_printed_once(deputy_chat):  # noqa: F811
    # Live play v12: "Your 18:25 run-sheet request “Dinner service: +20 minutes”: pending." twice.
    request = "kitchen behind, dinner need 15 more min"
    again = "food need 20 more min lah, kitchen says"
    chat = deputy_chat(StubPlanner({
        request: DeputyPlan(action="run_sheet_change", text="Dinner service", minutes=15),
        again: DeputyPlan(action="tell_coordinator", level="problem", text="Dinner service late", status_of=["R1"])}))
    chat.tap("banquet", f"confirm:{chat.send('banquet', request).telegram_draft_id}")
    reply = chat.send("banquet", again)
    assert reply.message.count("run-sheet request") == 1 and not reply.telegram_draft_id


def test_a_name_only_asked_about_is_not_left_out_of_a_message(deputy_chat):  # noqa: F811
    # Live play v12: "is Ryan on it now or not, and where is the shuttle for jordan" drafted a
    # message to Jordan, with "This message is not to Ryan Goh".
    text = "is Ryan on it now or not? tell jordan guests are waiting outside"
    reply = deputy_chat(StubPlanner({text: DeputyPlan(action="send_message", to="Jordan",
                                                      message="Guests are waiting outside.")})).send("coordinator", text)
    assert "Message to Jordan Tay:" in reply.message and "Ryan" not in reply.message.split("Message to")[0]


def test_a_message_needs_its_recipient_named_in_this_message(deputy_chat):  # noqa: F811
    # Live play v12: "Any open approvals or reports I must handle?" drafted a message to Taylor,
    # named only in an earlier message.
    planner = ReplanningPlanner({
        "is taylor here yet": [DeputyPlan(answer="")],
        "any approvals or reports I must handle?": [
            DeputyPlan(action="send_message", to="Taylor", message="Please confirm your arrival."),
            DeputyPlan(answer="")]})
    chat = deputy_chat(planner)
    chat.send("coordinator", "is taylor here yet")
    reply = chat.send("coordinator", "any approvals or reports I must handle?")
    assert planner.actions[-1] == ["none"] and not reply.telegram_draft_id
