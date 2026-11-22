"""Time-zone aware helpers for "today" and waiting until the configured send time."""

from __future__ import annotations

import time as _time
from collections.abc import Callable
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

# Never sleep longer than this; protects against misconfiguration eating the CI timeout.
MAX_WAIT_SECONDS = 25 * 60


def now_in(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def local_today(tz: ZoneInfo, now: datetime | None = None) -> date:
    """Today's date in ``tz`` (the date used for the once-per-day guard)."""
    return (now or now_in(tz)).astimezone(tz).date()


def seconds_until(send_time: time, tz: ZoneInfo, now: datetime | None = None) -> float:
    """Seconds from ``now`` until ``send_time`` today in ``tz``; 0 if already past."""
    current = (now or now_in(tz)).astimezone(tz)
    target = datetime.combine(current.date(), send_time, tzinfo=tz)
    return max(0.0, (target - current).total_seconds())


def wait_until(
    send_time: time,
    tz: ZoneInfo,
    *,
    sleep: Callable[[float], None] = _time.sleep,
    now: Callable[[], datetime] | None = None,
    max_wait: float = MAX_WAIT_SECONDS,
) -> float:
    """Block until ``send_time`` (capped at ``max_wait``). Returns the seconds waited."""
    delay = min(seconds_until(send_time, tz, now() if now else None), max_wait)
    if delay > 0:
        sleep(delay)
    return delay
