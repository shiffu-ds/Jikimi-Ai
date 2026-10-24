"""Does Zero-DCE++ help the detector in the dark (F18 ablation, plan Section 8.18)?

    uv run python -m eval.lowlight_check

Frames from the last 20 % of each clip in ``data/footage/`` (Zero-DCE++ trained on the first 60 %,
the method was chosen on 60-80 %) are darkened at three levels. The detector's boxes on the *original* frame are the reference;
for each dark version we count how many of them the detector still finds (IoU >= 0.5, same
class) with no enhancement, with CLAHE (the classic baseline) and with Zero-DCE++. Synthetic
darkness only - real night adds infrared, headlight glare and motion blur - so this decides
whether the step is worth its milliseconds, not how well the system sees at night.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LEVELS = {"dusk": (2.0, 0.40, 3.0), "night": (2.5, 0.28, 5.0), "dark": (3.0, 0.18, 7.0)}  # gamma, light, noise


def darken(img: np.ndarray, gamma: float, light: float, noise: float, seed: int) -> np.ndarray:
    x = np.power(img.astype(np.float32) / 255.0, gamma) * light
    x += np.random.default_rng(seed).normal(0, noise / 255.0, x.shape).astype(np.float32)
    return (np.clip(x, 0, 1) * 255).astype(np.uint8)


def clahe(img: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    x1, y1 = np.maximum(a[:, None, 0], b[None, :, 0]), np.maximum(a[:, None, 1], b[None, :, 1])
    x2, y2 = np.minimum(a[:, None, 2], b[None, :, 2]), np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a, area_b = ((r[:, 2] - r[:, 0]) * (r[:, 3] - r[:, 1]) for r in (a, b))
    return inter / (area_a[:, None] + area_b[None, :] - inter + 1e-9)


def found(ref: np.ndarray, got: np.ndarray) -> tuple[int, int]:
    """(reference boxes found again, extra boxes) at IoU >= 0.5 and the same class."""
    if not len(ref) or not len(got):
        return 0, len(got)
    iou = _iou(ref[:, :4], got[:, :4]) * (ref[:, None, 5] == got[None, :, 5])
    used: set[int] = set()
    hit = 0
    for i in range(len(ref)):
        row = iou[i].copy()
        row[list(used)] = -1
        j = int(row.argmax())
        if row[j] >= 0.5:
            used.add(j)
            hit += 1
    return hit, len(got) - len(used)


def main() -> None:
    import onnxruntime as ort
    from jikimi_edge.inference.lowlight import LowLightEnhancer
    from jikimi_ml_runtime.yolo import decode, letterbox, to_tensor

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--detector", default=str(ROOT / "models/yolo11n.onnx"))
    ap.add_argument("--model", default=str(ROOT / "models/zero_dce_pp.onnx"))
    ap.add_argument("--report", default="eval/reports/lowlight_check.json")
    args = ap.parse_args()

    det = ort.InferenceSession(args.detector, providers=["CPUExecutionProvider"])
    name = det.get_inputs()[0].name
    keep = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

    def detect(img: np.ndarray) -> np.ndarray:
        out = det.run(None, {name: to_tensor(letterbox(img, 640)[0])})[0]
        rows = decode(out, 0.3, 0.45)
        return rows[np.isin(rows[:, 5], list(keep))] if len(rows) else rows

    enhancer = LowLightEnhancer("zero_dce", args.model, tau=1.0)  # tau 1: enhance every test frame
    shipped = LowLightEnhancer("clahe", tau=1.0)
    frames = []
    for clip in sorted((ROOT / "data/footage").glob("*.mp4")):
        cap = cv2.VideoCapture(str(clip))
        n, fps = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), cap.get(cv2.CAP_PROP_FPS) or 25
        for i in range(int(n * 0.8), n, max(1, round(fps * 0.1))):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, img = cap.read()
            if ok:
                frames.append(cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA))
        cap.release()
    refs = [detect(f) for f in frames]
    total = sum(len(r) for r in refs)
    report: dict[str, Any] = {"frames": len(frames), "reference_objects": total}
    ms: dict[str, list[float]] = {"clahe": [], "zero_dce": []}
    for level, (gamma, light, noise) in LEVELS.items():
        row: dict[str, Any] = {}
        for method in ("none", "clahe", "zero_dce"):
            hits = extra = 0
            for k, (img, ref) in enumerate(zip(frames, refs, strict=True)):
                dark = darken(img, gamma, light, noise, k)
                t0 = time.perf_counter()
                seen = dark if method == "none" else shipped(dark) if method == "clahe" else enhancer(dark)
                if method != "none":
                    ms[method].append((time.perf_counter() - t0) * 1000)
                h, x = found(ref, detect(seen))
                hits, extra = hits + h, extra + x
            row[method] = {"recall_vs_original": round(hits / max(total, 1), 3), "extra_boxes": extra}
        report[level] = row
        print(level, json.dumps(row), flush=True)
    report["ms_per_frame_640x360"] = {k: round(statistics.fmean(v), 1) for k, v in ms.items() if v}
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
