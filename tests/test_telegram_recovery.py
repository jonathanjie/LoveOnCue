from dataclasses import replace
import json

import httpx
from sqlalchemy import select

from wedding_ops.agent import Assistant
from wedding_ops.auth import Auth
from wedding_ops.models import Approval, InboundUpdate, Notification
from wedding_ops.operations import notify
from wedding_ops.policy import Actor
from wedding_ops.telegram import TelegramIngress
from wedding_ops.worker import TelegramTransport, Worker


WEDDING = "demo-wedding"
WEBHOOK_SECRET = "fictional-webhook-secret-for-tests"
BOT_ID = 12345


def test_recovered_brief_is_coordinator_only(db, settings, clock, queries, ops):
    config = replace(settings, telegram_webhook_secret=WEBHOOK_SECRET)
    ingress = TelegramIngress(db, config, clock, Auth(db, config), Assistant(queries, ops), ops)
    coordinator = Actor(WEDDING, "coordinator")
    auth = Auth(db, config)
    for sender, member in [(101, "coordinator"), (102, "registration-a")]:
        auth.redeem(auth.issue_invite(coordinator, member)["token"], str(sender))
    clock.advance(12)
    ops.execute(coordinator, {"type": "propose_delay", "item_id": "dinner", "minutes": 12,
                             "reason": "Fictional delay"}, "brief-delay-fixture")
    with db.transaction(WEDDING, write=True) as (session, _):
        notify(session, WEDDING, "registration-a", "task_reminder", "Fictional instruction",
               "brief-delivery-fixture", clock.now())
        session.flush()
        notice = session.scalar(select(Notification).where(Notification.dedupe_key.like("brief-delivery-fixture:%")))
        notice.state = "failed"
    for number, sender, command in [(1, 101, "/brief"), (2, 101, "/brief_more"), (3, 102, "/brief")]:
        ingress.accept(WEBHOOK_SECRET, message_update(number, sender, text=command))
        assert ingress.process_one()

    short, full, denial = replies(db)
    assert short.message.startswith("Coordinator brief\n")
    assert "urgent" in short.message and "Confirm Desk B signage" in short.message
    assert "More details: /brief_more" in short.message
    assert short.required_permission == "timeline:approve"
    assert full.message.startswith("Coordinator brief\n")
    assert "Latest summary: /brief" in full.message
    assert "Unfinished prerequisites: Confirm Desk B signage" in full.message
    assert "Dinner service" in full.message and "1 delivery problem" in full.message
    assert "availability" in full.message.lower()
    assert "does not permit" in denial.message
    assert "signage" not in denial.message


def test_inline_confirmation_survives_outbox_and_uses_actor_authorization(db, settings, clock, queries, ops):
    config = replace(settings, telegram_webhook_secret=WEBHOOK_SECRET, telegram_bot_token="12345:fixture")
    auth = Auth(db, config)
    ingress = TelegramIngress(db, config, clock, auth, Assistant(queries, ops), ops)
    coordinator = Actor(WEDDING, "coordinator")
    for sender, member in [(101, "banquet"), (102, "coordinator")]:
        auth.redeem(auth.issue_invite(coordinator, member)["token"], str(sender))
    revision = queries.snapshot(coordinator)["wedding"]["timeline_version"]

    ingress.accept(WEBHOOK_SECRET, message_update(1, 101, text="/delay dinner 12"))
    assert ingress.process_one()
    draft = replies(db)[0].telegram_draft_id
    assert draft

    sent = []
    def send_fixture(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 17}})
    worker = Worker(db, config, clock, TelegramTransport(config.telegram_bot_token, httpx.MockTransport(send_fixture)))
    assert worker.dispatch_one()
    markup = sent[0]["reply_markup"]["inline_keyboard"]
    assert markup[0] == [{"text": "Confirm report", "callback_data": f"confirm:{draft}"}]
    assert not {"nav:guest", "nav:brief"} & {button.get("callback_data") for buttons in markup for button in buttons}

    for number, sender in [(2, 102), (3, 101), (4, 101)]:
        update = callback_update(number, sender, f"confirm:{draft}")
        acknowledgment = ingress.accept(WEBHOOK_SECRET, update)
        assert acknowledgment == {"method": "answerCallbackQuery", "callback_query_id": f"callback-{number}"}
        assert ingress.accept(WEBHOOK_SECRET, update) == acknowledgment
        assert ingress.process_one()
        assert not ingress.process_one()

    draft_reply, denial, confirmation, replay = replies(db)
    assert "original reporter" in denial.message
    assert "awaiting approval" in confirmation.message
    assert "Already recorded" in replay.message
    assert queries.snapshot(coordinator)["wedding"]["timeline_version"] == revision
    with db.sessions() as session:
        proposals = list(session.scalars(select(Approval)))
        assert len(proposals) == 1 and proposals[0].status == "pending"
        assert all(not item.payload for item in session.scalars(select(InboundUpdate)))


def test_navigation_acknowledges_callbacks_and_preserves_roles(db, settings, clock, queries, ops):
    config = replace(settings, telegram_webhook_secret=WEBHOOK_SECRET, telegram_bot_token="12345:fixture")
    auth = Auth(db, config)
    ingress = TelegramIngress(db, config, clock, auth, Assistant(queries, ops), ops)
    auth.redeem(auth.issue_invite(Actor(WEDDING, "coordinator"), "registration-a")["token"], "101")
    update = callback_update(1, 101, "nav:guest")
    forged_chat = callback_update(2, 101, "nav:guest", chat=102)
    assert ingress.accept(WEBHOOK_SECRET, forged_chat)["ignored"]
    assert ingress.accept(WEBHOOK_SECRET, update)["method"] == "answerCallbackQuery"
    assert ingress.process_one()
    assert not ingress.process_one()
    assert replies(db)[0].message.startswith("Find a guest")


def message_update(number, sender, **message):
    return {
        "update_id": number,
        "message": {"from": {"id": sender}, "chat": {"id": sender, "type": "private"}, **message},
    }


def callback_update(number, sender, data, *, chat=None):
    return {
        "update_id": number,
        "callback_query": {
            "id": f"callback-{number}",
            "from": {"id": sender},
            "message": {"from": {"id": BOT_ID, "is_bot": True}, "chat": {"id": chat or sender, "type": "private"}},
            "data": data,
        },
    }


def replies(db):
    with db.sessions() as session:
        rows = session.scalars(
            select(Notification)
            .where(Notification.topic == "bot_reply")
            .order_by(Notification.dedupe_key)
        )
        return list(rows)


def test_photo_review_disabled_replies_without_downloading(db, settings, clock, queries, ops):
    config = replace(settings, telegram_webhook_secret=WEBHOOK_SECRET)
    auth = Auth(db, config)
    auth.redeem(auth.issue_invite(Actor(WEDDING, "coordinator"), "registration-a")["token"], "101")
    ingress = TelegramIngress(db, config, clock, auth, Assistant(queries, ops), ops)
    update = message_update(1, 101, photo=[{"file_id": "fictional-photo", "file_size": 64}])
    assert ingress.accept(WEBHOOK_SECRET, update)["queued"]
    assert ingress.process_one()
    assert "Photo review is off" in replies(db)[0].message


def test_photo_review_uses_only_photo_and_caption_and_does_not_change_run_sheet(db, settings, clock, queries, ops):
    from contextlib import closing
    from wedding_ops.agent import MistralParser
    from wedding_ops.models import ActionDraft, Incident

    jpeg = b"\xff\xd8\xfffictional-image-bytes"
    config = replace(settings, telegram_webhook_secret=WEBHOOK_SECRET, telegram_bot_token="12345:fixture",
                     mistral_api_key="fixture-model-key", telegram_vision_model="fixture-vision")
    auth = Auth(db, config)
    coordinator = Actor(WEDDING, "coordinator")
    auth.redeem(auth.issue_invite(coordinator, "registration-a")["token"], "101")
    before = queries.snapshot(coordinator)["wedding"]["timeline_version"]
    telegram_calls, model_calls = [], []

    def telegram_fixture(request):
        telegram_calls.append(request)
        if request.url.path.endswith("/getFile"):
            assert json.loads(request.content) == {"file_id": "fictional-photo"}
            return httpx.Response(200, json={"ok": True, "result": {
                "file_path": "photos/file_1.jpg", "file_size": len(jpeg),
            }})
        assert request.url.path.endswith("/photos/file_1.jpg")
        return httpx.Response(200, content=jpeg, headers={"Content-Type": "image/jpeg"})

    def model_fixture(request):
        model_calls.append(request)
        data = json.loads(request.content)
        assert str(request.url) == "https://api.mistral.ai/v1/chat/completions"
        assert data["model"] == "fixture-vision"
        assert "tools" not in data and "Sarah Tan" not in request.content.decode()
        chunks = data["messages"][1]["content"]
        assert chunks[0]["text"] == "Fictional garden setup"
        assert chunks[1]["image_url"].startswith("data:image/jpeg;base64,")
        report = {"summary": "Garden setup", "observations": ["Tables flank a walkway."],
                  "uncertainties": ["Dimensions aren't shown."]}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(report),
        }}]})

    with closing(MistralParser(config, httpx.MockTransport(model_fixture))) as model:
        ingress = TelegramIngress(db, config, clock, auth, Assistant(queries, ops), ops,
                                  photo_reviewer=model.review_photo, photo_transport=httpx.MockTransport(telegram_fixture))
        for number, sender in [(1, 999), (2, 101)]:
            update = message_update(number, sender, caption="Fictional garden setup",
                                    photo=[{"file_id": "small-photo", "file_size": 8},
                                           {"file_id": "fictional-photo", "file_size": len(jpeg)}])
            assert ingress.accept(WEBHOOK_SECRET, update)["queued"]
            assert ingress.process_one()

    assert len(telegram_calls) == 2 and len(model_calls) == 1
    reply = replies(db)[0]
    assert "What I can see" in reply.message and "Uncertain" in reply.message
    assert "no event records changed" in reply.message.lower()
    assert reply.telegram_draft_id is None
    assert queries.snapshot(coordinator)["wedding"]["timeline_version"] == before
    with db.sessions() as session:
        assert not list(session.scalars(select(ActionDraft)))
        assert not list(session.scalars(select(Incident)))
        assert all(not item.payload for item in session.scalars(select(InboundUpdate)))


def test_photo_download_rejects_untrusted_path():
    import pytest
    from wedding_ops.telegram_photo import download_photo

    calls = []
    def fixture(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"file_path": "photos/../other.jpg"}})
    with pytest.raises(ValueError):
        download_photo("fixture-token", "fixture-photo", httpx.MockTransport(fixture))
    assert len(calls) == 1


def test_archived_photo_never_reaches_provider(db, settings, clock, queries, ops):
    config = replace(settings, telegram_webhook_secret=WEBHOOK_SECRET)
    coordinator = Actor(WEDDING, "coordinator")
    auth = Auth(db, config)
    auth.redeem(auth.issue_invite(coordinator, "registration-a")["token"], "101")
    ops.execute(coordinator, {"type": "set_wedding_status", "status": "archived"}, "archive-photo-fixture")
    network_calls = []

    def telegram_fixture(request):
        network_calls.append(request)
        return httpx.Response(500)

    ingress = TelegramIngress(
        db, config, clock, auth, Assistant(queries, ops), ops,
        photo_reviewer=lambda *_: None, photo_transport=httpx.MockTransport(telegram_fixture),
    )
    ingress.accept(WEBHOOK_SECRET, message_update(1, 101, photo=[{"file_id": "fixture", "file_size": 12}]))
    assert ingress.process_one()
    assert not network_calls
