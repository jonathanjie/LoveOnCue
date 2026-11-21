"""Fetch one bounded Telegram photo and render read-only observations."""
from __future__ import annotations

import re

import httpx

from .schemas import PhotoReview

MAX_PHOTO_BYTES = 2 * 1024 * 1024
# File paths come from getFile, but still stay within the Telegram download origin.
PHOTO_PATH = re.compile(r"(?:[A-Za-z0-9_-]+/)+[A-Za-z0-9_.-]+\.(?:jpg|jpeg)", re.IGNORECASE)


def download_photo(token: str, file_id: str, transport: httpx.BaseTransport | None = None) -> bytes:
    with httpx.Client(timeout=httpx.Timeout(6, connect=2), transport=transport,
                      follow_redirects=False, trust_env=False) as client:
        metadata = client.post(f"https://api.telegram.org/bot{token}/getFile", json={"file_id": file_id})
        metadata.raise_for_status()
        data = metadata.json()
        if data.get("ok") is not True or not isinstance(data.get("result"), dict):
            raise ValueError("Telegram did not return photo metadata")
        info = data["result"]
        file_path = info.get("file_path")
        size = info.get("file_size")
        if not isinstance(file_path, str) or not PHOTO_PATH.fullmatch(file_path):
            raise ValueError("Telegram returned an invalid photo path")
        if size is not None and (type(size) is not int or not 0 < size <= MAX_PHOTO_BYTES):
            raise ValueError("Photo exceeds the size limit")

        image = bytearray()
        download = f"https://api.telegram.org/file/bot{token}/{file_path}"
        with client.stream("GET", download, headers={"Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("Unexpected photo content encoding")
            for chunk in response.iter_bytes(chunk_size=65536):
                if len(image) + len(chunk) > MAX_PHOTO_BYTES:
                    raise ValueError("Photo exceeds the size limit")
                image.extend(chunk)
        if not image.startswith(b"\xff\xd8\xff"):
            raise ValueError("Expected a JPEG photo")
        return bytes(image)


def render_photo(review: PhotoReview) -> str:
    lines = ["Photo check", "", review.summary, "", "What I can see"]
    lines.extend(f"• {item}" for item in review.observations)
    lines.extend(["", "Uncertain"])
    lines.extend(f"• {item}" for item in review.uncertainties)
    lines.extend(["", "Visual observations only. No event records changed. Use a text report for issues or arrivals."])
    return "\n".join(lines)
