"""Time helpers. Sites default to Asia/Karachi; storage is always timezone-aware UTC."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

PK_TZ = ZoneInfo("Asia/Karachi")


def utcnow() -> datetime:
    return datetime.now(UTC)


def tz(name: str | ZoneInfo | None) -> ZoneInfo:
    if name is None:
        return PK_TZ
    return name if isinstance(name, ZoneInfo) else ZoneInfo(name)


def now_in(zone: str | ZoneInfo | None = None) -> datetime:
    return datetime.now(tz(zone))


def from_epoch(ts: float, zone: str | ZoneInfo | None = None) -> datetime:
    """Epoch seconds -> aware datetime (UTC unless a zone is given)."""
    return datetime.fromtimestamp(ts, UTC if zone is None else tz(zone))


def to_epoch(dt: datetime) -> float:
    if dt.tzinfo is None:
        raise ValueError("naive datetime; attach a timezone first")
    return dt.timestamp()


def ensure_aware(dt: datetime, default: ZoneInfo | None = None) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=default or UTC)
    return dt


def iso(dt: datetime, timespec: str = "seconds") -> str:
    return ensure_aware(dt).isoformat(timespec=timespec)


def parse_hhmm(value: str) -> dtime:
    hh, mm = value.split(":")
    return dtime(int(hh), int(mm))


def in_daily_window(t: dtime, start: dtime, end: dtime) -> bool:
    """True if ``t`` lies in ``[start, end)``; windows with ``end <= start`` cross midnight."""
    if start == end:
        return True
    if start < end:
        return start <= t < end
    return t >= start or t < end


def floor_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def day_bounds(dt: datetime) -> tuple[datetime, datetime]:
    start = floor_day(dt)
    return start, start + timedelta(days=1)


class WallClock:
    """Epoch clock anchored to ``time.monotonic`` so NTP steps cannot reorder events.

    Re-anchors if the system clock and the monotonic projection drift apart by more than
    ``max_drift_s`` (FMEA #11: clock drift weakens evidence) and reports the observed drift.
    """

    def __init__(self, max_drift_s: float = 2.0) -> None:
        self._anchor = time.time() - time.monotonic()
        self._max_drift = max_drift_s
        self.last_drift_s = 0.0

    def now(self) -> float:
        projected = self._anchor + time.monotonic()
        actual = time.time()
        drift = actual - projected
        if abs(drift) > self._max_drift:
            self.last_drift_s = drift
            self._anchor = actual - time.monotonic()
            return actual
        return projected
