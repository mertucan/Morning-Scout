"""Persistent memory (``state.json``): what was already sent and how watched pages looked.

The file is kept small so it stays well under the Gist API's 1 MB inline limit:
links are stored as 16-character hashes, and page snapshots are truncated and
zlib-compressed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from morning_scout.urls import short_hash

SCHEMA_VERSION = 1
SEEN_RETENTION_DAYS = 30
MAX_SNAPSHOT_CHARS = 20_000


class StateError(Exception):
    """``state.json`` exists but cannot be understood."""


@dataclass
class PageSnapshot:
    """Last known text of a watched page."""

    text_hash: str
    text: str
    checked_on: str  # ISO date

    @classmethod
    def from_text(cls, text: str, today: date) -> PageSnapshot:
        return cls(
            text_hash=text_digest(text),
            text=text[:MAX_SNAPSHOT_CHARS],
            checked_on=today.isoformat(),
        )

    def to_json(self) -> dict[str, str]:
        packed = zlib.compress(self.text.encode("utf-8"), level=9)
        return {
            "hash": self.text_hash,
            "text_z": base64.b64encode(packed).decode("ascii"),
            "checked_on": self.checked_on,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PageSnapshot:
        text = zlib.decompress(base64.b64decode(data["text_z"])).decode("utf-8")
        return cls(text_hash=data["hash"], text=text, checked_on=data.get("checked_on", ""))


@dataclass
class State:
    """Everything Morning Scout remembers between runs."""

    seen: dict[str, str] = field(default_factory=dict)  # key -> ISO date first sent
    pages: dict[str, PageSnapshot] = field(default_factory=dict)  # page_key(url) -> snapshot
    last_sent_date: str | None = None

    # -- daily guard -------------------------------------------------------
    def already_sent(self, today: date) -> bool:
        return self.last_sent_date == today.isoformat()

    # -- duplicate detection ----------------------------------------------
    def is_seen(self, *keys: str) -> bool:
        return any(key in self.seen for key in keys)

    def mark_seen(self, keys: list[str], today: date) -> None:
        for key in keys:
            self.seen.setdefault(key, today.isoformat())

    def prune(self, today: date, retention_days: int = SEEN_RETENTION_DAYS) -> int:
        """Forget links sent more than ``retention_days`` ago. Returns how many were removed."""
        cutoff = (today - timedelta(days=retention_days)).isoformat()
        stale = [key for key, sent_on in self.seen.items() if sent_on < cutoff]
        for key in stale:
            del self.seen[key]
        return len(stale)

    def forget_pages_except(self, active_keys: set[str]) -> None:
        """Drop snapshots of pages that were removed from the config."""
        for key in set(self.pages) - active_keys:
            del self.pages[key]

    # -- serialisation -----------------------------------------------------
    def to_json(self) -> str:
        data = {
            "version": SCHEMA_VERSION,
            "last_sent_date": self.last_sent_date,
            "seen": dict(sorted(self.seen.items())),
            "pages": {key: snap.to_json() for key, snap in sorted(self.pages.items())},
        }
        return json.dumps(data, indent=1, ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, text: str | None) -> State:
        """Parse ``state.json``. Missing or blank content yields a fresh state."""
        if text is None or not text.strip():
            return cls()
        try:
            data = json.loads(text)
            return cls(
                seen={str(k): str(v) for k, v in data.get("seen", {}).items()},
                pages={k: PageSnapshot.from_json(v) for k, v in data.get("pages", {}).items()},
                last_sent_date=data.get("last_sent_date"),
            )
        except (ValueError, TypeError, KeyError, AttributeError, zlib.error) as exc:
            raise StateError(f"state.json is corrupt ({type(exc).__name__})") from None


def page_key(url: str) -> str:
    """Stable key for a watched page (the URL itself is not stored)."""
    return short_hash("p:" + url.strip())


def text_digest(text: str) -> str:
    """Full SHA-256 of the page text, computed before truncation."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
