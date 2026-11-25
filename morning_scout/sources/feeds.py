"""RSS/Atom feeds, e.g. official job boards that publish their listings as a feed.

Unlike watched pages, every entry becomes its own citable item with its own
link, and entries already sent on a previous day are skipped by URL.
"""

from __future__ import annotations

import requests

from morning_scout.models import Item
from morning_scout.sources import TIMEOUT
from morning_scout.sources.news import parse_feed

MAX_ENTRIES_PER_FEED = 30


def fetch_feed(url: str, topic: str, session: requests.Session) -> list[Item]:
    """Download a feed and return its newest entries grouped under ``topic``."""
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return parse_feed(response.content, topic, source="feed", limit=MAX_ENTRIES_PER_FEED)
