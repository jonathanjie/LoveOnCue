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
    chat = deputy_chat(StubPlanner({text: DeputyPlan(answer="The run sheet doesn't say.", action="ask_coordinator")}))
    chat.tap("usher", f"confirm:{chat.send('usher', text).telegram_draft_id}")
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
