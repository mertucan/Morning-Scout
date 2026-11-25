"""Google News RSS search (articles from the last day)."""

from __future__ import annotations

import html
import re
from urllib.parse import quote_plus

import feedparser
import requests

from morning_scout.models import Item, SourceKind
from morning_scout.sources import TIMEOUT

FEED_URL = "https://news.google.com/rss/search?q={query}&hl=tr&gl=TR&ceid=TR:tr"
MAX_RESULTS_PER_QUERY = 10
_TAG_RE = re.compile(r"<[^>]+>")


def build_feed_url(query: str) -> str:
    """Google News search URL restricted to the last 24 hours."""
    return FEED_URL.format(query=quote_plus(f"{query} when:1d"))


def fetch_news(query: str, session: requests.Session, topic: str | None = None) -> list[Item]:
    """Return recent articles for ``query``, grouped under ``topic`` (default: the query).

    The feed is downloaded with ``requests`` (for timeouts and status checks) and
    parsed with ``feedparser``.
    """
    response = session.get(build_feed_url(query), timeout=TIMEOUT)
    response.raise_for_status()
    return parse_feed(response.content, topic=topic or query)


def parse_feed(
    content: bytes | str,
    topic: str,
    *,
    source: SourceKind = "news",
    limit: int = MAX_RESULTS_PER_QUERY,
) -> list[Item]:
    """Turn RSS/Atom content into :class:`Item` objects (at most ``limit``)."""
    feed = feedparser.parse(content)
    items: list[Item] = []
    for entry in feed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        summary = " ".join(html.unescape(_TAG_RE.sub(" ", entry.get("summary", ""))).split())
        if summary == title:
            summary = ""  # many job boards repeat the title; don't waste prompt space
        category = (entry.get("category") or "").strip()
        snippet = f"[{category}] {summary}".strip() if category else summary
        items.append(Item(source=source, topic=topic, title=title, url=link, snippet=snippet[:300]))
    return items
