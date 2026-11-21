"""Reproducible, wholly fictional demonstration. No real guest or vendor data."""
from __future__ import annotations

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .db import Database
from .models import *

DEMO_TIME = datetime(2026, 11, 14, 17, 45, tzinfo=ZoneInfo("Asia/Singapore"))


def at(hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return DEMO_TIME.replace(hour=hour, minute=minute)


def seed_demo(db: Database, wid: str = "demo-wedding") -> None:
    with db.sessions.begin() as s:
        if s.get(Wedding, wid):
            return
        s.add(Wedding(id=wid, name="Asha & Ben", timezone="Asia/Singapore", event_date="2026-11-14",
                      venue="Cedar House · fictional Singapore venue", status="live",
                      emergency_contact="Venue duty manager Lee (fictional), DEMO-NOT-A-REAL-NUMBER"))
        s.flush()
        for ident, name in [("coordination", "Coordination"), ("registration", "Registration"), ("ushers", "Ushers"),
                            ("family", "Family liaison"), ("photography", "Photography"), ("banquet", "Banquet"),
                            ("stage", "MC & AV"), ("transport", "Transport")]:
            s.add(Team(id=ident, wedding_id=wid, name=name))
        for ident, name, directions, x, y in [
            ("foyer", "Registration foyer", "Level 1, main entrance. Desks A and B beside the lift.", 12, 80),
            ("ballroom", "Cedar Ballroom", "Level 1, through the foyer's double doors.", 50, 45),
            ("garden", "Garden terrace", "Through the glass doors at the west side of the foyer.", 12, 30),
            ("stage", "Stage & AV desk", "Front of ballroom; AV desk at stage right.", 50, 10),
            ("service", "Banquet service door", "Staff-only east corridor. Keep access unobstructed.", 88, 55),
            ("portraits", "Portrait alcove", "North-west corner of the garden terrace.", 10, 10),
            ("entrance-b", "Ballroom Entrance B", "Second set of ballroom doors, off the foyer opposite the lift.", 30, 60),
            ("restrooms", "Restrooms", "Level 1, left of the foyer lift. Accessible restroom beside the service door.", 20, 70),
        ]:
            s.add(Location(id=ident, wedding_id=wid, name=name, directions=directions, x=x, y=y))
        s.flush()
        for number in range(1, 19):
            s.add(SeatingTable(id=f"table-{number}", wedding_id=wid, label=str(number), location_id="ballroom",
                               capacity=10, x=28 + ((number - 1) % 6) * 10, y=25 + ((number - 1) // 6) * 18))
        s.flush()
        names = [(f"guest-{i+1:03}", f"{first} {last}", None) for i, (first, last) in enumerate(
            (f, l) for f in ["Amelia", "Lucas", "Maya", "Ethan", "Chloe", "Noah", "Zoe", "Isaac", "Clara", "Liam", "Isla", "Oliver"]
            for l in ["Lim", "Ng", "Goh", "Wong", "Chan", "Lee", "Teo", "Ong", "Koh", "Yeo", "Chua", "Ho", "Tan", "Tay", "Sim"])]
        names[0:4] = [("father-bride", "Robert Tan", "father of bride"), ("mother-bride", "Grace Tan", "mother of bride"),
                      ("father-groom", "Daniel Lee", "father of groom"), ("mother-groom", "Mei Lee", "mother of groom")]
        names[-1] = ("sarah-tan", "Sarah Tan", None)
        for i, (ident, name, relationship) in enumerate(names):
            s.add(Person(id=ident, wedding_id=wid, name=name, is_guest=True, relationship=relationship,
                         table_id=f"table-{i//10+1}", rsvp="yes", attendance="onsite" if 4 <= i < 46 else "unknown",
                         arrived_at=at("17:35") if 4 <= i < 46 else None,
                         dietary_private="Vegetarian (fictional fixture)" if i % 17 == 0 else None,
                         private_phone="DEMO-NOT-A-REAL-NUMBER" if relationship else None))
        helpers = [
            ("coordinator", "Alex Morgan", ["coordinator"], ["coordination"]),
            ("registration-a", "Michelle Chen", ["registration"], ["registration"]),
            ("registration-b", "Ryan Goh", ["registration", "team_lead"], ["registration"]),
            ("usher", "Jamie Lim", ["usher"], ["ushers"]),
            ("family-liaison", "Priya Rao", ["family_liaison"], ["family"]),
            ("photographer", "Sam Koh", ["photographer"], ["photography"]),
            ("banquet", "Chris Wong", ["banquet", "team_lead"], ["banquet"]),
            ("mc", "Taylor Ng", ["mc"], ["stage"]),
            ("av", "Casey Teo", ["av"], ["stage"]),
            ("driver", "Jordan Tay", ["transport"], ["transport"]),
            ("couple", "Asha Tan", ["couple"], ["coordination"]),
        ]
        for ident, name, roles, teams in helpers:
            s.add(Person(id=f"person-{ident}", wedding_id=wid, name=name, is_guest=False))
        s.flush()
        for ident, name, roles, teams in helpers:
            s.add(Member(id=ident, wedding_id=wid, person_id=f"person-{ident}", roles=roles, active=True))
        s.flush()
        for ident, name, roles, teams in helpers:
            for team in teams:
                s.add(MemberTeam(wedding_id=wid, member_id=ident, team_id=team))
        for ident, title, time, duration, location, teams, instructions in [
            ("registration-open", "Guest registration", "18:00", 30, "foyer", ["registration", "ushers"], "Direct early arrivals to the garden terrace."),
            ("ceremony", "Garden ceremony", "18:30", 20, "garden", ["ushers", "photography", "family", "stage"], "Family liaison confirms front-row readiness before MC cue."),
            ("portraits", "Family portraits", "18:50", 10, "portraits", ["photography", "family"], "Assemble both parents and couple. Do not infer attendance."),
            ("dinner", "Dinner service", "19:00", 40, "ballroom", ["banquet", "ushers", "stage", "photography"], "Banquet captain confirms readiness. MC waits for coordinator cue."),
            ("speeches", "Family speeches", "19:45", 15, "stage", ["stage", "photography", "banquet"], "MC checks microphones. Photographer takes stage-left position."),
            ("dessert", "Dessert service", "20:00", 15, "ballroom", ["banquet"], "Serve after speeches finish."),
            ("toast", "Couple's toast", "20:20", 10, "stage", ["stage", "photography", "banquet"], "Confirm glassware and stage readiness."),
        ]:
            s.add(TimelineItem(id=ident, wedding_id=wid, title=title, planned_start=at(time), current_start=at(time),
                               duration_minutes=duration, latest_end=at("20:40") if ident == "toast" else None,
                               location_id=location, team_ids=teams, instructions=instructions, status="scheduled"))
        s.flush()
        for child, parent in [("ceremony", "registration-open"), ("portraits", "ceremony"), ("dinner", "portraits"),
                              ("speeches", "dinner"), ("dessert", "speeches"), ("toast", "dessert")]:
            s.add(TimelineDependency(wedding_id=wid, item_id=child, depends_on_id=parent, lag_minutes=0))
        task_data = [
            ("signage", "Confirm Desk B signage", "registration-b", "registration", "foyer", "17:40", None, 0, "Check the table-zone signs. Acknowledge when you have seen this assignment."),
            ("desk-a", "Open registration Desk A", "registration-a", "registration", "foyer", "17:55", "registration-open", -5, "Have the guest search open. Refer unlisted guests to Alex."),
            ("desk-b", "Open registration Desk B", "registration-b", "registration", "foyer", "17:55", "registration-open", -5, "Set up the second registration queue once signage is ready."),
            ("usher-ready", "Take position at Ballroom Entrance B", "usher", "ushers", "entrance-b", "17:50", None, 0, "Direct guests to the garden terrace until seating is announced."),
            ("family-check", "Confirm parents' arrival", "family-liaison", "family", "foyer", "18:15", None, 0, "Confirm reported arrival; unknown does not mean absent."),
            ("photo-family", "Assemble family portrait group A", "photographer", "photography", "portraits", "18:45", "portraits", -5, "Coordinate with Priya. The bride's parents are needed."),
            ("banquet-ready", "Confirm dinner readiness", "banquet", "banquet", "service", "18:50", "dinner", -10, "Confirm service staff and dietary meals. Report delays, do not change the master timeline."),
            ("mc-dinner", "Prepare dinner announcement", "mc", "stage", "stage", "18:58", "dinner", -2, "Wait for coordinator-approved go-ahead."),
            ("av-check", "Check wireless microphones", "av", "stage", "stage", "18:15", None, 0, "Test both microphones with the MC."),
            ("transport-ready", "Confirm shuttle drop-off route", "driver", "transport", "foyer", "17:50", None, 0, "Use the signed east driveway. No guest phone numbers are exposed."),
        ]
        for ident, title, owner, team, loc, due, timeline, offset, instructions in task_data:
            s.add(Task(id=ident, wedding_id=wid, title=title, owner_id=owner, team_id=team, location_id=loc,
                       planned_due=at(due), due_at=at(due), timeline_item_id=timeline, offset_minutes=offset,
                       instructions=instructions, state="pending"))
        s.flush()
        s.add(TaskDependency(wedding_id=wid, task_id="desk-b", depends_on_id="signage"))
        for ident, name, cat, contact, team, time in [
            ("vendor-catering", "Cedar Table Catering", "Banquet", "Chris Wong", "banquet", "16:30"),
            ("vendor-photo", "Silverleaf Photography", "Photography", "Sam Koh", "photography", "16:00"),
            ("vendor-av", "Clear Note AV", "Sound", "Casey Teo", "stage", "15:30"),
        ]:
            s.add(Vendor(id=ident, wedding_id=wid, name=name, category=cat, contact_name=contact,
                         contact_phone="DEMO CONTACT — not dialable", team_id=team, expected_at=at(time), status="onsite"))
        docs = [
            ("venue-guide", "Cedar House venue briefing", "cedar-house-briefing.txt", [],
             "Registration desks are in the Level 1 foyer beside the lift.\nThe service lift is in the east staff corridor, behind the banquet service door.\nPhotographers may use the portrait alcove on the north-west garden terrace.\nIn an emergency contact the on-site venue duty manager and local emergency services directly; do not wait for the AI.\nKeep all marked exits and the service corridor unobstructed."),
            ("banquet-guide", "Banquet service notes", "banquet-approved-runbook.txt", ["banquet"],
             "Vegetarian meals are labelled with green service cards. Confirm the table and name before serving.\nReport a service delay to the coordinator; only an approved timeline change alters the run sheet."),
        ]
        for ident, title, source, audience, text in docs:
            s.add(KnowledgeDocument(id=ident, wedding_id=wid, title=title, source_name=source,
                                   text=text, content_hash=hashlib.sha256(text.encode()).hexdigest(), audience_team_ids=audience,
                                   status="approved", created_by="coordinator", verified_at=at("16:00")))
        s.add(AuditEvent(wedding_id=wid, actor_id="system", event_type="demo_seeded", entity_id=wid,
                         detail={"fictional": True, "guests": 180}, state_version=1, created_at=DEMO_TIME))
