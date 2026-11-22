"""Data sources: Google News RSS, Tavily web search and watched web pages."""

import requests

USER_AGENT = "Mozilla/5.0 (compatible; MorningScout/1.0; personal daily digest)"
TIMEOUT = 20


def new_session() -> requests.Session:
    """HTTP session with a descriptive User-Agent."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session
