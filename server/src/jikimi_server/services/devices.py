"""What the site's edge devices report about themselves (heartbeat ``versions`` and ``extra``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Device


def _fresh_heartbeats(db: Session, site_id: str, now: datetime, fresh_s: float) -> list[dict[str, Any]]:
    return [
        d.last_heartbeat or {}
        for d in db.scalars(select(Device).where(Device.site_id == site_id, Device.status == "active"))
        if d.last_seen is not None and (now - d.last_seen).total_seconds() <= fresh_s
    ]


def edge_reports(db: Session, site_id: str, key: str, now: datetime, fresh_s: float = 300.0) -> set[str] | None:
    """``versions[key]`` from the heartbeats of the site's edges seen in the last ``fresh_s``
    seconds; ``None`` when no edge has reported recently."""
    beats = _fresh_heartbeats(db, site_id, now, fresh_s)
    if not beats:
        return None
    return {str((hb.get("versions") or {}).get(key)) for hb in beats}


def rush_ratio(db: Session, site_id: str, now: datetime, fresh_s: float = 300.0) -> float | None:
    """Highest bike-traffic multiple of the ordinary-day calibration any edge of the site reports."""
    ratios = [
        float(v)
        for hb in _fresh_heartbeats(db, site_id, now, fresh_s)
        for v in ((hb.get("extra") or {}).get("volume") or {}).values()
    ]
    return max(ratios) if ratios else None
