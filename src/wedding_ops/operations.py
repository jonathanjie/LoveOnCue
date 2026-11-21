"""All domain writes: reauthorize -> idempotency -> atomic mutation + audit + outbox."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import Clock, iso, parse_time, utcnow
from .db import Database
from .errors import OpsError, conflict, denied, missing
from .models import (
    ActionDraft, Approval, AuditEvent, CommandReceipt, GuestImport, Incident, KnowledgeDocument,
    Location, LoginSession, Member, MemberTeam, Notification, Person, SeatingTable, Task,
    TaskDependency, Team, TimelineDependency, TimelineItem, Vendor, Wedding, new_id,
)
from .policy import Access, Actor, ROLES, load_access, require_human
from .schemas import COMMAND, Command
from .scheduling import propose_shift
from .views import row, rows, rows_for_edges


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def audit(s: Session, w: Wedding, actor_id: str, event_type: str, entity_id: str, detail: dict, now) -> None:
    s.add(AuditEvent(wedding_id=w.id, actor_id=actor_id, event_type=event_type, entity_id=entity_id,
                     detail=detail, state_version=w.state_version, created_at=now))


def notify(s: Session, wid: str, member_id: str, topic: str, message: str, key: str, now,
           *, teams: list[str] | None = None, permission: str | None = None,
           timeline_version: int | None = None, task: Task | None = None,
           telegram_draft_id: str | None = None) -> None:
    unique = f"{key}:{member_id}"
    if s.scalar(select(Notification.id).where(Notification.wedding_id == wid, Notification.dedupe_key == unique)):
        return
    s.add(Notification(wedding_id=wid, recipient_id=member_id, topic=topic, message=message,
                       dedupe_key=unique, audience_team_ids=teams or [], required_permission=permission,
                       telegram_draft_id=telegram_draft_id,
                       timeline_version=timeline_version, task_id=task.id if task else None,
                       task_version=task.version if task else None, state="queued", attempts=0,
                       next_attempt_at=now, created_at=now))


def recipients(s: Session, wid: str, *, teams: list[str] | None = None, roles: set[str] | None = None,
               coordinators: bool = True) -> list[Member]:
    team_members = {mt.member_id for mt in rows_for_edges(s, MemberTeam, wid) if mt.team_id in (teams or [])}
    return [m for m in rows(s, Member, wid) if m.active and
            ((coordinators and "coordinator" in m.roles) or m.id in team_members or bool(set(m.roles).intersection(roles or set())))]


def assert_teams(s: Session, wid: str, ids: list[str]) -> None:
    for ident in set(ids):
        row(s, Team, wid, ident)


CAPABILITY = {
    "arrival": "guests:arrival", "report_incident": "incidents:report", "resolve_incident": "incidents:resolve",
    "propose_delay": "timeline:propose", "decide_approval": "timeline:approve",
    "acknowledge_notification": "notifications:own", "add_knowledge": "knowledge:manage",
    "review_knowledge": "knowledge:manage", "revoke_member": "members:manage", "broadcast": "messages:broadcast",
    "set_wedding_status": "wedding:manage", "apply_guest_import": "guests:manage",
    "edit_guest": "guests:manage", "create_team": "members:manage", "create_member": "members:manage", "create_task": "tasks:manage",
    "create_location": "wedding:manage", "create_table": "wedding:manage", "create_timeline_item": "timeline:manage",
    "timeline_action": "timeline:manage", "create_vendor": "vendors:manage", "vendor_status": "vendors:team",
}


class Operations:
    def __init__(self, db: Database, wedding_id: str, clock: Clock):
        self.db, self.wid, self.clock = db, wedding_id, clock

    def authorize(self, s: Session, a: Access, cmd: Command) -> None:
        if cmd.type == "task_action":
            task = row(s, Task, self.wid, cmd.task_id)
            if not a.can_edit_task(task):
                raise denied()
        else:
            a.require(CAPABILITY[cmd.type])
        if cmd.type == "vendor_status":
            vendor = row(s, Vendor, self.wid, cmd.vendor_id)
            if not a.coordinator and vendor.team_id not in a.team_ids:
                raise denied()
        if cmd.type == "report_incident":
            if cmd.kind == "location_unconfirmed":
                a.require("family:report")
            if cmd.subject_person_id:
                person = row(s, Person, self.wid, cmd.subject_person_id)
                if not person.relationship:
                    raise denied("Family-location reporting is restricted to the designated family roster")
                a.require("family:report")
            if cmd.task_id and not a.sees_task(row(s, Task, self.wid, cmd.task_id)):
                raise denied()
        if cmd.type == "propose_delay":
            item = row(s, TimelineItem, self.wid, cmd.item_id)
            if not a.coordinator and not a.team_ids.intersection(item.team_ids):
                raise denied("Only the relevant team or coordinator may propose this delay")
        if cmd.type == "acknowledge_notification":
            notice = row(s, Notification, self.wid, cmd.notification_id)
            if notice.recipient_id != a.member.id:
                raise denied()
        if cmd.type == "arrival" and not a.coordinator and "registration" not in a.member.roles:
            for ident in cmd.person_ids:
                if not row(s, Person, self.wid, ident).relationship:
                    raise denied("Family liaison arrival access is limited to the family roster")

    def execute(self, actor: Actor, command: Command | dict, request_id: str) -> dict:
        require_human(actor)
        cmd = COMMAND.validate_python(command) if isinstance(command, dict) else command
        payload = cmd.model_dump(mode="json")
        with self.db.transaction(self.wid, write=True) as (s, w):
            a = load_access(s, actor, self.wid)
            self.authorize(s, a, cmd)
            return self._execute_in_tx(s, w, actor, a, cmd, payload, request_id)

    def _execute_in_tx(self, s, w, actor, a, cmd, payload, request_id) -> dict:
        receipt = s.get(CommandReceipt, (self.wid, actor.member_id, request_id))
        if receipt:
            if receipt.payload_hash != digest(payload):
                raise conflict("This request ID was already used for a different command")
            return receipt.result | {"replayed": True}
        if w.status == "archived" and cmd.type not in {"acknowledge_notification", "revoke_member"}:
            raise conflict("This wedding is archived and read-only")
        now = self.clock.now()
        w.state_version += 1
        result = self._apply(s, w, actor, a, cmd, now)
        result |= {"state_version": w.state_version, "timeline_version": w.timeline_version, "replayed": False}
        entity_id = result.get("id", self.wid)
        audit(s, w, actor.member_id, cmd.type, entity_id,
              {"command_type": cmd.type, "request_id": request_id, "result": result}, now)
        s.add(CommandReceipt(wedding_id=self.wid, actor_id=actor.member_id, request_id=request_id,
                             payload_hash=digest(payload), result=result, created_at=now))
        s.flush()
        return result

    def _apply(self, s: Session, w: Wedding, actor: Actor, a: Access, cmd: Command, now) -> dict:
        wid = self.wid
        if cmd.type == "task_action":
            task = row(s, Task, wid, cmd.task_id)
            if task.version != cmd.expected_version:
                raise conflict("Task changed since you viewed it. Refresh before acting")
            if task.state in {"done", "cancelled"}:
                raise conflict("Task is already closed")
            if cmd.action in {"start", "complete"}:
                deps = [row(s, Task, wid, e.depends_on_id) for e in rows_for_edges(s, TaskDependency, wid) if e.task_id == task.id]
                if any(d.state != "done" for d in deps):
                    raise conflict("Complete the prerequisite tasks first")
            task.acknowledged_at = task.acknowledged_at or now
            if cmd.action == "start":
                task.state = "in_progress"
            if cmd.action == "complete":
                task.state, task.completed_at = "done", now
            task.version += 1
            return {"id": task.id, "status": task.state, "version": task.version}

        if cmd.type == "arrival":
            changed = []
            for ident in dict.fromkeys(cmd.person_ids):
                p = row(s, Person, wid, ident)
                if p.attendance == cmd.status:
                    continue
                p.attendance = cmd.status
                p.arrived_at = now if cmd.status == "onsite" else p.arrived_at
                p.version += 1
                changed.append(p.id)
                if p.relationship:
                    for m in recipients(s, wid, roles={"photographer", "family_liaison"}):
                        notify(s, wid, m.id, "family_arrival", f"Confirmed report: {p.name} ({p.relationship}) is {cmd.status}. Reported by the arrival team.",
                               f"arrival:{p.id}:{p.version}", now, permission="family:status")
                    if cmd.status == "onsite":
                        for incident in rows(s, Incident, wid):
                            if incident.subject_person_id == p.id and incident.kind == "location_unconfirmed" and incident.status == "open":
                                incident.status, incident.resolved_at = "resolved", now
                                audit(s, w, actor.member_id, "incident_resolved_by_arrival", incident.id, {"person_id": p.id}, now)
            return {"status": "recorded", "changed": changed}

        if cmd.type == "report_incident":
            audience = sorted(a.team_ids)
            if cmd.kind == "location_unconfirmed":
                target_members = recipients(s, wid, roles={"photographer", "family_liaison"})
                target_ids = {m.id for m in target_members}
                audience = sorted({mt.team_id for mt in rows_for_edges(s, MemberTeam, wid) if mt.member_id in target_ids})
            else:
                target_members = recipients(s, wid, teams=audience)
            incident = Incident(id=new_id(), wedding_id=wid, kind=cmd.kind, severity=cmd.severity,
                                title=cmd.title, details=cmd.details, subject_person_id=cmd.subject_person_id,
                                task_id=cmd.task_id, reported_by=a.member.id, audience_team_ids=audience,
                                status="open", created_at=now)
            s.add(incident)
            reporter = row(s, Person, wid, a.member.person_id).name
            for member in target_members:
                notify(s, wid, member.id, "incident",
                       f"{cmd.severity.upper()} report from {reporter} ({', '.join(a.member.roles)}): {cmd.title}\n{cmd.details}",
                       f"incident:{incident.id}", now, teams=audience,
                       permission="family:status" if cmd.kind == "location_unconfirmed" else None)
            return {"id": incident.id, "status": "open"}

        if cmd.type == "resolve_incident":
            incident = row(s, Incident, wid, cmd.incident_id)
            if incident.status != "open":
                raise conflict("Incident is already resolved")
            incident.status, incident.resolved_at = "resolved", now
            audit(s, w, actor.member_id, "resolution_note", incident.id, {"note": cmd.note}, now)
            return {"id": incident.id, "status": "resolved"}

        if cmd.type == "propose_delay":
            item = row(s, TimelineItem, wid, cmd.item_id)
            proposal = propose_shift(rows(s, TimelineItem, wid), rows_for_edges(s, TimelineDependency, wid), item.id, cmd.minutes)
            approval = Approval(id=new_id(), wedding_id=wid, proposed_by=a.member.id,
                                title=f"{item.title}: +{cmd.minutes} minutes", reason=cmd.reason,
                                base_timeline_version=w.timeline_version, changes=proposal["changes"],
                                affected_team_ids=proposal["affected_team_ids"], blockers=proposal["blockers"],
                                status="pending", created_at=now, expires_at=now + timedelta(minutes=10))
            s.add(approval)
            for member in recipients(s, wid):
                notify(s, wid, member.id, "approval_requested", f"Approval requested: {approval.title}. Review the proposed schedule and constraints in LoveOnCue. No times have changed.",
                       f"approval:{approval.id}", now, permission="timeline:approve")
            return {"id": approval.id, "status": "pending", "changed_items": len(approval.changes), "blocked": bool(approval.blockers)}

        if cmd.type == "decide_approval":
            approval = row(s, Approval, wid, cmd.approval_id)
            if approval.status != "pending":
                raise conflict("This proposal has already been decided")
            if approval.expires_at <= now:
                raise conflict("This proposal expired. Request a fresh proposal")
            if cmd.decision == "approve":
                if approval.base_timeline_version != w.timeline_version:
                    raise conflict("The timeline changed. Regenerate this proposal before approval")
                if approval.blockers:
                    raise conflict("Hard constraints block this proposal. Resolve them before creating a new proposal")
                for change in approval.changes:
                    item = row(s, TimelineItem, wid, change["item_id"])
                    if iso(item.current_start) != change["old_start"] or item.status != "scheduled":
                        raise conflict("An affected item changed. Request a fresh proposal")
                    item.current_start = parse_time(change["new_start"])
                    for task in rows(s, Task, wid):
                        if task.timeline_item_id == item.id and task.state not in {"done", "cancelled"}:
                            task.due_at = item.current_start + timedelta(minutes=task.offset_minutes)
                            task.version += 1
                w.timeline_version += 1
                for member in recipients(s, wid, teams=approval.affected_team_ids):
                    access = load_access(s, Actor(wid, member.id), wid)
                    relevant = [c for c in approval.changes if access.sees_teams(c["team_ids"])]
                    times = "; ".join(f"{c['title']} {parse_time(c['new_start']).astimezone(ZoneInfo(w.timezone)):%H:%M}" for c in relevant)
                    notify(s, wid, member.id, "timeline_updated", f"Coordinator-approved timeline v{w.timeline_version}: {times}. Check your updated tasks and acknowledge this message.",
                           f"timeline:{w.timeline_version}", now, teams=approval.affected_team_ids, timeline_version=w.timeline_version)
                approval.status = "approved"
            else:
                approval.status = "rejected"
            approval.decided_by, approval.decided_at, approval.decision_note = a.member.id, now, cmd.note
            return {"id": approval.id, "status": approval.status}

        if cmd.type == "acknowledge_notification":
            notice = row(s, Notification, wid, cmd.notification_id)
            notice.acknowledged_at = notice.acknowledged_at or now
            return {"id": notice.id, "status": "acknowledged"}

        if cmd.type == "add_knowledge":
            assert_teams(s, wid, cmd.audience_team_ids)
            doc = KnowledgeDocument(id=new_id(), wedding_id=wid, title=cmd.title, source_name=cmd.source_name,
                                    text=cmd.text, content_hash=hashlib.sha256(cmd.text.encode()).hexdigest(),
                                    audience_team_ids=sorted(set(cmd.audience_team_ids)), status="draft", created_by=a.member.id)
            s.add(doc)
            return {"id": doc.id, "status": "draft"}

        if cmd.type == "review_knowledge":
            doc = row(s, KnowledgeDocument, wid, cmd.document_id)
            doc.status = "approved" if cmd.decision == "approve" else "retired"
            doc.verified_at = now if doc.status == "approved" else doc.verified_at
            return {"id": doc.id, "status": doc.status}

        if cmd.type == "revoke_member":
            member = row(s, Member, wid, cmd.member_id)
            if member.id == a.member.id:
                raise conflict("You cannot revoke your own active coordinator session")
            member.active = False
            for login in rows(s, LoginSession, wid):
                if login.member_id == member.id:
                    login.revoked_at = utcnow()
            return {"id": member.id, "status": "revoked"}

        if cmd.type == "broadcast":
            assert_teams(s, wid, cmd.team_ids)
            ident = new_id()
            for member in recipients(s, wid, teams=cmd.team_ids, coordinators=False):
                notify(s, wid, member.id, "coordinator_message", cmd.message, f"broadcast:{ident}", now, teams=cmd.team_ids)
            return {"id": ident, "status": "queued"}

        if cmd.type == "set_wedding_status":
            w.status = cmd.status
            return {"id": wid, "status": w.status}

        if cmd.type == "apply_guest_import":
            batch = row(s, GuestImport, wid, cmd.import_id)
            if batch.applied_at:
                raise conflict("Import already applied")
            if batch.preview["errors"]:
                raise conflict("Fix the preview errors before importing")
            if batch.base_state_version != w.state_version - 1:
                raise conflict("Wedding data changed after preview. Upload again for a fresh preview")
            for data in batch.rows:
                s.add(Person(id=new_id(), wedding_id=wid, name=data["name"], is_guest=True,
                             table_id=data["table_id"], rsvp=data["rsvp"], dietary_private=data.get("dietary") or None))
            batch.applied_at = now
            return {"id": batch.id, "status": "applied", "created": len(batch.rows)}

        if cmd.type == "create_team":
            if any(t.name.casefold() == cmd.name.casefold() for t in rows(s, Team, wid)):
                raise conflict("A team with this name already exists")
            team = Team(id=new_id(), wedding_id=wid, name=cmd.name)
            s.add(team)
            return {"id": team.id, "status": "created"}

        if cmd.type == "create_member":
            if not set(cmd.roles).issubset(ROLES):
                raise OpsError("invalid_role", "Unknown role")
            assert_teams(s, wid, cmd.team_ids)
            if cmd.person_id:
                person = row(s, Person, wid, cmd.person_id)
                if s.scalar(select(Member.id).where(Member.wedding_id == wid, Member.person_id == person.id)):
                    raise conflict("This person already has a membership, including any revoked membership")
            else:
                person = Person(id=new_id(), wedding_id=wid, name=cmd.name, is_guest=False)
                s.add(person)
                s.flush()
            member = Member(id=new_id(), wedding_id=wid, person_id=person.id, roles=sorted(set(cmd.roles)), active=True)
            s.add(member)
            s.flush()
            for team in set(cmd.team_ids):
                s.add(MemberTeam(wedding_id=wid, member_id=member.id, team_id=team))
            return {"id": member.id, "status": "created"}

        if cmd.type == "edit_guest":
            person = row(s, Person, wid, cmd.person_id)
            if not person.is_guest:
                raise conflict("This endpoint edits guest records only")
            if person.version != cmd.expected_version:
                raise conflict("Guest changed since you viewed it. Refresh before editing")
            if cmd.table_id:
                table = row(s, SeatingTable, wid, cmd.table_id)
                occupied = sum(p.is_guest and p.id != person.id and p.table_id == table.id
                               for p in rows(s, Person, wid))
                if occupied >= table.capacity:
                    raise conflict("The selected table has no spare seats")
            person.name, person.table_id, person.rsvp = cmd.name, cmd.table_id, cmd.rsvp
            person.relationship = cmd.relationship
            person.dietary_private, person.private_phone = cmd.dietary or None, cmd.private_phone or None
            person.version += 1
            # Receipt and audit intentionally omit edited PII values.
            return {"id": person.id, "status": "updated", "version": person.version}

        if cmd.type == "create_task":
            row(s, Location, wid, cmd.location_id)
            row(s, Team, wid, cmd.team_id)
            owner = row(s, Member, wid, cmd.owner_id)
            access = load_access(s, Actor(wid, owner.id), wid)
            if cmd.team_id not in access.team_ids:
                raise conflict("Task owner must belong to the assigned team")
            for ident in cmd.depends_on_ids:
                row(s, Task, wid, ident)
            task = Task(id=new_id(), wedding_id=wid, title=cmd.title, instructions=cmd.instructions,
                        owner_id=owner.id, team_id=cmd.team_id, location_id=cmd.location_id,
                        due_at=cmd.due_at, planned_due=cmd.due_at)
            s.add(task)
            s.flush()
            for ident in set(cmd.depends_on_ids):
                s.add(TaskDependency(wedding_id=wid, task_id=task.id, depends_on_id=ident))
            return {"id": task.id, "status": "created"}
        if cmd.type == "create_location":
            ident = new_id()
            s.add(Location(id=ident, wedding_id=wid, name=cmd.name, directions=cmd.directions, x=cmd.x, y=cmd.y))
            return {"id": ident, "status": "created"}

        if cmd.type == "create_table":
            row(s, Location, wid, cmd.location_id)
            if any(t.label.casefold() == cmd.label.casefold() for t in rows(s, SeatingTable, wid)):
                raise conflict("A table with this label already exists")
            ident = new_id()
            s.add(SeatingTable(id=ident, wedding_id=wid, label=cmd.label, location_id=cmd.location_id,
                               capacity=cmd.capacity, x=cmd.x, y=cmd.y))
            return {"id": ident, "status": "created"}

        if cmd.type == "create_timeline_item":
            row(s, Location, wid, cmd.location_id)
            assert_teams(s, wid, cmd.team_ids)
            if cmd.latest_end and cmd.starts_at + timedelta(minutes=cmd.duration_minutes) > cmd.latest_end:
                raise conflict("The planned item already exceeds its latest-end constraint")
            for dep in cmd.depends_on_ids:
                parent = row(s, TimelineItem, wid, dep)
                if parent.current_start + timedelta(minutes=parent.duration_minutes) > cmd.starts_at:
                    raise conflict("A prerequisite ends after this item is scheduled to start")
            ident = new_id()
            s.add(TimelineItem(id=ident, wedding_id=wid, title=cmd.title, instructions=cmd.instructions,
                               planned_start=cmd.starts_at, current_start=cmd.starts_at, duration_minutes=cmd.duration_minutes,
                               latest_end=cmd.latest_end, location_id=cmd.location_id, team_ids=sorted(set(cmd.team_ids))))
            s.flush()
            for dep in set(cmd.depends_on_ids):
                s.add(TimelineDependency(wedding_id=wid, item_id=ident, depends_on_id=dep, lag_minutes=0))
            w.timeline_version += 1
            return {"id": ident, "status": "created"}

        if cmd.type == "timeline_action":
            if cmd.expected_timeline_version != w.timeline_version:
                raise conflict("The timeline changed. Refresh before issuing a cue")
            item = row(s, TimelineItem, wid, cmd.item_id)
            if cmd.action == "start":
                if item.status != "scheduled":
                    raise conflict("This item is no longer scheduled")
                for edge in rows_for_edges(s, TimelineDependency, wid):
                    if edge.item_id == item.id and row(s, TimelineItem, wid, edge.depends_on_id).status != "complete":
                        raise conflict("Confirm the preceding timeline items are complete before starting this one")
                item.status, item.actual_start = "live", now
            else:
                if item.status != "live":
                    raise conflict("Only a live item can be marked complete")
                item.status, item.actual_end = "complete", now
            w.timeline_version += 1
            return {"id": item.id, "status": item.status}

        if cmd.type == "create_vendor":
            row(s, Team, wid, cmd.team_id)
            ident = new_id()
            s.add(Vendor(id=ident, wedding_id=wid, name=cmd.name, category=cmd.category, contact_name=cmd.contact_name,
                         contact_phone=cmd.contact_phone, team_id=cmd.team_id, expected_at=cmd.expected_at, status="expected"))
            return {"id": ident, "status": "created"}

        if cmd.type == "vendor_status":
            vendor = row(s, Vendor, wid, cmd.vendor_id)
            vendor.status = cmd.status
            return {"id": vendor.id, "status": vendor.status}
        raise OpsError("unsupported_command", "This command is not supported")

    def draft(self, actor: Actor, command: dict, summary: str) -> dict:
        """The model may propose only an already-authorized command; no mutation occurs."""
        cmd = COMMAND.validate_python(command)
        if cmd.type not in {"arrival", "report_incident", "propose_delay"}:
            raise denied("This action cannot be initiated from AI chat")
        with self.db.transaction(self.wid, write=True) as (s, w):
            a = load_access(s, actor, self.wid)
            self.authorize(s, a, cmd)
            if w.status == "archived":
                raise conflict("This wedding is archived")
            now = utcnow()
            draft = ActionDraft(id=new_id(), wedding_id=self.wid, member_id=a.member.id, command=cmd.model_dump(mode="json"),
                                summary=summary, created_at=now, expires_at=now + timedelta(minutes=5))
            s.add(draft)
            return {"id": draft.id, "summary": summary, "expires_at": iso(draft.expires_at), "command_type": cmd.type}

    def confirm(self, actor: Actor, draft_id: str) -> dict:
        require_human(actor)
        with self.db.transaction(self.wid, write=True) as (s, w):
            a = load_access(s, actor, self.wid)
            draft = row(s, ActionDraft, self.wid, draft_id)
            if draft.member_id != a.member.id:
                raise denied("Only the original reporter may confirm this interpretation")
            cmd = COMMAND.validate_python(draft.command)
            self.authorize(s, a, cmd)
            receipt = s.get(CommandReceipt, (self.wid, actor.member_id, f"draft:{draft.id}"))
            if receipt:
                return receipt.result | {"replayed": True, "command_type": cmd.type}
            if draft.expires_at <= utcnow():
                raise conflict("This interpretation expired. Report it again")
            result = self._execute_in_tx(s, w, actor, a, cmd, draft.command, f"draft:{draft.id}")
            draft.consumed_at = utcnow()
            return result | {"command_type": cmd.type}
