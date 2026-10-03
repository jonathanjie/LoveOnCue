"""Construction from an empty cell, frozen migrations and database portability checks."""
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_mock_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from pydantic import ValidationError

from wedding_ops.auth import Auth
from wedding_ops.cli import bootstrap
from wedding_ops.clock import DemoClock, iso
from wedding_ops.config import Settings
from wedding_ops.db import Database
from wedding_ops.errors import OpsError
from wedding_ops.models import Base, TimelineItem
from wedding_ops.policy import Actor
from wedding_ops.seed import DEMO_TIME
from wedding_ops.views import Queries

WID='demo-wedding'
def actor(member='coordinator'):return Actor(WID,member)


def test_frozen_migration_upgrade_matches_metadata_and_downgrades(tmp_path,monkeypatch):
    url=f"sqlite:///{tmp_path/'migrated.db'}"
    monkeypatch.setenv('WEDDINGOPS_DATABASE_URL',url)
    config=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    command.upgrade(config,'head')
    database=Database(url)
    assert set(Base.metadata.tables).issubset(inspect(database.engine).get_table_names())
    command.check(config)
    # A real empty-wedding bootstrap uses the migration, not create_all.
    config_app=Settings(mode='test',database_url=url,wedding_id='fresh-cell')
    result=bootstrap(database,config_app,'Mira & Leo','2026-11-14','Example venue','Jo Coordinator','Asia/Singapore')
    login=Auth(database,config_app).redeem(result['invitation']['token'])
    session_actor=Auth(database,config_app).authenticate(login['token'])
    assert Queries(database,'fresh-cell',DemoClock(DEMO_TIME)).snapshot(session_actor)['wedding']['name']=='Mira & Leo'
    with pytest.raises(ValueError):bootstrap(database,config_app,'Again','2026-11-14','Venue','Jo','Asia/Singapore')
    database.close()
    command.downgrade(config,'base')
    after=Database(url)
    assert inspect(after.engine).get_table_names()==['alembic_version']
    after.close()


def test_postgres_ddl_compiles_and_constraint_names_do_not_collide():
    # Dialect compilation is not a PostgreSQL runtime test. CI runs the suite against PostgreSQL.
    index_names=[]
    for table in Base.metadata.sorted_tables:
        ddl=str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert 'CREATE TABLE' in ddl
        names=[str(c.name) for c in table.constraints if c.name]
        assert len(names)==len(set(names)),(table.name,names)
        index_names.extend(str(c.name) for c in table.constraints if c.__class__.__name__ in {'PrimaryKeyConstraint','UniqueConstraint'})
        index_names.extend(str(i.name) for i in table.indexes)
    assert len(index_names)==len(set(index_names))
    statements=[]
    engine=create_mock_engine('postgresql+psycopg://',lambda sql,*a,**k:statements.append(str(sql.compile(dialect=postgresql.dialect()))))
    Base.metadata.create_all(engine)
    assert sum('CREATE TABLE' in sql for sql in statements)==len(Base.metadata.tables)


def test_setup_crud_is_coordinator_only_and_scoped(ops,queries):
    location=ops.execute(actor(),{'type':'create_location','name':'Garden terrace','directions':'Through the west foyer','x':75,'y':25},'new-location-key')
    table=ops.execute(actor(),{'type':'create_table','label':'19','capacity':8,'location_id':location['id']},'new-table-key')
    team=ops.execute(actor(),{'type':'create_team','name':'Floristry'},'new-team-key')
    member=ops.execute(actor(),{'type':'create_member','name':'Morgan Florist','roles':['av'],'team_ids':[team['id']]},'new-member-key')
    task=ops.execute(actor(),{'type':'create_task','title':'Place terrace arrangements','owner_id':member['id'],'team_id':team['id'],'location_id':location['id'],'due_at':iso(DEMO_TIME+timedelta(minutes=5))},'new-task-key')
    snapshot=queries.snapshot(actor())
    assert any(t['id']==task['id'] for t in snapshot['tasks'])
    assert any(t['id']==table['id'] for t in snapshot['tables'])
    with pytest.raises(OpsError):ops.execute(actor('usher'),{'type':'create_team','name':'Elevated'},'unauthorized-team')
    with pytest.raises(OpsError):ops.execute(actor(),{'type':'create_member','name':'Bad Role','roles':['superuser'],'team_ids':[team['id']]},'unknown-role-key')
    with pytest.raises(OpsError):ops.execute(actor(),{'type':'create_table','label':'19','location_id':location['id']},'duplicate-table-key')


def test_setup_invalid_ownership_prerequisites_and_times(ops):
    payload={'type':'create_task','title':'Bad assignment','owner_id':'usher','team_id':'banquet','location_id':'foyer','due_at':iso(DEMO_TIME)}
    with pytest.raises(OpsError):ops.execute(actor(),payload,'ownership-invalid')
    with pytest.raises(ValidationError):ops.execute(actor(),dict(payload,due_at='2026-11-14T18:00:00'),'naive-timestamp-key')
    with pytest.raises(OpsError):ops.execute(actor(),{'type':'create_timeline_item','title':'Invalid event','starts_at':iso(DEMO_TIME),'duration_minutes':10,'location_id':'foyer','team_ids':['ushers'],'depends_on_ids':['missing-item']},'unknown-prerequisite')


def test_actual_timeline_cues_do_not_infer_completion(ops,queries,clock):
    assert next(x for x in queries.snapshot(actor())['timeline'] if x['id']=='registration-open')['status']=='scheduled'
    with pytest.raises(OpsError):ops.execute(actor(),{'type':'timeline_action','item_id':'ceremony','action':'start','expected_timeline_version':1},'premature-ceremony')
    start=ops.execute(actor(),{'type':'timeline_action','item_id':'registration-open','action':'start','expected_timeline_version':1},'start-registration')
    assert start['timeline_version']==2
    with pytest.raises(OpsError):ops.execute(actor(),{'type':'propose_delay','item_id':'registration-open','minutes':5,'reason':'Already live'},'delay-live-activity')
    clock.advance(5)
    complete=ops.execute(actor(),{'type':'timeline_action','item_id':'registration-open','action':'complete','expected_timeline_version':2},'finish-registration')
    assert complete['timeline_version']==3
    item=next(x for x in queries.snapshot(actor())['timeline'] if x['id']=='registration-open')
    assert item['actual_start'] and item['actual_end'] and item['actual_start']!=item['actual_end']
    with pytest.raises(OpsError):ops.execute(actor(),{'type':'timeline_action','item_id':'ceremony','action':'start','expected_timeline_version':2},'stale-timeline-cue')
    with pytest.raises(OpsError):ops.execute(actor('usher'),{'type':'timeline_action','item_id':'ceremony','action':'start','expected_timeline_version':3},'helper-timeline-cue')


def test_new_timeline_dependencies_reject_infeasible_initial_times(ops,queries):
    future=DEMO_TIME+timedelta(hours=3)
    command_data={'type':'create_timeline_item','title':'After-party transfer','starts_at':iso(future),'duration_minutes':15,'location_id':'foyer','team_ids':['transport'],'depends_on_ids':['toast']}
    added=ops.execute(actor(),command_data,'create-late-activity')
    assert added['id'] in [x['id'] for x in queries.snapshot(actor())['timeline']]
    with pytest.raises(OpsError):ops.execute(actor(),dict(command_data,starts_at=iso(DEMO_TIME)),'create-before-parent')
    with pytest.raises(OpsError):ops.execute(actor(),dict(command_data,latest_end=iso(DEMO_TIME)),'end-before-start')


def test_vendor_status_team_scoped_and_contact_not_guest_data(ops,queries):
    created=ops.execute(actor(),{'type':'create_vendor','name':'Example Catering','category':'Banquet','contact_name':'Fictional Contact','contact_phone':'DEMO-UNROUTABLE','team_id':'banquet','expected_at':iso(DEMO_TIME)},'create-vendor-demo')
    ops.execute(actor('banquet'),{'type':'vendor_status','vendor_id':created['id'],'status':'onsite'},'vendor-arrival-demo')
    with pytest.raises(OpsError):ops.execute(actor('photographer'),{'type':'vendor_status','vendor_id':created['id'],'status':'complete'},'wrong-team-vendor')
    assert any(x['id']==created['id'] and x['status']=='onsite' for x in queries.snapshot(actor('banquet'))['vendors'])
    assert all(x['id']!=created['id'] for x in queries.snapshot(actor('photographer'))['vendors'])


def test_utc_timestamp_roundtrip(db):
    with db.transaction(WID) as (s,w):
        timestamp=s.get(TimelineItem,'dinner').current_start
        assert timestamp.tzinfo is not None
        assert timestamp.utcoffset()==timedelta(0)


def test_demo_external_send_refused():
    with pytest.raises(ValueError):Settings(mode='demo',send_notifications=True,telegram_bot_token='not-real').validate()


def test_postgres_migration_runtime_when_configured(db,monkeypatch):
    """This case is explicitly skipped without a disposable PostgreSQL service."""
    if db.sqlite:pytest.skip('PostgreSQL service not available in local build environment')
    from sqlalchemy import text
    Base.metadata.drop_all(db.engine)
    with db.engine.begin() as connection:connection.execute(text('DROP TABLE IF EXISTS alembic_version'))
    monkeypatch.setenv('WEDDINGOPS_DATABASE_URL',db.engine.url.render_as_string(hide_password=False))
    config=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    command.upgrade(config,'head')
    command.check(config)
    assert set(Base.metadata.tables).issubset(inspect(db.engine).get_table_names())
    command.downgrade(config,'base')
