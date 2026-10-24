"""Is the F7 guarantee real? Two checks on the stored calibration sets, no new simulation.

1. Validity: calibrate on the first half of a set's runs, score the second half (other scenes):
   split-conformal p-values must satisfy P(p <= alpha) <= alpha (ties make them conservative).
2. Drift: the edge's KS monitor (score distribution) between two halves of ordinary days, and
   between ordinary days and the festival rush. Finding: it stays quiet in *both* cases, because
   the per-unit score distribution barely moves on a festival day; what moves is the volume of
   units per hour and the loitering tail. The calendar (F16), not the drift monitor, is what
   switches the baseline.

    uv run python -m eval.conformal_validity
"""

from __future__ import annotations

import json
from pathlib import Path

from jikimi_edge.calibration.conformal import SplitConformal
from jikimi_edge.calibration.drift import ks_2samp

ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "edge/config/calibration/society-gate-north"
ALPHAS = (0.01, 0.05, 0.1, 0.2)


def _scores(name: str) -> list[float]:
    return [float(s) for s in json.loads((CAL / name).read_text(encoding="utf-8"))["scores"]]


def validity(scores: list[float]) -> dict[str, float]:
    half = len(scores) // 2
    cal, test = SplitConformal(scores[:half]), scores[half:]
    p = [cal.p_value(s) for s in test]
    return {f"{a:g}": round(sum(x <= a for x in p) / len(p), 4) for a in ALPHAS}


def main() -> None:
    out: dict[str, object] = {}
    for kind in ("loitering", "snatch"):
        normal = _scores(f"{kind}.normal.json")
        festival_path = CAL / f"{kind}.chand_raat.json"
        festival = _scores(festival_path.name) if festival_path.exists() else []
        half = len(normal) // 2
        quiet = ks_2samp(normal[:half], normal[half:])
        entry: dict[str, object] = {
            "n_normal": len(normal),
            "P(p<=alpha), held-out ordinary days": validity(normal),
            "KS ordinary vs ordinary": {"p": round(quiet.p_value, 4), "drift": quiet.drift},
        }
        if festival:
            shift = ks_2samp(normal, festival)
            entry["P(p<=alpha), held-out festival (own set)"] = validity(festival)
            entry["KS ordinary vs festival"] = {"p": float(f"{shift.p_value:.3g}"), "drift": shift.drift}
        out[kind] = entry
    report = ROOT / "eval/reports/conformal_validity.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
