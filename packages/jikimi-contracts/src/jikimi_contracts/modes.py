"""Event-aware mode (F16, plan Section 8.16).

The "normal" of a market on Chand Raat is not the normal of an ordinary Tuesday, so every mode
has its own conformal calibration set. Hijri dates are estimates until an admin confirms them
after moon sighting; only confirmed windows reach the edge.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, Literal, get_args

from pydantic import AwareDatetime, BaseModel, Field, model_validator

EventMode = Literal["normal", "ramadan", "chand_raat", "eid", "muharram", "independence_day", "bazaar_day"]
MODES: tuple[str, ...] = get_args(EventMode)
MAX_WINDOW_DAYS = 40


class ModeWindowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    mode: EventMode
    starts: date
    ends: date
    """Inclusive, site-local dates."""

    @model_validator(mode="after")
    def _range(self) -> ModeWindowCreate:
        if self.ends < self.starts:
            raise ValueError("ends must not be before starts")
        if (self.ends - self.starts).days >= MAX_WINDOW_DAYS:
            raise ValueError(f"a mode window is at most {MAX_WINDOW_DAYS} days")
        if self.mode == "normal":
            raise ValueError("'normal' is the default, not a window")
        return self


class ModeWindow(ModeWindowCreate):
    id: int | None = None
    source: Literal["admin", "estimate"] = "admin"
    confirmed_by: str | None = None


class CalendarOut(BaseModel):
    site_id: str
    today: date
    current_mode: EventMode
    windows: list[ModeWindow]
    """Confirmed windows from 30 days ago on: these are what the edge uses."""
    estimates: list[ModeWindow]
    """Hijri estimates for the next 12 months that nobody has confirmed yet."""
    edge_synced: bool | None = None
    """``True`` once an edge of the site reports the current calendar; ``None`` without an edge."""
    rush_ratio: float | None = None
    """Bike traffic now as a multiple of the ordinary-day calibration (busiest camera). Around 2 or
    more on a "normal" day hints at an event worth confirming: the score drift monitor cannot see
    such a day, the volume can."""


class CalendarBundle(BaseModel):
    """Confirmed windows of one site, signed by the server; the edge pulls ``/v1/edge/calendar``."""

    site_id: str
    version: str
    windows: list[ModeWindow]
    key_id: str
    public_key: str
    signed_at: AwareDatetime
    signature: str

    def signing_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"signature"})


def mode_on(windows: Sequence[ModeWindowCreate], day: date, default: str = "normal") -> str:
    """Mode of a site-local day. The shortest covering window wins (Chand Raat inside Ramadan)."""
    covering = [w for w in windows if w.starts <= day <= w.ends]
    return min(covering, key=lambda w: (w.ends - w.starts).days).mode if covering else default
