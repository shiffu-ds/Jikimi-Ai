"""Does the Hawkes risk estimate point the guard to the right zones (F15)?

    uv run python -m eval.hotspot_check

A site with six zones on three cameras gets 90 days of incidents from a *known* process: hourly
base rates (lane and corner at night, shops in the evening) plus follow-ups (alpha 0.25, fading
over ~6 h, spreading to nearby zones). The model is fitted on days 0-60 and asked, every 4 hours
of days 60-90, which zones to watch. Compared: the true intensity (the best possible), the fitted
Hawkes model, hour-of-day history only (alpha 0) and the busiest zones overall. Scores: share of
next-window incidents in the top-2 zones, and in the zones a 30-minute patrol from the gate
reaches. Synthetic by design (the truth must be known); a quiet site and a busy market.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any

from jikimi_server.services.hotspots import (
    HOUR,
    Event,
    HawkesFit,
    base_rates,
    expected,
    fit_hawkes,
    patrol,
    zone_kernel,
)

GRAPH = [
    {"from": "cam-gate-01", "to": "cam-street-02"},
    {"from": "cam-street-02", "to": "cam-back-03"},
]
ZONES = [
    "cam-gate-01:gate",
    "cam-gate-01:parking",
    "cam-street-02:shops",
    "cam-street-02:corner",
    "cam-back-03:lane",
    "cam-back-03:wall",
]
PROFILE = {  # relative base rate by hour block
    "cam-gate-01:gate": lambda h: 1.0,
    "cam-gate-01:parking": lambda h: 0.4,
    "cam-street-02:shops": lambda h: 3.0 if 17 <= h < 22 else 0.6,
    "cam-street-02:corner": lambda h: 2.5 if h >= 21 or h < 3 else 0.5,
    "cam-back-03:lane": lambda h: 4.0 if h >= 22 or h < 4 else 0.3,
    "cam-back-03:wall": lambda h: 0.5,
}


def travel(a: str, b: str) -> float:
    ca, cb = a.split(":")[0], b.split(":")[0]
    if a == b:
        return 0.0
    if ca == cb:
        return 2.0
    near = {(g["from"], g["to"]) for g in GRAPH} | {(g["to"], g["from"]) for g in GRAPH}
    return 5.0 if (ca, cb) in near else 8.0


def simulate(per_day: float, days: float, alpha: float, decay_h: float, rng: random.Random) -> list[Event]:
    """Branching (cluster) form of the Hawkes process: immigrants + Poisson follow-ups."""
    kernel = zone_kernel(GRAPH)
    total_w = sum(PROFILE[z](h) for z in ZONES for h in range(24))
    events: list[Event] = []
    for d in range(int(days)):
        for h in range(24):
            for z in ZONES:
                lam = per_day * PROFILE[z](h) / total_w * 24.0 / 24.0  # events in this zone-hour
                for _ in range(_poisson(lam, rng)):
                    events.append(Event(d * 86400 + h * HOUR + rng.random() * HOUR, z))
    queue = list(events)
    while queue:
        parent = queue.pop()
        weights = [kernel(z, parent.zone) for z in ZONES]
        for _ in range(_poisson(alpha * sum(weights), rng)):
            z = rng.choices(ZONES, weights)[0]
            t = parent.t + rng.expovariate(1.0 / (decay_h * HOUR))
            if t < days * 86400:
                child = Event(t, z)
                events.append(child)
                queue.append(child)
    return sorted(events, key=lambda e: e.t)


def _poisson(lam: float, rng: random.Random) -> int:
    k, p, limit = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def run(per_day: float, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    alpha, decay_h = 0.25, 6.0  # follow-ups per incident <= 0.25 * 2.5 zones' weight: a stable process
    events = simulate(per_day, 90, alpha, decay_h, rng)
    kernel = zone_kernel(GRAPH)
    t_fit = 60 * 86400.0
    fit = fit_hawkes(events, ZONES, 0.0, t_fit, kernel)
    past = [e for e in events if e.t < t_fit]
    hist_only = HawkesFit(0.0, fit.beta, base_rates(past, ZONES, 60.0, 0.0), 0.0, len(past), 60.0)
    busiest = {z: sum(1 for e in events if e.zone == z and e.t < t_fit) for z in ZONES}
    total_w = sum(PROFILE[z](h) for z in ZONES for h in range(24))
    truth = HawkesFit(
        alpha,
        1 / (decay_h * HOUR),
        {z: [per_day * PROFILE[z](h) / total_w / HOUR for h in range(24)] for z in ZONES},
        0,
        0,
        0,
        0.0,
        kernel,
    )
    methods = {"true_intensity": truth, "hawkes_fit": fit, "hour_of_day_history": hist_only}
    top2 = dict.fromkeys([*methods, "busiest_zones"], 0)
    covered = dict.fromkeys([*methods, "busiest_zones"], 0)
    n_events = 0
    t = t_fit
    while t < 90 * 86400:
        actual = [e for e in events if t <= e.t < t + 4 * HOUR]
        n_events += len(actual)
        if actual:
            for name, model in methods.items():
                risk = {z: expected(model, events, z, t, 4.0, step_s=1800.0) for z in ZONES}
                best = sorted(ZONES, key=lambda z: -risk[z])[:2]
                route = {z for z, _ in patrol(risk, travel, "cam-gate-01:gate", 30.0)}
                top2[name] += sum(e.zone in best for e in actual)
                covered[name] += sum(e.zone in route for e in actual)
            best = sorted(ZONES, key=lambda z: -busiest[z])[:2]
            route = {z for z, _ in patrol({z: float(busiest[z]) for z in ZONES}, travel, "cam-gate-01:gate", 30.0)}
            top2["busiest_zones"] += sum(e.zone in best for e in actual)
            covered["busiest_zones"] += sum(e.zone in route for e in actual)
        t += 4 * HOUR
    return {
        "background_incidents_per_day": per_day,
        "observed_incidents_per_day": round(len(events) / 90, 2),
        "events_fit_period": sum(1 for e in events if e.t < t_fit),
        "events_test_period": n_events,
        "fitted": {
            "alpha": fit.alpha,
            "decay_hours": round(1 / fit.beta / HOUR, 1),
            "truth": {"alpha": alpha, "decay_hours": decay_h},
        },
        "share_in_top2_zones": {k: round(v / max(n_events, 1), 3) for k, v in top2.items()},
        "share_reached_by_30min_patrol": {k: round(v / max(n_events, 1), 3) for k, v in covered.items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", default="eval/reports/hotspot_check.json")
    args = ap.parse_args()
    report = {"quiet_site": run(0.7, 1), "busy_market": run(3.0, 2)}
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
