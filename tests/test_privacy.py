"""Logs must never contain personal data: topics, URLs, titles, summaries or the Gist id."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from morning_scout import app, notify
from morning_scout.app import RunOptions, run
from morning_scout.config import Query, Secrets
from morning_scout.models import Item
from morning_scout.privacy import REDACTED, RedactingFilter, Redactor, describe_error, redactor
from morning_scout.state import State
from morning_scout.storage import LocalStorage

TOPIC = "zz-private-topic-zz"
QUERY = "zz-private-search-zz"
PAGE_NAME = "zz-private-page-zz"
PAGE_URL = "https://private-page.example/zz"
TITLE = "zz-private-headline-zz"
ITEM_URL = "https://private-news.example/article/zz"
SUMMARY = "zz-private-summary-zz"
GIST_ID = "zzprivategistidzz"

SENSITIVE = [TOPIC, QUERY, PAGE_NAME, PAGE_URL, TITLE, ITEM_URL, SUMMARY, GIST_ID, "private-"]

CONFIG = f"""
news: ["{TOPIC}"]
searches: ["{QUERY}"]
pages:
  - name: {PAGE_NAME}
    url: {PAGE_URL}
send_time: "08:00"
"""


def test_redactor_scrubs_urls_and_registered_values() -> None:
    r = Redactor()
    r.register("Secret Topic", "", None, "ab")
    text = r.redact("failed for secret topic at https://x.example/a?q=secret+topic (ab)")
    assert "secret" not in text.lower()
    assert "x.example" not in text
    assert "(ab)" in text  # very short values are not treated as secrets


def test_describe_error_hides_exception_message() -> None:
    response = requests.Response()
    response.status_code = 404
    exc = requests.HTTPError(f"404 Client Error for url: {ITEM_URL}", response=response)
    assert describe_error(exc) == "HTTPError (HTTP 404)"
    assert describe_error(ValueError(TOPIC)) == "ValueError"


def test_filter_redacts_args_and_drops_tracebacks() -> None:
    r = Redactor()
    r.register(TOPIC)
    try:
        raise RuntimeError(TOPIC)
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "x", logging.ERROR, __file__, 1, "q=%s url=%s", (TOPIC, ITEM_URL), sys.exc_info()
        )
    RedactingFilter(r).filter(record)
    assert record.getMessage() == f"q={REDACTED} url={REDACTED}"
    assert record.exc_info is None


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    (tmp_path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    return tmp_path


@pytest.fixture
def mocked_sources(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    sent: dict[str, list] = {"ntfy": [], "email": []}

    def fake_news(query: Query) -> list[Item]:
        return [Item("news", query.topic, TITLE, ITEM_URL, "snippet")]

    def fake_search(query: Query, api_key: str, time_range: str) -> list[Item]:
        raise requests.HTTPError(
            f"500 Server Error for url: https://api.tavily.com/search?q={QUERY}"
        )

    def fake_page(page: object) -> str:
        return "page text"

    def fake_gemini(*_args: object, **_kwargs: object) -> str:
        return f"### {TOPIC}\n- {SUMMARY} [Kaynak]({ITEM_URL})"

    monkeypatch.setattr(app, "_fetch_news", fake_news)
    monkeypatch.setattr(app, "_search", fake_search)
    monkeypatch.setattr(app, "_fetch_page", fake_page)
    monkeypatch.setattr(app, "summarize_with_gemini", fake_gemini)
    monkeypatch.setattr(notify, "send_ntfy", lambda *a, **k: sent["ntfy"].append((a, k)))
    monkeypatch.setattr(notify, "send_email", lambda *a, **k: sent["email"].append(k))
    return sent


SECRETS = Secrets(
    gemini_api_key="gemini-key-123",
    tavily_api_key="tavily-key-123",
    gmail_address="me@example.com",
    gmail_app_password="app-pass-123",
    mail_to="me@example.com",
    ntfy_topic="ntfy-topic-123",
    gist_id=GIST_ID,
    gist_token="gist-token-123",
)


def _all_log_text(caplog: pytest.LogCaptureFixture) -> str:
    handler_filter = RedactingFilter(redactor)
    lines = []
    for record in caplog.records:
        handler_filter.filter(record)
        lines.append(record.getMessage())
    return "\n".join(lines)


def test_full_run_logs_contain_no_personal_data(
    data_dir: Path, mocked_sources: dict[str, list], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="morning_scout")

    code = run(RunOptions(now=True), secrets=SECRETS, storage=LocalStorage(data_dir))

    assert code == 0
    assert mocked_sources["ntfy"] and mocked_sources["email"]
    raw_logs = "\n".join(r.getMessage() for r in caplog.records if r.levelno >= logging.INFO)
    for value in [*SENSITIVE, *SECRETS.values()]:
        assert value not in raw_logs, f"sensitive value leaked into logs: {value!r}"
    # Aggregate, useful information is still there.
    assert "news: 1 results, 1 new" in raw_logs
    assert "search: query #1 failed: HTTPError" in raw_logs
    assert "pages: 0/1 changed, 1 first snapshot(s)" in raw_logs
    # Debug lines may name things but the handler filter scrubs them anyway.
    assert all(value not in _all_log_text(caplog) for value in SENSITIVE)


def test_second_run_same_day_does_not_send_again(
    data_dir: Path, mocked_sources: dict[str, list]
) -> None:
    storage = LocalStorage(data_dir)
    assert run(RunOptions(now=True), secrets=SECRETS, storage=storage) == 0
    assert run(RunOptions(now=True), secrets=SECRETS, storage=storage) == 0
    assert len(mocked_sources["ntfy"]) == 1
    assert len(mocked_sources["email"]) == 1


def test_forced_rerun_sends_nothing_new_without_email(
    data_dir: Path, mocked_sources: dict[str, list]
) -> None:
    storage = LocalStorage(data_dir)
    run(RunOptions(now=True), secrets=SECRETS, storage=storage)
    run(RunOptions(now=True, force=True), secrets=SECRETS, storage=storage)

    second_message = mocked_sources["ntfy"][1][0][2]
    assert "yeni bir gelişme yok" in second_message
    assert len(mocked_sources["email"]) == 1  # no e-mail on empty days


def test_dry_run_writes_no_state_and_sends_nothing(
    data_dir: Path, mocked_sources: dict[str, list], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(RunOptions(dry_run=True), secrets=SECRETS, storage=LocalStorage(data_dir)) == 0
    assert not (data_dir / "state.json").exists()
    assert not mocked_sources["ntfy"]
    assert SUMMARY in capsys.readouterr().out


def test_broken_config_alerts_with_line_only(
    data_dir: Path, mocked_sources: dict[str, list], caplog: pytest.LogCaptureFixture
) -> None:
    (data_dir / "config.yaml").write_text(f'news:\n  - "{TOPIC}\n  - x: [\n', encoding="utf-8")
    caplog.set_level(logging.INFO, logger="morning_scout")

    assert run(RunOptions(now=True), secrets=SECRETS, storage=LocalStorage(data_dir)) == 1

    args, _kwargs = mocked_sources["ntfy"][0]
    alert = args[2]
    assert "satır" in alert
    assert TOPIC not in alert
    assert TOPIC not in caplog.text
    assert not mocked_sources["email"]


def test_failed_delivery_keeps_state_for_retry(
    data_dir: Path, mocked_sources: dict[str, list], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise requests.ConnectionError(f"cannot reach {ITEM_URL}")

    monkeypatch.setattr(notify, "send_ntfy", boom)
    monkeypatch.setattr(notify, "send_email", boom)

    assert run(RunOptions(now=True), secrets=SECRETS, storage=LocalStorage(data_dir)) == 1
    assert not (data_dir / "state.json").exists()


def test_state_marks_sent_links_and_date(data_dir: Path, mocked_sources: dict[str, list]) -> None:
    storage = LocalStorage(data_dir)
    run(RunOptions(now=True), secrets=SECRETS, storage=storage)
    state = State.from_json(storage.read("state.json"))
    today = datetime.now(ZoneInfo("Europe/Istanbul")).date().isoformat()
    assert state.last_sent_date == today
    assert len(state.seen) == 2  # URL key + headline key
    assert len(state.pages) == 1
    raw = (data_dir / "state.json").read_text(encoding="utf-8")
    assert ITEM_URL not in raw and TITLE not in raw  # only hashes are stored
