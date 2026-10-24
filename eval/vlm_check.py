"""Is the local VLM a useful verifier (F5)? Measured on labelled frames before it may gate alerts.

    uv run python -m eval.vlm_check                   # both prompt styles, simulator + real clip
    uv run python -m eval.vlm_check --styles choice   # one style

Samples (rendered by the simulator, ground truth known):
* snatch: frames at the closest bike-pedestrian approach of scripted snatches (day and night)
  against the same moment of hard negatives (delivery hand-over, asking directions) and normal
  traffic; frames of the real junction clip (no incident) are extra negatives.
* tamper: frames while the camera is covered against normal frames.

Each style asks one question per frame: ``yesno`` ("Is ...? Answer yes or no", score P(yes)) or
``choice`` (two descriptions A / B, score P(A), asked in both orders to cancel order bias). The
report gives AUC, accuracy at 0.5 and the share of negatives a gate would drop while keeping
every positive. Small and synthetic: a go / no-go for gate mode, not a field accuracy.
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = {
    "snatch": {
        "yesno": "Is a person on a motorcycle grabbing a phone or a bag from a person standing or walking?",
        "choice": (
            "a person on a motorcycle is grabbing a phone or a bag from a pedestrian",
            "people and vehicles are moving normally and nobody is grabbing anything",
        ),
    },
    "tamper": {
        "yesno": "Is the camera view blocked, covered, very blurred or turned towards a wall or the sky?",
        "choice": (
            "the camera is covered, blocked or so blurred that the scene cannot be seen",
            "a clear, normal view of a street or a building",
        ),
    },
}


def _closest_frames(scenario: str, seed: int, camera: str, k: int = 2) -> list[np.ndarray]:
    """Frames where a two-wheeler with a rider is nearest to a pedestrian (the interaction)."""
    from jikimi_edge.sim.source import SimSource
    from jikimi_edge.tracking.riders import associate_riders

    src = SimSource(camera, scenario, fps=5.0, realtime=False, loop=False, start_ts=0.0, seed=seed)
    scored: list[tuple[float, np.ndarray]] = []
    while (f := src.read()) is not None:
        if f.image is None or not f.tracks:
            continue
        riders = associate_riders(f.tracks)
        rider_ids = {r for v in riders.values() for r in v}
        bikes = [t for t in f.tracks if t.cls == "motorcycle" and riders.get(t.track_id)]
        peds = [t for t in f.tracks if t.cls == "person" and t.track_id not in rider_ids]
        if not bikes or not peds:
            continue
        d = min(
            abs((b.bbox[0] + b.bbox[2]) / 2 - (p.bbox[0] + p.bbox[2]) / 2) + abs(b.bbox[3] - p.bbox[3])
            for b in bikes
            for p in peds
        )
        scored.append((d, f.image))
    scored.sort(key=lambda x: x[0])
    picked: list[np.ndarray] = []
    for _, img in scored:
        if len(picked) == k:
            break
        if all(float(np.abs(img.astype(np.int16) - p).mean()) > 1.0 for p in picked):  # not the same frame twice
            picked.append(img)
    return picked


def _frames_at(scenario: str, seed: int, camera: str, times: list[float]) -> list[np.ndarray]:
    from jikimi_edge.sim.source import SimSource

    src = SimSource(camera, scenario, fps=5.0, realtime=False, loop=False, start_ts=0.0, seed=seed)
    out, want = [], sorted(times)
    while want and (f := src.read()) is not None:
        if f.ts >= want[0] and f.image is not None:
            out.append(f.image)
            want.pop(0)
    return out


def samples(quick: bool) -> dict[str, list[tuple[int, np.ndarray, str]]]:
    n = 3 if quick else 6
    snatch: list[tuple[int, np.ndarray, str]] = []
    for seed in range(1, n + 1):
        cam = "cam-street-02" if seed % 2 else "cam-gate-01"
        snatch += [(1, img, f"snatch_basic/{seed}") for img in _closest_frames("snatch_basic", seed, cam)]
        snatch += [(0, img, f"delivery_drop/{seed}") for img in _closest_frames("delivery_drop", seed, cam)]
        snatch += [(0, img, f"asking_directions/{seed}") for img in _closest_frames("asking_directions", seed, cam)]
    for seed in range(1, n // 2 + 1):
        snatch += [(1, img, f"snatch_night/{seed}") for img in _closest_frames("snatch_night", seed, "cam-street-02")]
        snatch += [(0, img, f"normal_traffic/{seed}") for img in _closest_frames("normal_traffic", seed, "cam-gate-01")]
    clip = ROOT / "data/footage/pexels_36306512_intersection_1080p60.mp4"
    if clip.exists():
        cap = cv2.VideoCapture(str(clip))
        for pos in range(100, 1100, 1000 // n):
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ok, img = cap.read()
            if ok:
                snatch.append((0, img, f"real_clip/{pos}"))
        cap.release()
    tamper: list[tuple[int, np.ndarray, str]] = []
    for seed in range(1, n // 2 + 1):
        tamper += [
            (1, img, f"camera_cover/{seed}") for img in _frames_at("camera_cover", seed, "cam-gate-01", [50.0, 65.0])
        ]
        tamper += [
            (0, img, f"camera_cover/{seed}/before")
            for img in _frames_at("camera_cover", seed, "cam-gate-01", [15.0, 30.0])
        ]
    return {"snatch": snatch, "tamper": tamper}


def auc(y: list[int], s: list[float]) -> float | None:
    pos = [v for t, v in zip(y, s, strict=True) if t]
    neg = [v for t, v in zip(y, s, strict=True) if not t]
    if not pos or not neg:
        return None
    wins = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg)
    return round(wins / (len(pos) * len(neg)), 3)


def score(verifier: Any, img: np.ndarray, kind: str, style: str) -> float:
    if style == "yesno":
        return float(verifier.ask([img], PROMPTS[kind]["yesno"]).p_yes)
    return float(verifier.score(kind, img))  # the server's own scoring: A/B, both orders


def threshold(y: list[int], s: list[float]) -> tuple[float, float]:
    """``(threshold, spread)``: the cut with the best balanced accuracy, and mean(pos) - mean(neg)."""
    pos = [v for t, v in zip(y, s, strict=True) if t]
    neg = [v for t, v in zip(y, s, strict=True) if not t]
    cuts = sorted(set(s))
    best, best_bal = 0.5, -1.0
    for lo, hi in itertools.pairwise(cuts):
        c = (lo + hi) / 2
        bal = (np.mean([v >= c for v in pos]) + np.mean([v < c for v in neg])) / 2
        if bal > best_bal:
            best, best_bal = c, bal
    return round(float(best), 4), round(float(np.mean(pos) - np.mean(neg)), 4)


def main() -> None:
    from jikimi_server.services.vlm import VlmVerifier

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--styles", default="yesno,choice")
    ap.add_argument("--quick", action="store_true", help="fewer samples (smoke test)")
    ap.add_argument("--model", default=str(ROOT / "models/smolvlm-256m-instruct"))
    ap.add_argument("--report", default="eval/reports/vlm_check.json")
    args = ap.parse_args()

    verifier = VlmVerifier(Path(args.model))
    if not verifier.available:
        raise SystemExit("no VLM: `uv sync --extra vlm` and models/README.md")
    data = samples(args.quick)
    report: dict[str, Any] = {"model": verifier.name, "samples": {k: len(v) for k, v in data.items()}}
    calib: dict[str, dict[str, float]] = {}
    for style in args.styles.split(","):
        for kind, rows in data.items():
            y, s, ms, per = [], [], [], {}
            for label, img, src in rows:
                t0 = time.perf_counter()
                v = score(verifier, img, kind, style)
                ms.append((time.perf_counter() - t0) * 1000)
                y.append(label)
                s.append(v)
                per.setdefault(src.split("/")[0], []).append(round(v, 3))
            pos_min = min((v for t, v in zip(y, s, strict=True) if t), default=1.0)
            negs = [v for t, v in zip(y, s, strict=True) if not t]
            report[f"{kind}/{style}"] = {
                "auc": auc(y, s),
                "accuracy_at_0.5": round(
                    statistics.fmean(int((v >= 0.5) == bool(t)) for t, v in zip(y, s, strict=True)), 3
                ),
                "negatives_dropped_keeping_all_positives": round(sum(v < pos_min for v in negs) / max(len(negs), 1), 3),
                "ms_per_frame": round(statistics.fmean(ms)),
                "mean_score_by_source": {k: round(statistics.fmean(v), 3) for k, v in per.items()},
            }
            if style == "choice":  # what the server uses: threshold + spread for verifier.json
                thr, spread = threshold(y, s)
                calib[kind] = {
                    "auc": report[f"{kind}/{style}"]["auc"],
                    "threshold": thr,
                    "spread": spread,
                    "n_pos": sum(y),
                    "n_neg": len(y) - sum(y),
                }
            print(f"{kind}/{style}", json.dumps(report[f"{kind}/{style}"]), flush=True)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if calib and not args.quick:  # the server's verifier speaks only for types with AUC >= 0.8
        (Path(args.model) / "verifier.json").write_text(
            json.dumps({"source": "eval.vlm_check (simulator frames, in-sample threshold)", "types": calib}, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
