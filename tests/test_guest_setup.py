"""Guest corrections and dual guest/helper identity without expanding helper PII access."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from wedding_ops.api import create_app
from wedding_ops.config import Settings
from wedding_ops.errors import OpsError
from wedding_ops.models import Member, Person
from wedding_ops.policy import Actor
from wedding_ops.views import rows

WID = 'demo-wedding'
def actor(name='coordinator'): return Actor(WID, name)

def correction(queries, **changes):
    details = queries.guest_details(actor(), 'sarah-tan')
    return {'type':'edit_guest', 'person_id':details.pop('id'),
            'expected_version':details.pop('version'), **details, **changes}


def test_correct_guest_family_role_with_concurrency_and_audit(ops,queries):
    command = correction(queries, relationship='sister_of_bride', private_phone='DEMO-NOT-ROUTABLE')
    result = ops.execute(actor(), command, 'edit-sarah-family')
    assert result['version'] == 2 and 'private_phone' not in result
    assert any(p['name']=='Sarah Tan' for p in queries.family(actor('photographer')))
    assert next(p for p in queries.family_contacts(actor('family-liaison')) if p['id']=='sarah-tan')['private_phone']=='DEMO-NOT-ROUTABLE'
    with pytest.raises(OpsError): ops.execute(actor(), command, 'stale-edit-sarah-family')
    assert all('DEMO-NOT-ROUTABLE' not in str(e) for e in queries.audit(actor()))
    assert 'private_phone' not in queries.guests(actor('registration-a'),'Sarah')[0]
    assert 'private_phone' not in queries.family(actor('photographer'),'Sarah')[0]


@pytest.mark.parametrize('member',['usher','registration-a','photographer','banquet'])
def test_sensitive_guest_detail_and_family_contacts_denied(ops,queries,member):
    with pytest.raises(OpsError): queries.guest_details(actor(member),'sarah-tan')
    with pytest.raises(OpsError): queries.family_contacts(actor(member))
    with pytest.raises(OpsError): ops.execute(actor(member),correction(queries),'denied-edit-guest')


def test_family_contact_removal_and_agent_source_denial(ops,queries):
    ops.execute(actor(),correction(queries,relationship='sister_of_bride',private_phone='DEMO-PHONE'),'add-family-sarah')
    ops.execute(actor(),correction(queries,relationship=None),'remove-family-sarah')
    assert not any(p['id']=='sarah-tan' for p in queries.family_contacts(actor('family-liaison')))
    assert queries.guest_details(actor(),'sarah-tan')['private_phone']=='DEMO-PHONE'
    with pytest.raises(OpsError):queries.guest_details(Actor(WID,'coordinator','agent'),'sarah-tan')
    with pytest.raises(OpsError):queries.family_contacts(Actor(WID,'coordinator','agent'))


def test_edit_guest_seat_capacity_and_foreign_references(ops,queries):
    snap=queries.snapshot(actor())
    other=next(t['id'] for t in snap['tables'] if t['label']=='1')
    with pytest.raises(OpsError):ops.execute(actor(),correction(queries,table_id=other),'no-spare-seats')
    with pytest.raises(OpsError):ops.execute(actor(),correction(queries,table_id='other-wedding-table'),'cross-wedding-seat')
    result=ops.execute(actor(),correction(queries,table_id=None),'unassign-seat')
    assert result['status']=='updated'
    assert queries.guests(actor('usher'),'Sarah')[0]['table'] is None


def test_existing_guest_membership_preserves_single_person(db,ops,queries):
    with db.transaction(WID) as (s,w): before=len(rows(s,Person,WID))
    payload={'type':'create_member','person_id':'sarah-tan','roles':['usher'],'team_ids':['ushers']}
    result=ops.execute(actor(),payload,'sarah-usher-membership')
    with db.transaction(WID) as (s,w):
        assert len(rows(s,Person,WID))==before
        member=s.get(Member,result['id'])
        assert member.person_id=='sarah-tan'
    assert queries.guests(actor('usher'),'Sarah')[0]['table']=='18'
    assert queries.snapshot(actor(result['id']))['me']['name']=='Sarah Tan'
    with pytest.raises(OpsError):ops.execute(actor(),payload,'duplicate-guest-membership')
    with pytest.raises(ValidationError):ops.execute(actor(),dict(payload,name='Duplicate Sarah'),'ambiguous-person-source')
    with pytest.raises(OpsError):ops.execute(actor(),dict(payload,person_id='other-wedding-person'),'foreign-person-source')


def test_guest_detail_and_contact_routes_enforce_current_membership(db,clock):
    config=Settings(mode='demo')
    with TestClient(create_app(config,db,clock),base_url=config.public_url) as client:
        client.headers['Origin']=config.public_url
        assert client.get('/api/guests/sarah-tan/details').status_code==401
        client.post('/api/auth/demo',json={'member_id':'usher'})
        assert client.get('/api/guests/sarah-tan/details').status_code==403
        assert client.get('/api/family/contacts').status_code==403
        client.post('/api/auth/demo',json={'member_id':'family-liaison'})
        assert client.get('/api/family/contacts').status_code==200
        assert client.get('/api/guests/sarah-tan/details').status_code==403
        client.post('/api/auth/demo',json={'member_id':'coordinator'})
        assert client.get('/api/guests/sarah-tan/details').json()['name']=='Sarah Tan'
