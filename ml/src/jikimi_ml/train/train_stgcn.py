"""Train the two-person ST-GCN (plan Section 10.1): AdamW 1e-3 cosine, focal loss gamma=2,
batch 64, early stopping on validation AUC; exports ONNX for the edge (no torch at runtime).

Kaggle/Colab GPU for real PakSnatch; synthetic pre-training also runs on the laptop CPU:

    uv run --extra torch python -m jikimi_ml.train.train_stgcn \\
        --data data/ml/paksnatch_sim.npz --epochs 30 --out models/stgcn_paksnatch.onnx
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from ..data.paksnatch import batches, group_split, load_npz
from ..eval.metrics import expected_calibration_error, precision_at_recall, roc_auc
from ..eval.stats import cluster_bootstrap_ci


def main() -> None:
    import torch

    from ..models.stgcn import FocalLoss, TwoPersonSTGCN

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True)
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--patience", type=int, default=10)
    ap.add_argument("--out", default="models/stgcn_paksnatch.onnx")
    ap.add_argument("--init", default=None, help="checkpoint to fine-tune from (synthetic -> real)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    d = load_npz(args.data)
    split = group_split(d["group"])
    x, y = d["x"], d["y"]
    tr, va, te = (split == 0), (split == 1), (split == 2)
    print(
        f"windows: train {tr.sum()} ({int(y[tr].sum())}+) | val {va.sum()} ({int(y[va].sum())}+) | test {te.sum()} ({int(y[te].sum())}+)"
    )
    model = TwoPersonSTGCN()
    if args.init:
        model.load_state_dict(torch.load(args.init, map_location="cpu"))
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    loss_fn = FocalLoss(gamma=2.0)

    def predict(mask: np.ndarray) -> np.ndarray:
        model.eval()
        out = []
        with torch.no_grad():
            for xb, _ in batches(x[mask], y[mask], 256):
                out.append(torch.sigmoid(model(torch.from_numpy(xb))).numpy())
        return np.concatenate(out) if out else np.empty(0)

    best_auc, best_state, bad = -1.0, None, 0
    for epoch in range(args.epochs):
        model.train()
        t0 = time.time()
        total = 0.0
        for xb, yb in batches(x[tr], y[tr], args.batch, rng, train=True):
            opt.zero_grad()
            loss = loss_fn(model(torch.from_numpy(xb)), torch.from_numpy(yb))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            total += loss.item() * len(yb)
        sched.step()
        auc = roc_auc(y[va], predict(va))
        print(f"epoch {epoch + 1:3d} loss {total / max(tr.sum(), 1):.4f} val_auc {auc:.4f} ({time.time() - t0:.1f}s)")
        if auc > best_auc + 1e-4:
            best_auc, best_state, bad = auc, {k: v.clone() for k, v in model.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= args.patience:
                print("early stop")
                break
    assert best_state is not None
    model.load_state_dict(best_state)
    p_te = predict(te)
    auc = cluster_bootstrap_ci(y[te], p_te, d["group"][te], roc_auc)  # resample whole episodes
    report = {
        "val_auc": round(best_auc, 4),
        "test_auc": round(auc.estimate, 4),
        "test_auc_ci95": [round(auc.low, 4), round(auc.high, 4)],
        "test_precision_at_recall_0.8": round(precision_at_recall(y[te], p_te, 0.8), 4),
        "test_ece": round(expected_calibration_error(y[te], p_te), 4),
        "data": str(args.data),
        "windows": len(y),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_state, out.with_suffix(".pt"))
    from ..export.to_onnx import export

    export(model, out)
    out.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
