"""What reaches the coordinator at once, and what waits for the next digest (design S5).

Only items that need a decision before the next digest are pushed: approval requests,
urgent problems and helpers' questions. Everything else becomes a digest item keyed by
its subject, such as "task:<id>", so a newer item about the same task replaces the older
one instead of adding a second interruption.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DigestItem, Notification, Wedding

DIGEST_GAP = timedelta(minutes=15)  # at most one digest in this window: four an hour at most
DIGEST_ITEMS = 6                    # items listed in one digest; the rest lead the next one


def tell_coordinators(s: Session, w: Wedding, subject: str, text: str, now, *, push: bool = False,
                      topic: str = "incident", key: str | None = None, permission: str | None = None) -> None:
    """Push to every active coordinator now, or keep one unreported digest item for this subject."""
    from .operations import (  # Imported here: operations.py imports this module.
        notify,
        recipients,
    )

    if push:
        for coordinator in recipients(s, w.id):
            notify(s, w.id, coordinator.id, topic, text, key or subject, now, permission=permission)
        return
    waiting = s.scalar(select(DigestItem).where(DigestItem.wedding_id == w.id, DigestItem.subject == subject,
                                                DigestItem.reported_at.is_(None)))
    if waiting is not None:
        waiting.text, waiting.updated_at = text, now
        return
    s.add(DigestItem(wedding_id=w.id, subject=subject, text=text, created_at=now, updated_at=now))


def already_told(s: Session, wedding_id: str, subject: str, since) -> bool:
    """Whether the coordinator has had an item about this subject since a moment, sent or waiting."""
    # updated_at, not created_at: an unreported item rewritten in place still counts as telling them.
    return s.scalar(select(DigestItem.id).where(DigestItem.wedding_id == wedding_id, DigestItem.subject == subject,
                                                DigestItem.updated_at >= since).limit(1)) is not None


def age(created_at, now) -> str:
    minutes = int((now - created_at).total_seconds() // 60)
    return "just now" if minutes < 1 else f"{minutes} min ago"


def send_digest(s: Session, w: Wedding, now) -> int:
    """Send one "Update from the floor" when there is news and the last one is old enough."""
    from .operations import notify, recipients

    items = sorted(s.scalars(select(DigestItem).where(DigestItem.wedding_id == w.id,
                                                      DigestItem.reported_at.is_(None))).all(),
                   key=lambda item: (item.created_at, item.id))
    if not items:
        return 0
    last = s.scalar(select(Notification.created_at).where(
        Notification.wedding_id == w.id, Notification.dedupe_key.like("digest:%"))
        .order_by(Notification.created_at.desc()).limit(1))
    if last is not None and now - last < DIGEST_GAP:
        return 0
    listed = items[:DIGEST_ITEMS]
    lines = ["Update from the floor:"] + [f"• {item.text} ({age(item.created_at, now)})" for item in listed]
    if len(items) > len(listed):
        lines.append(f"{len(items) - len(listed)} more items will follow in the next update.")
    lines.append("Quoted words are helpers' own; nothing they typed changed records.")
    for coordinator in recipients(s, w.id):
        notify(s, w.id, coordinator.id, "deputy_digest", "\n".join(lines), f"digest:{now.isoformat()}", now)
    for item in listed:
        item.reported_at = now
    return 1
