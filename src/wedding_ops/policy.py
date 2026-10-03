"""Authorization is deterministic, reloaded for every operation, and deny-by-default."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .errors import denied, missing
from .models import Member, MemberTeam, Task

ROLES = {"coordinator", "team_lead", "registration", "usher", "photographer", "family_liaison", "banquet", "mc", "av", "transport", "helper", "couple"}
COMMON = {"context:read", "timeline:read", "tasks:read", "tasks:own", "incidents:report", "knowledge:read", "notifications:own"}
GRANTS = {
    "coordinator": {"*"},
    "team_lead": COMMON | {"tasks:team", "vendors:team"},
    "registration": COMMON | {"guests:seating", "guests:arrival", "family:status"},
    "usher": COMMON | {"guests:seating"},
    "photographer": COMMON | {"family:status", "family:report", "vendors:team"},
    "family_liaison": COMMON | {"family:status", "family:report", "family:contacts", "guests:arrival"},
    "banquet": COMMON | {"guests:dietary", "timeline:propose", "vendors:team"},
    "mc": COMMON | {"timeline:propose", "vendors:team"},
    "av": COMMON | {"vendors:team"},
    "transport": COMMON | {"family:status", "vendors:team"},
    "helper": COMMON,
    "couple": {"context:read", "timeline:read", "knowledge:read", "notifications:own"},
}


@dataclass(frozen=True)
class Actor:
    wedding_id: str
    member_id: str
    source: Literal["web", "telegram", "agent", "worker"] = "web"


@dataclass(frozen=True)
class Access:
    member: Member
    team_ids: frozenset[str]
    grants: frozenset[str]

    @property
    def coordinator(self) -> bool:
        return "coordinator" in self.member.roles

    def permits(self, capability: str) -> bool:
        return "*" in self.grants or capability in self.grants

    def require(self, capability: str) -> None:
        if not self.permits(capability):
            raise denied()

    def sees_teams(self, audience: list[str]) -> bool:
        return self.coordinator or not audience or bool(self.team_ids.intersection(audience))

    def can_edit_task(self, task: Task) -> bool:
        return self.coordinator or (self.permits("tasks:own") and task.owner_id == self.member.id) or (self.permits("tasks:team") and task.team_id in self.team_ids)

    def sees_task(self, task: Task) -> bool:
        return self.coordinator or task.owner_id == self.member.id or task.team_id in self.team_ids


def load_access(session: Session, actor: Actor, cell_id: str) -> Access:
    if actor.wedding_id != cell_id:
        raise missing()
    member = session.scalar(select(Member).where(Member.wedding_id == cell_id, Member.id == actor.member_id))
    if member is None or not member.active:
        raise denied("This membership is inactive or unavailable")
    grants: set[str] = set()
    for role in member.roles:
        grants.update(GRANTS.get(role, set()))
    teams = frozenset(session.scalars(select(MemberTeam.team_id).where(MemberTeam.wedding_id == cell_id, MemberTeam.member_id == member.id)))
    return Access(member, teams, frozenset(grants))


def require_human(actor: Actor) -> None:
    if actor.source not in {"web", "telegram"}:
        raise denied("An explicit authenticated human action is required")
