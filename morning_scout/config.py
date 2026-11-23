"""Loading and validating the user's ``config.yaml`` and the environment secrets.

Error messages here deliberately mention only field names and line numbers,
never the offending values: the config contains personal topics and URLs.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_GEMINI_FALLBACK_MODEL = "gemini-3.6-flash"
# Lightweight model tried last; it is rarely overloaded.
LAST_RESORT_GEMINI_MODEL = "gemini-3.5-flash-lite"
DEFAULT_SEND_TIME = "08:00"
DEFAULT_TIMEZONE = "Europe/Istanbul"
DEFAULT_LANGUAGE = "tr"
SEARCH_TIME_RANGES = ("day", "week")
# Tavily's free plan has 1,000 credits/month; a "basic" search costs 1 credit.
MONTHLY_TAVILY_CREDITS = 1000


class ConfigError(Exception):
    """The configuration is invalid. ``line`` is 1-based when known."""

    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


@dataclass(frozen=True)
class Query:
    """One news or web search query.

    Attributes:
        text: What is searched for.
        topic: Heading the results are grouped under (defaults to ``text``), so
            several queries can share one section of the digest.
        sites: Web searches only: restrict results to these domains
            (e.g. ``x.com``, ``instagram.com``).
        focus: Optional instruction for the summary, e.g. "only associate-degree
            listings"; results that don't match it are left out.
    """

    text: str
    topic: str
    sites: tuple[str, ...] = ()
    focus: str | None = None


@dataclass(frozen=True)
class PageConfig:
    """A web page whose text is watched for changes."""

    name: str
    url: str
    css_selector: str | None = None
    focus: str | None = None


@dataclass(frozen=True)
class Recipient:
    """Someone else who gets an e-mail with only the listed digest topics."""

    email: str
    topics: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    """Validated user configuration."""

    news: list[Query] = field(default_factory=list)
    searches: list[Query] = field(default_factory=list)
    pages: list[PageConfig] = field(default_factory=list)
    recipients: list[Recipient] = field(default_factory=list)
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_fallback_model: str = DEFAULT_GEMINI_FALLBACK_MODEL
    send_time: time = time(8, 0)
    timezone: str = DEFAULT_TIMEZONE
    summary_language: str = DEFAULT_LANGUAGE
    search_time_range: str = "day"

    @property
    def gemini_models(self) -> list[str]:
        """Primary model, then the fallback, then a lightweight last resort (no duplicates)."""
        models = [self.gemini_model, self.gemini_fallback_model, LAST_RESORT_GEMINI_MODEL]
        return list(dict.fromkeys(models))

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def focus_by_topic(self) -> dict[str, str]:
        """The ``focus`` instruction of each topic that has one (first one wins)."""
        focus: dict[str, str] = {}
        for query in [*self.news, *self.searches]:
            if query.focus:
                focus.setdefault(query.topic, query.focus)
        return focus

    def sensitive_values(self) -> list[str]:
        """Every user-provided value that must never appear in logs."""
        values: list[str] = []
        for query in [*self.news, *self.searches]:
            values.extend([query.text, query.topic, *query.sites, query.focus or ""])
        for page in self.pages:
            values.extend([page.name, page.url, page.css_selector or "", page.focus or ""])
        for recipient in self.recipients:
            values.extend([recipient.email, *recipient.topics])
        return [v for v in values if v]


@dataclass(frozen=True)
class Secrets:
    """Credentials read from the environment (GitHub Secrets or a local .env)."""

    gemini_api_key: str = ""
    tavily_api_key: str = ""
    gmail_address: str = ""
    gmail_app_password: str = ""
    mail_to: str = ""
    ntfy_topic: str = ""
    gist_id: str = ""
    gist_token: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Secrets:
        env = os.environ if env is None else env

        def get(name: str) -> str:
            return env.get(name, "").strip()

        return cls(
            gemini_api_key=get("GEMINI_API_KEY"),
            tavily_api_key=get("TAVILY_API_KEY"),
            gmail_address=get("GMAIL_ADDRESS"),
            gmail_app_password=get("GMAIL_APP_PASSWORD"),
            mail_to=get("MAIL_TO") or get("GMAIL_ADDRESS"),
            ntfy_topic=get("NTFY_TOPIC"),
            gist_id=get("GIST_ID"),
            gist_token=get("GIST_TOKEN"),
        )

    def values(self) -> list[str]:
        return [v for v in vars(self).values() if v]


def parse_config(text: str) -> Config:
    """Parse and validate YAML text into a :class:`Config`.

    Raises:
        ConfigError: on YAML syntax errors (with the line number) or invalid fields.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        line = mark.line + 1 if mark is not None else None
        raise ConfigError("config.yaml is not valid YAML", line=line) from None

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError("config.yaml must be a mapping of settings at the top level", line=1)

    news = _queries(data, "news", allow_sites=False)
    searches = _queries(data, "searches", allow_sites=True)
    pages = _pages(data.get("pages"))
    recipients = _recipients(data.get("recipients"))

    send_time = _parse_time(data.get("send_time") or DEFAULT_SEND_TIME)
    timezone = str(data.get("timezone") or DEFAULT_TIMEZONE)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError("'timezone' is not a valid IANA time zone name") from None

    time_range = str(data.get("search_time_range") or "day").lower()
    if time_range not in SEARCH_TIME_RANGES:
        raise ConfigError("'search_time_range' must be 'day' or 'week'")

    return Config(
        news=news,
        searches=searches,
        pages=pages,
        recipients=recipients,
        gemini_model=str(data.get("gemini_model") or DEFAULT_GEMINI_MODEL).strip(),
        gemini_fallback_model=str(
            data.get("gemini_fallback_model") or DEFAULT_GEMINI_FALLBACK_MODEL
        ).strip(),
        send_time=send_time,
        timezone=timezone,
        summary_language=str(data.get("summary_language") or DEFAULT_LANGUAGE).strip().lower(),
        search_time_range=time_range,
    )


def _queries(data: dict[str, Any], key: str, *, allow_sites: bool) -> list[Query]:
    """Parse a list whose entries are plain text or ``{query, topic, sites, focus}``."""
    raw = data.get(key) or []
    if not isinstance(raw, list):
        raise ConfigError(f"'{key}' must be a list (each line starting with '- ')")
    queries: list[Query] = []
    for index, value in enumerate(raw, start=1):
        if isinstance(value, dict):
            queries.append(_query_entry(value, key, index, allow_sites=allow_sites))
        elif isinstance(value, str | int | float) and str(value).strip():
            text = str(value).strip()
            queries.append(Query(text=text, topic=text))
        else:
            raise ConfigError(f"every entry in '{key}' must be non-empty text")
    return list(dict.fromkeys(queries))  # drop duplicates, keep order


def _query_entry(entry: dict[str, Any], key: str, index: int, *, allow_sites: bool) -> Query:
    text = _optional_text(entry.get("query"))
    if not text:
        raise ConfigError(f"{key} entry #{index} needs a 'query'")
    if set(entry) - {"query", "topic", "sites", "focus"}:
        # The unknown names are not echoed: a mis-indented line may be personal text.
        raise ConfigError(
            f"{key} entry #{index} has an unknown field (allowed: query, topic, sites, focus)"
        )
    sites = _sites(entry.get("sites"), key, index)
    if sites and not allow_sites:
        raise ConfigError(f"{key} entry #{index}: 'sites' is only supported in 'searches'")
    return Query(
        text=text,
        topic=_optional_text(entry.get("topic")) or text,
        sites=sites,
        focus=_optional_text(entry.get("focus")),
    )


def _sites(raw: Any, key: str, index: int) -> tuple[str, ...]:
    """Domains such as ``x.com``; a pasted ``https://www.x.com/`` is tidied up."""
    if raw is None:
        return ()
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise ConfigError(f"{key} entry #{index}: 'sites' must be a list of domains")
    sites: list[str] = []
    for value in raw:
        site = str(value).strip().lower().removeprefix("https://").removeprefix("http://")
        site = site.removeprefix("www.").strip("/")
        if not site or "/" in site or " " in site:
            raise ConfigError(
                f"{key} entry #{index}: every 'sites' item must be a domain like x.com"
            )
        sites.append(site)
    return tuple(dict.fromkeys(sites))


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _pages(raw: Any) -> list[PageConfig]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError("'pages' must be a list")
    pages: list[PageConfig] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"pages entry #{index} must have 'name' and 'url' fields")
        name = str(entry.get("name") or "").strip()
        url = str(entry.get("url") or "").strip()
        if not name or not url:
            raise ConfigError(f"pages entry #{index} needs both 'name' and 'url'")
        if not url.startswith(("http://", "https://")):
            raise ConfigError(f"pages entry #{index}: 'url' must start with http:// or https://")
        pages.append(
            PageConfig(
                name,
                url,
                css_selector=_optional_text(entry.get("css_selector")),
                focus=_optional_text(entry.get("focus")),
            )
        )
    return pages


def _recipients(raw: Any) -> list[Recipient]:
    """Extra e-mail recipients, each limited to some digest topics (headings)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError("'recipients' must be a list")
    recipients: list[Recipient] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"recipients entry #{index} must have 'email' and 'topics' fields")
        email = _optional_text(entry.get("email")) or ""
        if "@" not in email or " " in email:
            raise ConfigError(f"recipients entry #{index} needs a valid 'email'")
        topics = entry.get("topics")
        if isinstance(topics, str):
            topics = [topics]
        if not isinstance(topics, list) or not [t for t in topics if _optional_text(t)]:
            raise ConfigError(f"recipients entry #{index} needs a list of 'topics'")
        names = tuple(dict.fromkeys(t for t in map(_optional_text, topics) if t))
        recipients.append(Recipient(email=email, topics=names))
    return recipients


def _parse_time(value: Any) -> time:
    try:
        if isinstance(value, int) and not isinstance(value, bool):
            # YAML 1.1 reads an unquoted 8:00 as the base-60 integer 480.
            hour, minute = divmod(value, 60)
        else:
            hour, minute = (int(part) for part in str(value).strip().split(":"))
        return time(hour, minute)
    except ValueError:
        raise ConfigError("'send_time' must look like \"08:00\"") from None


def tavily_monthly_usage(config: Config, days: int = 31) -> int:
    """Approximate Tavily credits used per month by this configuration."""
    return len(config.searches) * days
