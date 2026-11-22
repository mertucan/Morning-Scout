"""Google News RSS search (articles from the last day)."""

from __future__ import annotations

import html
import re
from urllib.parse import quote_plus

import feedparser
import requests

from morning_scout.models import Item
from morning_scout.sources import TIMEOUT

FEED_URL = "https://news.google.com/rss/search?q={query}&hl=tr&gl=TR&ceid=TR:tr"
MAX_RESULTS_PER_QUERY = 10
_TAG_RE = re.compile(r"<[^>]+>")


def build_feed_url(query: str) -> str:
    """Google News search URL restricted to the last 24 hours."""
    return FEED_URL.format(query=quote_plus(f"{query} when:1d"))


def fetch_news(query: str, session: requests.Session) -> list[Item]:
    """Return recent articles for ``query``.

    The feed is downloaded with ``requests`` (for timeouts and status checks) and
    parsed with ``feedparser``.
    """
    response = session.get(build_feed_url(query), timeout=TIMEOUT)
    response.raise_for_status()
    return parse_feed(response.content, topic=query)


def parse_feed(content: bytes | str, topic: str) -> list[Item]:
    """Turn RSS content into :class:`Item` objects."""
    feed = feedparser.parse(content)
    items: list[Item] = []
    for entry in feed.entries[:MAX_RESULTS_PER_QUERY]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        summary = html.unescape(_TAG_RE.sub(" ", entry.get("summary", "")))
        items.append(
            Item(
                source="news",
                topic=topic,
                title=title,
                url=link,
                snippet=" ".join(summary.split())[:300],
            )
        )
    return items
