"""Operator entry points. Secrets are configured explicitly, never committed."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from .auth import Auth
from .clock import DemoClock, SystemClock
from .config import Settings
from .db import Database
from .models import Base, Location, Member, MemberTeam, Person, Team, Wedding, new_id
from .policy import Actor
from .seed import DEMO_TIME, seed_demo


def bootstrap(db: Database, settings: Settings, name: str, event_date: str, venue: str,
              coordinator: str, timezone: str) -> dict:
    date.fromisoformat(event_date)
    ZoneInfo(timezone)
    if not name.strip() or not coordinator.strip() or not venue.strip():
        raise ValueError("Wedding, venue and coordinator names are required")
    wid, person_id, member_id, team_id = settings.wedding_id, new_id(), new_id(), new_id()
    with db.sessions.begin() as s:
        if s.get(Wedding, wid):
            raise ValueError("This wedding cell already exists. Bootstrap never overwrites data")
        s.add(Wedding(id=wid,name=name,timezone=timezone,event_date=event_date,venue=venue,status="draft"))
        s.flush()
        s.add(Team(id=team_id,wedding_id=wid,name="Coordination"))
        s.add(Location(id=new_id(),wedding_id=wid,name="Main venue",directions=venue,x=50,y=50))
        s.add(Person(id=person_id,wedding_id=wid,name=coordinator,is_guest=False))
        s.flush()
        s.add(Member(id=member_id,wedding_id=wid,person_id=person_id,roles=["coordinator"],active=True))
        s.flush()
        s.add(MemberTeam(wedding_id=wid,member_id=member_id,team_id=team_id))
    invitation = Auth(db,settings).issue_invite(Actor(wid,member_id),member_id)
    return {"wedding_id":wid,"coordinator_member_id":member_id,"invitation":invitation}


def main() -> None:
    parser = argparse.ArgumentParser(prog="weddingops",description="WeddingOps operator CLI")
    sub = parser.add_subparsers(dest="command",required=True)
    demo=sub.add_parser("demo",help="Create/resume the fictional, local-only rehearsal")
    demo.add_argument("--reset",action="store_true",help="Explicitly delete WeddingOps demo tables and reseed")
    demo.add_argument("--port",type=int,default=8000)
    serve=sub.add_parser("serve",help="Serve an already migrated/configured wedding")
    serve.add_argument("--host",default="127.0.0.1");serve.add_argument("--port",type=int,default=8000)
    sub.add_parser("migrate",help="Apply Alembic migrations")
    worker=sub.add_parser("worker",help="Process Telegram ingress, reminders and durable outbox")
    worker.add_argument("--once",action="store_true")
    boot=sub.add_parser("bootstrap",help="Create an empty wedding and an initial coordinator invitation")
    boot.add_argument("--name",required=True);boot.add_argument("--date",required=True);boot.add_argument("--venue",required=True)
    boot.add_argument("--coordinator",required=True);boot.add_argument("--timezone",default="Asia/Singapore")
    export=sub.add_parser("export",help="Export a role-scoped operations snapshot, not authentication secrets")
    export.add_argument("--member",required=True);export.add_argument("--output",required=True)
    args=parser.parse_args()
    settings=Settings.from_env();settings.validate()
    if args.command=="migrate":
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config("alembic.ini"),"head")
        return
    db=Database(settings.database_url)
    if args.command=="demo":
        if not settings.demo or not db.sqlite or settings.wedding_id!="demo-wedding":
            parser.error("Demo only supports the local SQLite demo-wedding cell")
        if args.port != 8000 and settings.public_url == "http://127.0.0.1:8000":
            parser.error("Set WEDDINGOPS_PUBLIC_URL to match your chosen port")
        if args.reset:
            from sqlalchemy import inspect, select
            if "weddings" in inspect(db.engine).get_table_names():
                with db.sessions() as s:
                    if any(w.id!="demo-wedding" for w in s.scalars(select(Wedding))):
                        parser.error("Refusing reset: this database contains a non-demo wedding")
            Base.metadata.drop_all(db.engine)
        db.create_schema();seed_demo(db)
        from .api import create_app
        import uvicorn
        print(f"Fictional rehearsal: {settings.public_url}. No external messages are sent by default.")
        uvicorn.run(create_app(settings,db,DemoClock(DEMO_TIME)),host="127.0.0.1",port=args.port,access_log=False)
    elif args.command=="serve":
        if settings.demo and args.host not in {"127.0.0.1","::1","localhost"}:
            parser.error("Demo authentication must never be exposed on a public/network interface")
        from .api import create_app
        import uvicorn
        uvicorn.run(create_app(settings,db),host=args.host,port=args.port,access_log=False)
    elif args.command=="bootstrap":
        result=bootstrap(db,settings,args.name,args.date,args.venue,args.coordinator,args.timezone)
        print("PRIVATE: one-use coordinator invitation. Do not add this output to version control.",file=sys.stderr)
        print(json.dumps(result,indent=2))
    elif args.command=="worker":
        if settings.demo:
            parser.error("Use the web demo's Run reminders button; separate demo workers would have independent simulated clocks")
        from .agent import Assistant, MistralParser
        from .operations import Operations
        from .telegram import TelegramIngress
        from .views import Queries
        from .worker import Worker

        clock = SystemClock()
        auth = Auth(db, settings)
        queries = Queries(db, settings.wedding_id, clock)
        operations = Operations(db, settings.wedding_id, clock)
        model_parser = MistralParser(settings) if settings.agent_mode == "mistral" else None
        assistant = Assistant(queries, operations, model_parser)
        telegram = TelegramIngress(db, settings, clock, auth, assistant, operations)
        worker = Worker(db, settings, clock)
        try:
            while True:
                for _ in range(20):
                    if not telegram.process_one():
                        break
                result = worker.tick()
                if args.once:
                    print(json.dumps(result))
                    break
                time.sleep(2)
        finally:
            if model_parser is not None:
                model_parser.close()
            db.close()
    elif args.command=="export":
        from .views import Queries
        snapshot=Queries(db,settings.wedding_id,DemoClock(DEMO_TIME) if settings.demo else SystemClock()).snapshot(Actor(settings.wedding_id,args.member))
        target=Path(args.output)
        if target.exists():parser.error("Export target exists; choose a new path")
        target.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w") as handle:json.dump(snapshot,handle,indent=2)
        print(f"Exported {target}. Protect this file as event data; it is not a full database backup.")


if __name__=="__main__":
    main()
