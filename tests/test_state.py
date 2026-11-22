from datetime import date

import pytest

from morning_scout.app import select_new
from morning_scout.models import Item
from morning_scout.state import MAX_SNAPSHOT_CHARS, PageSnapshot, State, StateError
from morning_scout.urls import title_key, url_key

TODAY = date(2026, 11, 22)


def news(title: str, url: str, topic: str = "topic") -> Item:
    return Item(source="news", topic=topic, title=title, url=url)


def test_already_sent_only_matches_today() -> None:
    state = State(last_sent_date="2026-11-22")
    assert state.already_sent(TODAY)
    assert not state.already_sent(date(2026, 11, 23))


def test_select_new_skips_links_sent_before() -> None:
    state = State()
    state.mark_seen([url_key("https://example.com/old?utm_source=x")], TODAY)
    items = [
        news("Old story", "https://example.com/old"),
        news("New story", "https://example.com/new"),
    ]

    fresh, keys = select_new(items, state)

    assert [item.title for item in fresh] == ["New story"]
    assert url_key("https://example.com/new") in keys


def test_select_new_dedupes_news_by_title_and_within_run() -> None:
    state = State()
    state.mark_seen([title_key("Big announcement")], TODAY)
    items = [
        news("Big announcement - Publisher A", "https://news.example/r/1"),
        news("Another story", "https://a.example/x"),
        news("Another story - Publisher B", "https://b.example/y"),
        Item(source="search", topic="t", title="Another story", url="https://a.example/x/"),
    ]

    fresh, _ = select_new(items, state)

    assert [item.url for item in fresh] == ["https://a.example/x"]


def test_search_results_are_not_deduped_by_generic_titles() -> None:
    items = [
        Item(source="search", topic="t", title="Home", url="https://a.example"),
        Item(source="search", topic="t", title="Home", url="https://b.example"),
    ]
    fresh, _ = select_new(items, State())
    assert len(fresh) == 2


def test_prune_removes_entries_older_than_30_days() -> None:
    state = State(seen={"old": "2026-10-22", "edge": "2026-10-23", "new": "2026-11-20"})
    removed = state.prune(TODAY)
    assert removed == 1
    assert set(state.seen) == {"edge", "new"}


def test_mark_seen_keeps_first_date() -> None:
    state = State(seen={"k": "2026-11-01"})
    state.mark_seen(["k", "j"], TODAY)
    assert state.seen == {"k": "2026-11-01", "j": "2026-11-22"}


def test_roundtrip_compresses_and_truncates_page_text() -> None:
    long_text = "line of page text\n" * 5000
    state = State(
        seen={"abc": "2026-11-22"},
        pages={"p1": PageSnapshot.from_text(long_text, TODAY)},
        last_sent_date="2026-11-22",
    )
    raw = state.to_json()

    assert long_text[:50] not in raw  # stored compressed, not as plain text
    assert len(raw) < 5000

    restored = State.from_json(raw)
    assert restored.seen == state.seen
    assert restored.last_sent_date == "2026-11-22"
    assert restored.pages["p1"].text == long_text[:MAX_SNAPSHOT_CHARS]
    assert restored.pages["p1"].text_hash == state.pages["p1"].text_hash


@pytest.mark.parametrize("blank", [None, "", "  \n"])
def test_missing_state_starts_fresh(blank: str | None) -> None:
    assert State.from_json(blank) == State()


def test_corrupt_state_raises_without_content() -> None:
    with pytest.raises(StateError) as info:
        State.from_json('{"seen": "secret-topic-text"')
    assert "secret-topic-text" not in str(info.value)


def test_forget_pages_except() -> None:
    snap = PageSnapshot.from_text("x", TODAY)
    state = State(pages={"keep": snap, "drop": snap})
    state.forget_pages_except({"keep"})
    assert set(state.pages) == {"keep"}
