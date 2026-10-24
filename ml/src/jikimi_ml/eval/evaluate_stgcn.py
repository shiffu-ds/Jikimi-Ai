"""Evaluate an exported ST-GCN (ONNX) on the held-out episodes of a PakSnatch(-sim) file.

    uv run python -m jikimi_ml.eval.evaluate_stgcn --model models/stgcn_paksnatch_sim.onnx \\
        --data data/ml/paksnatch_sim.npz --update-report

Uses the training script's group-disjoint split (test = 2), so the numbers are on episodes the
model never saw. The AUC interval resamples whole episodes (``cluster_bootstrap_ci``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from ..data.paksnatch import group_split, load_npz
from .metrics import expected_calibration_error, precision_at_recall, roc_auc
from .stats import cluster_bootstrap_ci


def evaluate(model: str | Path, data: str | Path, part: int = 2, batch: int = 256) -> dict[str, Any]:
    import onnxruntime as ort

    d = load_npz(data)
    mask = group_split(d["group"]) == part
    x, y, g = d["x"][mask].astype(np.float32), d["y"][mask], d["group"][mask]
    sess = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    logits = np.concatenate(
        [sess.run(None, {"poses": x[i : i + batch]})[0].reshape(-1) for i in range(0, len(x), batch)]
    )
    p = 1.0 / (1.0 + np.exp(-logits))
    auc = cluster_bootstrap_ci(y, p, g, roc_auc)
    return {
        "test_auc": round(auc.estimate, 4),
        "test_auc_ci95": [round(auc.low, 4), round(auc.high, 4)],
        "test_precision_at_recall_0.8": round(precision_at_recall(y, p, 0.8), 4),
        "test_ece": round(expected_calibration_error(y, p), 4),
        "test_windows": int(mask.sum()),
        "test_positive_windows": int(y.sum()),
        "test_episodes": len(np.unique(g)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--update-report", action="store_true", help="merge into <model>.json")
    args = ap.parse_args()
    res = evaluate(args.model, args.data)
    if args.update_report:
        path = Path(args.model).with_suffix(".json")
        report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        path.write_text(json.dumps({**report, **res}, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
