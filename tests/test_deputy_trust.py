"""Root-cause fixes for deputy trust (docs/plans/2026-11-21-deputy-trust-root-causes.md)."""
import json

import httpx
from sqlalchemy import select
from test_core_loop import coordinator_news
from test_deputy import (  # noqa: F401  (deputy_chat is a fixture)
    StubPlanner,
    deputy_chat,
)

from wedding_ops.agent import MistralParser, ask_coordinator
from wedding_ops.deputy import DeputyPlan
from wedding_ops.models import Approval, Incident, Person, Task, TimelineItem, Wedding
from wedding_ops.policy import Actor

WEDDING = "demo-wedding"


def context_of(planner: StubPlanner) -> str:
    return planner.calls[-1][1]["content"]


# S1: code speaks for outcomes; history tells the truth --------------------------------------

def test_an_arrival_preview_shows_only_what_the_command_records(deputy_chat):
    planner = StubPlanner({"grace tan here liao": DeputyPlan(
        reply="Drafted her arrival.", action="draft_arrival", text="Grace Tan",
        details="Grace Tan arrived with two cousins and wants a seat near the front.")})
    reply = deputy_chat(planner).send("registration-a", "grace tan here liao").message
    assert "Record confirmed arrival for Grace Tan." in reply
    assert "cousins" not in reply and "Details" not in reply  # Arrivals send no details.


def test_history_says_whether_an_earlier_draft_was_sent(deputy_chat):
    planner = StubPlanner({
        "car flat tyre": DeputyPlan(reply="Drafted.", action="tell_coordinator", text="Bridal car flat tyre"),
        "speaker spoil": DeputyPlan(reply="Drafted.", action="tell_coordinator", text="Speaker broken"),
        "mic also spoil": DeputyPlan(reply="Drafted.", action="tell_coordinator", text="Mic broken"),
    })
    chat = deputy_chat(planner)
    sent = chat.send("driver", "car flat tyre")
    chat.tap("driver", f"confirm:{sent.telegram_draft_id}")
    chat.send("driver", "speaker spoil")      # Drafted but never tapped...
    chat.send("driver", "mic also spoil")      # ...and replaced by this newer draft.
    chat.send("driver", "so what happened")
    history = "\n".join(m["content"] for m in planner.calls[-1] if m["role"] == "assistant")
    assert "was SENT at" in history and "Bridal car flat tyre" in history
    assert "was NOT SENT (it expired or a newer draft replaced it)" in history
    assert "NOT SENT yet, waiting for their tap" in history
    assert "Draft waiting for their tap, NOT SENT" in context_of(planner)


def test_a_newer_draft_replaces_the_pending_one(deputy_chat, db):
    planner = StubPlanner({
        "dinner 20 late": DeputyPlan(reply="Drafted.", action="run_sheet_change", text="dinner", minutes=20),
        "food late, guests angry": DeputyPlan(reply="Drafted.", action="tell_coordinator", text="Food late"),
    })
    chat = deputy_chat(planner)
    first = chat.send("banquet", "dinner 20 late")
    chat.send("banquet", "food late, guests angry")
    refused = chat.tap("banquet", f"confirm:{first.telegram_draft_id}")
    assert "replaced by a newer one" in refused.message
    with db.sessions() as s:
        assert s.scalars(select(Approval)).all() == []


# S2: a sourced context ------------------------------------------------------------------------

def test_context_tags_sources_and_lists_places_on_the_run_sheet(deputy_chat, ops):
    ops.execute(Actor(WEDDING, "coordinator"), {"type": "broadcast", "team_ids": ["ushers"],
                "message": "Rain: guests wait in the foyer"}, "sourced-broadcast")
    planner = StubPlanner()
    chat = deputy_chat(planner)
    chat.worker.tick()
    chat.send("usher", "where guests go")
    context = context_of(planner)
    assert "18:30 Garden ceremony at Garden terrace" in context
    assert "[coordinator said" in context and "Rain: guests wait in the foyer" in context
    assert "[record] Emergency contact: Venue duty manager Lee" in context


def test_the_coordinators_context_shows_decisions_they_made(deputy_chat, db):
    planner = StubPlanner()
    chat = deputy_chat(planner)
    draft = chat.send("banquet", "/delay dinner 10")
    chat.tap("banquet", f"confirm:{draft.telegram_draft_id}")
    with db.sessions() as s:
        approval = s.scalars(select(Approval)).one()
    chat.send("coordinator", f"/approve {approval.id}")
    chat.send("coordinator", "did i approve the dinner delay")
    assert "you approved “Dinner service: +10 minutes” (requested by Chris Wong)" in context_of(planner)


# S3: the run sheet can change place, time and note; reports can be amended -----------------------

def test_coordinator_moves_the_ceremony_and_everyone_hears_it_from_the_change(deputy_chat, db):
    planner = StubPlanner({"rain, move ceremony to the ballroom at 18:40": DeputyPlan(
        reply="Here is the change.", action="run_sheet_change", text="ceremony", new_time="18:40",
        place="Cedar Ballroom", note="Guests enter through the foyer double doors.", details="Rain")})
    chat = deputy_chat(planner)
    with db.transaction(WEDDING, write=True) as (s, _):
        s.get(Task, "photo-family").timeline_item_id = "ceremony"  # Not at the garden: must not move.
        usher = s.get(Task, "usher-ready")
        s.add(Task(id="garden-chairs", wedding_id=WEDDING, title="Wipe garden chairs", instructions="",
                   owner_id="usher", team_id="ushers", location_id="garden", timeline_item_id="ceremony",
                   offset_minutes=-15, due_at=usher.due_at, planned_due=usher.due_at, state="pending"))
    draft = chat.send("coordinator", "rain, move ceremony to the ballroom at 18:40")
    assert "Garden ceremony 18:30 → 18:40, now at Cedar Ballroom (was Garden terrace)" in draft.message
    assert "Family portraits 18:50 → 19:00" in draft.message  # The cascade is shown before the tap.
    done = chat.tap("coordinator", f"confirm:{draft.telegram_draft_id}")
    assert done.message.startswith("Run sheet updated")
    with db.sessions() as s:
        ceremony = s.get(TimelineItem, "ceremony")
        assert ceremony.location_id == "ballroom" and ceremony.change_note.startswith("Guests enter")
        assert s.get(Task, "photo-family").location_id == "portraits"
        assert s.get(Task, "garden-chairs").location_id == "ballroom"  # It was at the old place, so it follows.
        assert s.scalars(select(Approval)).one().decided_by == "coordinator"
    notice = chat.last("usher", "timeline_updated")  # Ushers are not on the ceremony's teams, but guests move.
    assert "now at Cedar Ballroom (was Garden terrace)" in notice.message and "Acknowledge" in notice.message


def test_a_helpers_place_change_waits_for_the_coordinator(deputy_chat, db):
    planner = StubPlanner({"speeches better at the ballroom": DeputyPlan(
        reply="I'll ask Alex.", action="run_sheet_change", text="speeches", place="Cedar Ballroom")})
    chat = deputy_chat(planner)
    draft = chat.send("mc", "speeches better at the ballroom")
    assert "Nothing changes until the coordinator approves it." in draft.message
    chat.tap("mc", f"confirm:{draft.telegram_draft_id}")
    with db.sessions() as s:
        approval = s.scalars(select(Approval)).one()
        assert approval.status == "pending" and s.get(TimelineItem, "speeches").location_id == "stage"
    assert "now at Cedar Ballroom (was Stage & AV desk)" in chat.last("coordinator", "approval_requested").message
    chat.send("coordinator", f"/approve {approval.id}")
    with db.sessions() as s:
        assert s.get(TimelineItem, "speeches").location_id == "ballroom"


def test_a_follow_up_adds_to_the_open_report(deputy_chat, db):
    planner = StubPlanner({
        "car spoil": DeputyPlan(reply="Drafted.", action="tell_coordinator", text="Bridal car flat tyre"),
        "still cannot move!!": DeputyPlan(reply="Added.", action="tell_coordinator", text="Car still stuck",
                                          level="urgent", about="R1", details="Car still cannot move."),
    })
    chat = deputy_chat(planner)
    first = chat.send("driver", "car spoil")
    chat.tap("driver", f"confirm:{first.telegram_draft_id}")
    update = chat.send("driver", "still cannot move!!")
    assert "Add this update to your report “Bridal car flat tyre” and mark it URGENT" in update.message
    chat.tap("driver", f"confirm:{update.telegram_draft_id}")
    with db.sessions() as s:
        incident = s.scalars(select(Incident)).one()
    assert incident.severity == "urgent" and "Car still cannot move." in incident.details
    assert "Now URGENT" in chat.last("coordinator", "incident").message


# S4: actions from policy; one path to the coordinator; lookups ------------------------------------

def test_a_question_reaches_the_coordinator_and_the_answer_comes_back(deputy_chat, db):
    planner = StubPlanner({
        "where i put guests now, raining": DeputyPlan(
            reply="I don't know yet. I'll ask Alex.", action="tell_coordinator", level="question",
            text="Where should guests wait during the rain?"),
        "tell jamie foyer": DeputyPlan(reply="Here's the answer.", action="send_message", to="",
                                       about="Q1", text="Keep guests in the foyer until 18:35."),
    })
    chat = deputy_chat(planner)
    question = chat.send("usher", "where i put guests now, raining")
    assert "Ask the coordinator: Where should guests wait during the rain?" in question.message
    chat.tap("usher", f"confirm:{question.telegram_draft_id}")
    assert "Question from Jamie Lim" in chat.last("coordinator", "question").message  # Pushed: it needs an answer.
    answer = chat.send("coordinator", "tell jamie foyer")
    assert "This answers their question and closes it." in answer.message
    chat.tap("coordinator", f"confirm:{answer.telegram_draft_id}")
    assert "Keep guests in the foyer until 18:35." in chat.last("usher", "coordinator_message").message
    with db.sessions() as s:
        assert s.scalars(select(Incident)).one().status == "resolved"


def test_the_coordinator_can_message_one_person(deputy_chat):
    planner = StubPlanner({"ask jordan for car status": DeputyPlan(
        reply="Drafted.", action="send_message", to="Jordan", text="Please reply with the car status now.")})
    chat = deputy_chat(planner)
    draft = chat.send("coordinator", "ask jordan for car status")
    assert "Message to Jordan Tay" in draft.message
    chat.tap("coordinator", f"confirm:{draft.telegram_draft_id}")
    assert "car status" in chat.last("driver", "coordinator_message").message
    assert chat.notices("usher", "coordinator_message") == []


def test_several_guests_are_looked_up_in_one_message(deputy_chat):
    planner = StubPlanner({"chloe tan and ethan tan table?": DeputyPlan(
        reply="Here they are.", find_guests=["Chloe Tan", "Ethan Tan", "Nobody Here"])})
    reply = deputy_chat(planner).send("usher", "chloe tan and ethan tan table?").message
    assert "Chloe Tan: Table" in reply and "Ethan Tan: Table" in reply and "Nobody Here: not on the guest list" in reply


def test_registration_can_check_in_a_regular_guest(deputy_chat, db):
    planner = StubPlanner({"ethan ng reach already": DeputyPlan(reply="Drafted.", action="draft_arrival", text="Ethan Ng")})
    chat = deputy_chat(planner)
    draft = chat.send("registration-a", "ethan ng reach already")
    chat.tap("registration-a", f"confirm:{draft.telegram_draft_id}")
    with db.sessions() as s:
        assert s.scalars(select(Person).where(Person.name == "Ethan Ng")).one().attendance == "onsite"


def test_the_model_is_offered_only_this_persons_actions():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["schema"] = json.loads(request.content)["response_format"]["json_schema"]["schema"]
        body = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"reply": "Hi."})}}]}
        return httpx.Response(200, json=body)

    parser = MistralParser.__new__(MistralParser)  # No settings needed: only the request is checked.
    parser.model, parser.client = "test-model", httpx.Client(transport=httpx.MockTransport(handler))
    parser.plan([{"role": "user", "content": "hi"}], ["none", "acknowledge"])
    assert seen["schema"]["properties"]["action"]["enum"] == ["none", "acknowledge"]


# S5: coordinator attention ------------------------------------------------------------------------

def test_only_decisions_and_urgent_items_interrupt_the_coordinator(deputy_chat, ops, db):
    driver = Actor(WEDDING, "driver", "telegram")
    ops.execute(driver, {"type": "report_incident", "kind": "other", "title": "Shuttle running slow",
                         "details": "Five minutes behind."}, "normal-problem")
    ops.execute(driver, {"type": "report_incident", "kind": "other", "title": "Car on fire", "severity": "urgent",
                         "details": "Smoke from the bonnet."}, "urgent-problem")
    planner = StubPlanner()
    chat = deputy_chat(planner)
    pushed = [n.message for n in chat.notices("coordinator", "incident")]
    assert any("Car on fire" in message for message in pushed)
    assert not any("Shuttle running slow" in message for message in pushed)
    assert "Problem from Jordan Tay: Shuttle running slow" in coordinator_news(db)


# S6: chase unacknowledged updates -----------------------------------------------------------------

def test_an_unacknowledged_announcement_is_chased_once_with_a_button(db, settings, clock, queries, ops):
    from dataclasses import replace

    from test_core_loop import Chat

    from wedding_ops.worker import deputy_ping_markup
    chat = Chat(db, replace(settings, deputy=True), clock, queries, ops)
    with db.transaction(WEDDING, write=True) as (s, _):
        s.get(Task, "usher-ready").acknowledged_at = clock.now()  # So only the announcement needs chasing.
    ops.execute(Actor(WEDDING, "coordinator"), {"type": "broadcast", "team_ids": ["ushers"],
                "message": "Ceremony moves inside"}, "chase-broadcast")
    chat.worker.tick()
    clock.advance(6)
    chat.worker.tick()
    chases = [n for n in chat.notices("usher", "deputy_ping") if "did you see the coordinator's update" in n.message]
    assert len(chases) == 1 and "Ceremony moves inside" in chases[0].message
    with db.sessions() as s:
        markup = deputy_ping_markup(s, WEDDING, chases[0])
    assert markup["inline_keyboard"][0][0]["text"] == "Acknowledge"
    clock.advance(11)
    chat.worker.tick()
    assert len([n for n in chat.notices("usher", "deputy_ping") if "did you see" in n.message]) == 1


# S7: viewer-aware text and the emergency contact ----------------------------------------------------

def test_the_coordinator_is_never_told_to_ask_themself(queries):
    snapshot = queries.snapshot(Actor(WEDDING, "coordinator"))
    assert "Alex" not in ask_coordinator(snapshot)
    assert "Ask Alex Morgan" in ask_coordinator(queries.snapshot(Actor(WEDDING, "usher")))


def test_urgent_drafts_name_the_emergency_contact(deputy_chat, db):
    planner = StubPlanner({"guest fainted!!": DeputyPlan(reply="Drafted.", action="tell_coordinator",
                                                        level="urgent", text="Guest fainted at table 4")})
    chat = deputy_chat(planner)
    reply = chat.send("usher", "guest fainted!!").message
    assert "call Venue duty manager Lee (fictional), DEMO-NOT-A-REAL-NUMBER now" in reply
    with db.transaction(WEDDING, write=True) as (s, _):
        s.get(Wedding, WEDDING).emergency_contact = ""
    assert "call venue security or the duty manager now" in chat.send("usher", "guest fainted!!").message


def test_times_in_helpers_questions_do_not_ground_a_reply(deputy_chat, ops):
    ops.execute(Actor(WEDDING, "usher", "telegram"), {"type": "report_incident", "kind": "question",
                "title": "Is dinner moved to 23:59?", "details": "x"}, "question-time")
    planner = StubPlanner({"when is dinner": DeputyPlan(reply="Dinner is at 23:59.")})
    assert "23:59" not in deputy_chat(planner).send("coordinator", "when is dinner").message


def test_the_couple_can_ask_the_coordinator_but_not_report_problems(deputy_chat, db):
    planner = StubPlanner({"move speeches before dinner pls": DeputyPlan(
        reply="I'll ask Alex.", action="tell_coordinator", level="urgent", text="Move speeches before dinner?")})
    chat = deputy_chat(planner)
    draft = chat.send("couple", "move speeches before dinner pls")
    assert "Ask the coordinator: Move speeches before dinner?" in draft.message  # Asked, not an urgent report.
    chat.tap("couple", f"confirm:{draft.telegram_draft_id}")
    with db.sessions() as s:
        assert s.scalars(select(Incident)).one().kind == "question"


def test_a_helper_marks_their_own_task_done_by_saying_so(deputy_chat, db):
    planner = StubPlanner({"the food come alr, all ready": DeputyPlan(
        reply="Great, here it is.", action="complete_task", text="dinner readiness")})
    chat = deputy_chat(planner)
    draft = chat.send("banquet", "the food come alr, all ready")
    assert "Mark your task done: Confirm dinner readiness." in draft.message
    assert "Marked done" in chat.tap("banquet", f"confirm:{draft.telegram_draft_id}").message
    with db.sessions() as s:
        assert s.get(Task, "banquet-ready").state == "done"
