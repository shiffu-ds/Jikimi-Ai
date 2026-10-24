"""Federated learning across sites (F14, plan Section 8.14): FedAvg on the snatch ST-GCN.

    uv run python -m jikimi_ml.train.federated --rounds 8

Three *virtual sites* hold disjoint, differently mixed parts of PakSnatch-sim (site A sees most
snatches by day, site B mostly delivery and directions stops, site C the rest): pose windows
never leave a site, only weights do. Each round every site trains one local epoch from the
global weights and sends its update; the server averages them weighted by window counts
(FedAvg, McMahan et al. 2017). Optional client-level differential privacy: every update is
clipped to norm C and the average gets Gaussian noise sigma * C / sites (DP-FedAvg).

Compared on the fixed PakSnatch-sim test split: FedAvg at sigma 0 / 0.5 / 1.0, all data pooled
in one place (what federation tries to match without moving data) and each site alone. The
in-process loop is the algorithm Flower runs between edges; the transport is the outbox's.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..data.paksnatch import batches, group_split, load_npz
from ..eval.metrics import roc_auc

MIX = {  # share of each episode kind that lives at each site (non-IID on purpose)
    "snatch": (0.6, 0.15, 0.25),
    "delivery": (0.15, 0.6, 0.25),
    "directions": (0.15, 0.6, 0.25),
    "normal": (0.34, 0.33, 0.33),
}


def site_of(group: str) -> int:
    kind = group.split("-")[0]
    u = int(hashlib.sha256(f"site:{group}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    a, b, _ = MIX.get(kind, (1 / 3, 1 / 3, 1 / 3))
    return 0 if u < a else 1 if u < a + b else 2


def flat(model: Any) -> Any:
    import torch

    return torch.cat([p.detach().reshape(-1) for p in model.state_dict().values() if p.dtype.is_floating_point])


def load_flat(model: Any, vec: Any) -> None:
    sd, i = model.state_dict(), 0
    for k, v in sd.items():
        if v.dtype.is_floating_point:
            n = v.numel()
            sd[k] = vec[i : i + n].reshape(v.shape).clone()
            i += n
    model.load_state_dict(sd)


def local_epoch(model: Any, x: np.ndarray, y: np.ndarray, seed: int, lr: float = 1e-3) -> None:
    import torch

    from ..models.stgcn import FocalLoss

    rng = np.random.default_rng(seed)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    loss_fn = FocalLoss(gamma=2.0)
    model.train()
    for xb, yb in batches(x, y, 64, rng, train=True):
        opt.zero_grad()
        loss_fn(model(torch.from_numpy(xb)), torch.from_numpy(yb)).backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        opt.step()


def evaluate(model: Any, x: np.ndarray, y: np.ndarray) -> float | None:
    import torch

    if not len(y) or y.min() == y.max():
        return None  # AUC needs both classes
    model.eval()
    with torch.no_grad():
        p = np.concatenate(
            [torch.sigmoid(model(torch.from_numpy(x[i : i + 256]))).numpy() for i in range(0, len(x), 256)]
        )
    return round(roc_auc(y, p), 4)


def main() -> None:
    import torch

    from ..models.stgcn import TwoPersonSTGCN

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="data/ml/paksnatch_sim.npz")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--sigmas", default="0,0.5,1.0", help="DP noise multipliers to compare")
    ap.add_argument("--clip", type=float, default=1.0, help="update norm bound C")
    ap.add_argument("--report", default="eval/reports/federated.json")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    d = load_npz(args.data)
    split = group_split(d["group"])
    x, y, groups = d["x"].astype(np.float32), d["y"], d["group"]
    tr, te = split == 0, split == 2
    sites = np.asarray([site_of(str(g)) for g in groups])
    parts = [(x[tr & (sites == k)], y[tr & (sites == k)]) for k in range(3)]
    xt, yt = x[te], y[te]
    report: dict[str, Any] = {
        "sites": [{"windows": len(py), "positives": int(py.sum())} for _, py in parts],
        "test": {"windows": len(yt), "positives": int(yt.sum())},
    }

    def fresh() -> Any:
        torch.manual_seed(args.seed)
        return TwoPersonSTGCN()

    t0 = time.time()
    central = fresh()
    for r in range(args.rounds):
        local_epoch(central, x[tr], y[tr], args.seed + r)
    report["centralized_all_data_pooled"] = evaluate(central, xt, yt)
    report["each_site_alone"] = []
    for k, (px, py) in enumerate(parts):
        m = fresh()
        for r in range(args.rounds):
            local_epoch(m, px, py, args.seed + 100 * k + r)
        report["each_site_alone"].append(evaluate(m, xt, yt))
    print("baselines", report["centralized_all_data_pooled"], report["each_site_alone"], flush=True)

    weights = np.asarray([len(py) for _, py in parts], dtype=np.float64)
    weights /= weights.sum()
    gen = torch.Generator().manual_seed(args.seed)
    for sigma in (float(s) for s in args.sigmas.split(",")):
        glob = fresh()
        curve = []
        for r in range(args.rounds):
            base = flat(glob)
            agg = torch.zeros_like(base)
            for k, (px, py) in enumerate(parts):
                local = fresh()
                load_flat(local, base.clone())
                local_epoch(local, px, py, args.seed + 1000 * r + k)
                delta = flat(local) - base
                if sigma > 0:  # client-level DP: bound every site's influence
                    delta = delta * min(1.0, args.clip / (float(delta.norm()) + 1e-12))
                agg += float(weights[k]) * delta
            if sigma > 0:
                agg += torch.randn(agg.shape, generator=gen) * sigma * args.clip / len(parts)
            load_flat(glob, base + agg)
            curve.append(evaluate(glob, xt, yt))
        report[f"fedavg_sigma_{sigma:g}"] = {"final_auc": curve[-1], "auc_by_round": curve}
        print(f"fedavg sigma={sigma}", curve, flush=True)
    params = int(sum(p.numel() for p in fresh().parameters()))
    report["update_kb_per_site_per_round"] = round(params * 4 / 1024, 1)
    report["pose_windows_moved"] = 0
    report["seconds"] = round(time.time() - t0, 1)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
