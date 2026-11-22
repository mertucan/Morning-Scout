"""Plain data types shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SourceKind = Literal["news", "search"]


@dataclass(frozen=True)
class Item:
    """A single article or search result that may be worth reporting."""

    source: SourceKind
    topic: str
    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True)
class PageChange:
    """A detected change on a watched page, with a short human-readable diff."""

    name: str
    url: str
    diff: str
