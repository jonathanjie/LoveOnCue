"""Explicit configuration. No credentials are inferred from a developer's machine."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    database_url: str = "sqlite:///.data/weddingops.db"
    wedding_id: str = "demo-wedding"
    public_url: str = "http://127.0.0.1:8000"
    agent_mode: str = "deterministic"
    openclaw_url: str = "http://127.0.0.1:18789"
    openclaw_agent: str = "weddingops-intent"
    openclaw_token: str = ""
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_bot_username: str = ""
    send_notifications: bool = False
    session_ttl_seconds: int = 12 * 60 * 60
    body_limit: int = 262_144
    web_root: Path = Path(__file__).resolve().parents[2] / "web"

    @property
    def demo(self) -> bool:
        return self.mode == "demo"

    @classmethod
    def from_env(cls) -> "Settings":
        def env(name: str, fallback: str = "") -> str:
            return os.getenv("WEDDINGOPS_" + name, fallback)
        return cls(
            mode=env("MODE", "demo"),
            database_url=env("DATABASE_URL", "sqlite:///.data/weddingops.db"),
            wedding_id=env("WEDDING_ID", "demo-wedding"),
            public_url=env("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/"),
            agent_mode=env("AGENT_MODE", "deterministic"),
            openclaw_url=env("OPENCLAW_URL", "http://127.0.0.1:18789").rstrip("/"),
            openclaw_agent=env("OPENCLAW_AGENT", "weddingops-intent"),
            openclaw_token=env("OPENCLAW_TOKEN"),
            telegram_bot_token=env("TELEGRAM_BOT_TOKEN"),
            telegram_webhook_secret=env("TELEGRAM_WEBHOOK_SECRET"),
            telegram_bot_username=env("TELEGRAM_BOT_USERNAME"),
            send_notifications=env("SEND_NOTIFICATIONS", "false").lower() == "true",
        )

    def validate(self) -> None:
        if self.mode not in {"demo", "production", "test"}:
            raise ValueError("MODE must be demo, production or test")
        if self.agent_mode not in {"deterministic", "openclaw"}:
            raise ValueError("AGENT_MODE must be deterministic or openclaw")
        public = urlparse(self.public_url)
        if public.scheme not in {"http", "https"} or not public.hostname:
            raise ValueError("PUBLIC_URL must be an absolute HTTP(S) origin")
        if public.username or public.password or public.query or public.fragment or public.path not in {"", "/"}:
            raise ValueError("PUBLIC_URL must be an origin, without credentials, path or query")
        if self.mode == "production":
            if public.scheme != "https":
                raise ValueError("Production requires an HTTPS PUBLIC_URL")
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL; SQLite is for demo/tests")
            if self.wedding_id == "demo-wedding":
                raise ValueError("Use a distinct wedding cell ID in production")
        if self.demo and self.send_notifications:
            raise ValueError("Demo mode cannot send external notifications")
        if self.demo and public.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Demo authentication is local-only. Use production mode for public deployment")
        if self.agent_mode == "openclaw":
            target = urlparse(self.openclaw_url)
            if target.scheme not in {"http", "https"} or not target.hostname:
                raise ValueError("OPENCLAW_URL must be an absolute HTTP(S) origin")
            if target.username or target.password or target.query or target.fragment or target.path not in {"", "/"}:
                raise ValueError("OPENCLAW_URL must not contain credentials, path or query")
            if len(self.openclaw_token) < 24:
                raise ValueError("Set a strong OPENCLAW_TOKEN before enabling the adapter")
        if self.send_notifications and not self.telegram_bot_token:
            raise ValueError("Sending notifications requires a Telegram bot token")
