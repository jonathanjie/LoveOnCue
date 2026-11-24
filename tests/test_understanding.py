"""Understanding what people mean, and never leaving them at a dead end."""
from sqlalchemy import select
from test_core_loop import (  # noqa: F401  (fixture)
    chat_factory,
    confirmed_report,
    pending_approvals,
)

from wedding_ops.models import Incident
from wedding_ops.schemas import Intent


def test_my_tasks_say_where_to_go_and_what_to_do(chat_factory):
    reply = chat_factory().send("usher", "/now").message
    assert "Ballroom Entrance B" in reply and "Direct guests to the garden terrace" in reply


def test_lateness_reaches_the_coordinator(chat_factory, db):
    chat = chat_factory({"stuck in traffic, 25 min late": Intent(kind="late", minutes=25)})
    draft = chat.send("mc", "stuck in traffic, 25 min late")
    assert "Taylor Ng is running about 25 minutes late" in draft.message
    chat.tap("mc", f"confirm:{draft.telegram_draft_id}")
    from test_core_loop import coordinator_news
    assert "Taylor Ng is running about 25 minutes late" in coordinator_news(db)
    with db.sessions() as s:
        assert s.scalars(select(Incident)).one().reported_by == "mc"


def test_a_delay_without_an_activity_uses_my_last_delay_report(chat_factory, db):
    chat = chat_factory({"kitchen now 20 not 15": Intent(kind="delay", query="", minutes=20)})
    confirmed_report(chat, "banquet", "/delay dinner 15")
    draft = chat.send("banquet", "kitchen now 20 not 15")
    assert "Dinner service 19:00 \u2192 19:20" in draft.message and "replaces your pending request" in draft.message


def test_guest_lookup_forgives_honorifics_and_nicknames(chat_factory):
    chat = chat_factory({"where does auntie sarah sit": Intent(kind="guest", query="auntie sarah")})
    assert "Sarah Tan: Table 18" in chat.send("usher", "where does auntie sarah sit").message
    many = chat.send("usher", "/guest Mr Lee").message
    assert "guests match" in many and "full name" in many


def test_location_lookup_understands_everyday_words(chat_factory):
    chat = chat_factory({"where are the toilets": Intent(kind="location", query="toilets"),
                         "which door is entrance b": Intent(kind="location", query="entrance b")})
    assert "Restrooms" in chat.send("usher", "where are the toilets").message
    assert "Ballroom Entrance B" in chat.send("usher", "which door is entrance b").message
    listing = chat.send("usher", "/location").message
    assert "Cedar Ballroom" in listing and "Restrooms" in listing


def test_headcount_for_people_who_handle_guests(chat_factory):
    chat = chat_factory({"how many guests are here": Intent(kind="headcount")})
    assert "guests are recorded as onsite" in chat.send("registration-a", "how many guests are here").message


def test_denials_explain_the_role_and_who_to_ask(chat_factory):
    reply = chat_factory().send("usher", "/announce free drinks").message
    assert "does not permit" in reply and "usher" in reply and "Alex Morgan" in reply


def test_no_match_advice_does_not_point_people_back_at_themselves(chat_factory):
    reply = chat_factory().send("registration-a", "/guest Benjamin Wu").message
    assert "Ask registration" not in reply and "Alex Morgan" in reply
