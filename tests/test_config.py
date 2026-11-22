from datetime import time
from pathlib import Path

import pytest

from morning_scout.config import DEFAULT_GEMINI_MODEL, ConfigError, parse_config

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
    assert config.news == ["artificial intelligence"]  # duplicates removed
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
