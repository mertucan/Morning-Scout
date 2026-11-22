from datetime import date

import pytest

from morning_scout.config import PageConfig
from morning_scout.sources.pages import (
    SelectorNotFoundError,
    compare,
    extract_text,
    summarize_diff,
)
from morning_scout.state import PageSnapshot

TODAY = date(2026, 11, 22)
PAGE = PageConfig(name="Example", url="https://example.com/apply")

HTML = """
<html><head><title>t</title><style>body{color:red}</style></head>
<body>
  <nav>Menu</nav>
  <main id="content">
    <h1>Applications</h1>
    <p>Status:   <b>closed</b></p>
  </main>
  <script>var tracking = 1;</script>
</body></html>
"""


def test_extract_text_drops_scripts_and_normalises_whitespace() -> None:
    text = extract_text(HTML)
    assert "tracking" not in text
    assert "color:red" not in text
    assert "Status:" in text and "closed" in text
    assert "  " not in text


def test_extract_text_with_selector() -> None:
    text = extract_text(HTML, "#content")
    assert "Menu" not in text
    assert text.startswith("Applications")


def test_extract_text_selector_not_found() -> None:
    with pytest.raises(SelectorNotFoundError):
        extract_text(HTML, "#missing")


def test_new_page_is_only_recorded_not_reported() -> None:
    check = compare(PAGE, "Applications\nStatus: closed", previous=None, today=TODAY)
    assert check.status == "first_seen"
    assert check.change is None
    assert check.snapshot.text == "Applications\nStatus: closed"


def test_unchanged_page() -> None:
    previous = PageSnapshot.from_text("Applications\nStatus: closed", TODAY)
    check = compare(PAGE, "Applications\nStatus: closed", previous, TODAY)
    assert check.status == "unchanged"
    assert check.change is None


def test_changed_page_reports_short_diff() -> None:
    previous = PageSnapshot.from_text("Applications\nStatus: closed\nFooter", TODAY)
    check = compare(PAGE, "Applications\nStatus: open\nFooter", previous, TODAY)

    assert check.status == "changed"
    assert check.change is not None
    assert check.change.name == "Example"
    assert "- Status: closed" in check.change.diff
    assert "+ Status: open" in check.change.diff
    assert "Footer" not in check.change.diff


def test_change_beyond_truncated_snapshot_is_still_detected() -> None:
    base = "a\n" * 20_000
    previous = PageSnapshot.from_text(base + "old tail", TODAY)
    check = compare(PAGE, base + "new tail", previous, TODAY)
    assert check.status == "changed"
    assert check.change is not None and check.change.diff


def test_summarize_diff_is_capped() -> None:
    old = "\n".join(f"old {i}" for i in range(1000))
    new = "\n".join(f"new {i}" for i in range(1000))
    diff = summarize_diff(old, new, limit=200)
    assert len(diff) <= 202
    assert diff.endswith("…")
