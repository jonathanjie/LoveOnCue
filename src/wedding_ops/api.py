"""Same-origin web/API application. Telegram and model credentials never reach a browser."""
from __future__ import annotations

import json
import hashlib
from http.cookies import SimpleCookie, CookieError
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime
from threading import Lock
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .agent import Assistant, MistralParser, Parser
from .auth import Auth
from .clock import Clock, DemoClock, SystemClock
from .config import Settings
from .db import Database
from .errors import OpsError, denied
from .imports import Imports
from .operations import Operations
from .policy import Actor
from .schemas import ChatRequest, CommandRequest, ConfirmRequest, ID, Strict
from .seed import DEMO_TIME
from .telegram import TelegramIngress
from .views import Queries
from .worker import Worker

COOKIE = "weddingops_session"


class EnvelopeMiddleware:
    """Bound request bodies before parsing and apply single-process abuse controls."""
    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings
        self.windows = defaultdict(deque)
        self.lock = Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        now = time.monotonic()
        client = (scope.get("client") or ("unknown",))[0]
        # Shared venue Wi-Fi must not give every helper one 180-request bucket.
        # Cookie hashes divide traffic; they are NOT proof of authentication.
        headers = dict(scope.get("headers", []))
        token = ""
        try:
            cookies = SimpleCookie()
            cookies.load(headers.get(b"cookie", b"").decode("latin-1"))
            if COOKIE in cookies:
                token = cookies[COOKIE].value[:256]
        except CookieError:
            pass
        buckets = [(f"ip:{client}", 3000)]
        if scope["path"].startswith("/api/auth/"):
            buckets.append((f"login:{client}", 120))
        elif scope["path"].startswith("/api/telegram/"):
            buckets.append((f"telegram:{client}", 1000))
        elif token:
            buckets.append(("session:" + hashlib.sha256(token.encode()).hexdigest(), 180))
        else:
            buckets.append((f"anonymous:{client}", 300))
        with self.lock:
            limited = False
            for key, limit in buckets:
                window = self.windows[key]
                while window and window[0] <= now - 60:
                    window.popleft()
                if len(window) >= limit:
                    limited = True
                else:
                    window.append(now)
            # A reverse proxy/distributed limiter is still required before scaling workers.
            if len(self.windows) > 10000:
                self.windows = defaultdict(deque, {k:v for k,v in self.windows.items() if v and v[-1] > now - 60})
                if len(self.windows) > 10000:
                    self.windows.clear()
        if limited:
            return await JSONResponse({"error":{"code":"rate_limited","message":"Too many requests. Try again shortly."}},429,headers={"Retry-After":"30"})(scope,receive,send)
        if scope["method"] in {"POST","PUT","PATCH"}:
            chunks, count = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                count += len(chunk)
                if count > self.settings.body_limit:
                    return await JSONResponse({"error":{"code":"too_large","message":"Request exceeds the configured limit"}},413)(scope,receive,send)
                chunks.append(chunk)
                if not message.get("more_body"):
                    break
            body, delivered = b"".join(chunks), False
            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type":"http.request","body":body,"more_body":False}
                return await receive()
            return await self.app(scope, bounded_receive, send)
        return await self.app(scope,receive,send)


class LoginRequest(Strict):
    member_id: ID
class InviteRequest(Strict):
    member_id: ID
class TokenRequest(Strict):
    token: str = Field(min_length=20,max_length=128)
class TelegramLogin(Strict):
    init_data: str = Field(min_length=1,max_length=16384)
class ImportRequest(Strict):
    csv: str = Field(min_length=1,max_length=200000)
class TickRequest(Strict):
    minutes: int = Field(default=0,ge=0,le=120)


def create_app(settings: Settings | None = None, db: Database | None = None, clock: Clock | None = None,
               parser: Parser | None = None, transport=None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    db = db or Database(settings.database_url)
    clock = clock or (DemoClock(DEMO_TIME) if settings.demo else SystemClock())
    auth = Auth(db, settings)
    queries, operations = Queries(db,settings.wedding_id,clock), Operations(db,settings.wedding_id,clock)
    model_parser = MistralParser(settings) if parser is None and settings.agent_mode == "mistral" else None
    assistant = Assistant(queries, operations, parser if parser is not None else model_parser)
    worker = Worker(db,settings,clock,transport)
    telegram = TelegramIngress(db,settings,clock,auth,assistant,operations)
    imports = Imports(db,settings.wedding_id,clock)
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            if model_parser is not None:
                model_parser.close()

    app = FastAPI(title="WeddingOps",version="0.1.0",lifespan=lifespan,docs_url="/docs" if settings.mode != "production" else None,
                  redoc_url=None,openapi_url="/openapi.json" if settings.mode != "production" else None)
    app.state.services = {"db":db,"auth":auth,"queries":queries,"operations":operations,"assistant":assistant,
                          "worker":worker,"telegram":telegram,"imports":imports,"clock":clock,"settings":settings}
    host = urlparse(settings.public_url).hostname
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[host,"testserver"] if settings.mode == "test" else [host])
    app.add_middleware(EnvelopeMiddleware,settings=settings)

    @app.exception_handler(OpsError)
    async def domain_error(request, exc):
        return JSONResponse({"error":{"code":exc.code,"message":exc.message,"details":exc.details}},status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"error":{"code":"validation","message":"Check the submitted fields",
               "details":[{"field":".".join(map(str,e["loc"])),"message":e["msg"]} for e in exc.errors()]}},422)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' https://telegram.org; "
            "style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'self' https://web.telegram.org")
        if settings.mode == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def same_origin(request: Request):
        if request.headers.get("origin") != settings.public_url:
            raise denied("This action must originate from the WeddingOps application")

    def reader(request: Request) -> Actor:
        return auth.authenticate(request.cookies.get(COOKIE))

    def writer(request: Request) -> Actor:
        same_origin(request)
        return auth.authenticate(request.cookies.get(COOKIE),csrf=request.headers.get("x-csrf-token"),require_csrf=True)

    def login_response(result: dict, response: Response):
        response.set_cookie(COOKIE,result["token"],max_age=result["max_age"],httponly=True,secure=settings.mode == "production",samesite="strict",path="/")
        return {"member_id":result["member_id"],"csrf":result["csrf"]}

    @app.get("/health")
    def health(): return {"status":"ok","version":"0.1.0"}

    @app.get("/ready")
    def ready():
        try:
            with db.transaction(settings.wedding_id) as (s,w): pass
            return {"status":"ready"}
        except Exception:
            return JSONResponse({"status":"not_ready"},503)

    @app.get("/api/config")
    def config():
        demo_members=[]
        if settings.demo:
            snap=queries.snapshot(Actor(settings.wedding_id,"coordinator"))
            demo_members=[{"id":m["id"],"name":m["name"],"roles":m["roles"]} for m in snap["members"] if m["active"]]
        return {"demo":settings.demo,"demo_members":demo_members,"agent_mode":settings.agent_mode,
                "telegram_configured":bool(settings.telegram_bot_token),"notifications_live":settings.send_notifications}

    @app.post("/api/auth/demo")
    def demo_login(body:LoginRequest,request:Request,response:Response):
        same_origin(request)
        return login_response(auth.demo_login(body.member_id),response)

    @app.post("/api/auth/invite")
    def invitation_login(body:TokenRequest,request:Request,response:Response):
        same_origin(request)
        return login_response(auth.redeem(body.token),response)

    @app.post("/api/auth/telegram")
    def telegram_login(body:TelegramLogin,request:Request,response:Response):
        same_origin(request)
        return login_response(auth.telegram_login(body.init_data),response)

    @app.get("/api/session")
    def session(request:Request,actor:Actor=Depends(reader)):
        if request.headers.get("x-weddingops-client") != "1" or request.headers.get("sec-fetch-site") == "cross-site":
            raise denied()
        return {"member_id":actor.member_id,"csrf":auth.rotate_csrf(request.cookies[COOKIE])}

    @app.post("/api/logout")
    def logout(request:Request,response:Response,actor:Actor=Depends(writer)):
        auth.logout(request.cookies[COOKIE]);response.delete_cookie(COOKIE,path="/")
        return {"status":"signed_out"}

    @app.get("/api/snapshot")
    def snapshot(actor:Actor=Depends(reader)): return queries.snapshot(actor)

    @app.get("/api/guests")
    def guests(q:str="",sensitive:bool=False,actor:Actor=Depends(reader)):
        if len(q)>120: raise OpsError("validation","Search is too long")
        return {"items":queries.guests(actor,q,sensitive=sensitive),"limit":50}

    @app.get("/api/guests/{person_id}/details")
    def guest_details(person_id:str,actor:Actor=Depends(reader)):
        return queries.guest_details(actor,person_id)

    @app.get("/api/family/contacts")
    def family_contacts(actor:Actor=Depends(reader)):
        return {"items":queries.family_contacts(actor)}

    @app.get("/api/family")
    def family(q:str="",actor:Actor=Depends(reader)): return {"items":queries.family(actor,q[:160])}

    @app.get("/api/knowledge")
    def knowledge(q:str,actor:Actor=Depends(reader)): return {"items":queries.knowledge(actor,q[:300])}

    @app.get("/api/audit")
    def audit_log(actor:Actor=Depends(reader)): return {"items":queries.audit(actor)}

    @app.post("/api/commands")
    def command(body:CommandRequest,actor:Actor=Depends(writer)):
        return operations.execute(actor,body.command,body.request_id)

    @app.post("/api/chat")
    def chat(body:ChatRequest,actor:Actor=Depends(writer)): return assistant.ask(actor,body.text)

    @app.post("/api/confirm")
    def confirm(body:ConfirmRequest,actor:Actor=Depends(writer)): return operations.confirm(actor,body.draft_id)

    @app.post("/api/invitations")
    def invite(body:InviteRequest,actor:Actor=Depends(writer)): return auth.issue_invite(actor,body.member_id)

    @app.post("/api/import/guests")
    def import_guests(body:ImportRequest,actor:Actor=Depends(writer)): return imports.preview(actor,body.csv)

    @app.get("/api/export/guests.csv")
    def export_guests(actor:Actor=Depends(reader)):
        return PlainTextResponse(imports.export_guests(actor),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=wedding-guests.csv"})

    @app.post("/api/telegram/webhook")
    def webhook(body:dict,request:Request): return telegram.accept(request.headers.get("x-telegram-bot-api-secret-token"),body)

    @app.post("/api/demo/tick")
    def tick(body:TickRequest,actor:Actor=Depends(writer)):
        if not settings.demo or not isinstance(clock,DemoClock): raise OpsError("not_found","Not available",404)
        if "coordinator" not in queries.snapshot(actor)["me"]["roles"]: raise denied()
        clock.advance(body.minutes)
        return worker.tick()

    if (settings.web_root / "dist").exists():
        app.mount("/assets",StaticFiles(directory=settings.web_root / "dist"),name="assets")
    @app.get("/")
    def index(): return FileResponse(settings.web_root / "index.html")
    return app
