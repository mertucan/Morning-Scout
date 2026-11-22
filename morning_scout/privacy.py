"""Log hygiene: keep personal data (topics, URLs, titles, summaries) out of logs.

Two layers of defence:

1. Application code only logs aggregate information (counts, durations, error
   *types*), never the values themselves. :func:`describe_error` turns an
   exception into a safe one-liner without its message, because messages from
   ``requests`` and friends routinely contain the full URL and query string.
2. :class:`RedactingFilter` is attached to every log handler and scrubs URLs and
   any value registered with :data:`redactor` (queries, page names, gist id...),
   in case something slips through, including from third-party libraries.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

REDACTED = "[redacted]"
_URL_RE = re.compile(r"(?:https?|ftp)://[^\s'\"<>)]+", re.IGNORECASE)
_MIN_SECRET_LENGTH = 3  # avoid redacting every "a" or "of" in a log line


class Redactor:
    """Replaces URLs and registered sensitive strings with a placeholder."""

    def __init__(self) -> None:
        self._values: set[str] = set()

    def register(self, *values: str | None) -> None:
        """Mark values (e.g. queries, page names, secrets) as never-loggable."""
        for value in values:
            if value and len(value.strip()) >= _MIN_SECRET_LENGTH:
                self._values.add(value.strip())

    def register_many(self, values: Iterable[str | None]) -> None:
        self.register(*values)

    def clear(self) -> None:
        self._values.clear()

    def redact(self, text: str) -> str:
        """Return ``text`` with URLs and registered values replaced."""
        text = _URL_RE.sub(REDACTED, text)
        # Longest first so that "python release notes" wins over "python release".
        for value in sorted(self._values, key=len, reverse=True):
            text = re.sub(re.escape(value), REDACTED, text, flags=re.IGNORECASE)
        return text


redactor = Redactor()


def describe_error(exc: BaseException) -> str:
    """Describe an exception without its (potentially sensitive) message.

    Returns the exception type plus an HTTP status code when one is available,
    e.g. ``"HTTPError (HTTP 404)"`` or ``"ConnectTimeout"``.
    """
    name = type(exc).__name__
    status = _status_code(exc)
    return f"{name} (HTTP {status})" if status else name


def _status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is None:
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return status if isinstance(status, int) else None


class RedactingFilter(logging.Filter):
    """Logging filter that redacts messages and, unless verbose, drops tracebacks."""

    def __init__(self, active_redactor: Redactor, keep_tracebacks: bool = False) -> None:
        super().__init__()
        self._redactor = active_redactor
        self._keep_tracebacks = keep_tracebacks

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redactor.redact(record.getMessage())
        record.args = None
        if not self._keep_tracebacks:
            # Tracebacks embed exception messages (and therefore URLs/queries).
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


def configure_logging(verbose: bool = False) -> None:
    """Configure root logging with redaction.

    In normal mode only this package logs at INFO; noisy third-party loggers
    (``httpx`` logs full request URLs at INFO) are limited to WARNING. In verbose
    mode, intended for local debugging only, everything is shown unredacted.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
    if not verbose:
        handler.addFilter(RedactingFilter(redactor))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.WARNING)
    logging.getLogger("morning_scout").setLevel(logging.DEBUG if verbose else logging.INFO)
