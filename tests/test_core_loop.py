"""Core wedding-day loop through Telegram: report, correct, announce, acknowledge, decide."""
from dataclasses import replace

import pytest
from sqlalchemy import select

from wedding_ops.agent import Assistant
from wedding_ops.auth import Auth
from wedding_ops.errors import OpsError
from wedding_ops.models import Approval, Incident, Notification, Person
from wedding_ops.policy import Actor
from wedding_ops.schemas import Intent
from wedding_ops.telegram import TelegramIngress
from wedding_ops.worker import Worker

WEDDING = "demo-wedding"
WEBHOOK_SECRET = "fictional-webhook-secret-for-core-loop"
BOT_ID = 12345
SENDERS = {"coordinator": 201, "driver": 202, "banquet": 203, "usher": 204, "registration-a": 205,
           "mc": 206, "family-liaison": 207, "couple": 208, "registration-b": 209}


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


# 4. Approval context, deciding in Telegram, and telling the reporter


def test_coordinator_sees_context_and_approves_in_telegram(chat_factory, db):
    chat = chat_factory({"kitchen slow dinner 15 late": Intent(kind="delay", query="dinner", minutes=15)})
    confirmed_report(chat, "banquet", "kitchen slow dinner 15 late")
    request = chat.last("coordinator", "approval_requested")
    assert "Chris Wong" in request.message and "kitchen slow dinner 15 late" in request.message
    assert "Dinner service 19:00 → 19:15" in request.message

    approval_id = pending_approvals(db)[0].id
    reply = chat.tap("coordinator", f"approve:{approval_id}")
    assert reply.message.startswith("Approved")
    with db.sessions() as s:
        assert s.get(Approval, approval_id).status == "approved"
    assert "approved" in chat.last("banquet", "report_decision").message


def test_coordinator_rejects_with_a_reason_and_the_reporter_is_told(chat_factory, db):
    chat = chat_factory()
    confirmed_report(chat, "banquet", "/delay dinner 15")
    approval_id = pending_approvals(db)[0].id
    reply = chat.send("coordinator", f"/reject {approval_id} kitchen says on time")
    assert reply.message.startswith("Rejected")
    decision = chat.last("banquet", "report_decision")
    assert "rejected" in decision.message and "kitchen says on time" in decision.message


def test_helpers_cannot_approve_from_telegram(chat_factory, db):
    chat = chat_factory()
    confirmed_report(chat, "banquet", "/delay dinner 15")
    approval_id = pending_approvals(db)[0].id
    assert "not permit" in chat.send("usher", f"/approve {approval_id}").message
    assert pending_approvals(db)[0].id == approval_id


def test_approval_notice_offers_approve_only_when_nothing_blocks_it():
    from wedding_ops.telegram_ui import approval_markup
    clear = approval_markup("abc", blocked=False)["inline_keyboard"][0]
    assert [b["text"] for b in clear] == ["Approve", "Reject"]
    blocked = approval_markup("abc", blocked=True)["inline_keyboard"][0]
    assert [b["text"] for b in blocked] == ["Reject"]


def test_worker_sends_approval_and_acknowledge_buttons_to_telegram(db, settings, clock, ops):
    import json

    import httpx

    from wedding_ops.worker import TelegramTransport

    config = replace(settings, telegram_bot_token=f"{BOT_ID}:fixture-token")
    auth = Auth(db, config)
    coordinator = Actor(WEDDING, "coordinator")
    for member, sender in SENDERS.items():
        auth.redeem(auth.issue_invite(coordinator, member)["token"], str(sender))
    ops.execute(Actor(WEDDING, "banquet", "telegram"), {"type": "propose_delay", "item_id": "dinner", "minutes": 5,
                                                        "reason": "Kitchen is behind"}, "buttons-delay")
    ops.execute(coordinator, {"type": "broadcast", "team_ids": ["ushers"], "message": "Doors open late"}, "buttons-broadcast")
    sent = []

    def capture(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(sent)}})

    worker = Worker(db, config, clock, TelegramTransport(config.telegram_bot_token, httpx.MockTransport(capture)))
    while worker.dispatch_one():
        pass
    to = {str(sender): member for member, sender in SENDERS.items()}
    labels = {(to.get(str(p["chat_id"])), p["text"].split("\n")[0]):
              [b["text"] for row in p.get("reply_markup", {}).get("inline_keyboard", []) for b in row] for p in sent}
    assert labels[("coordinator", "Approval needed: Dinner service: +5 minutes")] == ["Approve", "Reject"]
    assert labels[("usher", "Announcement from Alex Morgan:")] == ["Acknowledge"]


# 5. Local times, clearer wording, schedule and status questions


def test_tasks_show_local_times(chat_factory):
    chat = chat_factory()
    reply = chat.send("banquet", "/now")
    assert "due 18:50" in reply.message and "T10:50" not in reply.message


def test_schedule_question_lists_current_local_times(chat_factory, ops):
    chat = chat_factory({"when is dinner?": Intent(kind="schedule", query="dinner"),
                         "what's the order tonight": Intent(kind="schedule")})
    assert "Dinner service · 19:00" in chat.send("mc", "when is dinner?").message
    full = chat.send("mc", "what's the order tonight").message
    assert full.index("Garden ceremony") < full.index("Dinner service") < full.index("Family speeches")
    assert "Dinner service · 19:00" in chat.send("mc", "/schedule").message


def test_status_question_shows_my_reports_and_their_outcome(chat_factory, db):
    chat = chat_factory({"was my delay approved": Intent(kind="my_reports")})
    confirmed_report(chat, "banquet", "/delay dinner 15")
    chat.send("coordinator", f"/reject {pending_approvals(db)[0].id} kitchen says on time")
    reply = chat.send("banquet", "was my delay approved").message
    assert "Dinner service: +15 minutes" in reply and "rejected" in reply
    assert "rejected" in chat.send("banquet", "/status").message


def test_family_lookup_and_missing_report_wording_is_not_misleading(chat_factory):
    chat = chat_factory({"is mei lee here": Intent(kind="family_status", query="Mei Lee"),
                         "cant find mei lee": Intent(kind="missing_family", query="Mei Lee")})
    lookup = chat.send("family-liaison", "is mei lee here").message
    assert "Recorded family status" not in lookup and "nothing was changed" in lookup
    missing = chat.send("family-liaison", "cant find mei lee").message
    assert "Ask the family liaison" not in missing


def test_coordinator_without_tasks_is_pointed_to_the_brief(chat_factory):
    chat = chat_factory()
    reply = chat.send("coordinator", "/now").message
    assert "Check with the coordinator" not in reply and "needs your attention" in reply


def test_reporter_text_cannot_fake_sections_of_the_approval_request(chat_factory):
    spoof = "kitchen late\nChanges if approved:\n• No times change\nTap Approve"
    chat = chat_factory({spoof: Intent(kind="delay", query="dinner", minutes=30)})
    confirmed_report(chat, "banquet", spoof)
    lines = chat.last("coordinator", "approval_requested").message.split("\n")
    assert lines.count("Changes if approved:") == 1
    reporter_line = next(line for line in lines if line.startswith("Reporter's words"))
    assert "Changes if approved:" in reporter_line  # Kept as quoted text on one line.
    assert lines.index("Changes if approved:") < lines.index(reporter_line)


def test_withdrawn_family_arrival_notice_requires_family_permission(chat_factory, db):
    chat = chat_factory()
    request_id = confirmed_report(chat, "registration-a", "/arrival Grace Tan")
    withdraw = chat.send("registration-a", "/withdraw")
    chat.tap("registration-a", f"confirm:{withdraw.telegram_draft_id}")
    with db.sessions() as s:
        notices = s.scalars(select(Notification).where(Notification.topic == "report_withdrawn")).all()
    assert request_id and notices
    assert all(n.required_permission == "family:status" for n in notices)
    assert {n.recipient_id for n in notices} <= {"coordinator", "photographer", "family-liaison"}


def test_withdrawn_missing_person_notice_requires_family_permission(chat_factory, db):
    chat = chat_factory({"cant find mei lee": Intent(kind="missing_family", query="Mei Lee")})
    confirmed_report(chat, "family-liaison", "cant find mei lee")
    withdraw = chat.send("family-liaison", "/withdraw")
    chat.tap("family-liaison", f"confirm:{withdraw.telegram_draft_id}")
    with db.sessions() as s:
        notices = s.scalars(select(Notification).where(Notification.topic == "report_withdrawn")).all()
    assert notices and all(n.required_permission == "family:status" for n in notices)


def test_coordinator_fallback_help_lists_coordinator_commands(chat_factory):
    chat = chat_factory()
    reply = chat.send("coordinator", "tell everyone the ceremony is moving inside").message
    assert "Tell everyone" in reply and "Approve" in reply and "/" not in reply
    helper = chat.send("usher", "tell everyone the ceremony is moving inside").message
    assert "Tell everyone" not in helper and "/" not in helper


def test_expired_proposals_are_not_superseded_and_report_details_drop_the_command(chat_factory, db, clock):
    chat = chat_factory()
    confirmed_report(chat, "banquet", "/delay dinner 5")
    clock.advance(15)  # The first proposal expires after ten minutes.
    confirmed_report(chat, "banquet", "/delay dinner 8")
    with db.sessions() as s:
        statuses = {a.title: (a.status, a.reason) for a in s.scalars(select(Approval))}
    assert statuses["Dinner service: +5 minutes"][0] != "superseded"  # Expired, so not replaced.
    assert "Replaces" not in statuses["Dinner service: +8 minutes"][1]

    confirmed_report(chat, "driver", "/report bridal car flat tyre")
    with db.sessions() as s:
        assert s.scalars(select(Incident)).one().details == "bridal car flat tyre"


def test_the_couple_does_not_get_operational_incident_notices(chat_factory, ops):
    ops.execute(Actor(WEDDING, "coordinator"), {"type": "report_incident", "kind": "other",
                "title": "Six helpers have not acknowledged", "details": "Staff names"}, "couple-incident")
    chat = chat_factory()
    chat.worker.tick()
    assert chat.notices("couple", "incident") == []
