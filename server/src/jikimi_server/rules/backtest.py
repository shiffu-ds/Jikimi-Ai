"""Backtest a rule on the last days of indexed tracks (plan 8.11: text -> rule -> backtest -> approval).

Track summaries carry camera, zones, object, start and end, but not the time spent inside one
zone, so dwell is the track's time on camera. That is an upper bound: the backtest errs towards
"this rule would be noisy", which is the safe side before an admin approves it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from jikimi_contracts.rules_dsl import Rule, RuleBacktest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ClipIndex

COUNT_REFRACTORY_S = 300.0  # the edge fires a count rule at most once per 5 min


def _object_ok(row: ClipIndex, rule: Rule) -> bool:
    want = rule.when.object
    return any(
        o.get("type") == want.type and (want.color is None or o.get("color") == want.color) for o in row.objects or []
    )


def backtest(db: Session, rule: Rule, tz: ZoneInfo, now: datetime, days: int = 7) -> RuleBacktest:
    w = rule.when
    rows = db.scalars(
        select(ClipIndex).where(
            ClipIndex.site_id == rule.site_id,
            ClipIndex.kind == "track",
            ClipIndex.camera_id.in_(w.camera_ids),
            ClipIndex.ts_end >= now - timedelta(days=days),
        )
    ).all()
    dwell = float(w.condition.dwell_seconds_gt or 0)
    tracks = [
        r
        for r in rows
        if _object_ok(r, rule)
        and (w.zone is None or w.zone in (r.zones or []))
        and (r.ts_end - r.ts_start).total_seconds() > dwell
    ]

    def active(t: datetime) -> bool:
        return w.schedule is None or w.schedule.contains(t.astimezone(tz))

    fires: list[datetime] = []
    if w.condition.count_gt is None:
        fires = [t for r in tracks if active(t := r.ts_start + timedelta(seconds=dwell))]
    else:
        # a track counts from the moment it has stayed `dwell` seconds until it leaves;
        # at the same instant, leaving is processed before entering
        events = sorted([(r.ts_start + timedelta(seconds=dwell), 1) for r in tracks] + [(r.ts_end, -1) for r in tracks])
        inside, last = 0, None
        for t, step in events:
            inside += step
            if (
                step > 0
                and inside > w.condition.count_gt
                and active(t)
                and (last is None or (t - last).total_seconds() > COUNT_REFRACTORY_S)
            ):
                fires.append(t)
                last = t
    fires.sort()
    return RuleBacktest(
        days=days,
        tracks_checked=len(rows),
        matches=len(fires),
        per_day=round(len(fires) / days, 2),
        last_matches=fires[::-1][:5],
    )
