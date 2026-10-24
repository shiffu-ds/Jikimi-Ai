"""Hijri (Islamic) dates without a dependency: the arithmetic calendar of Reingold & Dershowitz,
*Calendrical Calculations*.

Pakistan follows moon sighting, so a tabular date can be a day off. On the 2024-25 Pakistani
dates it is exact for both Eids and Ashura and one day early for the start of Ramadan; F16
therefore treats these dates as estimates that an admin confirms (plan Section 8.16).
"""

from __future__ import annotations

from datetime import date

_EPOCH = 227015  # date.toordinal() of 1 Muharram 1 AH (16 July 622, Julian calendar)


def to_gregorian(year: int, month: int, day: int) -> date:
    if not (1 <= month <= 12 and 1 <= day <= 30):
        raise ValueError("Hijri month must be 1..12 and day 1..30")
    days = day + 29 * (month - 1) + (6 * month - 1) // 11 + (year - 1) * 354 + (3 + 11 * year) // 30
    return date.fromordinal(days + _EPOCH - 1)


def from_gregorian(d: date) -> tuple[int, int, int]:
    """``(year, month, day)`` of the tabular Hijri date for ``d``."""
    year = (30 * (d.toordinal() - _EPOCH) + 10646) // 10631
    month = next(m for m in range(12, 0, -1) if to_gregorian(year, m, 1) <= d)
    return year, month, d.toordinal() - to_gregorian(year, month, 1).toordinal() + 1
