"""Operator-only tools for a fictional staging rehearsal.

One real Telegram account can test every role by moving its Telegram link from
one fixture member to another. This runs only from the operator CLI on the
server and only when WEDDINGOPS_REHEARSAL=true. There is no chat command for
it, so a Telegram user can never choose their own role.
"""
from __future__ import annotations

from sqlalchemy import select

from .clock import utcnow
from .config import Settings
from .db import Database
from .models import Member, Person
from .operations import audit

# Audit actor for changes made from the server shell, not by a wedding member.
OPERATOR_ACTOR_ID = "rehearsal-operator"


class RehearsalError(Exception):
    """An operator mistake or a refused rehearsal action."""


def require_rehearsal(settings: Settings) -> None:
    if not settings.rehearsal:
        raise RehearsalError("Rehearsal tools are disabled. Set WEDDINGOPS_REHEARSAL=true for a fictional staging cell.")


def list_members(db: Database, settings: Settings) -> list[dict]:
    """Active members with their roles. Telegram IDs are shown only as linked or not."""
    require_rehearsal(settings)
    with db.transaction(settings.wedding_id) as (s, _):
        rows = s.execute(
            select(Member, Person.name)
            .join(Person, (Person.wedding_id == Member.wedding_id) & (Person.id == Member.person_id))
            .where(Member.wedding_id == settings.wedding_id, Member.active)
            .order_by(Person.name)
        ).all()
        return [{"member_id": member.id, "name": name, "roles": list(member.roles),
                 "linked": member.telegram_user_id is not None} for member, name in rows]


def _choose_member(s, settings: Settings, role: str | None, member_id: str | None) -> Member:
    if (role is None) == (member_id is None):
        raise RehearsalError("Give either a role or a member ID.")
    query = select(Member).where(Member.wedding_id == settings.wedding_id, Member.active)
    if member_id is not None:
        member = s.scalar(query.where(Member.id == member_id))
        if member is None:
            raise RehearsalError(f"No active member has ID {member_id}.")
        return member
    candidates = [m for m in s.scalars(query.order_by(Member.id)) if role in m.roles]
    if not candidates:
        raise RehearsalError(f"No active member has the role {role}.")
    # Several members can share a role. Pick the first by ID so the choice is repeatable.
    return candidates[0]


def link_telegram(db: Database, settings: Settings, telegram_user_id: str, *,
                  role: str | None = None, member_id: str | None = None) -> dict:
    """Link one Telegram account to the chosen member, unlinking it from any other member."""
    require_rehearsal(settings)
    if not telegram_user_id.isdecimal() or int(telegram_user_id) <= 0:
        raise RehearsalError("The Telegram user ID must be a positive numeric ID.")
    with db.transaction(settings.wedding_id, write=True) as (s, wedding):
        target = _choose_member(s, settings, role, member_id)
        previous = s.scalar(select(Member).where(
            Member.wedding_id == settings.wedding_id, Member.telegram_user_id == telegram_user_id))
        if previous is not None and previous.id != target.id:
            previous.telegram_user_id = None
            # Clear the old link first, because one Telegram ID may belong to one member only.
            s.flush()
        target.telegram_user_id = telegram_user_id
        audit(s, wedding, OPERATOR_ACTOR_ID, "rehearsal_telegram_linked", target.id,
              {"previous_member_id": previous.id if previous else None}, utcnow())
        return {"member_id": target.id, "roles": list(target.roles),
                "previous_member_id": previous.id if previous else None}
