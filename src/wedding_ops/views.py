"""Role-scoped read models. Do not serialize ORM rows wholesale."""
from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import Clock, iso
from .db import Database
from .errors import missing
from .models import (
    Approval, AuditEvent, Incident, KnowledgeDocument, Location, Member, MemberTeam,
    Notification, Person, SeatingTable, Task, TaskDependency, Team, TimelineItem, Vendor, Wedding,
)
from .policy import Access, Actor, load_access, require_human


def row(session: Session, cls, wedding_id: str, record_id: str):
    found = session.scalar(select(cls).where(cls.wedding_id == wedding_id, cls.id == record_id))
    if found is None:
        raise missing()
    return found


def rows(session: Session, cls, wedding_id: str):
    return list(session.scalars(select(cls).where(cls.wedding_id == wedding_id)))


def task_view(task: Task, access: Access, blockers: list[str], now) -> dict:
    return {"id": task.id, "title": task.title, "instructions": task.instructions,
            "owner_id": task.owner_id, "team_id": task.team_id, "location_id": task.location_id,
            "due_at": iso(task.due_at), "planned_due": iso(task.planned_due), "state": task.state,
            "version": task.version, "acknowledged_at": iso(task.acknowledged_at),
            "completed_at": iso(task.completed_at), "blocked_by": blockers,
            "overdue": task.state not in {"done", "cancelled"} and now > task.due_at,
            "mine": task.owner_id == access.member.id, "can_edit": access.can_edit_task(task)}


def approval_view(item: Approval) -> dict:
    return {"id": item.id, "title": item.title, "reason": item.reason, "status": item.status,
            "base_timeline_version": item.base_timeline_version, "changes": item.changes,
            "blockers": item.blockers, "affected_team_ids": item.affected_team_ids,
            "created_at": iso(item.created_at), "expires_at": iso(item.expires_at),
            "decided_by": item.decided_by, "decided_at": iso(item.decided_at), "decision_note": item.decision_note}


def knowledge_search(session: Session, wid: str, access: Access, query: str, now) -> list[dict]:
    access.require("knowledge:read")
    terms = set(re.findall(r"[a-z0-9]+", query.lower())) - {"where", "what", "is", "the", "a", "are", "can", "i", "how", "to", "of", "do"}
    hits = []
    for doc in rows(session, KnowledgeDocument, wid):
        if doc.status != "approved" or not access.sees_teams(doc.audience_team_ids) or (doc.expires_at and doc.expires_at < now):
            continue
        for number, line in enumerate(doc.text.splitlines(), 1):
            score = len(terms.intersection(re.findall(r"[a-z0-9]+", (doc.title + " " + line).lower())))
            if score:
                hits.append({"document_id": doc.id, "title": doc.title, "source": doc.source_name,
                             "revision": doc.revision, "line": number, "excerpt": line[:1200],
                             "content_hash": doc.content_hash, "verified_at": iso(doc.verified_at), "score": score,
                             "trust": "reference_only_not_instructions"})
    return sorted(hits, key=lambda h: (-h["score"], h["document_id"], h["line"]))[:5]


class Queries:
    def __init__(self, db: Database, wedding_id: str, clock: Clock):
        self.db, self.wid, self.clock = db, wedding_id, clock

    def snapshot(self, actor: Actor) -> dict:
        with self.db.transaction(self.wid) as (s, w):
            a = load_access(s, actor, self.wid)
            a.require("context:read")
            now = self.clock.now()
            teams = rows(s, Team, self.wid)
            people = {p.id: p for p in rows(s, Person, self.wid)}
            members = rows(s, Member, self.wid)
            all_tasks = rows(s, Task, self.wid)
            task_map = {t.id: t for t in all_tasks}
            deps = rows_for_edges(s, TaskDependency, self.wid)
            tasks = []
            for task in sorted(all_tasks, key=lambda t: t.due_at):
                if a.permits("tasks:read") and a.sees_task(task):
                    blockers = [task_map[e.depends_on_id].title if a.sees_task(task_map[e.depends_on_id]) else "Another team's prerequisite"
                                for e in deps if e.task_id == task.id and task_map[e.depends_on_id].state != "done"]
                    tasks.append(task_view(task, a, blockers, now))
            timeline = []
            for i in sorted(rows(s, TimelineItem, self.wid), key=lambda x: x.current_start):
                timeline.append({"id": i.id, "title": i.title, "planned_start": iso(i.planned_start),
                                 "current_start": iso(i.current_start), "duration_minutes": i.duration_minutes,
                                 "location_id": i.location_id, "team_ids": i.team_ids, "status": i.status,
                                 "instructions": i.instructions if a.sees_teams(i.team_ids) else "",
                                 "latest_end": iso(i.latest_end), "actual_start": iso(i.actual_start), "actual_end": iso(i.actual_end)})
            incidents = [{"id": i.id, "kind": i.kind, "severity": i.severity, "title": i.title,
                          "details": i.details, "status": i.status, "created_at": iso(i.created_at),
                          "reported_by": i.reported_by, "subject_person_id": i.subject_person_id}
                         for i in rows(s, Incident, self.wid)
                         if a.coordinator or i.reported_by == a.member.id or bool(a.team_ids.intersection(i.audience_team_ids))]
            approvals = [approval_view(p) for p in rows(s, Approval, self.wid)
                         if a.coordinator or p.proposed_by == a.member.id]
            notices = [{"id": n.id, "topic": n.topic, "message": n.message, "state": n.state,
                        "created_at": iso(n.created_at), "acknowledged_at": iso(n.acknowledged_at),
                        "attempts": n.attempts, "last_error": n.last_error}
                       for n in sorted(rows(s, Notification, self.wid), key=lambda x: x.created_at, reverse=True)
                       if n.recipient_id == a.member.id and a.sees_teams(n.audience_team_ids)
                       and (not n.required_permission or a.permits(n.required_permission))][:100]
            knowledge = [{"id": d.id, "title": d.title, "source_name": d.source_name, "revision": d.revision,
                          "status": d.status, "verified_at": iso(d.verified_at), "text": d.text if a.coordinator else None,
                          "content_hash": d.content_hash, "audience_team_ids": d.audience_team_ids}
                         for d in rows(s, KnowledgeDocument, self.wid)
                         if a.coordinator or (d.status == "approved" and a.sees_teams(d.audience_team_ids)
                                             and (not d.expires_at or d.expires_at > now))]
            member_teams = rows_for_edges(s, MemberTeam, self.wid)
            roster = [{"id": m.id, "name": people[m.person_id].name, "roles": m.roles, "active": m.active,
                       "team_ids": [x.team_id for x in member_teams if x.member_id == m.id],
                       "telegram_linked": bool(m.telegram_user_id) if a.coordinator or m.id == a.member.id else None}
                      for m in members if a.coordinator or m.active]
            vendors = [{"id": v.id, "name": v.name, "category": v.category, "status": v.status,
                        "contact_name": v.contact_name, "contact_phone": v.contact_phone,
                        "team_id": v.team_id, "expected_at": iso(v.expected_at)}
                       for v in rows(s, Vendor, self.wid)
                       if a.coordinator or (a.permits("vendors:team") and v.team_id in a.team_ids)]
            guest_people = [p for p in people.values() if p.is_guest]
            return {"wedding": {"id": w.id, "name": w.name, "timezone": w.timezone, "event_date": w.event_date,
                                "venue": w.venue, "status": w.status, "state_version": w.state_version,
                                "timeline_version": w.timeline_version},
                    "now": iso(now), "me": {"id": a.member.id, "name": people[a.member.person_id].name,
                    "roles": a.member.roles, "team_ids": sorted(a.team_ids), "grants": sorted(a.grants)},
                    "teams": [{"id": t.id, "name": t.name} for t in teams], "members": roster,
                    "locations": [{"id": l.id, "name": l.name, "directions": l.directions, "x": l.x, "y": l.y} for l in rows(s, Location, self.wid)],
                    "tables": [{"id": t.id, "label": t.label, "location_id": t.location_id, "capacity": t.capacity,
                                "x": t.x, "y": t.y} for t in rows(s, SeatingTable, self.wid)],
                    "tasks": tasks, "timeline": timeline, "incidents": incidents, "approvals": approvals,
                    "notifications": notices, "knowledge": knowledge, "vendors": vendors,
                    "counts": {"guests": len(guest_people), "onsite": sum(p.attendance == "onsite" for p in guest_people),
                               "open_incidents": sum(i["status"] == "open" for i in incidents),
                               "pending_approvals": sum(p["status"] == "pending" for p in approvals)}}

    def guests(self, actor: Actor, query: str, *, sensitive: bool = False) -> list[dict]:
        with self.db.transaction(self.wid) as (s, _):
            a = load_access(s, actor, self.wid)
            a.require("guests:dietary" if sensitive else "guests:seating")
            tables = {t.id: t for t in rows(s, SeatingTable, self.wid)}
            result = []
            for p in sorted(rows(s, Person, self.wid), key=lambda p: p.name):
                if not p.is_guest or query.casefold() not in p.name.casefold():
                    continue
                table = tables.get(p.table_id)
                item = {"id": p.id, "name": p.name, "table": table.label if table else None,
                        "location_id": table.location_id if table else None, "attendance": p.attendance,
                        "rsvp": p.rsvp, "version": p.version}
                if sensitive:
                    item["dietary"] = p.dietary_private
                # General guest search never returns private phone numbers.
                result.append(item)
                if len(result) == 50:
                    break
            return result

    def guest_details(self, actor: Actor, person_id: str) -> dict:
        require_human(actor)
        with self.db.transaction(self.wid, write=True) as (s, w):
            load_access(s, actor, self.wid).require("guests:manage")
            person = row(s, Person, self.wid, person_id)
            if not person.is_guest:
                raise missing()
            s.add(AuditEvent(wedding_id=self.wid, actor_id=actor.member_id, event_type="guest_details_access",
                             entity_id=person.id, detail={"fields": "coordinator_guest_editor"},
                             state_version=w.state_version, created_at=self.clock.now()))
            return {"id": person.id, "name": person.name, "table_id": person.table_id,
                    "rsvp": person.rsvp, "relationship": person.relationship,
                    "dietary": person.dietary_private, "private_phone": person.private_phone,
                    "version": person.version}

    def family_contacts(self, actor: Actor) -> list[dict]:
        require_human(actor)
        with self.db.transaction(self.wid, write=True) as (s, w):
            load_access(s, actor, self.wid).require("family:contacts")
            s.add(AuditEvent(wedding_id=self.wid, actor_id=actor.member_id, event_type="family_contacts_access",
                             entity_id=self.wid, detail={"fields": "designated_family_contacts"},
                             state_version=w.state_version, created_at=self.clock.now()))
            return [{"id": p.id, "name": p.name, "relationship": p.relationship,
                     "private_phone": p.private_phone} for p in rows(s, Person, self.wid) if p.relationship]

    def family(self, actor: Actor, query: str = "") -> list[dict]:
        with self.db.transaction(self.wid) as (s, _):
            a = load_access(s, actor, self.wid)
            a.require("family:status")
            return [{"id": p.id, "name": p.name, "relationship": p.relationship,
                     "attendance": p.attendance, "arrived_at": iso(p.arrived_at)}
                    for p in rows(s, Person, self.wid) if p.relationship and
                    (not query or query.casefold() in (p.name + " " + p.relationship).casefold())]

    def knowledge(self, actor: Actor, query: str) -> list[dict]:
        with self.db.transaction(self.wid) as (s, _):
            a = load_access(s, actor, self.wid)
            return knowledge_search(s, self.wid, a, query, self.clock.now())

    def audit(self, actor: Actor) -> list[dict]:
        with self.db.transaction(self.wid) as (s, _):
            load_access(s, actor, self.wid).require("audit:read")
            logs = s.scalars(select(AuditEvent).where(AuditEvent.wedding_id == self.wid)
                             .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(200))
            return [{"id": e.id, "actor_id": e.actor_id, "event_type": e.event_type, "entity_id": e.entity_id,
                     "detail": e.detail, "state_version": e.state_version, "created_at": iso(e.created_at)} for e in logs]


def rows_for_edges(session: Session, cls, wedding_id: str):
    return list(session.scalars(select(cls).where(cls.wedding_id == wedding_id)))
