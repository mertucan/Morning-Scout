"""Tavily web search (free plan: 1,000 credits/month, 1 credit per basic search)."""

from __future__ import annotations

import requests

from morning_scout.models import Item
from morning_scout.sources import TIMEOUT

TAVILY_URL = "https://api.tavily.com/search"
MAX_RESULTS = 5


def search(
    query: str,
    api_key: str,
    session: requests.Session,
    time_range: str = "day",
    *,
    sites: tuple[str, ...] = (),
    topic: str | None = None,
) -> list[Item]:
    """Run one basic Tavily search and return up to five recent results.

    ``sites`` restricts results to those domains. This is how public social
    media posts are found: X and Instagram have no free read API, but posts
    that search engines index can be searched with e.g. ``("x.com",)``.
    """
    response = session.post(
        TAVILY_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json=build_request(query, time_range, sites),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return parse_results(response.json(), topic=topic or query)


def build_request(query: str, time_range: str, sites: tuple[str, ...] = ()) -> dict:
    """JSON body of a basic (1 credit) Tavily search."""
    body: dict = {
        "query": query,
        "search_depth": "basic",
        "max_results": MAX_RESULTS,
        "time_range": time_range,
        "include_answer": False,
    }
    if sites:
        body["include_domains"] = list(sites)
    return body


def parse_results(payload: dict, topic: str) -> list[Item]:
    """Convert a Tavily JSON response into :class:`Item` objects."""
    items: list[Item] = []
    for result in payload.get("results", [])[:MAX_RESULTS]:
        url = (result.get("url") or "").strip()
        if not url:
            continue
        items.append(
            Item(
                source="search",
                topic=topic,
                title=(result.get("title") or url).strip(),
                url=url,
                snippet=" ".join((result.get("content") or "").split())[:500],
            )
        )
    return items
