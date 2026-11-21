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
from .attention import tell_coordinators
from .scheduling import propose_shift
from .telegram_ui import ACK_PROMPT, ACK_TOPICS
from .views import row, rows, rows_for_edges


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


# A reporter can withdraw their own report for this long after confirming it.
WITHDRAW_WINDOW = timedelta(minutes=30)
# Withdrawing a report needs the same permission as making it.
WITHDRAW_CAPABILITY = {"arrival": "guests:arrival", "incident": "incidents:report", "approval": "timeline:propose"}


def one_line(text: str, limit: int) -> str:
    """Collapse user text onto one line, so it cannot imitate system-written sections."""
    return " ".join(text.split())[:limit]


def describe_change(change: dict, zone: ZoneInfo, places: dict[str, str]) -> str:
    """One run-sheet change in plain words, for previews, approval requests and notices."""
    def local(value: str) -> str:
        return parse_time(value).astimezone(zone).strftime("%H:%M")

    text = change["title"]
    if change["new_start"] != change["old_start"]:
        text += f" {local(change['old_start'])} \u2192 {local(change['new_start'])}"
    else:
        text += f" at {local(change['new_start'])}"
    if change.get("new_location_id"):
        text += (f", now at {places.get(change['new_location_id'], 'a new place')} "
                 f"(was {places.get(change['old_location_id'], 'the old place')})")
    if change.get("note"):
        text += f". Note: {change['note']}"
    return text


def approval_request_message(approval: Approval, reporter: str, roles: list[str], zone: ZoneInfo,
                             places: dict[str, str] | None = None) -> str:
    """What the coordinator needs to decide. System facts come first; the reporter's words are quoted last."""
    changes = "\n".join("• " + describe_change(c, zone, places or {}) for c in approval.changes)
    lines = [f"Approval needed: {approval.title}", f"Reported by {reporter} ({', '.join(roles)})",
             "Changes if approved:", changes or "• No times change"]
    if approval.blockers:
        lines += ["Blocked:"] + [f"• {b}" for b in approval.blockers]
    lines.append(f"Reporter's words: \u201c{one_line(approval.reason, 300)}\u201d")
    lines.append("Reject it, or adjust the run sheet in LoveOnCue." if approval.blockers else
                 "Tap Approve or Reject, or review it in LoveOnCue. Nothing changes until you decide.")
    return "\n".join(lines)


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
    "propose_delay": "timeline:propose", "change_item": "timeline:propose", "decide_approval": "timeline:approve",
    "acknowledge_notification": "notifications:own", "withdraw_report": "notifications:own",
    "set_deputy_enabled": "timeline:approve", "add_knowledge": "knowledge:manage",
    "review_knowledge": "knowledge:manage", "revoke_member": "members:manage", "broadcast": "messages:broadcast",
    "set_wedding_status": "wedding:manage", "set_emergency_contact": "wedding:manage", "apply_guest_import": "guests:manage",
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
        elif cmd.type == "report_incident" and cmd.kind in {"question", "note"}:
            a.require("coordinator:ask")  # A question or a note is not a problem report.
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
            if cmd.updates_incident_id:
                # A follow-up goes only onto the reporter's own open report (or any, for a coordinator).
                earlier = row(s, Incident, self.wid, cmd.updates_incident_id)
                if earlier.reported_by != a.member.id and not a.coordinator:
                    raise denied("You can only add to your own reports")
                if earlier.status != "open":
                    raise conflict("That report is already closed. Send a new one")
        if cmd.type == "broadcast":
            for ident in cmd.member_ids:
                if not row(s, Member, self.wid, ident).active:
                    raise conflict("That person is no longer on the team")
            if cmd.answers_incident_id and row(s, Incident, self.wid, cmd.answers_incident_id).kind != "question":
                raise conflict("That report is not a question")
        if cmd.type in {"propose_delay", "change_item"}:
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
            changed, previous, resolved_incidents = [], {}, []
            for ident in dict.fromkeys(cmd.person_ids):
                p = row(s, Person, wid, ident)
                if p.attendance == cmd.status:
                    continue
                old_attendance = p.attendance
                p.attendance = cmd.status
                p.arrived_at = now if cmd.status == "onsite" else p.arrived_at
                p.version += 1
                changed.append(p.id)
                # Kept so the reporter can withdraw this exact change later.
                previous[p.id] = {"attendance": old_attendance, "version": p.version}
                if p.relationship:
                    # Coordinators see arrivals in the brief; only the roles that act on them are interrupted.
                    for m in recipients(s, wid, roles={"photographer", "family_liaison"}, coordinators=False):
                        notify(s, wid, m.id, "family_arrival", f"Confirmed report: {p.name} ({p.relationship}) is {cmd.status}. Reported by the arrival team.",
                               f"arrival:{p.id}:{p.version}", now, permission="family:status")
                    if cmd.status == "onsite":
                        for incident in rows(s, Incident, wid):
                            if incident.subject_person_id == p.id and incident.kind == "location_unconfirmed" and incident.status == "open":
                                incident.status, incident.resolved_at = "resolved", now
                                resolved_incidents.append(incident.id)
                                audit(s, w, actor.member_id, "incident_resolved_by_arrival", incident.id, {"person_id": p.id}, now)
            return {"status": "recorded", "changed": changed, "previous": previous,
                    "set_to": cmd.status, "resolved_incidents": resolved_incidents}

        if cmd.type == "report_incident":
            if cmd.updates_incident_id:
                return self._update_incident(s, w, a, cmd, now)
            return self._report_incident(s, w, a, cmd, now)

        if cmd.type == "withdraw_report":
            return self._withdraw(s, w, a, cmd.request_id, now)

        if cmd.type == "set_deputy_enabled":
            w.deputy_enabled = cmd.enabled
            return {"id": wid, "status": "on" if cmd.enabled else "off"}

        if cmd.type == "resolve_incident":
            incident = row(s, Incident, wid, cmd.incident_id)
            if incident.status != "open":
                raise conflict("Incident is already resolved")
            incident.status, incident.resolved_at = "resolved", now
            audit(s, w, actor.member_id, "resolution_note", incident.id, {"note": cmd.note}, now)
            return {"id": incident.id, "status": "resolved"}

        if cmd.type == "propose_delay":
            # A delay report is always a proposal, even from a coordinator (the Mini App's approval flow).
            return self._change(s, w, a, cmd.item_id, cmd.minutes, None, "", cmd.reason, now, applies_now=False)

        if cmd.type == "change_item":
            return self._change(s, w, a, cmd.item_id, cmd.shift_minutes, cmd.location_id, cmd.note, cmd.reason, now,
                                applies_now=a.permits("timeline:approve"))

        if cmd.type == "decide_approval":
            approval = row(s, Approval, wid, cmd.approval_id)
            return self._decide(s, w, a, approval, cmd.decision, cmd.note, now)

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
            return self._message(s, w, a, cmd, now)

        if cmd.type == "set_emergency_contact":
            w.emergency_contact = cmd.contact
            return {"id": wid, "status": "updated"}

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

    def _report_incident(self, s: Session, w: Wedding, a: Access, cmd, now) -> dict:
        """A new problem, question or note. Teams hear about problems; the coordinator hears about all."""
        wid = self.wid
        reporter = row(s, Person, wid, a.member.person_id).name
        roles = ", ".join(a.member.roles)
        audience = sorted(a.team_ids)
        permission = None
        if cmd.kind == "location_unconfirmed":
            team_targets = recipients(s, wid, roles={"photographer", "family_liaison"}, coordinators=False)
            target_ids = {m.id for m in team_targets}
            audience = sorted({mt.team_id for mt in rows_for_edges(s, MemberTeam, wid) if mt.member_id in target_ids})
            permission = "family:status"
        elif cmd.kind in {"question", "note"}:
            team_targets, audience = [], []  # Questions and notes are for the coordinator only, also in views.
        else:
            team_targets = recipients(s, wid, teams=audience, coordinators=False)
        # Incidents are operational: the couple is never interrupted with staff problems.
        team_targets = [m for m in team_targets if "couple" not in m.roles and m.id != a.member.id]
        incident = Incident(id=new_id(), wedding_id=wid, kind=cmd.kind, severity=cmd.severity,
                            title=cmd.title, details=cmd.details, subject_person_id=cmd.subject_person_id,
                            task_id=cmd.task_id, reported_by=a.member.id, audience_team_ids=audience,
                            status="open", created_at=now)
        s.add(incident)
        words = f"\u201c{one_line(cmd.details, 600)}\u201d"
        message = (f"{cmd.severity.upper()} report from {reporter} ({roles}): {one_line(cmd.title, 160)}\n"
                   f"Details: {words}")
        for member in team_targets:
            notify(s, wid, member.id, "incident", message, f"incident:{incident.id}", now,
                   teams=audience, permission=permission)
        if cmd.kind == "question":
            first = reporter.split()[0]
            tell_coordinators(s, w, f"incident:{incident.id}",
                              f"Question from {reporter} ({roles}): {one_line(cmd.title, 160)}\nTheir words: {words}\n"
                              f"Answer by telling me, for example: tell {first} \u2026", now,
                              push=True, topic="question", key=f"incident:{incident.id}")
        elif cmd.kind == "note":
            tell_coordinators(s, w, f"incident:{incident.id}", f"Note from {reporter}: {one_line(cmd.title, 160)}", now)
        else:
            urgent = cmd.severity == "urgent"
            tell_coordinators(s, w, f"incident:{incident.id}", message if urgent else
                              f"Problem from {reporter}: {one_line(cmd.title, 160)}", now,
                              push=urgent or cmd.kind == "location_unconfirmed", key=f"incident:{incident.id}",
                              permission=permission)
        return {"id": incident.id, "status": "open"}

    def _update_incident(self, s: Session, w: Wedding, a: Access, cmd, now) -> dict:
        """Add a follow-up to an open report. Escalating to urgent pushes; anything else waits for the digest."""
        incident = row(s, Incident, self.wid, cmd.updates_incident_id)
        at = now.astimezone(ZoneInfo(w.timezone)).strftime("%H:%M")
        incident.details = f"{incident.details}\nUpdate {at}: {cmd.details}"[:8000]
        escalated = cmd.severity == "urgent" and incident.severity != "urgent"
        if escalated:
            incident.severity = "urgent"
        reporter = row(s, Person, self.wid, a.member.person_id).name
        text = (f"{'Now URGENT: ' if escalated else 'Update on '}{one_line(incident.title, 160)} from {reporter}: "
                f"\u201c{one_line(cmd.details, 300)}\u201d")
        tell_coordinators(s, w, f"incident:{incident.id}", text, now, push=escalated,
                          key=f"incident-update:{incident.id}:{at}")
        return {"id": incident.id, "status": "updated"}

    def _change_set(self, s: Session, item: TimelineItem, shift: int, location_id: str | None, note: str):
        """Every item a change moves, its blockers, and a short title. Reads only."""
        if item.status != "scheduled":
            raise conflict("Only a not-yet-started run-sheet item can be changed")
        if location_id == item.location_id:
            location_id = None
        new_place = row(s, Location, self.wid, location_id) if location_id else None
        if not (shift or new_place or note):
            raise conflict("This change would not change anything")
        proposal = (propose_shift(rows(s, TimelineItem, self.wid), rows_for_edges(s, TimelineDependency, self.wid),
                                  item.id, shift)
                    if shift else {"changes": [], "affected_team_ids": [], "blockers": []})
        changes = proposal["changes"]
        main = next((c for c in changes if c["item_id"] == item.id), None)
        if main is None:
            main = {"item_id": item.id, "title": item.title, "old_start": iso(item.current_start),
                    "new_start": iso(item.current_start), "delta_minutes": 0, "team_ids": item.team_ids}
            changes.insert(0, main)
        parts = [f"+{shift} minutes"] if shift else []
        if new_place:
            main["old_location_id"], main["new_location_id"] = item.location_id, new_place.id
            parts.append(f"move to {new_place.name}")
        if note:
            main["note"] = note
            parts.append("new note")
        teams = sorted(set(proposal["affected_team_ids"]) | set(item.team_ids))
        return changes, teams, proposal["blockers"], f"{item.title}: {', '.join(parts)}"

    def preview_change(self, actor: Actor, command: dict) -> dict:
        """What a run-sheet change would do, for its draft preview. Nothing is written."""
        cmd = COMMAND.validate_python(command)
        if cmd.type not in {"propose_delay", "change_item"}:
            raise OpsError("unsupported_command", "Only run-sheet changes have a preview")
        with self.db.transaction(self.wid) as (s, _):
            a = load_access(s, actor, self.wid)
            self.authorize(s, a, cmd)
            item = row(s, TimelineItem, self.wid, cmd.item_id)
            if cmd.type == "propose_delay":
                changes, _, blockers, _ = self._change_set(s, item, cmd.minutes, None, "")
            else:
                changes, _, blockers, _ = self._change_set(s, item, cmd.shift_minutes, cmd.location_id, cmd.note)
            now = self.clock.now()
            replaces = next((p.title for p in rows(s, Approval, self.wid)
                             if p.status == "pending" and p.expires_at > now and p.proposed_by == a.member.id
                             and p.changes and p.changes[0]["item_id"] == item.id), None)
            return {"changes": changes, "blockers": blockers, "replaces": replaces}

    def _change(self, s: Session, w: Wedding, a: Access, item_id: str, shift: int, location_id: str | None,
                note: str, reason: str, now, *, applies_now: bool) -> dict:
        """Propose a run-sheet change, or apply it when a coordinator makes it (applies_now)."""
        wid = self.wid
        item = row(s, TimelineItem, wid, item_id)
        changes, teams, blockers, title = self._change_set(s, item, shift, location_id, note)
        reason_text = reason
        # One live proposal per item: a newer report replaces older pending ones.
        for older in rows(s, Approval, wid):
            live = older.status == "pending" and older.expires_at > now
            if live and older.changes and older.changes[0]["item_id"] == item.id:
                replacer = row(s, Person, wid, a.member.person_id).name
                older.status, older.decided_at = "superseded", now
                if older.proposed_by == a.member.id:
                    older.decision_note = "Replaced by their newer request."
                else:
                    older.decision_note = (f"Replaced by the coordinator's change ({replacer})." if applies_now
                                           else f"Replaced by {replacer}'s newer request.")
                    notify(s, wid, older.proposed_by, "report_decision",
                           f"Your request ({older.title}) was {older.decision_note[0].lower() + older.decision_note[1:]}",
                           f"superseded:{older.id}", now)
                reason_text = f"{reason_text}\nReplaces the earlier proposal: {older.title.split(': ', 1)[-1]}."
        approval = Approval(id=new_id(), wedding_id=wid, kind="timeline_change", proposed_by=a.member.id,
                            title=title, reason=reason_text[:2000], base_timeline_version=w.timeline_version,
                            changes=changes, affected_team_ids=teams, blockers=blockers, status="pending",
                            created_at=now, expires_at=now + timedelta(minutes=10))
        s.add(approval)
        s.flush()
        if applies_now:
            # The coordinator confirmed a code-rendered preview of this exact change: that tap is the
            # approval. The same checks as any decision run, in this one transaction.
            return self._decide(s, w, a, approval, "approve", "Changed by the coordinator.", now) | {
                "changed_items": len(approval.changes), "blocked": False}
        message = approval_request_message(approval, row(s, Person, wid, a.member.person_id).name,
                                           a.member.roles, ZoneInfo(w.timezone), self._place_names(s))
        tell_coordinators(s, w, f"approval:{approval.id}", message, now, push=True, topic="approval_requested",
                          key=f"approval:{approval.id}", permission="timeline:approve")
        return {"id": approval.id, "status": "pending", "changed_items": len(approval.changes),
                "blocked": bool(approval.blockers)}

    def _place_names(self, s: Session) -> dict[str, str]:
        return {location.id: location.name for location in rows(s, Location, self.wid)}

    def _decide(self, s: Session, w: Wedding, a: Access, approval: Approval, decision: str, note: str, now) -> dict:
        wid = self.wid
        if approval.status != "pending":
            raise conflict("This proposal has already been decided")
        if approval.expires_at <= now:
            raise conflict("This proposal expired. Request a fresh proposal")
        if decision == "approve":
            if approval.base_timeline_version != w.timeline_version:
                raise conflict("The timeline changed. Regenerate this proposal before approval")
            if approval.blockers:
                raise conflict("Hard constraints block this proposal: " + "; ".join(approval.blockers))
            for change in approval.changes:
                item = row(s, TimelineItem, wid, change["item_id"])
                moved_since = "old_location_id" in change and item.location_id != change["old_location_id"]
                if iso(item.current_start) != change["old_start"] or item.status != "scheduled" or moved_since:
                    raise conflict("An affected item changed. Request a fresh proposal")
                item.current_start = parse_time(change["new_start"])
                for task in rows(s, Task, wid):
                    if task.timeline_item_id == item.id and task.state not in {"done", "cancelled"}:
                        task.due_at = item.current_start + timedelta(minutes=task.offset_minutes)
                        # Only tasks that were at the item's old place follow it to the new one.
                        if change.get("new_location_id") and task.location_id == change["old_location_id"]:
                            task.location_id = change["new_location_id"]
                        task.version += 1
                if change.get("new_location_id"):
                    item.location_id = change["new_location_id"]
                if change.get("note"):
                    item.change_note = change["note"]
            w.timeline_version += 1
            self._announce_change(s, w, a, approval, now)
            approval.status = "approved"
        else:
            approval.status = "rejected"
        approval.decided_by, approval.decided_at, approval.decision_note = a.member.id, now, note
        if approval.proposed_by != a.member.id:
            decider = row(s, Person, wid, a.member.person_id).name
            outcome = ("approved. The run sheet is updated; check My tasks" if approval.status == "approved"
                       else "rejected. The run sheet is unchanged")
            extra = f"\nNote: {note}" if note else ""
            notify(s, wid, approval.proposed_by, "report_decision",
                   f"Your report ({approval.title}) was {outcome}. Decided by {decider}.{extra}",
                   f"decision:{approval.id}", now)
        return {"id": approval.id, "status": approval.status}

    def _announce_change(self, s: Session, w: Wedding, a: Access, approval: Approval, now) -> None:
        """Tell people about an approved change, in words generated from the change itself."""
        zone, places = ZoneInfo(w.timezone), self._place_names(s)
        moved_place = any(c.get("new_location_id") for c in approval.changes)
        # A place change moves guests, which every helper handles; a time change concerns the affected teams.
        audience = ([m for m in rows(s, Member, self.wid) if m.active and "couple" not in m.roles] if moved_place
                    else recipients(s, self.wid, teams=approval.affected_team_ids))
        for member in audience:
            if member.id == a.member.id:
                continue  # The coordinator who made or approved it already knows.
            access = load_access(s, Actor(self.wid, member.id), self.wid)
            relevant = [c for c in approval.changes if access.sees_teams(c["team_ids"]) or c.get("new_location_id")]
            if not relevant:
                continue
            lines = "\n".join("• " + describe_change(c, zone, places) for c in relevant)
            notify(s, self.wid, member.id, "timeline_updated",
                   f"Run sheet updated by the coordinator (version {w.timeline_version}):\n{lines}\n"
                   f"Check your tasks. {ACK_PROMPT}",
                   f"timeline:{w.timeline_version}", now, timeline_version=w.timeline_version)

    def _message(self, s: Session, w: Wedding, a: Access, cmd, now) -> dict:
        """A coordinator message to teams and named people. Answering a question closes it."""
        wid = self.wid
        assert_teams(s, wid, cmd.team_ids)
        ident = new_id()
        sender = row(s, Person, wid, a.member.person_id).name
        member_ids = list(cmd.member_ids)
        if cmd.answers_incident_id:
            question = row(s, Incident, wid, cmd.answers_incident_id)
            member_ids.append(question.reported_by)  # The person who asked always gets the answer.
            if question.status == "open":
                question.status, question.resolved_at = "resolved", now
                audit(s, w, a.member.id, "question_answered", question.id, {"message_id": ident}, now)
        heading = "Announcement" if cmd.team_ids else "Message"
        message = f"{heading} from {sender}:\n{cmd.message}\n\n{ACK_PROMPT}"
        told = set()
        for member in recipients(s, wid, teams=cmd.team_ids, coordinators=False):
            if member.id != a.member.id:
                notify(s, wid, member.id, "coordinator_message", message, f"broadcast:{ident}", now, teams=cmd.team_ids)
                told.add(member.id)
        for member_id in dict.fromkeys(member_ids):
            member = row(s, Member, wid, member_id)
            if member.active and member.id != a.member.id and member.id not in told:
                # Named people get it whatever their team, so no team restriction applies.
                notify(s, wid, member.id, "coordinator_message", message, f"broadcast:{ident}", now)
                told.add(member.id)
        return {"id": ident, "status": "queued", "recipients": len(told)}

    def set_deputy_quiet(self, actor: Actor, quiet: bool) -> None:
        """A member's own choice to stop unprompted deputy messages."""
        require_human(actor)
        with self.db.transaction(self.wid, write=True) as (s, w):
            member = row(s, Member, self.wid, actor.member_id)
            member.deputy_quiet = quiet
            audit(s, w, actor.member_id, "deputy_quiet", member.id, {"quiet": quiet}, self.clock.now())

    def set_deputy_enabled(self, actor: Actor, enabled: bool) -> None:
        """The coordinator's switch for the deputy's unprompted messages."""
        require_human(actor)
        with self.db.transaction(self.wid, write=True) as (s, w):
            load_access(s, actor, self.wid).require("timeline:approve")
            w.deputy_enabled = enabled
            w.state_version += 1
            audit(s, w, actor.member_id, "deputy_enabled", self.wid, {"enabled": enabled}, self.clock.now())

    def acknowledge_latest(self, actor: Actor, notification_id: str | None = None) -> str | None:
        """Acknowledge one update that asks for it: the given one, or the newest waiting one."""
        with self.db.transaction(self.wid) as (s, _):
            waiting = sorted((n for n in rows(s, Notification, self.wid)
                              if n.recipient_id == actor.member_id and n.topic in ACK_TOPICS
                              and n.acknowledged_at is None and n.state in {"sent", "simulated"}
                              and (notification_id is None or n.id == notification_id)),
                             key=lambda n: (n.created_at, n.id))
            if not waiting:
                return None
            notice_id, message = waiting[-1].id, waiting[-1].message
        self.execute(actor, {"type": "acknowledge_notification", "notification_id": notice_id}, f"ack:{notice_id}")
        return message

    def recent_actions(self, actor: Actor, zone: ZoneInfo, hours: int = 1) -> list[str]:
        """What this person recorded recently, in plain words, for the deputy's context."""
        with self.db.transaction(self.wid) as (s, _):
            cutoff = self.clock.now() - timedelta(hours=hours)
            events = sorted((e for e in rows(s, AuditEvent, self.wid)
                             if e.actor_id == actor.member_id and e.created_at >= cutoff
                             and e.event_type in {"arrival", "report_incident", "propose_delay", "change_item",
                                                  "report_withdrawn"}),
                            key=lambda e: e.created_at)
            lines = []
            for event in events[-8:]:
                at = event.created_at.astimezone(zone).strftime("%H:%M")
                result = event.detail.get("result", {})
                if event.event_type == "arrival":
                    names = [row(s, Person, self.wid, i).name for i in result.get("changed", [])]
                    lines.append(f"{at} recorded arrival of {', '.join(names) or 'nobody new'}")
                elif event.event_type == "report_withdrawn":
                    lines.append(f"{at} withdrew a report ({event.detail.get('kind', 'report')})")
                elif event.event_type in {"propose_delay", "change_item"}:
                    applied = result.get("status") == "approved"
                    lines.append(f"{at} {'changed the run sheet' if applied else 'sent a run-sheet change request'}")
                elif result.get("status") == "updated":
                    lines.append(f"{at} added an update to an open report")
                else:
                    kind = self._incident_kind(s, result.get("id"))
                    lines.append(f"{at} sent {'a question' if kind == 'question' else 'a note' if kind == 'note' else 'a problem report'}")
            return lines

    def _incident_kind(self, s: Session, incident_id: str | None) -> str | None:
        incident = s.scalar(select(Incident).where(Incident.wedding_id == self.wid, Incident.id == incident_id))
        return incident.kind if incident else None

    def latest_report(self, actor: Actor) -> dict | None:
        """The sender's most recent confirmed report that can still be withdrawn."""
        with self.db.transaction(self.wid) as (s, _):
            withdrawn = {e.entity_id for e in rows(s, AuditEvent, self.wid) if e.event_type == "report_withdrawn"}
            receipts = sorted((r for r in s.scalars(select(CommandReceipt).where(
                CommandReceipt.wedding_id == self.wid, CommandReceipt.actor_id == actor.member_id,
                CommandReceipt.request_id.like("draft:%")))), key=lambda r: r.created_at, reverse=True)
            for receipt in receipts:
                if receipt.request_id in withdrawn or self.clock.now() - receipt.created_at > WITHDRAW_WINDOW:
                    continue
                target = self._report_target(s, receipt)
                if target and target["withdrawable"]:
                    return {"request_id": receipt.request_id, "title": target["title"]}
            return None

    def _report_target(self, s, receipt: CommandReceipt) -> dict | None:
        """Describe what a confirmed report created, from its stored result."""
        result = receipt.result
        if "changed" in result:
            names = [row(s, Person, self.wid, ident).name for ident in result["changed"]]
            # Arrivals recorded before this release did not keep enough detail to undo safely.
            return {"kind": "arrival", "title": "arrival of " + ", ".join(names),
                    "withdrawable": bool(names) and "set_to" in result}
        approval = s.scalar(select(Approval).where(Approval.wedding_id == self.wid, Approval.id == result.get("id")))
        if approval:
            return {"kind": "approval", "title": approval.title, "record": approval,
                    "withdrawable": approval.status == "pending"}
        incident = s.scalar(select(Incident).where(Incident.wedding_id == self.wid, Incident.id == result.get("id")))
        if incident and result.get("status") == "updated":
            # A follow-up cannot be withdrawn on its own: that would close the whole report.
            return {"kind": "incident", "title": f"update to {incident.title}", "record": incident, "withdrawable": False}
        if incident:
            return {"kind": "incident", "title": incident.title, "record": incident,
                    "withdrawable": incident.status == "open"}
        return None

    def _withdraw(self, s, w: Wedding, a: Access, request_id: str, now) -> dict:
        receipt = s.get(CommandReceipt, (self.wid, a.member.id, request_id))
        already = any(e.event_type == "report_withdrawn" and e.entity_id == request_id for e in rows(s, AuditEvent, self.wid))
        target = self._report_target(s, receipt) if receipt else None
        too_old = receipt is None or now - receipt.created_at > WITHDRAW_WINDOW
        if target is None or already or too_old or not target["withdrawable"]:
            raise conflict("This report can no longer be withdrawn. Ask the coordinator to correct it")
        # The reporter must still hold the permission the original report needed.
        private = target["kind"] == "incident" and target["record"].kind in {"question", "note"}
        a.require("coordinator:ask" if private else WITHDRAW_CAPABILITY[target["kind"]])
        reporter = row(s, Person, self.wid, a.member.person_id).name
        if target["kind"] == "arrival":
            people = {ident: row(s, Person, self.wid, ident) for ident in receipt.result["previous"]}
            for ident, before in receipt.result["previous"].items():
                person = people[ident]
                if person.attendance != receipt.result["set_to"] or person.version != before["version"]:
                    raise conflict(f"{person.name}'s status changed since your report. Ask the coordinator to correct it")
            for ident, before in receipt.result["previous"].items():
                people[ident].attendance = before["attendance"]
                people[ident].version += 1
            for incident_id in receipt.result.get("resolved_incidents", []):
                incident = row(s, Incident, self.wid, incident_id)
                incident.status, incident.resolved_at = "open", None
            # Match the original arrival notice: family members only, to family-cleared roles.
            family = [p.name for p in people.values() if p.relationship]
            notice = (f"Arrival of {', '.join(family)}" if family else None, "family:status", None)
            audience = recipients(s, self.wid, roles={"photographer", "family_liaison"}) if family else []
        elif target["kind"] == "approval":
            target["record"].status, target["record"].decided_at = "withdrawn", now
            target["record"].decision_note = f"Withdrawn by {reporter}."
            notice = (target["title"], "timeline:approve", None)
            audience = recipients(s, self.wid, coordinators=True)
        else:
            incident = target["record"]
            incident.status, incident.resolved_at = "resolved", now
            permission = "family:status" if incident.kind == "location_unconfirmed" else None
            notice = (target["title"], permission, incident.audience_team_ids)
            audience = recipients(s, self.wid, teams=incident.audience_team_ids)
        audit(s, w, a.member.id, "report_withdrawn", request_id, {"kind": target["kind"]}, now)
        title, permission, teams = notice
        if title:
            # The coordinator reads withdrawals in the next digest; they need no decision.
            tell_coordinators(s, w, f"report:{request_id}", f"Withdrawn by {reporter}: {one_line(title, 160)}.", now)
        for member in audience:
            if member.id != a.member.id and title and "coordinator" not in member.roles:
                # Same restrictions as the original notice, so nobody learns more than before.
                notify(s, self.wid, member.id, "report_withdrawn",
                       f"Withdrawn by {reporter}: {one_line(title, 160)}. Ignore the earlier report.",
                       f"withdrawn:{request_id}", now, teams=teams, permission=permission)
        return {"id": request_id, "status": "withdrawn", "title": target["title"]}

    def draft(self, actor: Actor, command: dict, summary: str) -> dict:
        """The model may propose only an already-authorized command; no mutation occurs."""
        cmd = COMMAND.validate_python(command)
        if cmd.type not in {"arrival", "report_incident", "propose_delay", "change_item", "withdraw_report", "broadcast",
                            "set_deputy_enabled", "task_action"}:
            raise denied("This action cannot be initiated from AI chat")
        with self.db.transaction(self.wid, write=True) as (s, w):
            a = load_access(s, actor, self.wid)
            self.authorize(s, a, cmd)
            if w.status == "archived":
                raise conflict("This wedding is archived")
            now = utcnow()
            # One pending draft per person: a newer draft replaces any earlier one, so a repeated
            # message can never leave two different reports waiting for a tap.
            for earlier in rows(s, ActionDraft, self.wid):
                if earlier.member_id == a.member.id and earlier.consumed_at is None and earlier.expires_at > now:
                    earlier.expires_at = now
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
                raise conflict("This draft expired or was replaced by a newer one. Use the newest draft, or tell me again")
            result = self._execute_in_tx(s, w, actor, a, cmd, draft.command, f"draft:{draft.id}")
            draft.consumed_at = utcnow()
            return result | {"command_type": cmd.type}
