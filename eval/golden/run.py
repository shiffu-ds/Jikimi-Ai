"""Golden replay: scripted scenarios -> expected alerts (plan Section 15.1).

    uv run python -m eval.golden.run            # print a pass/fail table
    uv run pytest -m slow eval/tests            # same cases as tests

A case passes when every expected alert type appears inside its time window with at least the
given route, no forbidden type appears, and alert counts stay within limits. Hard negatives
are >= 40 % of cases (here 3 of 7 scenario types, 8 of 18 runs).
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jikimi_contracts import Route

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).with_name("expected_alerts.jsonl")
START = 1_793_000_000.0
RANK = {"LOG_ONLY": 0, "VERIFY": 1, "ALERT_NOW": 2}


@dataclass
class Result:
    case: str
    seed: int
    ok: bool
    reason: str
    alerts: list[dict[str, Any]]


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_case(case: dict[str, Any], seed: int) -> Result:
    from jikimi_edge.runner import replay
    from jikimi_edge.settings import load_settings

    settings = load_settings(ROOT / "edge/config/site.demo.yaml", repo_root=ROOT)
    start = START + 3600.0 * float(case.get("start_offset_h", 0.0))  # e.g. +9 h: 21:33 local
    res = replay(settings, case["camera"], case["case"], seed=seed, start_ts=start)
    shown = [a for a in res.alerts if a.route != Route.LOG_ONLY]
    alerts = [
        {
            "type": a.type.value,
            "route": a.route.value if a.route else None,
            "t_s": round(a.ts_end.timestamp() - start, 1),
            "check": a.features.get("check"),
            "pattern": a.features.get("pattern"),
            "on_foot": a.features.get("on_foot"),
            "severity": a.severity.value,
        }
        for a in shown
    ]
    for exp in case.get("expect", []):
        lo, hi = exp["t_s"]
        hits = [
            a
            for a in alerts
            if a["type"] == exp["type"]
            and lo <= a["t_s"] <= hi
            and RANK[a["route"]] >= RANK[exp.get("min_route", "VERIFY")]
        ]
        for k in ("check", "pattern", "on_foot"):
            if exp.get(k) is not None:
                hits = [a for a in hits if a[k] == exp[k]]
        if not hits:
            return Result(
                case["case"], seed, False, f"missing {exp['type']} >= {exp.get('min_route')} in {lo}-{hi}s", alerts
            )
    bad = [a for a in alerts if a["type"] in case.get("forbid", []) or a["pattern"] in case.get("forbid", [])]
    if bad:
        return Result(case["case"], seed, False, f"forbidden alert {bad[0]['type']} at {bad[0]['t_s']}s", alerts)
    if "max_alerts" in case and len(alerts) > case["max_alerts"]:
        return Result(case["case"], seed, False, f"{len(alerts)} alerts > max {case['max_alerts']}", alerts)
    now = [a for a in alerts if a["route"] == "ALERT_NOW"]
    if "max_alerts_now" in case and len(now) > case["max_alerts_now"]:
        return Result(case["case"], seed, False, f"{len(now)} ALERT_NOW > max {case['max_alerts_now']}", alerts)
    return Result(case["case"], seed, True, "ok", alerts)


def _run(job: tuple[dict[str, Any], int]) -> Result:
    logging.disable(logging.WARNING)
    return run_case(*job)


def main() -> int:
    import argparse
    from concurrent.futures import ProcessPoolExecutor

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", default="", help="comma-separated case names")
    args = ap.parse_args()
    logging.disable(logging.WARNING)
    only = {x for x in args.only.split(",") if x}
    jobs = [(c, s) for c in load_cases() if not only or c["case"] in only for s in c["seeds"]]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(_run, jobs))
    width = max(len(r.case) for r in results)
    for r in results:
        print(
            f"{'PASS' if r.ok else 'FAIL'}  {r.case:<{width}}  seed={r.seed}  {r.reason}  {[(a['type'], a['route'], a['t_s']) for a in r.alerts]}"
        )
    passed = sum(r.ok for r in results)
    print(f"\n{passed}/{len(results)} golden runs passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
