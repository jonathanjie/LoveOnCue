"""Code-written replies say who was actually told (live play v9, docs/plans/2026-11-22-deputy-claim-check.md).

Before, "Arrival recorded. The family liaison and photographer have been told." and "Everyone who
was told has been told to ignore it." were fixed text, true only for some records.
"""
from test_deputy import StubPlanner, deputy_chat  # noqa: F401  (fixture)

from wedding_ops.deputy import DeputyPlan


def test_an_arrival_names_who_was_told(deputy_chat):  # noqa: F811
    chat = deputy_chat(StubPlanner())
    guest = chat.tap("registration-a", f"confirm:{chat.send('registration-a', '/arrival Sarah Tan').telegram_draft_id}")
    # A regular guest's arrival is not announced to anyone.
    assert guest.message == "Arrival recorded\nIt is in the records. Nobody else is notified."
    family = chat.tap("registration-a", f"confirm:{chat.send('registration-a', '/arrival Grace Tan').telegram_draft_id}")
    assert family.message.startswith("Arrival recorded\n") and "Priya Rao" in family.message


def test_taking_back_a_question_says_question_and_tells_nobody_else(deputy_chat):  # noqa: F811
    chat = deputy_chat(StubPlanner({"speech order how": DeputyPlan(answer="The records don't say.")}))
    chat.tap("mc", f"confirm:{chat.send('mc', 'speech order how').ask_draft_id}")
    draft = chat.send("mc", "/withdraw")
    assert "Take back your question: speech order how." in draft.message and "ignore it" not in draft.message
    done = chat.tap("mc", f"confirm:{draft.telegram_draft_id}")
    assert done.message == ("Withdrawn\nYour question (speech order how) is taken back. "
                            "The coordinator sees this in their next update.")


def test_a_message_to_one_person_says_one_person(deputy_chat):  # noqa: F811
    chat = deputy_chat(StubPlanner({"tell asha speeches stay after dinner": DeputyPlan(
        action="send_message", to="Asha", message="Speeches stay after dinner.")}))
    sent = chat.tap("coordinator", f"confirm:{chat.send('coordinator', 'tell asha speeches stay after dinner').telegram_draft_id}")
    assert sent.message.startswith("Message sent\n1 person gets it")
