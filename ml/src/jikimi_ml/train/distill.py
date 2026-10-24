"""VLM-to-edge distillation, one round (F6, plan Section 8.5).

    uv run python -m jikimi_ml.train.distill --episodes 60 --budget 48

1. New, unlabeled episodes from the simulator (their truth is kept aside to score the teacher).
2. The current student (two-person ST-GCN) scores every window.
3. Sampling for the teacher: 70 % of the budget from uncertain windows (student 0.2-0.8), 30 % at
   random.
4. Teacher: the local VLM looks at the frame at each sampled window's end, cropped around the bike
   and the pedestrian, and picks "grabbing" or "moving normally" (the server's A/B scoring, both
   orders); confidence below 2/3 is discarded (the plan's self-consistency rule).
5. "Human spot-check" of 10 %: here the simulator's truth (an agreement report).
6. Student fine-tuned on its own training data + the teacher labels (label smoothing 0.1).
7. Gate on the fixed PakSnatch-sim test split: AUC >= current and ECE <= current, otherwise the
   round is rejected and the current student stays (shadow mode would come next).

A control round with the simulator's *true* labels in place of the teacher shows what the loop
does with a perfect teacher, so a rejected round can be blamed on the teacher or on the loop.
Report: ``eval/reports/distill_round.json``.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..data.paksnatch import batches, group_split, load_npz
from ..data.synthetic import Episode, episode
from ..eval.metrics import expected_calibration_error, roc_auc

KINDS = ["snatch"] * 4 + ["delivery"] * 2 + ["directions"] * 2 + ["normal"] * 2


def render_crop(ep: Episode, t: float, bike_id: int, ped_id: int) -> np.ndarray:
    """The frame at ``t``, cropped around the bike and the pedestrian (what a keyframe crop shows)."""
    from datetime import datetime

    from jikimi_edge.sim.render import H, W, render

    st = ep.world.state(t, 1_700_000_000.0 + t)
    img = render(st, "street", "sim", datetime(2026, 1, 1, 21, 0), seed=7, rng=np.random.default_rng(0))
    boxes = [tr.bbox for tr in st.tracks if tr.track_id in (bike_id, ped_id)]
    if not boxes:
        return img
    x1, y1 = min(b[0] for b in boxes) * W, min(b[1] for b in boxes) * H
    x2, y2 = max(b[2] for b in boxes) * W, max(b[3] for b in boxes) * H
    cx, cy, half = (x1 + x2) / 2, (y1 + y2) / 2, max(x2 - x1, y2 - y1, 80) * 0.8
    a, b = max(int(cx - half), 0), max(int(cy - half), 0)
    return img[b : min(int(cy + half), H), a : min(int(cx + half), W)]


def finetune(model: Any, x: np.ndarray, y: np.ndarray, xv: np.ndarray, yv: np.ndarray, epochs: int, seed: int) -> Any:
    import torch

    from ..models.stgcn import FocalLoss

    rng = np.random.default_rng(seed)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    loss_fn = FocalLoss(gamma=2.0)
    best, best_state = -1.0, {k: v.clone() for k, v in model.state_dict().items()}
    for _ in range(epochs):
        model.train()
        for xb, yb in batches(x, y, 64, rng, train=True):
            opt.zero_grad()
            loss = loss_fn(model(torch.from_numpy(xb)), torch.from_numpy(yb))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
        auc = roc_auc(yv, predict(model, xv))
        if auc > best:
            best, best_state = auc, {k: v.clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    return model


def predict(model: Any, x: np.ndarray) -> np.ndarray:
    import torch

    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(x), 256):
            out.append(torch.sigmoid(model(torch.from_numpy(x[i : i + 256].astype(np.float32)))).numpy())
    return np.concatenate(out) if out else np.empty(0)


def main() -> None:
    import torch

    from ..models.stgcn import TwoPersonSTGCN

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="data/ml/paksnatch_sim.npz")
    ap.add_argument("--student", default="models/stgcn_paksnatch_sim.pt")
    ap.add_argument("--vlm", default="models/smolvlm-256m-instruct")
    ap.add_argument("--episodes", type=int, default=60)
    ap.add_argument("--budget", type=int, default=48, help="teacher (VLM) calls this round")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--report", default="eval/reports/distill_round.json")
    args = ap.parse_args()
    torch.manual_seed(args.seed)
    rnd = random.Random(args.seed)

    d = load_npz(args.data)
    split = group_split(d["group"])
    x, y = d["x"], d["y"]
    tr, va, te = split == 0, split == 1, split == 2
    student = TwoPersonSTGCN()
    student.load_state_dict(torch.load(args.student, map_location="cpu"))
    p_te = predict(student, x[te])
    before = {"auc": round(roc_auc(y[te], p_te), 4), "ece": round(expected_calibration_error(y[te], p_te), 4)}

    # 1-2: unlabeled pool, scored by the student (seeds far from the training data's)
    eps = [episode(rnd.choice(KINDS), 900_000 + args.seed * 1000 + i) for i in range(args.episodes)]
    pool = [(e, k) for e in eps for k in range(len(e.windows))]
    xs = np.stack([e.windows[k] for e, k in pool]).astype(np.float32)
    truth = np.asarray([e.labels[k] for e, k in pool])
    p_pool = predict(student, xs)
    # 3: 70 % uncertain + 30 % random
    unc = [i for i, p in enumerate(p_pool) if 0.2 <= p <= 0.8]
    rest = [i for i in range(len(pool)) if i not in set(unc)]
    n_unc = min(len(unc), round(0.7 * args.budget))
    picked = rnd.sample(unc, n_unc) + rnd.sample(rest, min(len(rest), args.budget - n_unc))

    # 4: teacher labels
    from jikimi_server.services.vlm import VlmVerifier

    vlm = VlmVerifier(Path(args.vlm))
    if not vlm.available:
        raise SystemExit("no VLM: `uv sync --extra vlm` and models/README.md")
    labelled: list[tuple[int, int, float]] = []
    t0 = time.perf_counter()
    for i in picked:
        e, k = pool[i]
        t, bike, ped = e.meta[k]
        p = vlm.score("snatch", render_crop(e, t, bike, ped))
        if max(p, 1.0 - p) >= 2 / 3:  # agreement below 2/3: discarded
            labelled.append((i, int(p >= 0.5), p))
    vlm_s = time.perf_counter() - t0
    kept = [i for i, _, _ in labelled]
    teacher_acc = float(np.mean([lab == truth[i] for i, lab, _ in labelled])) if labelled else None
    spot = rnd.sample(labelled, max(1, len(labelled) // 10)) if labelled else []

    # 6-7: fine-tune with teacher labels, and the control with true labels; gate both
    def round_with(idx: list[int], labels: np.ndarray) -> dict[str, Any]:
        model = TwoPersonSTGCN()
        model.load_state_dict(torch.load(args.student, map_location="cpu"))
        xn = np.concatenate([x[tr], xs[idx]])
        yn = np.concatenate([y[tr].astype(np.float32), labels.astype(np.float32) * 0.9 + 0.05])
        model = finetune(model, xn, yn, x[va], y[va], args.epochs, args.seed)
        p = predict(model, x[te])
        after = {"auc": round(roc_auc(y[te], p), 4), "ece": round(expected_calibration_error(y[te], p), 4)}
        passed = after["auc"] >= before["auc"] and after["ece"] <= before["ece"]
        return {
            "labels": len(idx),
            "test": after,
            "gate": "promote (to shadow mode)" if passed else "reject: keep the current student",
        }

    teacher_labels = np.asarray([lab for _, lab, _ in labelled])
    report = {
        "pool": {"episodes": len(eps), "windows": len(pool), "positives": int(truth.sum()), "uncertain": len(unc)},
        "teacher": {
            "model": vlm.name,
            "calls": len(picked),
            "kept": len(labelled),
            "discarded_unclear": len(picked) - len(labelled),
            "accuracy_vs_truth": None if teacher_acc is None else round(teacher_acc, 3),
            "positives_called": int(teacher_labels.sum()) if len(labelled) else 0,
            "true_positives_among_sampled": int(truth[picked].sum()),
            "spot_check_10pct_agreement": round(float(np.mean([lab == truth[i] for i, lab, _ in spot])), 3)
            if spot
            else None,
            "seconds": round(vlm_s, 1),
        },
        "student_before": before,
        "round_with_teacher_labels": round_with(kept, teacher_labels)
        if kept
        else "skipped: no confident teacher label",
        # the same windows with the simulator's truth: what this loop does with a perfect teacher
        "control_with_true_labels": round_with(picked, truth[picked]),
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
