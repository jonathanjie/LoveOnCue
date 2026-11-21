"""Normalized operational records. No LLM transcript is an authoritative record."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    false, true,
    JSON, Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
    Index, Integer, MetaData, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .clock import utcnow


def new_id() -> str:
    return uuid4().hex


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive database timestamp refused")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s", "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s", "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


class TenantRecord:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    wedding_id: Mapped[str] = mapped_column(String(64), ForeignKey("weddings.id"), index=True)


class Wedding(Base):
    __tablename__ = "weddings"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Singapore")
    event_date: Mapped[str] = mapped_column(String(10))
    venue: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    state_version: Mapped[int] = mapped_column(Integer, default=1)
    timeline_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    # The coordinator's standing orders for the deputy, and its on/off switch.
    deputy_orders: Mapped[str] = mapped_column(Text, default="", server_default="")
    deputy_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    __table_args__ = (CheckConstraint("status IN ('draft','live','archived')", name="status"),)


class Team(TenantRecord, Base):
    __tablename__ = "teams"
    name: Mapped[str] = mapped_column(String(100))
    __table_args__ = (UniqueConstraint("wedding_id", "id"), UniqueConstraint("wedding_id", "name"))


class Location(TenantRecord, Base):
    __tablename__ = "locations"
    name: Mapped[str] = mapped_column(String(120))
    directions: Mapped[str] = mapped_column(Text, default="")
    x: Mapped[int] = mapped_column(Integer, default=0)
    y: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("wedding_id", "id"),)


class SeatingTable(TenantRecord, Base):
    __tablename__ = "seating_tables"
    label: Mapped[str] = mapped_column(String(40))
    location_id: Mapped[str] = mapped_column(String(64))
    capacity: Mapped[int] = mapped_column(Integer, default=10)
    x: Mapped[int] = mapped_column(Integer, default=0)
    y: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"), UniqueConstraint("wedding_id", "label"),
        ForeignKeyConstraint(["wedding_id", "location_id"], ["locations.wedding_id", "locations.id"]),
        CheckConstraint("capacity > 0", name="capacity"),
    )


class Person(TenantRecord, Base):
    __tablename__ = "people"
    name: Mapped[str] = mapped_column(String(120), index=True)
    relationship: Mapped[str | None] = mapped_column(String(80))
    is_guest: Mapped[bool] = mapped_column(Boolean, default=True)
    table_id: Mapped[str | None] = mapped_column(String(64))
    rsvp: Mapped[str] = mapped_column(String(16), default="yes")
    attendance: Mapped[str] = mapped_column(String(16), default="unknown")
    arrived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    private_phone: Mapped[str | None] = mapped_column(String(64))
    dietary_private: Mapped[str | None] = mapped_column(String(300))
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"),
        ForeignKeyConstraint(["wedding_id", "table_id"], ["seating_tables.wedding_id", "seating_tables.id"]),
        CheckConstraint("attendance IN ('unknown','onsite','departed')", name="attendance"),
        CheckConstraint("rsvp IN ('yes','no','unknown')", name="rsvp"),
    )


class Member(TenantRecord, Base):
    __tablename__ = "members"
    person_id: Mapped[str] = mapped_column(String(64))
    roles: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    telegram_user_id: Mapped[str | None] = mapped_column(String(32))
    # Set when the member says "stop pinging me": the deputy sends them nothing unprompted except urgent items.
    deputy_quiet: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"), UniqueConstraint("wedding_id", "person_id"),
        UniqueConstraint("wedding_id", "telegram_user_id"),
        ForeignKeyConstraint(["wedding_id", "person_id"], ["people.wedding_id", "people.id"]),
    )


class MemberTeam(Base):
    __tablename__ = "member_teams"
    wedding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    member_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(["wedding_id", "member_id"], ["members.wedding_id", "members.id"]),
        ForeignKeyConstraint(["wedding_id", "team_id"], ["teams.wedding_id", "teams.id"]),
    )


class TimelineItem(TenantRecord, Base):
    __tablename__ = "timeline_items"
    title: Mapped[str] = mapped_column(String(160))
    instructions: Mapped[str] = mapped_column(Text, default="")
    planned_start: Mapped[datetime] = mapped_column(UTCDateTime())
    current_start: Mapped[datetime] = mapped_column(UTCDateTime())
    duration_minutes: Mapped[int] = mapped_column(Integer)
    actual_start: Mapped[datetime | None] = mapped_column(UTCDateTime())
    actual_end: Mapped[datetime | None] = mapped_column(UTCDateTime())
    latest_end: Mapped[datetime | None] = mapped_column(UTCDateTime())
    location_id: Mapped[str] = mapped_column(String(64))
    team_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"),
        ForeignKeyConstraint(["wedding_id", "location_id"], ["locations.wedding_id", "locations.id"]),
        CheckConstraint("duration_minutes > 0", name="duration"),
        CheckConstraint("status IN ('scheduled','live','complete')", name="status"),
    )


class TimelineDependency(Base):
    __tablename__ = "timeline_dependencies"
    wedding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depends_on_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lag_minutes: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        ForeignKeyConstraint(["wedding_id", "item_id"], ["timeline_items.wedding_id", "timeline_items.id"]),
        ForeignKeyConstraint(["wedding_id", "depends_on_id"], ["timeline_items.wedding_id", "timeline_items.id"]),
        CheckConstraint("item_id <> depends_on_id", name="not_self"),
        CheckConstraint("lag_minutes >= 0", name="lag"),
    )


class Task(TenantRecord, Base):
    __tablename__ = "tasks"
    title: Mapped[str] = mapped_column(String(160))
    instructions: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[str] = mapped_column(String(64))
    team_id: Mapped[str] = mapped_column(String(64))
    location_id: Mapped[str] = mapped_column(String(64))
    timeline_item_id: Mapped[str | None] = mapped_column(String(64))
    offset_minutes: Mapped[int] = mapped_column(Integer, default=0)
    planned_due: Mapped[datetime] = mapped_column(UTCDateTime())
    due_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    state: Mapped[str] = mapped_column(String(16), default="pending")
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"),
        ForeignKeyConstraint(["wedding_id", "owner_id"], ["members.wedding_id", "members.id"]),
        ForeignKeyConstraint(["wedding_id", "team_id"], ["teams.wedding_id", "teams.id"]),
        ForeignKeyConstraint(["wedding_id", "location_id"], ["locations.wedding_id", "locations.id"]),
        ForeignKeyConstraint(["wedding_id", "timeline_item_id"], ["timeline_items.wedding_id", "timeline_items.id"]),
        CheckConstraint("state IN ('pending','in_progress','done','cancelled')", name="state"),
    )


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    wedding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depends_on_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(["wedding_id", "task_id"], ["tasks.wedding_id", "tasks.id"]),
        ForeignKeyConstraint(["wedding_id", "depends_on_id"], ["tasks.wedding_id", "tasks.id"]),
        CheckConstraint("task_id <> depends_on_id", name="not_self"),
    )


class Vendor(TenantRecord, Base):
    __tablename__ = "vendors"
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80))
    contact_name: Mapped[str] = mapped_column(String(120))
    contact_phone: Mapped[str] = mapped_column(String(64))
    team_id: Mapped[str] = mapped_column(String(64))
    expected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20), default="expected")
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"),
        ForeignKeyConstraint(["wedding_id", "team_id"], ["teams.wedding_id", "teams.id"]),
    )


class Incident(TenantRecord, Base):
    __tablename__ = "incidents"
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    title: Mapped[str] = mapped_column(String(160))
    details: Mapped[str] = mapped_column(Text, default="")
    subject_person_id: Mapped[str | None] = mapped_column(String(64))
    task_id: Mapped[str | None] = mapped_column(String(64))
    reported_by: Mapped[str] = mapped_column(String(64))
    audience_team_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"),
        ForeignKeyConstraint(["wedding_id", "subject_person_id"], ["people.wedding_id", "people.id"]),
        ForeignKeyConstraint(["wedding_id", "task_id"], ["tasks.wedding_id", "tasks.id"]),
        ForeignKeyConstraint(["wedding_id", "reported_by"], ["members.wedding_id", "members.id"]),
        CheckConstraint("status IN ('open','resolved')", name="status"),
    )


class Approval(TenantRecord, Base):
    __tablename__ = "approvals"
    kind: Mapped[str] = mapped_column(String(32), default="timeline_shift")
    proposed_by: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(180))
    reason: Mapped[str] = mapped_column(Text)
    base_timeline_version: Mapped[int] = mapped_column(Integer)
    changes: Mapped[list] = mapped_column(JSON)
    affected_team_ids: Mapped[list] = mapped_column(JSON)
    blockers: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    decided_by: Mapped[str | None] = mapped_column(String(64))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decision_note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"),
        ForeignKeyConstraint(["wedding_id", "proposed_by"], ["members.wedding_id", "members.id"]),
        ForeignKeyConstraint(["wedding_id", "decided_by"], ["members.wedding_id", "members.id"]),
        CheckConstraint("status IN ('pending','approved','rejected','expired','withdrawn','superseded')", name="status"),
    )


class Notification(TenantRecord, Base):
    __tablename__ = "notifications"
    recipient_id: Mapped[str] = mapped_column(String(64))
    topic: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    telegram_draft_id: Mapped[str | None] = mapped_column(String(64))
    dedupe_key: Mapped[str] = mapped_column(String(220))
    audience_team_ids: Mapped[list] = mapped_column(JSON, default=list)
    required_permission: Mapped[str | None] = mapped_column(String(80))
    timeline_version: Mapped[int | None] = mapped_column(Integer)
    task_id: Mapped[str | None] = mapped_column(String(64))
    task_version: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime())
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    lease_token: Mapped[str | None] = mapped_column(String(64))
    provider_message_id: Mapped[str | None] = mapped_column(String(80))
    last_error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"), UniqueConstraint("wedding_id", "dedupe_key"),
        ForeignKeyConstraint(["wedding_id", "recipient_id"], ["members.wedding_id", "members.id"]),
        ForeignKeyConstraint(["wedding_id", "task_id"], ["tasks.wedding_id", "tasks.id"]),
        CheckConstraint("state IN ('queued','sending','sent','simulated','failed','undeliverable','superseded','cancelled')", name="state"),
        Index("ix_notifications_dispatch", "wedding_id", "state", "next_attempt_at"),
    )


class AuditEvent(TenantRecord, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    state_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    __table_args__ = (UniqueConstraint("wedding_id", "id"),)


class CommandReceipt(Base):
    __tablename__ = "command_receipts"
    wedding_id: Mapped[str] = mapped_column(String(64), ForeignKey("weddings.id"), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class KnowledgeDocument(TenantRecord, Base):
    __tablename__ = "knowledge_documents"
    title: Mapped[str] = mapped_column(String(160))
    source_name: Mapped[str] = mapped_column(String(180))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    audience_team_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_by: Mapped[str] = mapped_column(String(64))
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"),
        ForeignKeyConstraint(["wedding_id", "created_by"], ["members.wedding_id", "members.id"]),
        CheckConstraint("status IN ('draft','approved','retired')", name="status"),
    )


class Invitation(TenantRecord, Base):
    __tablename__ = "invitations"
    member_id: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"),
        ForeignKeyConstraint(["wedding_id", "member_id"], ["members.wedding_id", "members.id"]),
    )


class LoginSession(TenantRecord, Base):
    __tablename__ = "login_sessions"
    member_id: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"),
        ForeignKeyConstraint(["wedding_id", "member_id"], ["members.wedding_id", "members.id"]),
    )


class ActionDraft(TenantRecord, Base):
    __tablename__ = "action_drafts"
    member_id: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"),
        ForeignKeyConstraint(["wedding_id", "member_id"], ["members.wedding_id", "members.id"]),
    )


class GuestImport(TenantRecord, Base):
    __tablename__ = "guest_imports"
    created_by: Mapped[str] = mapped_column(String(64))
    rows: Mapped[list] = mapped_column(JSON)
    preview: Mapped[dict] = mapped_column(JSON)
    base_state_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"),
        ForeignKeyConstraint(["wedding_id", "created_by"], ["members.wedding_id", "members.id"]),
    )


class InboundUpdate(TenantRecord, Base):
    __tablename__ = "inbound_updates"
    provider_update_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    lease_token: Mapped[str | None] = mapped_column(String(64))
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"), UniqueConstraint("wedding_id", "provider_update_id"),
    )


class AuthReplay(Base):
    __tablename__ = "auth_replays"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    wedding_id: Mapped[str] = mapped_column(String(64), ForeignKey("weddings.id"))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ConversationTurn(TenantRecord, Base):
    """Short-lived chat memory for the deputy: the last few turns per person, deleted after 12 hours."""
    __tablename__ = "conversation_turns"
    member_id: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"),
        ForeignKeyConstraint(["wedding_id", "member_id"], ["members.wedding_id", "members.id"]),
        CheckConstraint("role IN ('user','assistant')", name="role"),
        Index("ix_conversation_turns_member", "wedding_id", "member_id", "created_at"),
    )


class DeputyPing(TenantRecord, Base):
    """A question the deputy sent on its own, paired with the answer or its expiry."""
    __tablename__ = "deputy_pings"
    recipient_id: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    answer: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("wedding_id", "id"),
        ForeignKeyConstraint(["wedding_id", "recipient_id"], ["members.wedding_id", "members.id"]),
        Index("ix_deputy_pings_recipient", "wedding_id", "recipient_id", "created_at"),
    )

