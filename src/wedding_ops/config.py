"""Explicit configuration. No credentials are inferred from a developer's machine."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_MISTRAL_MODEL = "deepseek-v4-1-flash-1017"


@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    database_url: str = "sqlite:///.data/weddingops.db"
    wedding_id: str = "demo-wedding"
    public_url: str = "http://127.0.0.1:8000"
    agent_mode: str = "deterministic"
    mistral_model: str = DEFAULT_MISTRAL_MODEL
    mistral_api_key: str = field(default="", repr=False)
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_bot_username: str = ""
    telegram_vision_model: str = ""
    send_notifications: bool = False
    # Enables operator-only role switching for a fictional staging cell.
    rehearsal: bool = False
    # Answer free-form chat with the conversational deputy (ADR 0003). Needs the model key.
    deputy: bool = False
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
            mistral_model=env("MISTRAL_MODEL", DEFAULT_MISTRAL_MODEL).strip(),
            mistral_api_key=env("MISTRAL_API_KEY").strip(),
            telegram_bot_token=env("TELEGRAM_BOT_TOKEN"),
            telegram_webhook_secret=env("TELEGRAM_WEBHOOK_SECRET"),
            telegram_bot_username=env("TELEGRAM_BOT_USERNAME"),
            telegram_vision_model=env("TELEGRAM_VISION_MODEL").strip(),
            send_notifications=env("SEND_NOTIFICATIONS", "false").lower() == "true",
            rehearsal=env("REHEARSAL", "false").lower() == "true",
            deputy=env("DEPUTY", "false").lower() == "true",
        )

    def validate(self) -> None:
        if self.mode not in {"demo", "production", "test"}:
            raise ValueError("MODE must be demo, production or test")
        if self.agent_mode not in {"deterministic", "mistral"}:
            raise ValueError("AGENT_MODE must be deterministic or mistral")
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
        if (self.agent_mode == "mistral" or self.telegram_vision_model) and not self.mistral_api_key:
            raise ValueError("Set WEDDINGOPS_MISTRAL_API_KEY before enabling Mistral")
        if self.deputy and not self.mistral_api_key:
            raise ValueError("Set WEDDINGOPS_MISTRAL_API_KEY before enabling the deputy")
        if self.agent_mode == "mistral" and not self.mistral_model:
            raise ValueError("Set WEDDINGOPS_MISTRAL_MODEL to an available model ID")
        if self.telegram_vision_model and (self.demo or not self.telegram_bot_token):
            raise ValueError("Telegram photo review requires a configured bot outside demo mode")
        if self.send_notifications and not self.telegram_bot_token:
            raise ValueError("Sending notifications requires a Telegram bot token")
