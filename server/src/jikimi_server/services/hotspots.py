"""Hotspots and a patrol route (F15, plan Section 8.15): a risk *estimate*, not a crime prediction.

A spatio-temporal Hawkes process on the site's incidents per zone:

    lambda(z, t) = mu_z(hour(t)) + sum_{t_i < t} alpha * beta * exp(-beta * (t - t_i)) * k(z, z_i)

``mu_z(h)`` is the zone's base rate in that hour of the day (events / days observed, smoothed
towards the site average); the second term says an incident makes more incidents nearby likely
for a while (k = 1 in the same zone, 0.5 in another zone of the same camera, 0.25 on a camera next
to it in the camera graph). ``alpha`` (how many follow-ups one incident brings) and ``beta``
(how fast that fades) are fitted by maximum likelihood on a grid - robust with the few events a
site has. Patrol: zones by expected events in the coming window, visited greedily by expected
events per minute of walking, within the guard's time budget.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from jikimi_contracts.api import Hotspots, HotspotZone, PatrolStop
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Alert, Camera, Site

HOUR = 3600.0
ALPHAS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7)
BETAS_H = (0.5, 1.0, 3.0, 6.0, 12.0, 24.0, 72.0)  # decay time (hours) = 1 / beta


@dataclass(frozen=True)
class Event:
    t: float  # epoch seconds
    zone: str  # "camera_id:zone_id"


@dataclass
class HawkesFit:
    alpha: float
    beta: float  # per second
    mu: dict[str, list[float]]  # per zone: 24 hourly base rates (events per second)
    loglik: float
    events: int
    days: float
    tz_offset_s: float = 0.0
    kernel: Callable[[str, str], float] = field(default=lambda a, b: 1.0 if a == b else 0.0)

    def hour(self, t: float) -> int:
        return int(((t + self.tz_offset_s) % 86400) // HOUR)


def zone_kernel(graph: list[dict[str, object]]) -> Callable[[str, str], float]:
    near = {(str(g["from"]), str(g["to"])) for g in graph} | {(str(g["to"]), str(g["from"])) for g in graph}

    def k(a: str, b: str) -> float:
        if a == b:
            return 1.0
        ca, cb = a.split(":", 1)[0], b.split(":", 1)[0]
        return 0.5 if ca == cb else 0.25 if (ca, cb) in near else 0.0

    return k


def base_rates(events: list[Event], zones: list[str], days: float, tz_offset_s: float) -> dict[str, list[float]]:
    """Hourly base rate per zone, shrunk towards the zone's daily average (few events per hour)."""
    days = max(days, 1.0)
    out: dict[str, list[float]] = {}
    for z in zones:
        counts = [0] * 24
        for e in events:
            if e.zone == z:
                counts[int(((e.t + tz_offset_s) % 86400) // HOUR)] += 1
        daily = (sum(counts) + 0.5) / 24.0
        out[z] = [(c + daily) / (days + 1.0) / HOUR for c in counts]  # 1 pseudo-day at the average
    return out


def _loglik(events: list[Event], zones: list[str], fit: HawkesFit, t0: float, t1: float) -> float:
    if fit.alpha == 0.0:
        excite = [0.0] * len(events)
    else:
        excite = []
        for i, e in enumerate(events):
            s = 0.0
            for j in range(i - 1, -1, -1):
                dt = e.t - events[j].t
                if dt * fit.beta > 30:  # the rest has faded
                    break
                k = fit.kernel(e.zone, events[j].zone)
                if k:
                    s += fit.alpha * fit.beta * math.exp(-fit.beta * dt) * k
            excite.append(s)
    ll = sum(math.log(fit.mu[e.zone][fit.hour(e.t)] + x) for e, x in zip(events, excite, strict=True))
    base = sum(sum(r) * HOUR for r in fit.mu.values()) * (t1 - t0) / 86400.0
    triggered = fit.alpha * sum(
        (1 - math.exp(-fit.beta * (t1 - e.t))) * sum(fit.kernel(z, e.zone) for z in zones) for e in events
    )
    return ll - base - triggered


def fit_hawkes(
    events: list[Event],
    zones: list[str],
    t0: float,
    t1: float,
    kernel: Callable[[str, str], float],
    tz_offset_s: float = 0.0,
) -> HawkesFit:
    events = sorted((e for e in events if t0 <= e.t <= t1 and e.zone in zones), key=lambda e: e.t)
    days = (t1 - t0) / 86400.0
    mu = base_rates(events, zones, days, tz_offset_s)
    reach = [sum(kernel(z, src) for z in zones) for src in zones]  # follow-ups spread over these zones
    best: HawkesFit | None = None
    for a in ALPHAS:
        if a * max(reach, default=1.0) >= 0.95:  # one incident must bring < 1 follow-up (stable process)
            continue
        share = a * sum(reach) / max(len(reach), 1)  # part of the events that are follow-ups
        for bh in BETAS_H if a else BETAS_H[:1]:
            f = HawkesFit(
                a,
                1.0 / (bh * HOUR),
                {z: [r * (1 - share) for r in v] for z, v in mu.items()},
                0.0,
                len(events),
                days,
                tz_offset_s,
                kernel,
            )
            f.loglik = _loglik(events, zones, f, t0, t1)
            if best is None or f.loglik > best.loglik:
                best = f
    assert best is not None
    return best


def expected(fit: HawkesFit, events: list[Event], zone: str, t0: float, hours: float, step_s: float = 600.0) -> float:
    """Expected events in ``zone`` during ``[t0, t0 + hours]`` (no new events assumed inside)."""
    total, t = 0.0, t0
    past = [e for e in events if e.t < t0]
    while t < t0 + hours * HOUR:
        lam = fit.mu[zone][fit.hour(t)]
        for e in past:
            k = fit.kernel(zone, e.zone)
            if k:
                lam += fit.alpha * fit.beta * math.exp(-fit.beta * (t - e.t)) * k
        total += lam * step_s
        t += step_s
    return total


def patrol(
    risk: dict[str, float],
    travel_min: Callable[[str, str], float],
    start: str,
    budget_min: float,
    stay_min: float = 3.0,
) -> list[tuple[str, float]]:
    """Greedy route: next the zone with the most expected events per minute of getting there."""
    route: list[tuple[str, float]] = []
    here, clock, left = start, 0.0, {z for z, r in risk.items() if r > 0}
    while left:
        z = max(left, key=lambda c: risk[c] / (travel_min(here, c) + stay_min))
        arrive = clock + travel_min(here, z)
        if arrive + stay_min > budget_min:
            left.discard(z)
            continue
        route.append((z, round(arrive, 1)))
        here, clock = z, arrive + stay_min
        left.discard(z)
    return route


INCIDENT_TYPES = ("snatch", "loitering", "sos", "rule", "person_in_danger", "vehicle_theft")
LOOKBACK_DAYS = 90


def site_hotspots(db: Session, site_id: str, now: datetime, hours: float = 4.0, budget_min: float = 30.0) -> Hotspots:
    site = db.get(Site, site_id)
    assert site is not None
    cams = db.scalars(select(Camera).where(Camera.site_id == site_id).order_by(Camera.id)).all()
    names: dict[str, tuple[str, str | None, str, str | None]] = {}
    for c in cams:
        for z in c.zones or []:
            names[f"{c.id}:{z['id']}"] = (z.get("name") or z["id"], z.get("name_ur"), c.id, z["id"])
        names[f"{c.id}:*"] = (c.name, c.name_ur, c.id, None)  # incidents outside any zone
    since = now - timedelta(days=LOOKBACK_DAYS)
    rows = db.scalars(
        select(Alert).where(
            Alert.site_id == site_id,
            Alert.created_at >= since,
            Alert.type.in_(INCIDENT_TYPES),
            Alert.status.not_in(("false_alarm", "logged_only")),
        )
    ).all()
    events = [
        Event(a.ts_end.timestamp(), key)
        for a in rows
        if a.camera_id and (key := f"{a.camera_id}:{a.zone_id}" if a.zone_id else f"{a.camera_id}:*") in names
    ]
    zones = list(names)
    tz = ZoneInfo(site.timezone or "Asia/Karachi")
    offset = (now.astimezone(tz).utcoffset() or timedelta()).total_seconds()
    graph = (site.config or {}).get("camera_graph") or []
    kernel = zone_kernel(graph)
    first = min((e.t for e in events), default=now.timestamp())
    t0 = max(since.timestamp(), first - 86400.0)
    fit = fit_hawkes(events, zones, t0, now.timestamp(), kernel, tz_offset_s=offset)
    risk = {z: expected(fit, events, z, now.timestamp(), hours, step_s=1800.0) for z in zones}
    near = {(str(g["from"]), str(g["to"])) for g in graph} | {(str(g["to"]), str(g["from"])) for g in graph}

    def walk(a: str, b: str) -> float:
        ca, cb = a.split(":", 1)[0], b.split(":", 1)[0]
        return 0.0 if a == b else 2.0 if ca == cb else 5.0 if (ca, cb) in near else 8.0

    start = zones[0] if zones else ""
    route = patrol({z: r for z, r in risk.items() if not z.endswith(":*")}, walk, start, budget_min) if zones else []
    counts = {z: sum(1 for e in events if e.zone == z) for z in zones}
    ranked = sorted(zones, key=lambda z: -risk[z])
    return Hotspots(
        site_id=site_id,
        window_hours=hours,
        zones=[
            HotspotZone(
                zone_key=z,
                camera_id=names[z][2],
                zone_id=names[z][3],
                name=names[z][0],
                name_ur=names[z][1],
                expected_events=round(risk[z], 4),
                events_90d=counts[z],
            )
            for z in ranked
        ],
        patrol=[PatrolStop(zone_key=z, name=names[z][0], name_ur=names[z][1], arrive_min=m) for z, m in route],
        alpha=fit.alpha,
        decay_hours=round(1.0 / fit.beta / HOUR, 1),
        events_used=len(events),
        days=round((now.timestamp() - t0) / 86400.0, 1),
    )
