"""Opaque sessions and person-bound, one-use enrollment. No self-selected roles."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from urllib.parse import parse_qsl

from sqlalchemy import delete, select

from .clock import utcnow
from .config import Settings
from .db import Database
from .errors import OpsError, conflict, denied
from .models import AuthReplay, Invitation, LoginSession, Member, new_id
from .operations import audit
from .policy import Actor, load_access, require_human
from .views import row


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def validate_init_data(raw: str, bot_token: str, *, max_age_seconds: int = 300, now=None) -> tuple[str, str]:
    """Telegram official HMAC validation; caller stores replay digest transactionally."""
    now = now or utcnow()
    if not bot_token or len(raw) > 16384:
        raise denied("Telegram authentication is unavailable or invalid")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError("Duplicate fields")
        supplied = data.pop("hash")
        check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if len(supplied) != 64 or not hmac.compare_digest(expected, supplied):
            raise ValueError("Invalid hash")
        age = now.timestamp() - int(data["auth_date"])
        if age < -30 or age > max_age_seconds:
            raise ValueError("Expired or future data")
        user = json.loads(data["user"])
        ident = user["id"]
        if type(ident) is not int or ident <= 0 or ident > 2**52 or user.get("is_bot"):
            raise ValueError("Invalid user")
        return str(ident), hashlib.sha256((expected + "|" + check).encode()).hexdigest()
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise denied("Telegram sign-in is invalid or expired. Reopen the Mini App") from exc


class Auth:
    def __init__(self, db: Database, settings: Settings):
        self.db, self.settings, self.wid = db, settings, settings.wedding_id

    def _session(self, s, member_id: str) -> dict:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = utcnow()
        login = LoginSession(id=new_id(), wedding_id=self.wid, member_id=member_id,
                             token_hash=hash_token(token), csrf_hash=hash_token(csrf), created_at=now,
                             expires_at=now + timedelta(seconds=self.settings.session_ttl_seconds))
        s.add(login)
        return {"token": token, "csrf": csrf, "member_id": member_id, "max_age": self.settings.session_ttl_seconds}

    def demo_login(self, member_id: str) -> dict:
        if not self.settings.demo:
            raise OpsError("not_found", "Not available", 404)
        with self.db.transaction(self.wid, write=True) as (s, w):
            a = load_access(s, Actor(self.wid, member_id), self.wid)
            return self._session(s, a.member.id)

    def authenticate(self, token: str | None, *, csrf: str | None = None, require_csrf: bool = False) -> Actor:
        if not token or len(token) > 128:
            raise OpsError("unauthenticated", "Sign in to this wedding first", 401)
        with self.db.transaction(self.wid) as (s, _):
            login = s.scalar(select(LoginSession).where(LoginSession.wedding_id == self.wid, LoginSession.token_hash == hash_token(token)))
            if not login or login.revoked_at or login.expires_at <= utcnow():
                raise OpsError("unauthenticated", "Session expired. Sign in again", 401)
            if require_csrf and (not csrf or not hmac.compare_digest(login.csrf_hash, hash_token(csrf))):
                raise denied("Invalid request verification token. Reload the application")
            actor = Actor(self.wid, login.member_id)
            load_access(s, actor, self.wid)
            return actor

    def rotate_csrf(self, token: str) -> str:
        """Same-origin-only endpoint. CSRF secret is never placed in local storage."""
        self.authenticate(token)
        csrf = secrets.token_urlsafe(32)
        with self.db.transaction(self.wid, write=True) as (s, _):
            login = s.scalar(select(LoginSession).where(LoginSession.wedding_id == self.wid, LoginSession.token_hash == hash_token(token)))
            if not login or login.revoked_at or login.expires_at <= utcnow():
                raise denied()
            login.csrf_hash = hash_token(csrf)
        return csrf

    def logout(self, token: str) -> None:
        with self.db.transaction(self.wid, write=True) as (s, _):
            login = s.scalar(select(LoginSession).where(LoginSession.wedding_id == self.wid, LoginSession.token_hash == hash_token(token)))
            if login:
                login.revoked_at = utcnow()

    def issue_invite(self, actor: Actor, member_id: str) -> dict:
        require_human(actor)
        token = secrets.token_urlsafe(24)
        with self.db.transaction(self.wid, write=True) as (s, w):
            load_access(s, actor, self.wid).require("members:manage")
            member = row(s, Member, self.wid, member_id)
            if not member.active:
                raise denied("Reactivate the member before inviting them")
            now = utcnow()
            invite = Invitation(id=new_id(), wedding_id=self.wid, member_id=member.id, token_hash=hash_token(token),
                                created_at=now, expires_at=now + timedelta(hours=24))
            s.add(invite)
            audit(s, w, actor.member_id, "invitation_issued", invite.id, {"member_id": member.id}, now)
        return {"token": token, "web_url": f"{self.settings.public_url}/#invite={token}",
                "telegram_url": f"https://t.me/{self.settings.telegram_bot_username}?start={token}" if self.settings.telegram_bot_username else None,
                "expires_in_hours": 24}

    def redeem(self, token: str, telegram_user_id: str | None = None) -> dict:
        if not token or len(token) > 128:
            raise denied("Invitation is invalid or expired")
        if telegram_user_id is not None and (not telegram_user_id.isdecimal() or int(telegram_user_id) <= 0):
            raise denied()
        with self.db.transaction(self.wid, write=True) as (s, w):
            now = utcnow()
            invitation = s.scalar(select(Invitation).where(Invitation.wedding_id == self.wid, Invitation.token_hash == hash_token(token)))
            if not invitation or invitation.consumed_at or invitation.expires_at <= now:
                raise denied("Invitation is invalid, expired or already used")
            member = row(s, Member, self.wid, invitation.member_id)
            if not member.active:
                raise denied()
            if telegram_user_id:
                other = s.scalar(select(Member).where(Member.wedding_id == self.wid, Member.telegram_user_id == telegram_user_id))
                if other and other.id != member.id:
                    raise conflict("This Telegram account is already linked to another wedding role")
                if member.telegram_user_id and member.telegram_user_id != telegram_user_id:
                    raise conflict("This role is linked to a different Telegram account. Ask the coordinator to review it")
                member.telegram_user_id = telegram_user_id
            invitation.consumed_at = now
            audit(s, w, member.id, "invitation_redeemed", invitation.id, {"channel": "telegram" if telegram_user_id else "web"}, now)
            return {"member_id": member.id} if telegram_user_id else self._session(s, member.id)

    def telegram_login(self, raw: str) -> dict:
        ident, replay = validate_init_data(raw, self.settings.telegram_bot_token)
        with self.db.transaction(self.wid, write=True) as (s, w):
            now = utcnow()
            s.execute(delete(AuthReplay).where(AuthReplay.wedding_id == self.wid, AuthReplay.expires_at < now))
            if s.get(AuthReplay, replay):
                raise denied("This sign-in was already used. Reopen the Mini App")
            member = s.scalar(select(Member).where(Member.wedding_id == self.wid, Member.telegram_user_id == ident))
            if not member or not member.active:
                raise denied("Use your coordinator's personal invitation in the bot before opening the Mini App")
            s.add(AuthReplay(digest=replay, wedding_id=self.wid, expires_at=now + timedelta(minutes=6)))
            return self._session(s, member.id)

    def telegram_actor(self, ident: str, *, require_open_event: bool = False) -> Actor:
        with self.db.transaction(self.wid) as (s, wedding):
            if require_open_event and wedding.status == "archived":
                raise denied("This wedding is archived")
            member = s.scalar(select(Member).where(Member.wedding_id == self.wid, Member.telegram_user_id == ident))
            if not member or not member.active:
                raise denied("Unregistered or inactive Telegram sender")
            return Actor(self.wid, member.id, "telegram")
