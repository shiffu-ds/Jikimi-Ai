"""Train the audio-event classifier (F13) on labelled recordings, with honest cross-validation.

    uv run python -m jikimi_ml.train.train_audio --data data/audio          # your recordings
    uv run python -m jikimi_ml.train.train_audio --synthetic 40             # pipeline smoke test only

``--data`` holds one folder per class - ``background``, ``firing``, ``scream``, ``glass_break``,
``firecracker`` - with any audio files PyAV reads (wav, ogg, webm, m4a, mp3). Each file is cut into
0.96 s log-mel windows (the edge's own ``log_mel``). Five-fold cross-validation keeps every
file's windows on one side, then the model trained on everything is exported to
``models/audio_events.onnx`` with its class list. ``--synthetic`` makes toy sounds (an impulse
with a decaying tail for "firing", bursts of pops for "firecracker", a rising tone for "scream",
a hiss with tinkles for "glass") to check the plumbing: its accuracy says nothing about real
sound. The plan's data: licensed public recordings plus the site's own safe recordings, and
firecrackers on purpose (weddings).
"""

from __future__ import annotations

import argparse
import io
import json
import random
from pathlib import Path

import numpy as np

CLASSES = ["background", "firing", "scream", "glass_break", "firecracker"]
EXTS = {".wav", ".ogg", ".webm", ".m4a", ".mp3", ".opus", ".flac"}


def decode(path: Path) -> np.ndarray:
    import av
    from jikimi_edge.analytics.audio.features import RATE

    out = []
    with av.open(io.BytesIO(path.read_bytes())) as c:
        res = av.AudioResampler(format="flt", layout="mono", rate=RATE)
        for frame in c.decode(audio=0):
            out.extend(o.to_ndarray().reshape(-1) for o in res.resample(frame))
        out.extend(o.to_ndarray().reshape(-1) for o in res.resample(None))
    return np.concatenate(out) if out else np.zeros(0, np.float32)


def synthetic(kind: str, rng: np.random.Generator, seconds: float = 2.0) -> np.ndarray:
    from jikimi_edge.analytics.audio.features import RATE

    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    x = rng.normal(0, 0.02, n) * (1 + 0.5 * np.sin(2 * np.pi * rng.uniform(0.2, 1) * t))  # street hiss
    x += 0.03 * np.sin(2 * np.pi * rng.uniform(80, 140) * t)  # engine hum
    at = int(rng.uniform(0.2, 0.8) * RATE)
    if kind == "firing":
        burst = rng.normal(0, 1, int(0.25 * RATE)) * np.exp(-np.arange(int(0.25 * RATE)) / (0.03 * RATE))
        x[at : at + len(burst)] += 0.9 * burst
    elif kind == "firecracker":
        for _ in range(rng.integers(8, 25)):
            p = at + int(rng.uniform(0, 1.0) * RATE)
            pop = rng.normal(0, 1, 400) * np.exp(-np.arange(400) / 60)
            x[p : p + 400] += rng.uniform(0.2, 0.5) * pop[: len(x[p : p + 400])]
    elif kind == "scream":
        dur = int(rng.uniform(0.5, 0.9) * RATE)
        f0 = rng.uniform(700, 1200) + np.linspace(0, rng.uniform(300, 900), dur)
        phase = 2 * np.pi * np.cumsum(f0 * (1 + 0.02 * np.sin(2 * np.pi * 6 * np.arange(dur) / RATE))) / RATE
        x[at : at + dur] += 0.5 * (np.sin(phase) + 0.3 * np.sin(2 * phase))
    elif kind == "glass_break":
        dur = int(0.4 * RATE)
        hiss = rng.normal(0, 1, dur) * np.exp(-np.arange(dur) / (0.08 * RATE))
        hi = np.fft.irfft(np.fft.rfft(hiss) * (np.fft.rfftfreq(dur, 1 / RATE) > 3000), n=dur)
        x[at : at + dur] += 2.5 * hi
        for _ in range(6):
            p = at + int(rng.uniform(0.05, 0.6) * RATE)
            k = np.arange(800)
            x[p : p + 800] += 0.2 * np.sin(2 * np.pi * rng.uniform(4000, 7000) * k / RATE) * np.exp(-k / 150)
    return np.clip(x, -1, 1).astype(np.float32)


def dataset(args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    from jikimi_edge.analytics.audio.features import log_mel, windows

    xs, ys, gs = [], [], []
    if args.synthetic:
        rng = np.random.default_rng(args.seed)
        items = [(c, f"syn-{c}-{i}", synthetic(c, rng)) for c in CLASSES for i in range(args.synthetic)]
    else:
        root = Path(args.data)
        items = [
            (c, f"{c}/{p.name}", decode(p))
            for c in CLASSES
            if (root / c).is_dir()
            for p in sorted((root / c).iterdir())
            if p.suffix.lower() in EXTS
        ]
    classes = [c for c in CLASSES if any(i[0] == c for i in items)]
    for c, group, samples in items:
        for w in windows(samples) or [samples]:
            xs.append(log_mel(w))
            ys.append(classes.index(c))
            gs.append(group)
    if not xs:
        raise SystemExit(f"no audio found: folders {CLASSES} under {args.data}")
    return np.stack(xs)[:, None], np.asarray(ys), np.asarray(gs), classes


def make_model(n_classes: int):  # type: ignore[no-untyped-def]
    from torch import nn

    def block(cin: int, cout: int) -> nn.Sequential:
        return nn.Sequential(nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(), nn.MaxPool2d(2))

    return nn.Sequential(
        nn.BatchNorm2d(1),
        block(1, 16),
        block(16, 32),
        block(32, 64),
        nn.AdaptiveAvgPool2d(1),
        nn.Flatten(),
        nn.Linear(64, n_classes),
    )


def fit(x: np.ndarray, y: np.ndarray, n_classes: int, epochs: int, seed: int):  # type: ignore[no-untyped-def]
    import torch

    torch.manual_seed(seed)
    model = make_model(n_classes)
    opt = torch.optim.Adam(model.parameters(), lr=2e-3)
    counts = np.bincount(y, minlength=n_classes).astype(np.float32)
    loss_fn = torch.nn.CrossEntropyLoss(weight=torch.tensor(counts.sum() / np.maximum(counts, 1) / n_classes))
    rng = np.random.default_rng(seed)
    for _ in range(epochs):
        model.train()
        for i in range(0, len(y), 32):
            sel = rng.permutation(len(y))[i : i + 32]
            opt.zero_grad()
            loss_fn(model(torch.from_numpy(x[sel])), torch.from_numpy(y[sel])).backward()
            opt.step()
    return model.eval()


def main() -> None:
    import torch

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="data/audio")
    ap.add_argument("--synthetic", type=int, default=0, help="toy clips per class (plumbing test)")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--out", default="models/audio_events.onnx")
    ap.add_argument("--report", default="eval/reports/audio_check.json")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    x, y, groups, classes = dataset(args)
    files = sorted(set(groups))
    random.Random(args.seed).shuffle(files)
    fold_of = {g: i % 5 for i, g in enumerate(files)}
    pred = np.zeros(len(y), int)
    for k in range(5):
        test = np.asarray([fold_of[g] == k for g in groups])
        model = fit(x[~test], y[~test], len(classes), args.epochs, args.seed + k)
        with torch.no_grad():
            pred[test] = model(torch.from_numpy(x[test])).argmax(1).numpy()
    conf = np.zeros((len(classes), len(classes)), int)
    for t, p in zip(y, pred, strict=True):
        conf[t, p] += 1
    per = {
        c: {
            "recall": round(conf[i, i] / max(conf[i].sum(), 1), 3),
            "precision": round(conf[i, i] / max(conf[:, i].sum(), 1), 3),
            "windows": int(conf[i].sum()),
        }
        for i, c in enumerate(classes)
    }
    report = {
        "data": "synthetic toy sounds (plumbing only)" if args.synthetic else str(args.data),
        "files": len(files),
        "windows": len(y),
        "cv_accuracy_5fold_by_file": round(float((pred == y).mean()), 3),
        "per_class": per,
        "confusion_rows_true_cols_predicted": {"classes": classes, "matrix": conf.tolist()},
    }
    if "firing" in classes and "firecracker" in classes:
        i, j = classes.index("firing"), classes.index("firecracker")
        report["firecracker_called_firing"] = round(conf[j, i] / max(conf[j].sum(), 1), 3)
    model = fit(x, y, len(classes), args.epochs, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        (torch.from_numpy(x[:1]),),
        str(out),
        input_names=["mel"],
        output_names=["logits"],
        opset_version=17,
        dynamo=False,
    )
    out.with_suffix(".json").write_text(json.dumps({"classes": classes, "report": report}, indent=2), encoding="utf-8")
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
