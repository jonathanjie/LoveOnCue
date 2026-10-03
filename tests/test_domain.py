from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from wedding_ops.agent import Assistant
from wedding_ops.errors import OpsError
from wedding_ops.models import Approval, AuditEvent, Notification, Person, Task, TimelineDependency, TimelineItem, Wedding
from wedding_ops.policy import Actor
from wedding_ops.schemas import COMMAND
from wedding_ops.views import rows

WID = "demo-wedding"
def actor(name="coordinator", source="web"):
    return Actor(WID, name, source)

def proposal(ops, minutes=12, key="proposal-test-1"):
    return ops.execute(actor("banquet"), {"type":"propose_delay", "item_id":"dinner", "minutes":minutes,"reason":"Kitchen reports a delay"},key)

def decide(ops, ident, decision="approve", key="decide-test-1", who="coordinator", source="web"):
    return ops.execute(actor(who,source), {"type":"decide_approval", "approval_id":ident,"decision":decision},key)


def test_seed_and_role_tasks(queries):
    view = queries.snapshot(actor("usher"))
    assert view["counts"]["guests"] == 180
    assert [t["id"] for t in view["tasks"]] == ["usher-ready"]
    assert view["vendors"] == []
    assert all("private_phone" not in m for m in view["members"])


def test_seating_and_private_field_policy(queries):
    result = queries.guests(actor("registration-a"), "Sarah Tan")
    assert result[0]["table"] == "18"
    assert "dietary" not in result[0] and "private_phone" not in result[0]
    with pytest.raises(OpsError) as error:
        queries.guests(actor("usher"), "Robert", sensitive=True)
    assert error.value.status == 403
    assert queries.guests(actor("banquet"), "Robert", sensitive=True)[0]["dietary"]


def test_delay_needs_human_approval_and_preserves_slack(ops, queries, db):
    before = queries.snapshot(actor())["timeline"]
    p = proposal(ops)
    assert queries.snapshot(actor())["timeline"] == before
    with pytest.raises(OpsError):
        decide(ops, p["id"], who="banquet")
    with pytest.raises(OpsError):
        decide(ops, p["id"], source="agent")
    decide(ops, p["id"])
    after = queries.snapshot(actor())["timeline"]
    changes = {a["id"]: a["current_start"] for a in after}
    assert changes["dinner"].endswith("11:12:00Z")
    assert changes["speeches"].endswith("11:52:00Z")  # absorbs five-minute gap
    assert changes["toast"].endswith("12:22:00Z")  # absorbs another five minutes
    with db.transaction(WID) as (s,w):
        assert w.timeline_version == 2
        assert s.get(Task,"banquet-ready").due_at.minute == 2
        notices = [n for n in rows(s,Notification,WID) if n.topic == "timeline_updated"]
        assert "registration-a" not in [n.recipient_id for n in notices]
        assert {"coordinator","banquet","usher","mc","photographer"}.issubset({n.recipient_id for n in notices})
        banquet_text = next(n.message for n in notices if n.recipient_id == "banquet")
        assert "19:12" in banquet_text
        assert any(e.event_type == "decide_approval" for e in rows(s,AuditEvent,WID))


def test_duplicate_approval_does_not_shift_twice(ops,queries):
    p=proposal(ops)
    one=decide(ops,p["id"])
    two=decide(ops,p["id"])
    assert two["replayed"] and two["timeline_version"] == one["timeline_version"]
    with pytest.raises(OpsError):
        decide(ops,p["id"],key="different-key")


def test_idempotency_payload_conflict(ops):
    proposal(ops)
    with pytest.raises(OpsError) as error:
        proposal(ops,minutes=13)
    assert error.value.status == 409


def test_stale_proposal_cannot_commit(ops):
    one=proposal(ops,key="first-proposal")
    two=proposal(ops,key="second-proposal")
    decide(ops,one["id"])
    with pytest.raises(OpsError) as error:
        decide(ops,two["id"],key="other-approval")
    assert "timeline changed" in error.value.message.lower()


def test_concurrent_decisions_only_one_wins(ops):
    p=proposal(ops)
    def attempt(key):
        try:
            return decide(ops,p["id"],key=key)["status"]
        except OpsError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,["concurrent-one","concurrent-two"]))
    assert sorted(results)==["approved","conflict"]


def test_expired_and_blocked_proposals(ops,clock):
    p=proposal(ops)
    clock.advance(11)
    with pytest.raises(OpsError,match="expired"):
        decide(ops,p["id"])
    p=proposal(ops,minutes=100,key="huge-delay-key")
    assert p["blocked"]
    with pytest.raises(OpsError,match="Hard constraints"):
        decide(ops,p["id"],key="blocked-approve")


def test_reject_keeps_schedule(ops,queries):
    before=queries.snapshot(actor())["timeline"]
    p=proposal(ops)
    assert decide(ops,p["id"],decision="reject")["status"]=="rejected"
    assert queries.snapshot(actor())["timeline"]==before


def test_dependency_cycle_blocks_proposal(db,ops):
    with db.transaction(WID,write=True) as (s,w):
        s.add(TimelineDependency(wedding_id=WID,item_id="dinner",depends_on_id="toast",lag_minutes=0))
    with pytest.raises(OpsError) as err:
        proposal(ops)
    assert err.value.code=="dependency_cycle"


def test_task_authority_version_and_dependencies(ops):
    cmd={"type":"task_action","task_id":"desk-b","action":"complete","expected_version":1}
    with pytest.raises(OpsError): ops.execute(actor("usher"),cmd,"bad-task-user")
    with pytest.raises(OpsError,match="prerequisite"): ops.execute(actor("registration-b"),cmd,"blocked-task")
    ops.execute(actor("registration-b"),{"type":"task_action","task_id":"signage","action":"complete","expected_version":1},"complete-signage")
    assert ops.execute(actor("registration-b"),cmd,"complete-desk-b")["status"]=="done"
    with pytest.raises(OpsError): ops.execute(actor("registration-b"),cmd,"stale-desk-b")


def test_family_reporting_then_arrival_targets_teams(ops,queries,db):
    bot=Assistant(queries,ops)
    d=bot.ask(actor("photographer"),"Bride's father isn't here yet.")["draft"]
    assert queries.snapshot(actor())["counts"]["open_incidents"]==0
    report=ops.confirm(actor("photographer"),d["id"])
    assert queries.family(actor("photographer"),"father of bride")[0]["attendance"]=="unknown"
    d=bot.ask(actor("registration-a"),"Bride's parents just arrived.")["draft"]
    ops.confirm(actor("registration-a"),d["id"])
    assert queries.family(actor("photographer"),"father of bride")[0]["attendance"]=="onsite"
    assert queries.snapshot(actor("photographer"))["incidents"][0]["status"]=="resolved"
    assert queries.snapshot(actor("usher"))["incidents"]==[]
    with db.transaction(WID) as (s,w):
        assert all(n.recipient_id in {"coordinator","photographer","family-liaison"} for n in rows(s,Notification,WID))


def test_confirmation_owned_and_idempotent(ops,queries):
    draft=Assistant(queries,ops).ask(actor("banquet"),"Dinner needs another 12 minutes")["draft"]
    with pytest.raises(OpsError): ops.confirm(actor(),draft["id"])
    result=ops.confirm(actor("banquet"),draft["id"])
    assert ops.confirm(actor("banquet"),draft["id"])["replayed"]
    assert result["status"]=="pending"


def test_tenant_id_and_cross_tenant_foreign_keys(db,queries):
    with pytest.raises(OpsError) as error:
        queries.snapshot(Actor("some-other-wedding","coordinator"))
    assert error.value.status==404
    with db.sessions.begin() as s:
        s.add(Wedding(id="other",name="Other",timezone="UTC",event_date="2026-11-14",venue="Other"))
    with pytest.raises(IntegrityError):
        with db.sessions.begin() as s:
            s.add(Person(id="foreign-guest",wedding_id="other",name="Example",table_id="table-18"))


def test_agent_and_injected_identity_rejected(ops):
    with pytest.raises(ValidationError):
        COMMAND.validate_python({"type":"arrival","person_ids":["sarah-tan"],"roles":["coordinator"]})
    with pytest.raises(OpsError):
        ops.execute(actor("coordinator","agent"),{"type":"arrival","person_ids":["sarah-tan"]},"agent-write-attempt")


def test_revocation_applies_to_replays(ops):
    p=proposal(ops)
    ops.execute(actor(),{"type":"revoke_member","member_id":"banquet"},"revoke-banquet")
    with pytest.raises(OpsError): proposal(ops)


def test_archive_blocks_writes(ops):
    ops.execute(actor(),{"type":"set_wedding_status","status":"archived"},"archive-wedding")
    with pytest.raises(OpsError,match="archived"): proposal(ops)
