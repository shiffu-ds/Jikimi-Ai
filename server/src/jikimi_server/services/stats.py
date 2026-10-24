"""Operational statistics for the dashboard (US10: weekly false-alarm rate and MTTA)."""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from jikimi_contracts.api import CountByKey, StatsOut
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Alert, AlertEvent, Camera, Review


def compute(db: Session, site_ids: list[str], site_id: str | None, days: int, now: datetime, tz: ZoneInfo) -> StatsOut:
    sites = [site_id] if site_id else site_ids
    since = now - timedelta(days=days)
    alerts = db.scalars(select(Alert).where(Alert.site_id.in_(sites), Alert.created_at >= since)).all()
    shown = [a for a in alerts if a.status != "logged_only"]
    today = now.astimezone(tz).date()
    ids = [a.id for a in alerts]
    reviews = db.scalars(select(Review).where(Review.alert_id.in_(ids))).all() if ids else []
    last_verdict = {r.alert_id: r.verdict for r in sorted(reviews, key=lambda r: r.at)}
    false_alarms = sum(1 for v in last_verdict.values() if v == "false")
    acks = (
        db.scalars(select(AlertEvent).where(AlertEvent.alert_id.in_(ids), AlertEvent.kind == "acked")).all()
        if ids
        else []
    )
    mtta = [float(e.payload["mtta_s"]) for e in acks if (e.payload or {}).get("mtta_s") is not None]
    cams = db.scalars(select(Camera).where(Camera.site_id.in_(sites))).all()
    by_day = Counter(a.created_at.astimezone(tz).date().isoformat() for a in shown)
    day_keys = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    return StatsOut(
        site_id=site_id,
        days=days,
        open_alerts=sum(1 for a in alerts if a.status in ("open", "escalated", "verifying")),
        alerts_today=sum(1 for a in shown if a.created_at.astimezone(tz).date() == today),
        alerts_total=len(shown),
        reviewed=len(last_verdict),
        false_alarms=false_alarms,
        false_alarm_rate=round(false_alarms / len(last_verdict), 3) if last_verdict else None,
        mtta_median_s=round(statistics.median(mtta), 1) if mtta else None,
        mtta_p95_s=round(sorted(mtta)[max(0, int(0.95 * len(mtta)) - 1)], 1) if mtta else None,
        sms_fallbacks=sum(1 for a in alerts if a.sms_sent),
        by_type=[CountByKey(key=k, count=v) for k, v in Counter(a.type for a in shown).most_common()],
        by_status=[CountByKey(key=k, count=v) for k, v in Counter(a.status for a in alerts).most_common()],
        by_day=[CountByKey(key=k, count=by_day.get(k, 0)) for k in day_keys],
        cameras_online=sum(1 for c in cams if c.status == "online"),
        cameras_total=len(cams),
    )
