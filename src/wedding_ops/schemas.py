"""Public contracts deliberately contain no actor, role, tenant or SQL parameters."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

ID = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=2000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TaskAction(Strict):
    type: Literal["task_action"]
    task_id: ID
    action: Literal["acknowledge", "start", "complete"]
    expected_version: int = Field(ge=1)


class Arrival(Strict):
    type: Literal["arrival"]
    person_ids: list[ID] = Field(min_length=1, max_length=20)
    status: Literal["onsite", "departed"] = "onsite"


class ReportIncident(Strict):
    type: Literal["report_incident"]
    # "question" needs an answer from the coordinator; "note" is for their information only.
    kind: Literal["location_unconfirmed", "vendor", "logistics", "other", "question", "note"]
    title: Annotated[str, Field(min_length=3, max_length=160)]
    details: Text
    subject_person_id: ID | None = None
    task_id: ID | None = None
    # Set to add a follow-up to the reporter's own open report instead of opening a new one.
    updates_incident_id: ID | None = None
    # Severity is not used to trigger automated emergency broadcasts.
    severity: Literal["normal", "urgent"] = "normal"


class ResolveIncident(Strict):
    type: Literal["resolve_incident"]
    incident_id: ID
    note: Text


class ProposeDelay(Strict):
    type: Literal["propose_delay"]
    item_id: ID
    minutes: int = Field(ge=1, le=180)
    reason: Text


class ChangeItem(Strict):
    """Change one run-sheet item's time, place or note. A shift moves dependent items too."""
    type: Literal["change_item"]
    item_id: ID
    shift_minutes: int = Field(default=0, ge=-60, le=180)
    location_id: ID | None = None
    note: Annotated[str, Field(max_length=300)] = ""
    reason: Text

    @model_validator(mode="after")
    def changes_something(self):
        if not (self.shift_minutes or self.location_id or self.note):
            raise ValueError("A change needs a new time, a new place or a note")
        return self


class DecideApproval(Strict):
    type: Literal["decide_approval"]
    approval_id: ID
    decision: Literal["approve", "reject"]
    note: Annotated[str, Field(max_length=1000)] = ""


class AcknowledgeNotification(Strict):
    type: Literal["acknowledge_notification"]
    notification_id: ID


class AddKnowledge(Strict):
    type: Literal["add_knowledge"]
    title: Annotated[str, Field(min_length=3, max_length=160)]
    source_name: Annotated[str, Field(min_length=1, max_length=180)]
    text: Annotated[str, Field(min_length=1, max_length=60000)]
    audience_team_ids: list[ID] = Field(default_factory=list, max_length=30)


class ReviewKnowledge(Strict):
    type: Literal["review_knowledge"]
    document_id: ID
    decision: Literal["approve", "retire"]


class RevokeMember(Strict):
    type: Literal["revoke_member"]
    member_id: ID


class Broadcast(Strict):
    """A coordinator message to teams, to named members, or both."""
    type: Literal["broadcast"]
    team_ids: list[ID] = Field(default_factory=list, max_length=30)
    member_ids: list[ID] = Field(default_factory=list, max_length=30)
    message: Text
    # Set when the message answers a helper's question: the question is closed.
    answers_incident_id: ID | None = None

    @model_validator(mode="after")
    def has_recipients(self):
        if not (self.team_ids or self.member_ids):
            raise ValueError("A message needs at least one team or member")
        return self


class SetEmergencyContact(Strict):
    """Who people should call when someone is hurt or in danger. Shown on every urgent draft."""
    type: Literal["set_emergency_contact"]
    contact: Annotated[str, Field(min_length=3, max_length=200)]


class SetWeddingStatus(Strict):
    type: Literal["set_wedding_status"]
    status: Literal["draft", "live", "archived"]


class ApplyGuestImport(Strict):
    type: Literal["apply_guest_import"]
    import_id: ID


class CreateTeam(Strict):
    type: Literal["create_team"]
    name: Annotated[str, Field(min_length=2, max_length=100)]


class CreateMember(Strict):
    type: Literal["create_member"]
    # A person may be both guest and helper. Reuse their record rather than duplicate it.
    name: Annotated[str, Field(min_length=2, max_length=120)] | None = None
    person_id: ID | None = None
    roles: list[str] = Field(min_length=1, max_length=6)
    team_ids: list[ID] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def identity_source(self):
        if (self.name is None) == (self.person_id is None):
            raise ValueError("Supply exactly one of name or existing person_id")
        return self


class EditGuest(Strict):
    type: Literal["edit_guest"]
    person_id: ID
    expected_version: int = Field(ge=1)
    name: Annotated[str, Field(min_length=2, max_length=120)]
    table_id: ID | None
    rsvp: Literal["yes", "no", "unknown"]
    relationship: Annotated[str, Field(min_length=1, max_length=80)] | None
    dietary: Annotated[str, Field(max_length=300)] | None
    private_phone: Annotated[str, Field(max_length=64)] | None


class CreateTask(Strict):
    type: Literal["create_task"]
    title: Annotated[str, Field(min_length=3, max_length=160)]
    instructions: Annotated[str, Field(max_length=2000)] = ""
    owner_id: ID
    team_id: ID
    location_id: ID
    due_at: datetime
    depends_on_ids: list[ID] = Field(default_factory=list, max_length=30)

    @field_validator("due_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Include a timezone offset")
        return value


class CreateLocation(Strict):
    type: Literal["create_location"]
    name: Annotated[str, Field(min_length=2, max_length=120)]
    directions: Annotated[str, Field(max_length=2000)] = ""
    x: int = Field(default=50, ge=0, le=100)
    y: int = Field(default=50, ge=0, le=100)


class CreateTable(Strict):
    type: Literal["create_table"]
    label: Annotated[str, Field(min_length=1, max_length=40)]
    location_id: ID
    capacity: int = Field(default=10, ge=1, le=100)
    x: int = Field(default=50, ge=0, le=100)
    y: int = Field(default=50, ge=0, le=100)


class CreateTimelineItem(Strict):
    type: Literal["create_timeline_item"]
    title: Annotated[str, Field(min_length=3, max_length=160)]
    instructions: Annotated[str, Field(max_length=2000)] = ""
    starts_at: datetime
    duration_minutes: int = Field(ge=1, le=1440)
    latest_end: datetime | None = None
    location_id: ID
    team_ids: list[ID] = Field(min_length=1, max_length=30)
    depends_on_ids: list[ID] = Field(default_factory=list, max_length=30)

    @field_validator("starts_at", "latest_end")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Include a timezone offset")
        return value


class TimelineAction(Strict):
    type: Literal["timeline_action"]
    item_id: ID
    action: Literal["start", "complete"]
    expected_timeline_version: int = Field(ge=1)


class CreateVendor(Strict):
    type: Literal["create_vendor"]
    name: Annotated[str, Field(min_length=2, max_length=120)]
    category: Annotated[str, Field(min_length=2, max_length=80)]
    contact_name: Annotated[str, Field(min_length=2, max_length=120)]
    contact_phone: Annotated[str, Field(min_length=1, max_length=64)]
    team_id: ID
    expected_at: datetime

    @field_validator("expected_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Include a timezone offset")
        return value


class VendorStatus(Strict):
    type: Literal["vendor_status"]
    vendor_id: ID
    status: Literal["expected", "onsite", "late", "complete"]


class SetDeputyEnabled(Strict):
    """The coordinator's switch for the deputy's check-ins, confirmed with a tap."""
    type: Literal["set_deputy_enabled"]
    enabled: bool


class WithdrawReport(Strict):
    """Withdraw the sender's own confirmed report, identified by its draft request ID."""
    type: Literal["withdraw_report"]
    request_id: Annotated[str, Field(min_length=7, max_length=80, pattern=r"^draft:[a-zA-Z0-9_-]+$")]


Command = Annotated[
    TaskAction | Arrival | ReportIncident | WithdrawReport | SetDeputyEnabled | ResolveIncident | ProposeDelay | ChangeItem | DecideApproval |
    AcknowledgeNotification | AddKnowledge | ReviewKnowledge | RevokeMember | Broadcast |
    SetWeddingStatus | SetEmergencyContact | ApplyGuestImport | CreateTeam | CreateMember | CreateTask |
    CreateLocation | CreateTable | CreateTimelineItem | TimelineAction | CreateVendor | VendorStatus | EditGuest,
    Field(discriminator="type"),
]
COMMAND = TypeAdapter(Command)


class CommandRequest(Strict):
    command: Command
    request_id: Annotated[str, Field(min_length=8, max_length=120, pattern=r"^[a-zA-Z0-9:_-]+$")]


class ChatRequest(Strict):
    text: Annotated[str, Field(min_length=1, max_length=2000)]


class ConfirmRequest(Strict):
    draft_id: ID


class Intent(Strict):
    """Untrusted model output. No approval, broadcast, admin, IDs or arbitrary tools."""
    kind: Literal["now", "guest", "location", "vendor", "knowledge", "family_status", "arrival", "missing_family", "delay", "incident", "urgent_incident", "withdraw", "schedule", "my_reports", "late", "headcount", "acknowledge", "unknown"]
    query: Annotated[str, Field(max_length=160)] = ""
    minutes: int | None = Field(default=None, ge=1, le=180)



PhotoDetail = Annotated[str, Field(min_length=1, max_length=230)]


class PhotoReview(Strict):
    """Untrusted observations from one photo. This schema has no command fields."""
    summary: Annotated[str, Field(min_length=1, max_length=300)]
    observations: Annotated[list[PhotoDetail], Field(min_length=1, max_length=5)]
    uncertainties: Annotated[list[PhotoDetail], Field(min_length=1, max_length=5)]
