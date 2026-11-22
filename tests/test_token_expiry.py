from datetime import UTC, datetime
from types import SimpleNamespace

from morning_scout.app import token_expiry_warning
from morning_scout.storage import parse_token_expiration

NOW = datetime(2027, 2, 10, 5, 0, tzinfo=UTC)


def test_parse_github_expiration_header() -> None:
    assert parse_token_expiration("2027-02-20 21:14:46 UTC") == datetime(
        2027, 2, 20, 21, 14, 46, tzinfo=UTC
    )
    assert parse_token_expiration(None) is None
    assert parse_token_expiration("garbage") is None


def test_warning_shown_within_two_weeks() -> None:
    storage = SimpleNamespace(token_expires_at=datetime(2027, 2, 20, 21, 14, tzinfo=UTC))
    warning = token_expiry_warning(storage, "tr", now=NOW)
    assert warning is not None
    assert "10 gün" in warning and "20.02.2027" in warning


def test_no_warning_when_far_away_or_unknown() -> None:
    far = SimpleNamespace(token_expires_at=datetime(2027, 6, 1, tzinfo=UTC))
    assert token_expiry_warning(far, "tr", now=NOW) is None
    assert token_expiry_warning(SimpleNamespace(), "tr", now=NOW) is None
