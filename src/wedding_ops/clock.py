from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Protocol


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return utcnow()


class DemoClock:
    """Explicit simulated business clock. Authentication always uses real UTC time."""
    def __init__(self, at: datetime):
        if at.tzinfo is None:
            raise ValueError("A clock requires an aware timestamp")
        self._at = at.astimezone(UTC)
        self._lock = Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._at

    def advance(self, minutes: int) -> datetime:
        with self._lock:
            self._at += timedelta(minutes=minutes)
            return self._at
