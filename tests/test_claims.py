"""The claim check: facts in model-written text must trace to records or the person's words."""

from sqlalchemy import select
from test_deputy import StubPlanner, deputy_chat  # noqa: F401  (fixture)

from wedding_ops.claims import (
    Support,
    check_answer,
    facts,
    from_their_words,
    is_confirmation,
    self_acts,
    without_quotes,
)
from wedding_ops.deputy import CANNOT_CONFIRM, DeputyPlan

NAMES = {"cedar ballroom", "garden terrace", "sarah tan", "noah lim", "alex"}


# The extractor -------------------------------------------------------------------------------

def test_clock_times_are_read_in_every_common_form():
    found = {fact.shown: fact.forms for fact in facts("18:40, 6.40pm, 6:40 pm and 7pm", set())}
    assert found["18:40"] == {"time:18:40"}
    assert found["6.40pm"] == {"time:18:40"} and found["6:40 pm"] == {"time:18:40"}
    assert found["7pm"] == {"time:19:00"}
    assert len(found) == 4  # "40pm" inside "6:40 pm" is not read again as an hour


def test_a_time_without_am_or_pm_matches_either_half_of_the_day():
    support = Support("[run sheet] - 19:15 Dinner service", set())
    assert support.missing("Dinner is 7.15", set()) == []
    assert support.missing("Dinner is 8.15", set()) == ["8.15"]


def test_tables_counts_references_and_known_names_are_facts():
    shown = {fact.shown for fact in facts("Sarah Tan sits at Table 18; 44 of 180 onsite; see R2.", NAMES)}
    assert shown == {"sarah tan", "Table 18", "44 of 180", "R2"}


def test_quoted_words_do_not_support_facts():
    line = without_quotes("R1 18:02 question “dinner at 21:00?”: open")
    assert Support(line, set()).missing("Dinner is at 21:00.", set()) == ["21:00"]


def test_a_name_the_person_just_used_may_be_echoed_but_not_given_a_table():
    support = Support("[record] Places: Cedar Ballroom", NAMES, extra_names="where sarah tan sit")
    assert support.missing("Let me look up Sarah Tan.", NAMES) == []
    assert support.missing("Sarah Tan is at Table 18.", NAMES) == ["Table 18"]


# The answer check ----------------------------------------------------------------------------

def test_only_the_sentence_with_an_unsupported_fact_is_removed():
    support = Support("[run sheet] - 18:30 Garden ceremony at Garden terrace.", NAMES)
    checked = check_answer("The ceremony is at 18:30 at Garden terrace. Guests wait in Cedar Ballroom.", support, NAMES)
    assert checked.text == "The ceremony is at 18:30 at Garden terrace."
    assert checked.removed == ["Guests wait in Cedar Ballroom."]


def test_sentences_stating_a_reports_status_are_left_to_code():
    support = Support("R1 17:46 run-sheet request: approved", NAMES, {"R1"})
    checked = check_answer("Your request R1 is still pending with Alex. Dinner is on the run sheet.", support, NAMES)
    assert checked.text == "Dinner is on the run sheet."
    assert checked.status == ["Your request R1 is still pending with Alex."] and checked.status_references == {"R1"}


def test_first_person_acts_are_counted():
    assert self_acts("I'll flag it to the coordinator now. I'm sending it. Tap Send.") == 2
    assert self_acts("I'll put that to everyone. Let me check her table. I've told Alex.") == 3
    assert self_acts("Here's the report. Tap Send if it looks right. I'm not sure of the time.") == 0


def test_a_name_passed_on_must_come_from_the_persons_words():
    assert from_their_words("Sarah Tan", "auntie sarah where she sit")
    assert not from_their_words("Noah Lim", "benjamin wu table?")
    assert from_their_words("Lee", "Mr Lee where his seat ah")


# In the deputy -------------------------------------------------------------------------------

def test_an_invented_instruction_is_removed_and_the_rest_kept(deputy_chat):  # noqa: F811
    planner = StubPlanner({"where guests go": DeputyPlan(
        answer="The ceremony is at the Garden terrace. Keep guests in the Cedar Ballroom until 18:20.")})
    message = deputy_chat(planner).send("usher", "where guests go").message
    assert "Garden terrace" in message and "18:20" not in message


def test_the_clock_line_does_not_support_a_time_but_say_time_states_it(deputy_chat):  # noqa: F811
    planner = StubPlanner({
        "how long more": DeputyPlan(answer="The car arrived at 17:45."),
        "what time now": DeputyPlan(say_time=True),
    })
    chat = deputy_chat(planner)
    assert "17:45" not in chat.send("driver", "how long more").message
    assert chat.send("driver", "what time now").message.startswith("It's 17:45 now.")


def test_a_reports_status_comes_from_the_record_not_the_model(deputy_chat):  # noqa: F811
    planner = StubPlanner({
        "car spoil": DeputyPlan(action="tell_coordinator", text="Bridal car flat tyre"),
        "alex see already?": DeputyPlan(answer="Yes, Alex has answered your report."),
    })
    chat = deputy_chat(planner)
    chat.tap("driver", f"confirm:{chat.send('driver', 'car spoil').telegram_draft_id}")
    message = chat.send("driver", "alex see already?").message
    assert "answered" not in message
    assert "Your " in message and "“Bridal car flat tyre”: open." in message


def test_status_asked_by_reference_is_stated_from_the_record(deputy_chat):  # noqa: F811
    planner = StubPlanner({
        "car spoil": DeputyPlan(action="tell_coordinator", text="Bridal car flat tyre"),
        "my report how": DeputyPlan(status_of=["R1"]),
    })
    chat = deputy_chat(planner)
    chat.tap("driver", f"confirm:{chat.send('driver', 'car spoil').telegram_draft_id}")
    assert "“Bridal car flat tyre”: open." in chat.send("driver", "my report how").message


def test_an_answer_with_nothing_supported_says_so_and_offers_to_ask(deputy_chat):  # noqa: F811
    planner = StubPlanner({"which table uncle lee": DeputyPlan(answer="He is at Table 99.")})
    reply = deputy_chat(planner).send("usher", "which table uncle lee")
    assert reply.message == CANNOT_CONFIRM + "\nTap Ask the coordinator to send them this message."
    assert reply.telegram_draft_id


def test_a_table_from_this_messages_lookup_supports_the_answer(deputy_chat):  # noqa: F811
    planner = StubPlanner({"sarah tan table?": DeputyPlan(answer="Sarah Tan is at Table 18.", find_guests=["Sarah Tan"])})
    message = deputy_chat(planner).send("usher", "sarah tan table?").message
    assert message.startswith("Sarah Tan is at Table 18.") and "• Sarah Tan: Table 18" in message


def test_an_outcome_claim_beside_a_draft_is_removed_and_nothing_replaces_it(deputy_chat):  # noqa: F811
    planner = StubPlanner({"mic spoil": DeputyPlan(answer="Noted, the mic report is recorded.",
                                                   action="tell_coordinator", text="Mic broken")})
    message = deputy_chat(planner).send("mc", "mic spoil").message
    # The draft under the reply is its status; a claim about it before the tap is never true.
    assert "recorded" not in message and "no reports" not in message
    assert message.startswith("Nothing is sent until you tap the button.")


def test_an_answer_stays_beside_a_report_but_not_beside_a_run_sheet_change(deputy_chat):  # noqa: F811
    planner = StubPlanner({
        "who i call, car spoil": DeputyPlan(answer="The emergency contact is on record below.", action="tell_coordinator",
                                            level="urgent", text="Bridal car broken"),
        "kitchen late, dinner 15 min later": DeputyPlan(answer="Dinner service is at 19:00.", action="run_sheet_change",
                                                        text="dinner", minutes=15),
    })
    chat = deputy_chat(planner)
    assert chat.send("driver", "who i call, car spoil").message.startswith("The emergency contact is on record below.")
    change = chat.send("banquet", "kitchen late, dinner 15 min later").message
    # The preview says 19:00 → 19:15; an answer saying "19:00" beside it would read as a contradiction.
    assert not change.startswith("Dinner service is at 19:00.") and "19:00 \u2192 19:15" in change


def test_offers_to_act_in_any_mood_are_first_person_acts():
    assert self_acts("I can flag this to the coordinator. Want me to ask Alex? I've taken back that report.") == 3
    assert self_acts("I can look up a guest's seat if you give me a name.") == 0


def test_a_sentence_naming_an_action_is_removed(deputy_chat):  # noqa: F811
    planner = StubPlanner({"where i stand": DeputyPlan(
        answer="Stand at Ballroom Entrance B. I can use tell_coordinator if you need more.")})
    message = deputy_chat(planner).send("usher", "where i stand").message
    assert message == "Stand at Ballroom Entrance B."


def test_a_message_with_an_unsupported_table_is_not_drafted(deputy_chat):  # noqa: F811
    planner = StubPlanner({"tell ushers vip at front": DeputyPlan(
        action="send_message", to="Ushers", message="VIPs sit at Table 99.")})
    reply = deputy_chat(planner).send("coordinator", "tell ushers vip at front")
    assert not reply.telegram_draft_id and "exact wording" in reply.message


def test_a_question_title_cannot_ground_a_coordinator_answer(deputy_chat, ops, db):  # noqa: F811
    from wedding_ops.models import Incident
    from wedding_ops.policy import Actor
    ops.execute(Actor("demo-wedding", "usher", "telegram"), {
        "type": "report_incident", "kind": "question", "title": "Is dinner at 21:30?", "details": "x"}, "q-time")
    with db.sessions() as s:
        assert s.scalars(select(Incident)).one().kind == "question"
    planner = StubPlanner({"dinner when": DeputyPlan(answer="Dinner is at 21:30.")})
    assert "21:30" not in deputy_chat(planner).send("coordinator", "dinner when").message


def test_a_drafts_status_is_stated_by_code_from_the_pending_draft(deputy_chat):  # noqa: F811
    planner = StubPlanner({
        "mic spoil": DeputyPlan(action="tell_coordinator", text="Mic broken"),
        "sent or not": DeputyPlan(answer="Your report was sent to Alex."),
    })
    chat = deputy_chat(planner)
    chat.send("mc", "mic spoil")
    message = chat.send("mc", "sent or not").message
    assert "was sent" not in message
    assert message.count("Its button sends only this: Send a problem report") == 1


def test_a_promise_to_act_without_a_draft_is_removed_and_nothing_is_implied(deputy_chat):  # noqa: F811
    planner = StubPlanner({"tell alex the mic spoil": DeputyPlan(answer="I'll let Alex know right away.")})
    message = deputy_chat(planner).send("mc", "tell alex the mic spoil").message
    assert "let Alex know" not in message and message.startswith("I haven't done anything with that.")


def test_an_empty_answer_with_no_action_never_says_okay(deputy_chat):  # noqa: F811
    planner = StubPlanner({"how many guests arrived": DeputyPlan()})
    assert deputy_chat(planner).send("registration-a", "how many guests arrived").message.startswith("I haven't done")


def test_a_record_time_moved_by_the_persons_duration_is_supported():
    support = Support("[run sheet] - 19:00 Dinner service", set(), shifts_from="dinner pushed 15 min")
    assert support.missing("Dinner is now at 19:15.", set()) == []
    assert support.missing("Dinner is now at 19:20.", set()) == ["19:20"]


def test_only_a_confirmation_can_acknowledge_without_a_tap():
    for text in ["ok noted", "on it", "ok can \U0001f44d", "got it boss", "roger"]:
        assert is_confirmation(text), text
    for text in ["eh where i stand ah", "eh what i need do ah", "ok but when?", "how many guests arrived so far"]:
        assert not is_confirmation(text), text


def test_a_question_after_a_ping_is_answered_not_acknowledged(deputy_chat, db):  # noqa: F811
    from wedding_ops.models import Task
    planner = StubPlanner({"eh where i stand ah": DeputyPlan(answer="Ballroom Entrance B.", action="acknowledge")})
    deputy_chat(planner).send("usher", "eh where i stand ah")
    with db.sessions() as s:
        assert all(t.acknowledged_at is None for t in s.scalars(select(Task).where(Task.owner_id == "usher")))
