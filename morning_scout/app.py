"""The daily pipeline: load → collect → dedupe → summarise → wait → deliver → save."""

from __future__ import annotations

import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from morning_scout import notify, render, timing
from morning_scout.config import (
    MONTHLY_TAVILY_CREDITS,
    Config,
    ConfigError,
    PageConfig,
    Secrets,
    parse_config,
    tavily_monthly_usage,
)
from morning_scout.messages import messages_for
from morning_scout.models import Item, PageChange
from morning_scout.privacy import describe_error, redactor
from morning_scout.sources import new_session
from morning_scout.sources.news import fetch_news
from morning_scout.sources.pages import compare, fetch_page_text
from morning_scout.sources.search import search
from morning_scout.state import PageSnapshot, State, StateError, page_key
from morning_scout.storage import (
    CONFIG_FILE,
    STATE_FILE,
    GistStorage,
    LocalStorage,
    Storage,
    StorageError,
)
from morning_scout.summarizer import SummaryError, fallback_summary, summarize_with_gemini
from morning_scout.urls import title_key, url_key

log = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("data")
MAX_WORKERS = 8

EXIT_OK = 0
EXIT_FAILURE = 1


@dataclass(frozen=True)
class RunOptions:
    """Command-line switches (see ``python -m morning_scout --help``)."""

    dry_run: bool = False
    now: bool = False
    force: bool = False
    local: bool = False
    verbose: bool = False


@dataclass
class Collection:
    """Everything gathered from the sources in one run."""

    news: list[Item] = field(default_factory=list)
    search: list[Item] = field(default_factory=list)
    changes: list[PageChange] = field(default_factory=list)
    snapshots: dict[str, PageSnapshot] = field(default_factory=dict)
    failures: int = 0


def run(options: RunOptions, secrets: Secrets | None = None, storage: Storage | None = None) -> int:
    """Execute one daily run and return a process exit code."""
    secrets = secrets or Secrets.from_env()
    redactor.register_many(secrets.values())

    try:
        storage = storage or make_storage(options, secrets)
        config = load_config(storage)
    except ConfigError as exc:
        where = f" at line {exc.line}" if exc.line else ""
        log.error("Config: invalid%s: %s", where, exc)
        _alert(secrets, "config_error", line=exc.line, dry_run=options.dry_run)
        return EXIT_FAILURE
    except StorageError as exc:
        log.error("Storage: %s", exc)
        return EXIT_FAILURE

    redactor.register_many(config.sensitive_values())
    tz = config.tz
    today = timing.local_today(tz)

    try:
        state = State.from_json(storage.read(STATE_FILE))
    except (StateError, StorageError) as exc:
        log.error("State: %s", exc)
        if isinstance(exc, StateError):
            _alert(
                secrets, "state_error", language=config.summary_language, dry_run=options.dry_run
            )
        return EXIT_FAILURE

    if state.already_sent(today) and not options.force:
        log.info("Digest already sent today; nothing to do (use --force to override)")
        return EXIT_OK

    log.info(
        "Config: %d news queries, %d searches, %d pages",
        len(config.news),
        len(config.searches),
        len(config.pages),
    )
    if tavily_monthly_usage(config) > MONTHLY_TAVILY_CREDITS:
        log.warning(
            "Tavily: %d searches/day may exceed the free monthly credits", len(config.searches)
        )

    collection = collect(config, secrets, state, today)
    new_items, new_keys = select_new([*collection.news, *collection.search], state)
    redactor.register_many(item.title for item in new_items)
    _log_counts(collection, new_items, len(config.pages))

    summary, kind = build_summary(new_items, collection.changes, config, secrets)
    title = messages_for(config.summary_language)["title"].format(date=today.strftime("%d.%m.%Y"))

    if options.dry_run:
        print(f"\n{title}\n{'=' * len(title)}\n\n{summary}\n")
        log.info("Dry run: nothing sent, state not saved")
        return EXIT_OK

    if not options.now:
        waited = timing.wait_until(config.send_time, tz)
        if waited:
            log.info("Waited %.0f s for the configured send time", waited)

    if not deliver(summary, title, kind, config.summary_language, secrets):
        log.error("Delivery: every channel failed; state not updated so the next run retries")
        return EXIT_FAILURE

    state.mark_seen(new_keys, today)
    state.last_sent_date = today.isoformat()
    state.pages.update(collection.snapshots)
    state.forget_pages_except({page_key(page.url) for page in config.pages})
    pruned = state.prune(today)
    try:
        storage.write(STATE_FILE, state.to_json())
    except StorageError as exc:
        log.error("State: saving failed after delivery: %s", exc)
        return EXIT_FAILURE
    log.info("State: saved (%d remembered links, %d expired)", len(state.seen), pruned)
    return EXIT_OK


def make_storage(options: RunOptions, secrets: Secrets) -> Storage:
    """Local folder for development (``--local`` or ``DATA_DIR``), otherwise the Gist."""
    data_dir = os.environ.get("DATA_DIR")
    if options.local or data_dir:
        return LocalStorage(Path(data_dir) if data_dir else DEFAULT_DATA_DIR)
    return GistStorage(secrets.gist_id, secrets.gist_token)


def load_config(storage: Storage) -> Config:
    text = storage.read(CONFIG_FILE)
    if text is None:
        raise ConfigError("config.yaml was not found in the data store")
    return parse_config(text)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect(config: Config, secrets: Secrets, state: State, today: date) -> Collection:
    """Query every source in parallel. A failing source is logged and skipped."""
    result = Collection()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        news_jobs = [pool.submit(_fetch_news, query) for query in config.news]

        search_jobs: list[Future[list[Item]]] = []
        if config.searches and not secrets.tavily_api_key:
            log.warning(
                "Tavily: TAVILY_API_KEY not set; skipping %d searches", len(config.searches)
            )
        elif config.searches:
            search_jobs = [
                pool.submit(_search, query, secrets.tavily_api_key, config.search_time_range)
                for query in config.searches
            ]
            log.info("Tavily: %d searches", len(search_jobs))

        page_jobs = [(page, pool.submit(_fetch_page, page)) for page in config.pages]

        result.news = _gather("news", news_jobs, result)
        result.search = _gather("search", search_jobs, result)

        statuses = {"first_seen": 0, "unchanged": 0, "changed": 0}
        for index, (page, job) in enumerate(page_jobs, start=1):
            try:
                text = job.result()
            except Exception as exc:
                result.failures += 1
                log.warning("pages: page #%d failed: %s", index, describe_error(exc))
                continue
            key = page_key(page.url)
            check = compare(page, text, state.pages.get(key), today)
            statuses[check.status] += 1
            result.snapshots[key] = check.snapshot
            if check.change:
                result.changes.append(check.change)
            log.debug("pages: %s -> %s", page.name, check.status)
        if config.pages:
            log.info(
                "pages: %d/%d changed, %d first snapshot(s)",
                statuses["changed"],
                len(config.pages),
                statuses["first_seen"],
            )
    return result


def _fetch_news(query: str) -> list[Item]:
    with new_session() as session:
        return fetch_news(query, session)


def _search(query: str, api_key: str, time_range: str) -> list[Item]:
    with new_session() as session:
        return search(query, api_key, session, time_range)


def _fetch_page(page: PageConfig) -> str:
    with new_session() as session:
        return fetch_page_text(page, session)


def _gather(label: str, jobs: list[Future[list[Item]]], result: Collection) -> list[Item]:
    items: list[Item] = []
    for index, job in enumerate(jobs, start=1):
        try:
            items.extend(job.result())
        except Exception as exc:
            result.failures += 1
            log.warning("%s: query #%d failed: %s", label, index, describe_error(exc))
    return items


def select_new(items: list[Item], state: State) -> tuple[list[Item], list[str]]:
    """Drop items already sent on a previous day or duplicated within this run.

    News items are matched by URL *and* headline (Google News hands out different
    redirect URLs for the same story); search results by URL only, since generic
    page titles ("Home", "Blog") would cause false matches.
    """
    fresh: list[Item] = []
    keys: list[str] = []
    batch: set[str] = set()
    for item in items:
        item_keys = [url_key(item.url)]
        if item.source == "news":
            item_keys.append(title_key(item.title))
        if state.is_seen(*item_keys) or batch.intersection(item_keys):
            continue
        batch.update(item_keys)
        keys.extend(item_keys)
        fresh.append(item)
    return fresh, keys


def _log_counts(collection: Collection, new_items: list[Item], page_count: int) -> None:
    for label, items in (("news", collection.news), ("search", collection.search)):
        new = sum(1 for item in new_items if item.source == label)
        log.info("%s: %d results, %d new", label, len(items), new)
    if collection.failures:
        log.warning("Sources: %d request(s) failed (see warnings above)", collection.failures)


# ---------------------------------------------------------------------------
# Summary and delivery
# ---------------------------------------------------------------------------


def build_summary(
    items: list[Item], changes: list[PageChange], config: Config, secrets: Secrets
) -> tuple[str, str]:
    """Return ``(markdown, kind)`` where kind is ``"empty"``, ``"ai"`` or ``"fallback"``."""
    language = config.summary_language
    if not items and not changes:
        return messages_for(language)["nothing_new"], "empty"
    try:
        text = summarize_with_gemini(
            items,
            changes,
            api_key=secrets.gemini_api_key,
            model=config.gemini_model,
            language=language,
        )
        log.info("Gemini: summary created (%d characters)", len(text))
        return text, "ai"
    except SummaryError as exc:
        cause = describe_error(exc.__cause__) if exc.__cause__ else str(exc)
        log.warning("Gemini: failed (%s); sending the raw list instead", cause)
        return fallback_summary(items, changes, language), "fallback"


def deliver(summary: str, title: str, kind: str, language: str, secrets: Secrets) -> bool:
    """Send via every configured channel. Returns True if at least one succeeded.

    On days with nothing new only the short push is sent (no e-mail), unless
    ntfy is not configured.
    """
    has_ntfy = bool(secrets.ntfy_topic)
    has_mail = bool(secrets.gmail_address and secrets.gmail_app_password and secrets.mail_to)
    if not has_ntfy and not has_mail:
        log.error("Delivery: no channel configured (set NTFY_TOPIC and/or the GMAIL_* secrets)")
        return False

    delivered = False
    if has_ntfy:
        try:
            notify.send_ntfy(secrets.ntfy_topic, title, render.ntfy_message(summary, language))
            log.info("ntfy: sent")
            delivered = True
        except Exception as exc:
            log.warning("ntfy: failed: %s", describe_error(exc))

    if has_mail and (kind != "empty" or not has_ntfy):
        try:
            notify.send_email(
                sender=secrets.gmail_address,
                app_password=secrets.gmail_app_password,
                recipient=secrets.mail_to,
                subject=title,
                html_body=render.email_html(summary, title, language),
                text_body=render.email_text(summary),
            )
            log.info("e-mail: sent")
            delivered = True
        except Exception as exc:
            log.warning("e-mail: failed: %s", describe_error(exc))
    return delivered


def _alert(
    secrets: Secrets,
    message_key: str,
    *,
    line: int | None = None,
    language: str = "tr",
    dry_run: bool = False,
) -> None:
    """Best-effort ntfy alert about a broken data file (never includes its content)."""
    msg = messages_for(language)
    text = msg[message_key]
    if message_key == "config_error":
        text = text.format(line=msg["config_error_line"].format(line=line) if line else "")
    if dry_run or not secrets.ntfy_topic:
        return
    try:
        notify.send_ntfy(secrets.ntfy_topic, "Morning Scout", text, priority=4, tags=["warning"])
        log.info("ntfy: error alert sent")
    except Exception as exc:
        log.warning("ntfy: error alert failed: %s", describe_error(exc))
