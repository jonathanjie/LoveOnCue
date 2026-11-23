"""Fixes for the causes found in live play v11 (docs/plans/2026-11-22-deputy-claim-check.md)."""
from sqlalchemy import select
from test_deputy import StubPlanner, deputy_chat  # noqa: F401  (fixture)

from wedding_ops.claims import acts_claimed, says_arrived, says_done, says_late
from wedding_ops.deputy import DeputyPlan
from wedding_ops.models import Approval, Incident, TimelineItem
from wedding_ops.operations import first_line
from wedding_ops.policy import Actor
from wedding_ops.telegram import confirmation_reply

WEDDING = "demo-wedding"


class ReplanningPlanner(StubPlanner):
    """Returns the scripted plans for a message in order, so a second plan can differ from the first."""

    def __init__(self, plans: dict[str, list[DeputyPlan]]):
        super().__init__()
        self.queue = {text: list(items) for text, items in plans.items()}

    def plan(self, messages, actions, *, lookups=True):
        super().plan(messages, actions, lookups=lookups)
        items = self.queue.get(messages[-1]["content"], [])
        return items.pop(0) if len(items) > 1 else (items[0] if items else DeputyPlan(answer="Not sure."))


def test_a_stated_word_counts_and_a_questioned_or_denied_one_does_not():
    assert says_arrived("Grace Tan just arrived at the desk, can you log it and confirm?")
    assert says_arrived("robert tan reach liao, which table ah?")
    assert says_arrived("Robert Tan here already. mark him arrived pls")
    assert not says_arrived("what is Grace Tan status now? arrived or not")
    assert not says_arrived("Grace Tan haven't arrive leh, waiting 20 min")
    assert not says_arrived("she will reach in 10 min")
    assert says_done("task done, can you mark it?") and says_done("can mark my task done?")
    assert not says_done("is it done?") and not says_done("not ready yet")
    assert says_late("stuck in jam, 20 min late") and not says_late("not late, on the way")


def test_any_completed_act_is_a_claim_but_reading_is_not():
    assert acts_claimed("Thanks Michelle — I've noted Grace Tan's arrival at the registration desk.")
    assert acts_claimed("I've set that change for you to confirm.")
    assert not acts_claimed("I've checked the run sheet.")
    assert not acts_claimed("I have two tasks listed for you.")
    assert not acts_claimed("I've only been given the run sheet.")


def test_a_done_claim_beside_a_draft_counts_only_for_the_drafts_object():
    assert acts_claimed("Noted, Robert Tan is marked as arrived.", offered=True, objects=("Robert Tan",))
    assert not acts_claimed("43 of 180 guests are recorded as onsite.", offered=True, objects=("Robert Tan",))
    assert not acts_claimed("Noted, Robert Tan is marked as arrived.")  # without a draft it may be a record


def test_a_request_phrased_as_a_question_still_drafts_the_arrival(deputy_chat):  # noqa: F811
    text = "hi, Grace Tan (mother of the bride) just arrived at the registration desk, can you log it and confirm?"
    planner = StubPlanner({text: DeputyPlan(answer="Thanks.", action="draft_arrival", text="Grace Tan")})
    reply = deputy_chat(planner).send("registration-a", text)
    assert reply.telegram_draft_id and "Record confirmed arrival for Grace Tan" in reply.message


def test_a_vetoed_action_is_planned_again_without_it(deputy_chat):  # noqa: F811
    # Live play v11: the veto kept "I've noted Grace Tan's arrival" with nothing recorded.
    text = "what is Grace Tan status now? arrived or not"
    planner = ReplanningPlanner({text: [
        DeputyPlan(answer="I've noted Grace Tan's arrival.", action="draft_arrival", text="Grace Tan"),
        DeputyPlan(answer="Grace Tan is not checked in yet.")]})
    reply = deputy_chat(planner).send("registration-a", text)
    assert "draft_arrival" not in planner.actions[-1] and len(planner.actions) == 2
    assert reply.message == "Grace Tan is not checked in yet." and not reply.telegram_draft_id


def test_a_question_link_needs_the_coordinators_words(deputy_chat, ops, db):  # noqa: F811
    ops.execute(Actor(WEDDING, "couple", "telegram"), {"type": "report_incident", "kind": "question",
                "title": "Has my Ah Ma Tan arrived yet?", "details": "Has my Ah Ma Tan arrived yet?"}, "asha-q")
    text = "tell chris dinner is now 20 minutes late"
    planner = StubPlanner({text: DeputyPlan(answer="Drafted.", action="send_message", to="Chris", about="Q1",
                                            message="Dinner is now 20 minutes late.")})
    reply = deputy_chat(planner).send("coordinator", text)
    assert "Message to Chris Wong:" in reply.message and "closes it" not in reply.message


def test_a_note_made_only_of_questions_goes_by_the_question_button(deputy_chat, db):  # noqa: F811
    text = "the coordinator got my message or not? Did you tell them already?"
    planner = StubPlanner({text: DeputyPlan(answer="I can't see that.", action="tell_coordinator", level="fyi",
                                            text="Did the coordinator get my message")})
    reply = deputy_chat(planner).send("family-liaison", text)
    assert "Ask the coordinator" in reply.message and "for their information" not in reply.message


def test_a_messaged_run_sheet_change_becomes_the_change(deputy_chat, db):  # noqa: F811
    # Live play v11: the rain move was announced as a message only; the run sheet kept 18:30.
    text = "rain, garden ceremony move into Cedar Ballroom and start 6:40 pm. announce to everyone"
    planner = ReplanningPlanner({text: [
        DeputyPlan(answer="", action="send_message", to="everyone",
                   message="Due to rain, the garden ceremony moves to Cedar Ballroom and starts at 6:40 pm."),
        DeputyPlan(answer="", action="run_sheet_change", text="Garden ceremony", new_time="18:40",
                   place="Cedar Ballroom")]})
    reply = deputy_chat(planner).send("coordinator", text)
    assert planner.actions[-1] == ["none", "run_sheet_change"]
    assert "Change the run sheet:" in reply.message and "To send a message only, say so." in reply.message


def test_a_message_without_a_new_time_stays_a_message(deputy_chat):  # noqa: F811
    text = "message only pls, tell everyone the ceremony moves inside"
    planner = StubPlanner({text: DeputyPlan(answer="", action="send_message", to="everyone",
                                            message="The garden ceremony moves inside.")})
    reply = deputy_chat(planner).send("coordinator", text)
    assert "Message to everyone:" in reply.message and len(planner.actions) == 1


def test_a_blocked_helper_change_becomes_a_report(deputy_chat):  # noqa: F811
    text = "kitchen say dinner 100 min late"
    planner = StubPlanner({text: DeputyPlan(answer="", action="run_sheet_change", text="Dinner service", minutes=100)})
    reply = deputy_chat(planner).send("banquet", text)
    assert "can't go through" in reply.message and "latest allowed end time" in reply.message
    assert reply.telegram_draft_id and "Send a problem report" in reply.message


def test_code_text_names_what_it_did():
    assert first_line("Message to everyone:\n“Rain plan”") == "Message to everyone: “Rain plan”"
    reply = confirmation_reply({"command_type": "change_item", "status": "approved", "timeline_version": 2,
                                "told": 9, "informed": 1, "overtaken": ["Dinner service: +20 minutes (Chris Wong)"]})
    assert "9 people are told, with an Acknowledge button. The couple see the new times too." in reply
    assert "Closed, because they no longer fit the new run sheet: Dinner service: +20 minutes (Chris Wong)" in reply


def test_a_coordinator_change_closes_a_helpers_request_it_moves(ops, db):
    helper = ops.execute(Actor(WEDDING, "banquet", "telegram"), {
        "type": "propose_delay", "item_id": "dinner", "minutes": 20, "reason": "kitchen 20 min behind"}, "v11-kitchen")
    result = ops.execute(Actor(WEDDING, "coordinator", "telegram"), {
        "type": "change_item", "item_id": "ceremony", "shift_minutes": 10, "location_id": "ballroom",
        "reason": "Rain"}, "v11-rain")
    assert result["overtaken"] == ["Dinner service: +20 minutes (Chris Wong)"]
    with db.sessions() as s:
        assert s.get(Approval, helper["id"]).status == "superseded"
        assert s.get(TimelineItem, "dinner").current_start is not None
        assert not s.scalars(select(Incident)).all()


def test_a_second_plan_only_answers(deputy_chat):  # noqa: F811
    # Replay v11: offered every other action, the model turned "kitchen ok anot? dinner 7pm still on?"
    # into a run-sheet change.
    text = "kitchen ok anot? dinner 7pm still on?"
    planner = ReplanningPlanner({text: [
        DeputyPlan(answer="", action="send_message", to="Chris", message="Is the kitchen on time?"),
        DeputyPlan(answer="Dinner is at 19:00.")]})
    deputy_chat(planner).send("coordinator", text)
    assert planner.actions[-1] == ["none"]


def test_a_group_from_the_records_may_get_a_message_the_person_asked_for(deputy_chat):  # noqa: F811
    text = "Ok nudge the 2 who never acked: ceremony now Cedar Ballroom. Ack pls."
    planner = StubPlanner({text: DeputyPlan(answer="", action="send_message", to="Jamie Lim, Jordan Tay",
                                            message="The ceremony is now in Cedar Ballroom. Please acknowledge.")})
    reply = deputy_chat(planner).send("coordinator", text)
    assert "Message to Jamie Lim, Jordan Tay:" in reply.message and len(planner.actions) == 1
