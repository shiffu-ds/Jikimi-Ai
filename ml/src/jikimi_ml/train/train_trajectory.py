"""Train the cross-camera trajectory transformer (F2 Tier 2, plan Section 8.3) on synthetic routes.

    uv run python -m jikimi_ml.train.train_trajectory --out models/trajectory_tf.onnx

A three-camera site (gate, street, back lane) with the camera graph of the example site. Normal
visits: passing through (1-2 cameras), deliveries (gate -> long stop on the street -> gate),
shoppers, residents, and the guard's own night patrol loop (a hard negative: it circles too, but
on a schedule, alone and at patrol speed). Scouting: 4-8 alternating passes within 10-30 min, slow,
with u-turns, two riders, mostly evening and night. Self-supervised on normal routes only (masked
segments, 15 %); scored by the edge's leave-one-out NLL (``TrajectoryScorer``) so training and
serving cannot drift. Writes the ONNX model, a split-conformal calibration set from held-out
normal routes (``loitering_xcam``) and a report: AUC, and the share of scouts flagged at p <= 0.01
after 3, 4 and 6 segments. All synthetic: the site's own normal routes must replace the
calibration set during the pilot.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

import numpy as np

CAMERAS = ["cam-gate-01", "cam-street-02", "cam-back-03"]
MAX_LEN = 16
GRAPH = [
    {"from": "cam-gate-01", "to": "cam-street-02", "mean_s": 25, "std_s": 10},
    {"from": "cam-street-02", "to": "cam-back-03", "mean_s": 40, "std_s": 15},
    {"from": "cam-gate-01", "to": "cam-back-03", "mean_s": 60, "std_s": 20},
]


def _travel(a: str, b: str, rng: random.Random) -> float:
    if a == b:
        return rng.uniform(60, 600)
    for g in GRAPH:
        if {g["from"], g["to"]} == {a, b}:
            return max(5.0, rng.gauss(g["mean_s"], g["std_s"]))
    return rng.uniform(30, 90)


def route(kind: str, rng: random.Random) -> list:  # list[Segment]
    from jikimi_edge.analytics.cross_camera import Segment

    def seg(cam: str, start: float, dwell: float, speed: float, turns: int, tod: float) -> Segment:
        return Segment(cam, start, start + dwell, speed, turns, tod % 24.0)

    tod = rng.choice([rng.uniform(7, 23)] * 9 + [rng.uniform(0, 24)])
    t = 0.0
    segs = []
    if kind == "pass":
        cams = rng.choice(
            [["cam-street-02"], ["cam-gate-01", "cam-street-02"], ["cam-street-02", "cam-back-03"], ["cam-gate-01"]]
        )
        for c in cams:
            segs.append(seg(c, t, rng.uniform(3, 15), rng.uniform(0.15, 0.4), 0, tod + t / 3600))
            t = segs[-1].end + _travel(c, rng.choice(CAMERAS), rng)
    elif kind == "delivery":
        segs.append(seg("cam-gate-01", t, rng.uniform(4, 15), rng.uniform(0.12, 0.3), 0, tod))
        t = segs[-1].end + _travel("cam-gate-01", "cam-street-02", rng)
        segs.append(
            seg(
                "cam-street-02",
                t,
                rng.uniform(60, 300),
                rng.uniform(0.02, 0.1),
                rng.choice([0, 1, 1, 2]),
                tod + t / 3600,
            )
        )
        if rng.random() < 0.4:  # a second drop in the back lane
            t = segs[-1].end + _travel("cam-street-02", "cam-back-03", rng)
            segs.append(
                seg("cam-back-03", t, rng.uniform(40, 200), rng.uniform(0.02, 0.1), rng.choice([0, 1]), tod + t / 3600)
            )
        t = segs[-1].end + _travel(segs[-1].camera, "cam-gate-01", rng)
        segs.append(seg("cam-gate-01", t, rng.uniform(4, 15), rng.uniform(0.12, 0.3), 0, tod + t / 3600))
    elif kind == "shopper":
        segs.append(seg("cam-street-02", t, rng.uniform(20, 120), rng.uniform(0.05, 0.2), rng.choice([0, 1]), tod))
        t = segs[-1].end + _travel("cam-street-02", "cam-back-03", rng)
        segs.append(seg("cam-back-03", t, rng.uniform(10, 60), rng.uniform(0.08, 0.25), 0, tod + t / 3600))
    elif kind == "resident":
        segs.append(seg("cam-gate-01", t, rng.uniform(5, 20), rng.uniform(0.1, 0.25), rng.choice([0, 1]), tod))
    elif kind == "patrol":  # the guard's own round: loops, but on schedule, alone, at night
        tod = rng.choice([22.0, 0.0, 2.0, 4.0]) + rng.uniform(-0.2, 0.2)
        for _ in range(rng.randint(1, 2)):
            for c in ("cam-gate-01", "cam-street-02", "cam-back-03"):
                segs.append(seg(c, t, rng.uniform(8, 20), rng.uniform(0.1, 0.2), 0, tod + t / 3600))
                t = segs[-1].end + _travel(c, "cam-street-02" if c != "cam-street-02" else "cam-back-03", rng)
    elif kind == "scout":
        tod = rng.choice([rng.uniform(18, 24), rng.uniform(0, 3), rng.uniform(10, 18)])
        cams = (
            ["cam-gate-01", "cam-street-02"] if rng.random() < 0.7 else ["cam-gate-01", "cam-street-02", "cam-back-03"]
        )
        for k in range(rng.randint(4, 8)):
            c = cams[k % len(cams)]
            segs.append(
                seg(c, t, rng.uniform(8, 40), rng.uniform(0.04, 0.15), rng.choice([0, 1, 1, 2, 3]), tod + t / 3600)
            )
            t = segs[-1].end + rng.uniform(30, 240)  # around the block and back
    return segs


NORMAL = ["pass"] * 50 + ["delivery"] * 15 + ["shopper"] * 15 + ["resident"] * 15 + ["patrol"] * 5


def main() -> None:
    import torch
    from jikimi_edge.analytics.cross_camera import TrajectoryScorer, encode

    from ..eval.metrics import roc_auc
    from ..models.trajectory_tf import TrajectoryTransformer, masked_nll, random_mask

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--routes", type=int, default=12000, help="normal training routes")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--out", default="models/trajectory_tf.onnx")
    ap.add_argument("--calibration", default="edge/config/calibration/society-gate-north/loitering_xcam.normal.json")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--reuse", action="store_true", help="skip training: load the .pt next to --out")
    args = ap.parse_args()
    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)

    def batch(routes: list) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        L = max(len(r) for r in routes)
        cams = torch.zeros((len(routes), L), dtype=torch.long)  # padding: any camera, masked out
        cont = torch.zeros((len(routes), L, 6))
        pad = torch.ones((len(routes), L), dtype=torch.bool)
        for i, r in enumerate(routes):
            c, x = encode(r, CAMERAS)
            cams[i, : len(r)], cont[i, : len(r)], pad[i, : len(r)] = torch.from_numpy(c), torch.from_numpy(x), False
        return cams, cont, pad

    train = [route(rng.choice(NORMAL), rng) for _ in range(args.routes)]
    train = [r for r in train if len(r) >= 2]  # one segment has nothing to predict from
    model = TrajectoryTransformer(len(CAMERAS), d_model=64, heads=4, layers=2, max_len=MAX_LEN)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    gen = torch.Generator().manual_seed(args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.reuse:
        model.load_state_dict(torch.load(out.with_suffix(".pt"), map_location="cpu"))
    for epoch in range(0 if args.reuse else args.epochs):
        model.train()
        order = rng.sample(range(len(train)), len(train))
        total = 0.0
        for i in range(0, len(order), 128):
            cams, cont, pad = batch([train[j] for j in order[i : i + 128]])
            mask = random_mask(tuple(cams.shape), 0.15, gen) & ~pad
            mask[:, 0] |= ~mask.any(dim=1)
            loss = masked_nll(model, cams, cont, mask, pad).mean()
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total += float(loss.detach()) * len(cams)
        print(f"epoch {epoch + 1} loss {total / len(train):.4f}", flush=True)
    torch.save(model.state_dict(), out.with_suffix(".pt"))
    model.eval()
    # fixed length 16 with a padding mask: nn.TransformerEncoder does not export with a dynamic length
    example = batch([max(train, key=len)])
    cams = torch.zeros((1, MAX_LEN), dtype=torch.long)
    cont = torch.zeros((1, MAX_LEN, 6))
    pad = torch.ones((1, MAX_LEN), dtype=torch.bool)
    n = example[0].shape[1]
    cams[:, :n], cont[:, :n], pad[:, :n] = example[0], example[1], example[2]
    torch.backends.mha.set_fastpath_enabled(False)  # the fused path does not export
    torch.onnx.export(
        model,
        (cams, cont, pad),
        str(out),
        input_names=["cams", "cont", "pad"],
        output_names=["logits", "mu", "logvar"],
        opset_version=17,
        dynamo=False,
    )
    scorer = TrajectoryScorer(str(out), CAMERAS)

    def running_max(r: list) -> list[float]:
        """The edge's score after each segment from the 3rd on: the highest so far, so a route is
        one calibration unit and P(any alert on a normal route) <= alpha."""
        out, best = [], -math.inf
        for k in range(3, len(r) + 1):
            best = max(best, scorer(r[:k]))
            out.append(best)
        return out

    held = [r for r in (route(rng.choice(NORMAL), rng) for _ in range(6000)) if len(r) >= 3]
    scouts = [route("scout", rng) for _ in range(600)]
    patrols = [route("patrol", rng) for _ in range(300)]
    cut = int(len(held) * 0.6)
    cal = sorted(running_max(r)[-1] for r in held[:cut])  # whole normal routes, final running max
    test = [running_max(r) for r in held[cut:]]
    scout_runs = [running_max(r) for r in scouts]
    patrol_runs = [running_max(r) for r in patrols if len(r) >= 3]

    def p_value(s: float) -> float:
        n_ge = len(cal) - int(np.searchsorted(cal, s, side="left"))
        return (1 + n_ge) / (len(cal) + 1)

    def flagged(runs: list[list[float]], k: int | None, alpha: float = 0.01) -> float:
        """Share of routes alerted by segment ``k`` (None: ever)."""
        return round(float(np.mean([p_value(run[: None if k is None else k - 2][-1]) <= alpha for run in runs])), 4)

    report: dict[str, object] = {
        "cameras": CAMERAS,
        "calibration_routes": len(cal),
        "train_routes": len(train),
        "normal_routes_alerted_ever_at_p_0.01": flagged(test, None),
        "normal_test_routes": len(test),
        "patrol_routes_alerted_ever_at_p_0.01": flagged(patrol_runs, None),
        "auc_scout_vs_normal_whole_route": round(
            roc_auc([0] * len(test) + [1] * len(scout_runs), [r[-1] for r in test] + [r[-1] for r in scout_runs]), 3
        ),
    }
    for k in (3, 4, 6):
        runs = [r for r in scout_runs if len(r) >= k - 2]
        report[f"scouts_alerted_by_segment_{k}_at_p_0.01"] = flagged(runs, k)
    calib = Path(args.calibration)
    calib.parent.mkdir(parents=True, exist_ok=True)
    calib.write_text(
        json.dumps(
            {
                "site_id": calib.parent.name,
                "alert_type": "loitering_xcam",
                "mode": "normal",
                "n": len(cal),
                "model_version": "xcam-tf-v1",
                "source": "synthetic routes (train_trajectory.py); replace with the site's own",
                "scores": [round(s, 5) for s in cal],
            }
        ),
        encoding="utf-8",
    )
    out.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
