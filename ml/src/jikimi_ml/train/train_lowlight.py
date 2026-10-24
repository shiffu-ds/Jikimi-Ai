"""Train Zero-DCE++ for night / smog frames (F18) on local footage, without reference images.

    uv run python -m jikimi_ml.train.train_lowlight --out models/zero_dce_pp.onnx

Inputs are frames from the first 60 % of each clip in ``data/footage/`` and of the simulator's
night scene, darkened the way a cheap camera sees dusk: gamma 1.8-3.2, 15-50 % of the light,
sensor noise. The last 40 % of each clip is left for ``eval.lowlight_check``. Synthetic darkness
is not real night (no infrared switch, headlight glare or motion blur): re-train on the site's
own night footage during the pilot.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[4]  # repository root
SIZE = (384, 216)


def darken(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """BGR uint8 -> a dusk / night version (float32 RGB in [0, 1])."""
    x = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    x = np.power(x, rng.uniform(1.8, 3.2)) * rng.uniform(0.15, 0.5)
    x = x + np.random.default_rng(rng.randrange(1 << 30)).normal(0, rng.uniform(2, 8) / 255.0, x.shape).astype(
        np.float32
    )
    return np.clip(x, 0.0, 1.0)


def clip_frames(first: float, last: float, step_s: float) -> list[np.ndarray]:
    """Frames between fractions ``first`` and ``last`` of every clip in data/footage/."""
    out = []
    for clip in sorted((ROOT / "data/footage").glob("*.mp4")):
        cap = cv2.VideoCapture(str(clip))
        n, fps = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), cap.get(cv2.CAP_PROP_FPS) or 25
        for i in range(int(n * first), int(n * last), max(1, round(fps * step_s))):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, img = cap.read()
            if ok:
                out.append(cv2.resize(img, SIZE, interpolation=cv2.INTER_AREA))
        cap.release()
    return out


def sim_night(n: int) -> list[np.ndarray]:
    from jikimi_edge.sim.source import SimSource

    src = SimSource("cam-street-02", "snatch_night", fps=1.0, realtime=False, loop=False, start_ts=0.0, seed=11)
    out = []
    while len(out) < n and (f := src.read()) is not None:
        if f.image is not None:
            out.append(cv2.cvtColor(cv2.resize(f.image, SIZE), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0)
    return out


def main() -> None:
    import torch

    from ..models.zero_dce import ZeroDCEpp, zero_reference_loss

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="models/zero_dce_pp.onnx")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)

    day = clip_frames(0.0, 0.6, 0.1)
    data = [darken(img, rng) for img in day for _ in range(2)] + sim_night(40)
    if not data:
        raise SystemExit("no frames: put a clip in data/footage/")
    x = torch.from_numpy(np.stack(data)).permute(0, 3, 1, 2).contiguous()
    model = ZeroDCEpp()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    t0 = time.time()
    for epoch in range(args.epochs):
        model.train()
        order = torch.randperm(len(x))
        total = 0.0
        for i in range(0, len(order), 8):
            xb = x[order[i : i + 8]]
            enh, a = model(xb)
            loss = zero_reference_loss(xb, enh, a)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 0.1)
            opt.step()
            total += float(loss.detach()) * len(xb)
        print(f"epoch {epoch + 1} loss {total / len(x):.4f}", flush=True)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    torch.save(model.state_dict(), out.with_suffix(".pt"))
    torch.onnx.export(
        model,
        (x[:1],),
        str(out),
        input_names=["image"],
        output_names=["enhanced", "curves"],
        dynamic_axes={"image": {2: "h", 3: "w"}, "enhanced": {2: "h", 3: "w"}, "curves": {2: "h", 3: "w"}},
        opset_version=17,
        dynamo=False,
    )
    info = {
        "params": sum(p.numel() for p in model.parameters()),
        "train_images": len(data),
        "seconds": round(time.time() - t0, 1),
        "darkening": "gamma 1.8-3.2, light 15-50 %, noise 2-8/255 (synthetic, not real night)",
    }
    out.with_suffix(".json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
