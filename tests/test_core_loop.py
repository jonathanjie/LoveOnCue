"""Core wedding-day loop through Telegram: report, correct, announce, acknowledge, decide."""
from dataclasses import replace

import pytest
from sqlalchemy import select

from wedding_ops.agent import Assistant
from wedding_ops.errors import OpsError
from wedding_ops.auth import Auth
from wedding_ops.models import Approval, Incident, Notification, Person
from wedding_ops.policy import Actor
from wedding_ops.schemas import Intent
from wedding_ops.telegram import TelegramIngress
from wedding_ops.worker import Worker

WEDDING = "demo-wedding"
WEBHOOK_SECRET = "fictional-webhook-secret-for-core-loop"
BOT_ID = 12345
SENDERS = {"coordinator": 201, "driver": 202, "banquet": 203, "usher": 204, "registration-a": 205}


class StubParser:
    """Stands in for the model: maps exact messages to intents."""

    def __init__(self, intents: dict[str, Intent]):
        self.intents = intents

    def parse(self, text: str) -> Intent:
        return self.intents.get(text, Intent(kind="unknown"))


class Chat:
    """Drives the real Telegram ingress for several enrolled fixture members."""

    def __init__(self, db, settings, clock, queries, ops, intents=None):
        self.db, self.clock = db, clock
        self.config = replace(settings, telegram_webhook_secret=WEBHOOK_SECRET,
                              telegram_bot_token=f"{BOT_ID}:fixture-token")
        auth = Auth(db, self.config)
        coordinator = Actor(WEDDING, "coordinator")
        for member, sender in SENDERS.items():
            auth.redeem(auth.issue_invite(coordinator, member)["token"], str(sender))
        parser = StubParser(intents or {})
        self.ingress = TelegramIngress(db, self.config, clock, auth, Assistant(queries, ops, parser), ops)
        self.worker = Worker(db, self.config, clock)
        self.update_id = 0

    def _deliver(self, member: str, update: dict) -> Notification:
        """Process one update and return the bot reply it created."""
        before = {n.id for n in self.notices(member, "bot_reply")}
        self.update_id += 1
        update["update_id"] = self.update_id
        self.ingress.accept(WEBHOOK_SECRET, update)
        while self.ingress.process_one():
            pass
        self.worker.tick()  # Deliver queued notices, so people can act on them.
        created = [n for n in self.notices(member, "bot_reply") if n.id not in before]
        assert len(created) == 1, f"expected one reply, got {len(created)}"
        return created[0]

    def send(self, member: str, text: str) -> Notification:
        sender = SENDERS[member]
        return self._deliver(member, {"message": {"from": {"id": sender},
                                                  "chat": {"id": sender, "type": "private"}, "text": text}})

    def tap(self, member: str, data: str) -> Notification:
        sender = SENDERS[member]
        return self._deliver(member, {"callback_query": {
            "id": f"cb-{self.update_id}", "data": data, "from": {"id": sender},
            "message": {"chat": {"id": sender, "type": "private"}, "from": {"id": BOT_ID, "is_bot": True}}}})

    def last(self, member: str, topic: str) -> Notification:
        """The newest notice of a topic. Only use when one such notice is expected."""
        notices = self.notices(member, topic)
        assert notices, f"no {topic} notice for {member}"
        return notices[-1]

    def notices(self, member: str, topic: str) -> list[Notification]:
        with self.db.sessions() as s:
            return s.scalars(select(Notification).where(
                Notification.recipient_id == member, Notification.topic == topic)).all()


@pytest.fixture
def chat_factory(db, settings, clock, queries, ops):
    return lambda intents=None: Chat(db, settings, clock, queries, ops, intents)


# 1. Incident reports from chat


def test_free_form_problem_report_reaches_the_coordinator_once_confirmed(chat_factory, db):
    chat = chat_factory({"help car spoil flat tyre": Intent(kind="urgent_incident", query="Bridal car flat tyre")})
    reply = chat.send("driver", "help car spoil flat tyre")
    assert reply.telegram_draft_id and "Bridal car flat tyre" in reply.message

    confirmed = chat.tap("driver", f"confirm:{reply.telegram_draft_id}")
    assert "Report sent" in confirmed.message
    with db.sessions() as s:
        incident = s.scalars(select(Incident)).one()
    assert incident.severity == "urgent" and incident.reported_by == "driver"
    notice = chat.last("coordinator", "incident")
    assert "Bridal car flat tyre" in notice.message and "Jordan Tay" in notice.message


def test_report_command_works_without_the_model(chat_factory, db):
    chat = chat_factory()
    reply = chat.send("banquet", "/report two vegetarian meals missing for table 18")
    assert reply.telegram_draft_id
    chat.tap("banquet", f"confirm:{reply.telegram_draft_id}")
    with db.sessions() as s:
        assert s.scalars(select(Incident)).one().title.startswith("two vegetarian meals missing")


def test_a_repeat_report_warns_about_the_earlier_one(chat_factory):
    chat = chat_factory({
        "FLAT TYRE": Intent(kind="urgent_incident", query="Flat tyre"),
        "car cannot move": Intent(kind="incident", query="Car cannot move"),
    })
    first = chat.send("driver", "FLAT TYRE")
    chat.tap("driver", f"confirm:{first.telegram_draft_id}")
    second = chat.send("driver", "car cannot move")
    assert "You already reported" in second.message and "Flat tyre" in second.message


# 2. Withdraw a report; a new delay replaces an older pending one


def pending_approvals(db):
    with db.sessions() as s:
        return s.scalars(select(Approval).where(Approval.status == "pending")).all()


def test_a_newer_delay_report_replaces_the_pending_one_for_the_same_item(chat_factory, db):
    chat = chat_factory()
    for minutes in (20, 10):
        draft = chat.send("banquet", f"/delay dinner {minutes}")
        chat.tap("banquet", f"confirm:{draft.telegram_draft_id}")
    live = pending_approvals(db)
    assert [a.title for a in live] == ["Dinner service: +10 minutes"]
    assert "Replaces" in live[0].reason and "+20" in live[0].reason
    with db.sessions() as s:
        older = s.scalars(select(Approval).where(Approval.title == "Dinner service: +20 minutes")).one()
    assert older.status == "superseded"


def test_withdraw_cancels_my_last_pending_delay(chat_factory, db):
    chat = chat_factory({"cancel my last report": Intent(kind="withdraw")})
    draft = chat.send("banquet", "/delay dinner 15")
    chat.tap("banquet", f"confirm:{draft.telegram_draft_id}")
    withdraw = chat.send("banquet", "cancel my last report")
    assert "Dinner service: +15 minutes" in withdraw.message and withdraw.telegram_draft_id
    done = chat.tap("banquet", f"confirm:{withdraw.telegram_draft_id}")
    assert "Withdrawn" in done.message
    assert pending_approvals(db) == []
    assert "Withdrawn" in chat.last("coordinator", "report_withdrawn").message


def test_withdraw_reverts_a_wrong_arrival(chat_factory, db):
    chat = chat_factory()
    draft = chat.send("registration-a", "/arrival Grace Tan")
    chat.tap("registration-a", f"confirm:{draft.telegram_draft_id}")
    withdraw = chat.send("registration-a", "/withdraw")
    chat.tap("registration-a", f"confirm:{withdraw.telegram_draft_id}")
    with db.sessions() as s:
        assert s.scalars(select(Person).where(Person.name == "Grace Tan")).one().attendance == "unknown"


def test_withdraw_closes_my_open_incident_and_cannot_repeat(chat_factory, db):
    chat = chat_factory()
    draft = chat.send("driver", "/report flat tyre")
    chat.tap("driver", f"confirm:{draft.telegram_draft_id}")
    withdraw = chat.send("driver", "/withdraw")
    chat.tap("driver", f"confirm:{withdraw.telegram_draft_id}")
    with db.sessions() as s:
        assert s.scalars(select(Incident)).one().status == "resolved"
    assert "nothing to withdraw" in chat.send("driver", "/withdraw").message.lower()


# 3. Coordinator announcement and acknowledgement in Telegram


def test_coordinator_announces_and_helpers_acknowledge(chat_factory, db, queries):
    chat = chat_factory()
    draft = chat.send("coordinator", "/announce Rain: ceremony moves to the Cedar Ballroom at 18:40")
    assert draft.telegram_draft_id and "everyone" in draft.message.lower()
    sent = chat.tap("coordinator", f"confirm:{draft.telegram_draft_id}")
    assert "Announcement sent" in sent.message

    notice = chat.last("usher", "coordinator_message")
    assert "Cedar Ballroom" in notice.message and "Acknowledge" in notice.message
    assert chat.notices("coordinator", "coordinator_message") == []

    reply = chat.tap("usher", f"ack:{notice.id}")
    assert reply.message.startswith("Acknowledged")
    assert "Acknowledged" in chat.send("driver", "/ack").message

    brief = queries.coordinator_brief(Actor(WEDDING, "coordinator"))
    unacknowledged = [detail for title, detail in brief["followups"] if title.startswith("Not acknowledged")]
    assert unacknowledged and "Jamie Lim" not in unacknowledged[0] and "Jordan Tay" not in unacknowledged[0]


def test_helpers_cannot_announce(chat_factory):
    chat = chat_factory()
    assert "not permit" in chat.send("usher", "/announce free drinks for all").message


def test_ack_with_nothing_pending_says_so(chat_factory):
    chat = chat_factory()
    assert "Nothing to acknowledge" in chat.send("usher", "/ack").message


def test_notices_that_need_acknowledgement_get_an_acknowledge_button():
    from wedding_ops.telegram_ui import notice_markup
    markup = notice_markup("coordinator_message", "abc123")
    assert markup == {"inline_keyboard": [[{"text": "Acknowledge", "callback_data": "ack:abc123"}]]}
    assert notice_markup("task_reminder", "abc123") is None


# Withdrawal safety: time window, newer changes, and incidents closed by an arrival


def confirmed_report(chat, member, text):
    draft = chat.send(member, text)
    chat.tap(member, f"confirm:{draft.telegram_draft_id}")
    return f"draft:{draft.telegram_draft_id}"


def test_withdraw_is_refused_after_the_window(chat_factory, ops, clock):
    chat = chat_factory()
    request_id = confirmed_report(chat, "driver", "/report flat tyre")
    clock.advance(31)
    with pytest.raises(OpsError, match="no longer be withdrawn"):
        ops.execute(Actor(WEDDING, "driver"), {"type": "withdraw_report", "request_id": request_id}, "late-withdraw")


def test_withdraw_does_not_overwrite_a_newer_arrival_change(chat_factory, ops, db):
    chat = chat_factory()
    request_id = confirmed_report(chat, "registration-a", "/arrival Grace Tan")
    with db.sessions() as s:
        grace = s.scalars(select(Person).where(Person.name == "Grace Tan")).one().id
    ops.execute(Actor(WEDDING, "coordinator"), {"type": "arrival", "person_ids": [grace], "status": "departed"}, "left-early")
    with pytest.raises(OpsError, match="changed since"):
        ops.execute(Actor(WEDDING, "registration-a"), {"type": "withdraw_report", "request_id": request_id}, "stale-withdraw")


def test_withdrawing_an_arrival_reopens_the_missing_person_report_it_closed(chat_factory, ops, db):
    chat = chat_factory()
    with db.sessions() as s:
        mei = s.scalars(select(Person).where(Person.name == "Mei Lee")).one().id
    ops.execute(Actor(WEDDING, "coordinator"), {"type": "report_incident", "kind": "location_unconfirmed",
                                                "title": "Locate Mei Lee", "details": "Not seen", "subject_person_id": mei},
                "missing-mei")
    request_id = confirmed_report(chat, "registration-a", "/arrival Mei Lee")
    ops.execute(Actor(WEDDING, "registration-a"), {"type": "withdraw_report", "request_id": request_id}, "undo-mei")
    with db.sessions() as s:
        assert s.scalars(select(Incident).where(Incident.title == "Locate Mei Lee")).one().status == "open"
