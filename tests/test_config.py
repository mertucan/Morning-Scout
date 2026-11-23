from datetime import time
from pathlib import Path

import pytest

from morning_scout.config import DEFAULT_GEMINI_MODEL, ConfigError, Query, parse_config

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.yaml"


def test_example_config_is_valid() -> None:
    config = parse_config(EXAMPLE.read_text(encoding="utf-8"))
    assert config.news and config.searches and config.pages
    assert config.send_time == time(8, 0)
    assert config.timezone == "Europe/Istanbul"


def test_defaults_for_empty_file() -> None:
    config = parse_config("")
    assert config.news == []
    assert config.gemini_model == DEFAULT_GEMINI_MODEL
    assert config.summary_language == "tr"


def test_full_config() -> None:
    config = parse_config(
        """
news:
  - artificial intelligence
  - artificial intelligence
searches: ["Python release"]
pages:
  - name: Docs
    url: https://example.com
    css_selector: "#main"
send_time: "07:30"
summary_language: EN
"""
    )
    assert [q.text for q in config.news] == ["artificial intelligence"]  # duplicates removed
    assert config.pages[0].css_selector == "#main"
    assert config.send_time == time(7, 30)
    assert config.summary_language == "en"


def test_unquoted_time_is_understood() -> None:
    # YAML 1.1 reads 8:00 as the base-60 integer 480.
    assert parse_config("send_time: 8:00").send_time == time(8, 0)


def test_yaml_syntax_error_reports_line_without_content() -> None:
    broken = 'news:\n  - "secret topic one"\n  - "unterminated\nsearches: [oops\n'
    with pytest.raises(ConfigError) as info:
        parse_config(broken)
    assert info.value.line is not None and info.value.line >= 3
    assert "secret topic" not in str(info.value)


def test_tab_indentation_is_reported_with_line() -> None:
    with pytest.raises(ConfigError) as info:
        parse_config("news:\n\t- topic\n")
    assert info.value.line == 2


@pytest.mark.parametrize(
    "text",
    [
        "- just a list",
        "news: not-a-list",
        "news:\n  - ''",
        "pages:\n  - name: X",
        "pages:\n  - name: X\n    url: example.com",
        "send_time: noon",
        "timezone: Mars/Olympus",
        "search_time_range: month",
    ],
)
def test_invalid_values_raise(text: str) -> None:
    with pytest.raises(ConfigError):
        parse_config(text)


def test_error_message_hides_values() -> None:
    with pytest.raises(ConfigError) as info:
        parse_config("pages:\n  - name: My Private Page\n    url: private.example/secret")
    assert "Private" not in str(info.value)
    assert "secret" not in str(info.value)


def test_gemini_models_chain_ends_with_last_resort_without_duplicates() -> None:
    from morning_scout.config import LAST_RESORT_GEMINI_MODEL

    config = parse_config("gemini_model: a\ngemini_fallback_model: a")
    assert config.gemini_models == ["a", LAST_RESORT_GEMINI_MODEL]


def test_query_entries_with_topic_sites_and_focus() -> None:
    config = parse_config(
        """
news:
  - plain topic
  - query: associate degree jobs
    topic: Jobs
    focus: only associate-degree listings
searches:
  - query: pilot cadet applications
    topic: Jobs
    sites: [https://www.X.com/, instagram.com]
"""
    )
    plain, jobs = config.news
    assert plain == Query(text="plain topic", topic="plain topic")
    assert jobs.topic == "Jobs" and jobs.focus == "only associate-degree listings"
    assert config.searches[0].sites == ("x.com", "instagram.com")
    assert config.focus_by_topic == {"Jobs": "only associate-degree listings"}


def test_sensitive_values_cover_every_query_field() -> None:
    config = parse_config(
        "searches:\n  - query: q1\n    topic: t1\n    sites: [s1.example]\n    focus: f1\n"
        "pages:\n  - name: n1\n    url: https://u1.example\n    focus: f2\n"
    )
    assert {"q1", "t1", "s1.example", "f1", "n1", "https://u1.example", "f2"} <= set(
        config.sensitive_values()
    )
    assert "" not in config.sensitive_values()


@pytest.mark.parametrize(
    "text",
    [
        "news:\n  - query: q\n    sites: [x.com]",  # sites only work with Tavily
        "searches:\n  - topic: no query",
        "searches:\n  - query: q\n    sites: [x.com/someone]",
        "searches:\n  - query: q\n    site: x.com",  # typo
    ],
)
def test_invalid_query_entries_raise(text: str) -> None:
    with pytest.raises(ConfigError):
        parse_config(text)
