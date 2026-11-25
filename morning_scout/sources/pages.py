"""Watching web pages for text changes."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import date
from typing import Literal

import requests
from bs4 import BeautifulSoup

from morning_scout.config import PageConfig
from morning_scout.models import PageChange
from morning_scout.sources import TIMEOUT
from morning_scout.state import PageSnapshot, text_digest

MAX_DIFF_CHARS = 3000
_NOISE_TAGS = ("script", "style", "noscript", "template", "svg", "iframe")

PageStatus = Literal["first_seen", "unchanged", "changed"]


class SelectorNotFoundError(Exception):
    """The configured CSS selector matched nothing on the page."""


@dataclass(frozen=True)
class PageCheck:
    """Result of comparing a page with its previous snapshot."""

    status: PageStatus
    snapshot: PageSnapshot
    change: PageChange | None = None


def fetch_page_text(page: PageConfig, session: requests.Session) -> str:
    """Download ``page.url`` and return its visible text (optionally only ``css_selector``)."""
    response = session.get(page.url, timeout=TIMEOUT)
    response.raise_for_status()
    return extract_text(response.text, page.css_selector)


def extract_text(html: str, css_selector: str | None = None) -> str:
    """Visible text of an HTML document, one non-empty line per block, whitespace-normalised."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()

    if css_selector:
        nodes = soup.select(css_selector)
        if not nodes:
            raise SelectorNotFoundError("css_selector matched no elements")
    else:
        nodes = [soup.body or soup]

    lines: list[str] = []
    for node in nodes:
        for raw in node.get_text("\n").splitlines():
            line = " ".join(raw.split())
            if line:
                lines.append(line)
    return "\n".join(lines)


def compare(page: PageConfig, text: str, previous: PageSnapshot | None, today: date) -> PageCheck:
    """Compare freshly fetched ``text`` with the stored snapshot.

    A page seen for the first time is only recorded (``first_seen``) so that
    adding a page to the config never triggers a bogus "changed" alert.
    """
    snapshot = PageSnapshot.from_text(text, today)
    if previous is None:
        return PageCheck("first_seen", snapshot)
    if previous.text_hash == text_digest(text):
        return PageCheck("unchanged", snapshot)
    diff = summarize_diff(previous.text, snapshot.text)
    if not diff:
        # Only the part beyond the stored (truncated) text changed.
        diff = "…"
    return PageCheck(
        "changed", snapshot, PageChange(page.name, page.url, diff, page.focus, page.topic)
    )


def summarize_diff(old: str, new: str, limit: int = MAX_DIFF_CHARS) -> str:
    """Compact "+ added / - removed" lines between two texts, capped at ``limit`` characters.

    Added lines come first: on listing pages they are the new listings, while
    removed lines are mostly expired ones, so those are what the cap cuts.
    """
    old_lines, new_lines = old.splitlines(), new.splitlines()
    added: list[str] = []
    removed: list[str] = []
    for line in difflib.unified_diff(old_lines, new_lines, lineterm="", n=0):
        if line.startswith(("+++", "---", "@@")):
            continue
        if line[:1] == "+":
            added.append(f"+ {line[1:].strip()}")
        elif line[:1] == "-":
            removed.append(f"- {line[1:].strip()}")
    text = "\n".join([*added, *removed])
    return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0] + "\n…"
