"""Shadow comparison of the two snatch scorers inside the real edge plugin (plan 14.3: baseline
vs model on the same units).

Every scene is replayed twice, once with the B1 heuristic and once with the ST-GCN, and every
bike-pedestrian pair gets a score from each (the simulator is deterministic, so pairs match).
Label: in snatch scenes the pair behind the alert inside the scripted grab window is the snatch
(the golden suite checks that window); every other pair, in every scene, is a negative.

    uv run python -m eval.shadow_snatch --model models/stgcn_paksnatch_sim.onnx

Simulator scenes only, and the ST-GCN was pre-trained on the same simulator family: this checks
that the model works inside the edge pipeline, not how it does on real streets.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
START = 1_793_000_000.0
SNATCH_WINDOW = (29.0, 36.0)
SCENES = (
    [("snatch_basic", s) for s in range(1, 9)]
    + [("snatch_night", s) for s in range(1, 9)]
    + [("delivery_drop", s) for s in range(1, 5)]
    + [("asking_directions", s) for s in range(1, 5)]
    + [("normal_traffic", s) for s in (7, 8)]
)


def _scores(scene: str, seed: int, model: str | None) -> tuple[dict[str, float], list[str]]:
    from jikimi_edge.analytics.snatch.plugin import SnatchPlugin
    from jikimi_edge.runner import build_pipeline, replay
    from jikimi_edge.settings import load_settings

    with tempfile.TemporaryDirectory() as tmp:
        base = load_settings(ROOT / "edge/config/site.demo.yaml", repo_root=ROOT)
        raw = json.loads(json.dumps(base.raw))
        raw.setdefault("plugins", {}).setdefault("snatch", {})["model"] = model or "-"
        settings = dataclasses.replace(base, raw=raw, data_dir=Path(tmp))
        pipeline, _, _ = build_pipeline(settings, with_outbox=False, record_clips=False)
        plugin = next(p for p in pipeline.cameras["cam-street-02"].plugins if isinstance(p, SnatchPlugin))
        assert (model is None) == (plugin.version == "heuristic-v1"), plugin.version
        plugin.score_log = {}
        res = replay(settings, "cam-street-02", scene, seed=seed, start_ts=START, pipeline=pipeline)
    hits = [
        str(a.features["dedupe_key"])
        for a in res.alerts
        if a.type.value == "snatch" and SNATCH_WINDOW[0] <= a.ts_end.timestamp() - START <= SNATCH_WINDOW[1]
    ]
    return dict(plugin.score_log), hits


def _scene(job: tuple[str, int, str]) -> dict[str, Any]:
    scene, seed, model = job
    heur, hits = _scores(scene, seed, None)
    stgcn, _ = _scores(scene, seed, model)
    positive = hits[0] if scene.startswith("snatch") and hits else None
    return {"scene": scene, "seed": seed, "positive": positive, "heuristic": heur, "stgcn": stgcn}


def main() -> None:
    import numpy as np
    from jikimi_ml.eval.metrics import roc_auc
    from jikimi_ml.eval.stats import cluster_bootstrap_ci

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="models/stgcn_paksnatch_sim.onnx")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--report", default="eval/reports/shadow_snatch.json")
    args = ap.parse_args()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        scenes = list(pool.map(_scene, [(s, seed, args.model) for s, seed in SCENES]))
    rows = []  # one per pair scored by both: (group, label, heuristic, stgcn, hard negative?)
    for sc in scenes:
        for key in sorted(set(sc["heuristic"]) & set(sc["stgcn"])):
            hard = sc["scene"] in ("delivery_drop", "asking_directions")
            rows.append(
                (
                    f"{sc['scene']}-{sc['seed']}",
                    int(key == sc["positive"]),
                    sc["heuristic"][key],
                    sc["stgcn"][key],
                    hard,
                )
            )
    groups = np.array([r[0] for r in rows])
    y = np.array([r[1] for r in rows])
    out: dict[str, Any] = {
        "scenes": len(scenes),
        "snatch_scenes_with_a_positive": sum(sc["positive"] is not None for sc in scenes),
        "pairs": len(rows),
        "positives": int(y.sum()),
    }
    for i, name in ((2, "heuristic"), (3, "stgcn")):
        s = np.array([r[i] for r in rows])
        auc = cluster_bootstrap_ci(y, s, groups, roc_auc)
        hard = [r[i] for r in rows if r[4]]
        out[name] = {
            "auc": round(auc.estimate, 4),
            "auc_ci95": [round(auc.low, 4), round(auc.high, 4)],
            "min_positive": round(float(s[y == 1].min()), 3),
            "max_negative": round(float(s[y == 0].max()), 3),
            "max_hard_negative": round(max(hard), 3) if hard else None,
        }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
