import pytest

from morning_scout.urls import normalize_url, title_key, url_key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.com/a/", "https://example.com/a"),
        ("HTTP://WWW.Example.COM/a", "https://example.com/a"),
        ("https://example.com/a#section", "https://example.com/a"),
        ("https://example.com/a?utm_source=x&utm_medium=y", "https://example.com/a"),
        ("https://example.com/a?fbclid=123&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("https://example.com:8443/a", "https://example.com:8443/a"),
        ("  https://example.com/  ", "https://example.com"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


def test_url_key_ignores_tracking_differences() -> None:
    a = url_key("https://www.example.com/news/1?utm_campaign=mail#top")
    b = url_key("http://example.com/news/1/")
    assert a == b
    assert len(a) == 16


def test_url_key_distinguishes_meaningful_query() -> None:
    assert url_key("https://example.com/item?id=1") != url_key("https://example.com/item?id=2")


def test_title_key_ignores_publisher_suffix_case_and_punctuation() -> None:
    assert title_key("Python 3.14 released! - Example News") == title_key("python 3 14 released")
    assert title_key("Python 3.14 released") != title_key("Python 3.15 released")
