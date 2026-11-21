import pytest
from sqlalchemy import select
from wedding_ops.config import Settings
from wedding_ops.models import AuditEvent, Member
from wedding_ops.rehearsal import RehearsalError, link_telegram, list_members

TESTER_TELEGRAM_ID = "424242"


def rehearsal_settings():
    return Settings(mode="test", rehearsal=True)


def member_with_role(db, role):
    with db.sessions() as s:
        return next(m for m in s.scalars(select(Member).where(Member.active)) if role in m.roles)


def test_rehearsal_commands_refuse_without_the_rehearsal_flag(db):
    plain = Settings(mode="test")
    with pytest.raises(RehearsalError, match="WEDDINGOPS_REHEARSAL"):
        list_members(db, plain)
    with pytest.raises(RehearsalError, match="WEDDINGOPS_REHEARSAL"):
        link_telegram(db, plain, TESTER_TELEGRAM_ID, role="coordinator")


def test_link_moves_one_telegram_account_between_roles_and_audits(db):
    settings = rehearsal_settings()
    coordinator = link_telegram(db, settings, TESTER_TELEGRAM_ID, role="coordinator")
    banquet = member_with_role(db, "banquet")
    linked = link_telegram(db, settings, TESTER_TELEGRAM_ID, member_id=banquet.id)

    assert coordinator["roles"] == ["coordinator"] and linked["member_id"] == banquet.id
    with db.sessions() as s:
        holders = s.scalars(select(Member).where(Member.telegram_user_id == TESTER_TELEGRAM_ID)).all()
        events = s.scalars(select(AuditEvent).where(AuditEvent.event_type == "rehearsal_telegram_linked")).all()
    assert [m.id for m in holders] == [banquet.id]
    assert len(events) == 2 and all(e.actor_id == "rehearsal-operator" for e in events)
    assert all(TESTER_TELEGRAM_ID not in str(e.detail) for e in events)


def test_link_requires_exactly_one_target_and_an_active_member(db):
    settings = rehearsal_settings()
    with pytest.raises(RehearsalError, match="either"):
        link_telegram(db, settings, TESTER_TELEGRAM_ID)
    with pytest.raises(RehearsalError, match="No active member"):
        link_telegram(db, settings, TESTER_TELEGRAM_ID, role="astronaut")
    with pytest.raises(RehearsalError, match="numeric"):
        link_telegram(db, settings, "not-a-number", role="coordinator")


def test_list_shows_links_without_telegram_ids(db):
    settings = rehearsal_settings()
    link_telegram(db, settings, TESTER_TELEGRAM_ID, role="coordinator")
    members = list_members(db, settings)
    assert any(m["linked"] and "coordinator" in m["roles"] for m in members)
    assert TESTER_TELEGRAM_ID not in str(members)
