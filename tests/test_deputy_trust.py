"""Root-cause fixes for deputy trust (docs/plans/2026-11-21-deputy-trust-root-causes.md)."""
import json

import httpx
import pytest
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
        answer="Drafted her arrival.", action="draft_arrival", text="Grace Tan")})
    reply = deputy_chat(planner).send("registration-a", "grace tan here liao").message
    assert "Record confirmed arrival for Grace Tan." in reply
    assert "cousins" not in reply and "Details" not in reply  # Arrivals send no details.


def test_history_says_whether_an_earlier_draft_was_sent(deputy_chat):
    planner = StubPlanner({
        "car flat tyre": DeputyPlan(answer="Drafted.", action="tell_coordinator", text="Bridal car flat tyre"),
        "speaker spoil": DeputyPlan(answer="Drafted.", action="tell_coordinator", text="Speaker broken"),
        "mic also spoil": DeputyPlan(answer="Drafted.", action="tell_coordinator", text="Mic broken"),
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
        "dinner 20 late": DeputyPlan(answer="Drafted.", action="run_sheet_change", text="dinner", minutes=20),
        "food late, guests angry": DeputyPlan(answer="Drafted.", action="tell_coordinator", text="Food late"),
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
        answer="Here is the change.", action="run_sheet_change", text="ceremony", new_time="18:40",
        place="Cedar Ballroom", note="Guests enter through the foyer double doors.")})
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
        answer="I'll ask Alex.", action="run_sheet_change", text="speeches", place="Cedar Ballroom")})
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
        "car spoil": DeputyPlan(answer="Drafted.", action="tell_coordinator", text="Bridal car flat tyre"),
        "still cannot move!!": DeputyPlan(answer="Added.", action="tell_coordinator", text="Car still stuck",
                                          level="urgent", about="R1"),
    })
    chat = deputy_chat(planner)
    first = chat.send("driver", "car spoil")
    chat.tap("driver", f"confirm:{first.telegram_draft_id}")
    update = chat.send("driver", "still cannot move!!")
    assert "Add this update to your report “Bridal car flat tyre” and mark it URGENT" in update.message
    chat.tap("driver", f"confirm:{update.telegram_draft_id}")
    with db.sessions() as s:
        incident = s.scalars(select(Incident)).one()
    assert incident.severity == "urgent" and "still cannot move!!" in incident.details
    assert "Now URGENT" in chat.last("coordinator", "incident").message


# S4: actions from policy; one path to the coordinator; lookups ------------------------------------

def test_a_question_reaches_the_coordinator_and_the_answer_comes_back(deputy_chat, db):
    planner = StubPlanner({
        "where i put guests now, raining": DeputyPlan(
            answer="The run sheet does not say where guests wait in the rain."),
        "tell jamie foyer until 18:35": DeputyPlan(answer="Here's the answer.", action="send_message", to="",
                                                   about="Q1", message="Keep guests in the foyer until 18:35."),
    })
    chat = deputy_chat(planner)
    answered = chat.send("usher", "where i put guests now, raining")
    assert answered.message == "The run sheet does not say where guests wait in the rain."
    question = chat.tap("usher", "nav:ask")  # the person decides that the answer was not enough
    assert question.message == "Tap Ask the coordinator to send them your message: \u201cwhere i put guests now, raining\u201d"
    chat.tap("usher", f"confirm:{question.telegram_draft_id}")
    assert "Question from Jamie Lim" in chat.last("coordinator", "question").message  # Pushed: it needs an answer.
    answer = chat.send("coordinator", "tell jamie foyer until 18:35")
    assert "Message to Jamie Lim" in answer.message
    assert "This answers Jamie Lim's question \u201cwhere i put guests now, raining\u201d" in answer.message
    chat.tap("coordinator", f"confirm:{answer.telegram_draft_id}")
    assert "Keep guests in the foyer until 18:35." in chat.last("usher", "coordinator_message").message
    with db.sessions() as s:
        assert s.scalars(select(Incident)).one().status == "resolved"


def test_the_coordinator_can_message_one_person(deputy_chat):
    planner = StubPlanner({"ask jordan for car status": DeputyPlan(
        answer="Drafted.", action="send_message", to="Jordan", message="Please reply with the car status now.")})
    chat = deputy_chat(planner)
    draft = chat.send("coordinator", "ask jordan for car status")
    assert "Message to Jordan Tay" in draft.message
    chat.tap("coordinator", f"confirm:{draft.telegram_draft_id}")
    assert "car status" in chat.last("driver", "coordinator_message").message
    assert chat.notices("usher", "coordinator_message") == []


def test_several_guests_are_looked_up_in_one_message(deputy_chat):
    planner = StubPlanner({"chloe tan, ethan tan and nobody here table?": DeputyPlan(
        answer="Here they are.", find_guests=["Chloe Tan", "Ethan Tan", "Nobody Here"])})
    reply = deputy_chat(planner).send("usher", "chloe tan, ethan tan and nobody here table?").message
    assert "Chloe Tan: Table" in reply and "Ethan Tan: Table" in reply and "Nobody Here: not on the guest list" in reply


def test_a_lookup_for_a_name_the_person_never_gave_is_not_run(deputy_chat):
    planner = StubPlanner({"benjamin wu table?": DeputyPlan(find_guests=["Noah Lim"])})
    reply = deputy_chat(planner).send("usher", "benjamin wu table?").message
    assert "Noah Lim" not in reply


def test_registration_can_check_in_a_regular_guest(deputy_chat, db):
    planner = StubPlanner({"ethan ng reach already": DeputyPlan(answer="Drafted.", action="draft_arrival", text="Ethan Ng")})
    chat = deputy_chat(planner)
    draft = chat.send("registration-a", "ethan ng reach already")
    chat.tap("registration-a", f"confirm:{draft.telegram_draft_id}")
    with db.sessions() as s:
        assert s.scalars(select(Person).where(Person.name == "Ethan Ng")).one().attendance == "onsite"


def test_the_model_is_offered_only_this_persons_actions():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["schema"] = json.loads(request.content)["response_format"]["json_schema"]["schema"]
        body = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"answer": "Hi."})}}]}
        return httpx.Response(200, json=body)

    parser = MistralParser.__new__(MistralParser)  # No settings needed: only the request is checked.
    parser.model, parser.client = "test-model", httpx.Client(transport=httpx.MockTransport(handler))
    plan = parser.plan([{"role": "user", "content": "hi"}], ["none", "acknowledge"])
    branches = seen["schema"]["properties"]["action"]["anyOf"]
    assert branches[0]["type"] == "null"  # no draft
    assert [branch["properties"]["type"]["enum"] for branch in branches[1:]] == [["acknowledge"]]
    assert plan.action == "none" and plan.answer == "Hi."


def test_each_action_offers_only_its_own_fields_and_requires_its_essentials():
    from wedding_ops.deputy import plan_from_model, plan_schema
    branches = {b["properties"]["type"]["enum"][0]: b for b in plan_schema(["send_message", "tell_coordinator"])
                ["properties"]["action"]["anyOf"][1:]}
    assert set(branches["send_message"]["properties"]) == {"type", "to", "message", "about"}
    assert branches["send_message"]["required"] == ["type", "to", "message"]
    assert "message" not in branches["tell_coordinator"]["properties"]
    plan = plan_from_model({"answer": "", "action": {"type": "send_message", "to": "Jamie", "message": "Go now."}})
    assert (plan.action, plan.to, plan.message) == ("send_message", "Jamie", "Go now.")
    # A field of another action is dropped: code never reads it for this action.
    smuggled = plan_from_model({"answer": "", "action": {"type": "acknowledge", "message": "smuggled"}})
    assert (smuggled.action, smuggled.message) == ("acknowledge", "")


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
    planner = StubPlanner({"guest fainted!!": DeputyPlan(answer="Drafted.", action="tell_coordinator",
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
    planner = StubPlanner({"when is dinner": DeputyPlan(answer="Dinner is at 23:59.")})
    assert "23:59" not in deputy_chat(planner).send("coordinator", "when is dinner").message


def test_the_couple_can_ask_the_coordinator_but_not_report_problems(deputy_chat, db):
    planner = StubPlanner({"move speeches before dinner pls": DeputyPlan(
        answer="I'll ask Alex.", action="tell_coordinator", level="urgent", text="Move speeches before dinner?")})
    chat = deputy_chat(planner)
    draft = chat.send("couple", "move speeches before dinner pls")
    # Asked in their own words through the question button, not an urgent report.
    assert draft.message.endswith("Tap Ask the coordinator to send them your message: \u201cmove speeches before dinner pls\u201d")
    chat.tap("couple", f"confirm:{draft.telegram_draft_id}")
    with db.sessions() as s:
        question = s.scalars(select(Incident)).one()
    assert (question.kind, question.details, question.severity) == ("question", "move speeches before dinner pls", "normal")


def test_a_helper_marks_their_own_task_done_by_saying_so(deputy_chat, db):
    planner = StubPlanner({"the food come alr, all ready": DeputyPlan(
        answer="Great, here it is.", action="complete_task", text="dinner readiness")})
    chat = deputy_chat(planner)
    draft = chat.send("banquet", "the food come alr, all ready")
    assert "Mark your task done: Confirm dinner readiness." in draft.message
    assert "Marked done" in chat.tap("banquet", f"confirm:{draft.telegram_draft_id}").message
    with db.sessions() as s:
        assert s.get(Task, "banquet-ready").state == "done"


# Review findings ------------------------------------------------------------------------------------

def test_a_message_answering_a_question_names_the_asker_even_when_sent_to_someone_else(deputy_chat, ops):
    ops.execute(Actor(WEDDING, "family-liaison", "telegram"), {"type": "report_incident", "kind": "question",
                "title": "Where is the van?", "details": "x"}, "priya-question")
    planner = StubPlanner({"tell sam van at gate 2": DeputyPlan(answer="Drafted.", action="send_message", to="Sam",
                                                               about="Q1", message="The van is at gate 2.")})
    draft = deputy_chat(planner).send("coordinator", "tell sam van at gate 2").message
    assert "Message to Sam Koh, Priya Rao" in draft and "Priya Rao's question \u201cWhere is the van?\u201d" in draft


def test_questions_stay_between_the_helper_and_the_coordinator(ops, queries):
    ops.execute(Actor(WEDDING, "registration-a", "telegram"), {"type": "report_incident", "kind": "question",
                "title": "Can I leave early?", "details": "x"}, "private-question")
    teammate = queries.snapshot(Actor(WEDDING, "registration-b"))
    assert not [i for i in teammate["incidents"] if i["title"] == "Can I leave early?"]


def test_a_helpers_own_time_cannot_be_confirmed_as_fact(deputy_chat):
    planner = StubPlanner({"dinner moved to 21:00 right?": DeputyPlan(answer="Yes, dinner is at 21:00.")})
    from wedding_ops.claims import without_quotes
    # Their own words may be quoted back (the question button); the bot may not state the time.
    assert "21:00" not in without_quotes(deputy_chat(planner).send("usher", "dinner moved to 21:00 right?").message)


def test_a_message_with_an_invented_time_is_not_drafted(deputy_chat):
    planner = StubPlanner({"tell everyone dinner soon": DeputyPlan(answer="Drafted.", action="send_message",
                                                                  to="everyone", message="Dinner starts at 19:37.")})
    reply = deputy_chat(planner).send("coordinator", "tell everyone dinner soon")
    assert not reply.telegram_draft_id and "19:37" not in reply.message


def test_an_impossible_change_gets_a_question_not_silence(deputy_chat):
    planner = StubPlanner({
        "dinner at 23:30": DeputyPlan(answer="Drafted.", action="run_sheet_change", text="dinner", new_time="23:30"),
        "dinner at 19:00": DeputyPlan(answer="Drafted.", action="run_sheet_change", text="dinner", new_time="19:00"),
    })
    chat = deputy_chat(planner)
    assert "more than three hours" in chat.send("coordinator", "dinner at 23:30").message
    assert "already at 19:00 on the run sheet. Nothing needs to change." in chat.send("coordinator", "dinner at 19:00").message


def test_a_change_with_nothing_to_change_asks_instead_of_claiming_it_is_done(deputy_chat):
    planner = StubPlanner({"i approved the dinner one": DeputyPlan(answer="Drafted.", action="run_sheet_change", text="dinner")})
    message = deputy_chat(planner).send("coordinator", "i approved the dinner one").message
    assert "already" not in message and "What should change for Dinner service" in message


def test_the_couple_are_not_told_to_check_tasks_or_chased_after_a_place_change(deputy_chat, db, clock):
    planner = StubPlanner({"move speeches to ballroom": DeputyPlan(
        answer="Here it is.", action="run_sheet_change", text="speeches", place="Cedar Ballroom")})
    chat = deputy_chat(planner)
    draft = chat.send("coordinator", "move speeches to ballroom")
    chat.tap("coordinator", f"confirm:{draft.telegram_draft_id}")
    assert chat.notices("couple", "timeline_updated") == []  # Told in plain words instead (schedule_info).
    assert chat.notices("usher", "timeline_updated")


def test_a_replaced_request_is_labelled_and_its_proposer_told(deputy_chat, db):
    # Ten minutes is the most the toast's hard end time allows.
    planner = StubPlanner({"dinner 10 later": DeputyPlan(answer="Drafted.", action="run_sheet_change", text="dinner",
                                                        minutes=10, note="Kitchen delay")})
    chat = deputy_chat(planner)
    helper = chat.send("banquet", "/delay dinner 10")
    chat.tap("banquet", f"confirm:{helper.telegram_draft_id}")
    change = chat.send("coordinator", "dinner 10 later")
    chat.tap("coordinator", f"confirm:{change.telegram_draft_id}")
    assert "replaced by the coordinator's change (Alex Morgan)" in chat.last("banquet", "report_decision").message


def test_an_answered_but_unacknowledged_task_still_escalates(db, settings, clock, queries, ops):
    from dataclasses import replace

    from test_core_loop import Chat

    from wedding_ops.deputy import Deputy
    chat = Chat(db, replace(settings, deputy=True), clock, queries, ops)
    chat.ingress.deputy = Deputy(queries, ops, chat.ingress.assistant, StubPlanner(), db, clock)
    clock.advance(6)
    chat.worker.tick()          # 17:51: the usher is pinged about the 17:50 task.
    chat.send("usher", "ok")    # A reply, not an acknowledgement.
    clock.advance(6)
    chat.worker.tick()
    news = coordinator_news(db)
    assert "Not acknowledged: \u201cTake position at Ballroom Entrance B\u201d" in news or "not acknowledged yet" in news


def test_the_coordinator_can_state_team_task_times(deputy_chat):
    planner = StubPlanner({"wat needs my attention now": DeputyPlan(
        answer="Ryan hasn't acknowledged Desk B signage, due 17:40.")})
    reply = deputy_chat(planner).send("coordinator", "wat needs my attention now").message
    assert reply == "Ryan hasn't acknowledged Desk B signage, due 17:40."
    assert "17:40 Confirm Desk B signage (Ryan Goh" in context_of(planner)


# Gate v5 findings ------------------------------------------------------------------------------------

def test_a_blocked_change_is_explained_not_drafted(deputy_chat):
    planner = StubPlanner({"dinner 30 late": DeputyPlan(answer="Drafted.", action="run_sheet_change", text="dinner", minutes=30)})
    # The coordinator gets the reason; a helper gets a report draft instead (live play v11 test file).
    reply = deputy_chat(planner).send("coordinator", "dinner 30 late")
    assert not reply.telegram_draft_id and "can't go through" in reply.message and "Couple's toast" in reply.message


def test_a_promised_draft_that_does_not_exist_is_corrected(deputy_chat):
    planner = StubPlanner({"nudge jamie": DeputyPlan(answer="Here's a nudge for Jamie. Tap Send.", action="send_message", to="Jamie")})
    reply = deputy_chat(planner).send("coordinator", "nudge jamie")
    assert not reply.telegram_draft_id and reply.message.startswith("I didn't make a draft for that.")


def test_the_unsent_draft_note_appears_once(deputy_chat):
    planner = StubPlanner({"car spoil": DeputyPlan(answer="Drafted.", action="tell_coordinator", text="Car flat tyre"),
                           "what time dinner": DeputyPlan(answer="Dinner is at 19:00.")})
    chat = deputy_chat(planner)
    chat.send("driver", "car spoil")
    assert "still unsent" in chat.send("driver", "what time dinner").message
    assert "still unsent" not in chat.send("driver", "what time dinner").message


def test_saying_on_it_acknowledges_my_task(deputy_chat, db):
    planner = StubPlanner({"ok on it": DeputyPlan(answer="Great.", action="acknowledge", text="Ballroom Entrance B")})
    reply = deputy_chat(planner).send("usher", "ok on it").message
    assert "Acknowledged your task: Take position at Ballroom Entrance B" in reply
    with db.sessions() as s:
        assert s.get(Task, "usher-ready").acknowledged_at is not None


def test_a_withdrawal_targets_the_report_named(deputy_chat, db):
    planner = StubPlanner({
        "mei lee missing": DeputyPlan(answer="Drafted.", action="tell_coordinator", text="Mei Lee not found"),
        "cancel the mei one": DeputyPlan(answer="Drafted.", action="withdraw_last", about="R1"),
    })
    chat = deputy_chat(planner)
    first = chat.send("family-liaison", "mei lee missing")
    chat.tap("family-liaison", f"confirm:{first.telegram_draft_id}")
    arrival = chat.send("family-liaison", "/arrival Grace Tan")
    chat.tap("family-liaison", f"confirm:{arrival.telegram_draft_id}")
    withdraw = chat.send("family-liaison", "cancel the mei one")
    assert "Take back your report: Mei Lee not found" in withdraw.message


def test_guest_status_reads_in_plain_words(deputy_chat):
    planner = StubPlanner({"sarah tan where": DeputyPlan(answer="Here.", find_guests=["Sarah Tan"])})
    assert "Sarah Tan: Table 18; not checked in yet" in deputy_chat(planner).send("usher", "sarah tan where").message


# Gate v4 findings ----------------------------------------------------------------------------------

def test_two_names_make_one_arrival_draft(deputy_chat, db):
    planner = StubPlanner({"robert and grace reach": DeputyPlan(answer="Drafted.", action="draft_arrival",
                                                                text="Robert Tan and Grace Tan")})
    chat = deputy_chat(planner)
    draft = chat.send("family-liaison", "robert and grace reach")
    assert "Record confirmed arrival for Robert Tan, Grace Tan." in draft.message
    chat.tap("family-liaison", f"confirm:{draft.telegram_draft_id}")
    with db.sessions() as s:
        assert {p.attendance for p in s.scalars(select(Person).where(Person.name.in_(["Robert Tan", "Grace Tan"])))} == {"onsite"}


def test_a_live_older_button_says_what_it_sends(deputy_chat):
    planner = StubPlanner({"car spoil": DeputyPlan(answer="Drafted.", action="tell_coordinator", text="Car flat tyre"),
                           "what time dinner": DeputyPlan(answer="Dinner is at 19:00.")})
    chat = deputy_chat(planner)
    chat.send("driver", "car spoil")
    reply = chat.send("driver", "what time dinner").message
    assert "Your earlier draft is still unsent. Its button sends only this: Send a problem report" in reply


def test_a_message_action_without_a_message_keeps_the_answer_and_asks_for_the_words(deputy_chat):
    planner = StubPlanner({"who never ack? chase jamie": DeputyPlan(
        answer="Jamie and Jordan have not acknowledged yet.", action="send_message", to="Jamie")})
    assert deputy_chat(planner).send("coordinator", "who never ack? chase jamie").message == (
        "Jamie and Jordan have not acknowledged yet.\nWhat should the message to Jamie say?")


def test_a_message_goes_only_to_people_the_coordinator_named(deputy_chat):
    # Live play v11: "Who is late and what is the current car situation?" drafted a message to
    # Chris and Asha. A question that names nobody gets its answer and no draft.
    planner = StubPlanner({"who never ack": DeputyPlan(answer="Jamie and Jordan have not acknowledged yet.",
                                                       action="send_message", to="Jamie", message="Please acknowledge.")})
    reply = deputy_chat(planner).send("coordinator", "who never ack")
    assert reply.message == "Jamie and Jordan have not acknowledged yet."


def test_the_coordinator_sees_who_has_not_acknowledged_as_a_record(deputy_chat, ops):
    ops.execute(Actor(WEDDING, "coordinator"), {"type": "broadcast", "team_ids": ["ushers", "transport"],
                "message": "Ceremony moves inside"}, "ack-record")
    planner = StubPlanner()
    chat = deputy_chat(planner)
    chat.worker.tick()
    chat.send("coordinator", "who never ack yet")
    trusted_part = context_of(planner).split("Coordinator brief")[0]
    assert ("[record] Not acknowledged: announcement sent 17:45 \u201cCeremony moves inside\u201d (0 of 2 acknowledged). "
            "Not yet: Jamie Lim, Jordan Tay") in trusted_part


def test_lookups_a_role_may_not_run_are_explained(deputy_chat):
    planner = StubPlanner({"where sarah sit": DeputyPlan(answer="Let me check.", find_guests=["Sarah Tan"])})
    assert "Guest seating is for the registration team and ushers." in deputy_chat(planner).send("mc", "where sarah sit").message


def test_the_couple_hear_about_a_venue_change_without_task_language(deputy_chat):
    planner = StubPlanner({"move ceremony to ballroom": DeputyPlan(
        answer="Here it is.", action="run_sheet_change", text="ceremony", place="Cedar Ballroom")})
    chat = deputy_chat(planner)
    draft = chat.send("coordinator", "move ceremony to ballroom")
    chat.tap("coordinator", f"confirm:{draft.telegram_draft_id}")
    notice = chat.last("couple", "schedule_info")
    assert "now at Cedar Ballroom" in notice.message and "tasks" not in notice.message and "Acknowledge" not in notice.message
