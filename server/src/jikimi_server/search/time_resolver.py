"""Deterministic relative-time resolution in the site timezone (plan: never let the LLM do it).

"kal raat" at 2026-11-22 10:00 PKT -> 2026-11-21 18:00 .. 2026-11-22 06:00. In a *search*,
"kal" always means yesterday (the past). Rules, in order:

1. "abhi" -> last 15 min;  "pichle 2 ghante" -> last 2 h
2. nothing said -> last 7 days (flagged as default)
3. a day (aaj / kal / parson / weekday) with an optional day part (subah, raat, ...)
4. only a day part -> its most recent occurrence ("raat" at noon = last night)
5. a clock time ("11 baje", "23:30") -> +/- 30 min, or "ke baad" / "se pehle" / "2 se 4"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .lexicon import DAY_PARTS

NIGHT_PARTS = ("raat", "aadhi_raat")


@dataclass
class TimeSpec:
    day_offset: int | None = None
    weekday: int | None = None
    day_part: str | None = None
    clock: tuple[int, int] | None = None
    clock_end: tuple[int, int] | None = None
    after: bool = False
    before: bool = False
    last_amount: float | None = None
    last_unit: str | None = None
    now_window: bool = False
    phrases: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return (
            self.day_offset is None
            and self.weekday is None
            and self.day_part is None
            and self.clock is None
            and self.last_unit is None
            and not self.now_window
        )


def _set(day: datetime, h: int, m: int = 0) -> datetime:
    return day.replace(hour=h, minute=m, second=0, microsecond=0)


def part_range(day: datetime, part: str) -> tuple[datetime, datetime]:
    (sh, sm), (eh, em) = ((int(x) for x in s.split(":")) for s in DAY_PARTS[part])
    start, end = _set(day, sh, sm), _set(day, eh, em)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def clock_hours(h: int, part: str | None) -> list[int]:
    """24 h candidates for a spoken hour given the day part ("raat 11" -> 23)."""
    if h >= 13 or h == 0:
        return [h % 24]
    if part in NIGHT_PARTS:
        return [h + 12 if 6 <= h <= 11 else (0 if h == 12 else h)]
    if part in ("shaam", "sehpahar"):
        return [h + 12 if h < 12 else 12]
    if part == "dopahar":
        return [h + 12 if h < 6 else h]
    if part == "subah":
        return [0 if h == 12 else h]
    return sorted({h % 12, h % 12 + 12})


def _anchor(day: datetime, hour: int, minute: int, part: str | None) -> datetime:
    t = _set(day, hour, minute)
    if part in NIGHT_PARTS and hour < 6:
        t += timedelta(days=1)  # "kal raat 2 baje": the night continues past midnight
    return t


def _part_end_after(t: datetime, part: str) -> datetime:
    for back in (1, 0):
        start, end = part_range(t - timedelta(days=back), part)
        if start <= t < end:
            return end
    return t + timedelta(hours=6)


def resolve(spec: TimeSpec, now: datetime, default_days: int = 7) -> tuple[datetime, datetime, bool]:
    """``(from, to, is_default)``; ``now`` must be timezone-aware (site timezone)."""
    today = _set(now, 0)
    if spec.now_window:
        return now - timedelta(minutes=15), now, False
    if spec.last_unit is not None:
        n = spec.last_amount or 1
        unit = {
            "minutes": timedelta(minutes=n),
            "hours": timedelta(hours=n),
            "days": timedelta(days=n),
            "weeks": timedelta(weeks=n),
        }
        return now - unit[spec.last_unit], now, False
    if spec.empty:
        return now - timedelta(days=default_days), now, True

    day: datetime | None = None
    if spec.day_offset is not None:
        day = today - timedelta(days=spec.day_offset)
    elif spec.weekday is not None:
        day = today - timedelta(days=(today.weekday() - spec.weekday) % 7)
    part = spec.day_part

    if spec.clock is None:
        if day is not None:
            return (*part_range(day, part), False) if part else (day, day + timedelta(days=1), False)
        assert part is not None
        start, end = part_range(today, part)
        if start > now:
            start, end = start - timedelta(days=1), end - timedelta(days=1)
        return start, end, False

    h, m = spec.clock
    hours = clock_hours(h, part)
    if day is not None:
        start = max(_anchor(day, hh, m, part) for hh in hours)
    else:
        cands = [_anchor(today - timedelta(days=k), hh, m, part) for k in (0, 1, 2) for hh in hours]
        past = [c for c in cands if c <= now]
        start = max(past) if past else min(cands)
    if spec.clock_end is not None:
        eh, em = spec.clock_end
        ends = [
            _anchor(start.replace(hour=0, minute=0), hh, em, None) + timedelta(days=k)
            for k in (0, 1)
            for hh in clock_hours(eh, part)
        ]
        after = [e for e in ends if e > start]
        return start, min(after) if after else start + timedelta(hours=2), False
    if spec.after:
        end = _part_end_after(start, part) if part else start + timedelta(hours=6)
        return start, end, False
    if spec.before:
        return start - timedelta(hours=3), start, False
    return start - timedelta(minutes=30), start + timedelta(minutes=30), False
