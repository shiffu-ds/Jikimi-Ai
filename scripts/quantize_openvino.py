"""ONNX -> OpenVINO INT8 with NNCF, calibrated on local frames: no dataset download, no PyTorch.

    uv run python scripts/quantize_openvino.py            # detector + pose for the `laptop` profile
    uv run python scripts/quantize_openvino.py --only detector

Calibration frames come from the clips in data/footage/ (real traffic) and from simulator scenes
(day and night); other frames of the same sources validate the result. The INT8 model is compared
with the FP32 ONNX model it came from: does it find the same objects (matched boxes: IoU >= 0.5,
same class), how far do keypoints move, and how fast is it on this CPU. The report goes to
eval/reports/openvino_int8.json. openvino + nncf are needed at export time only; the edge needs
only openvino. The YOLO head's box / keypoint decoding stays in floating point (as in
Ultralytics' own INT8 export): quantizing it costs pixels for no speed.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from jikimi_ml_runtime.yolo import decode, letterbox, to_tensor

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "detector": ("models/yolo11n.onnx", "models/yolo11n_int8_openvino_model/yolo11n.xml", False),
    "pose": ("models/yolo11n-pose.onnx", "models/yolo11n-pose_int8_openvino_model/yolo11n-pose.xml", True),
}
HEAD_DECODE = [r".*/model\.23/(Add|Sub|Mul|Div|Sigmoid|Concat|Slice)(_\d+)?$", r".*/model\.23/dfl/.*"]
SIM_SCENES = ("normal_traffic", "festival_traffic", "snatch_night", "loiter_basic", "demo_street")
Infer = Callable[[np.ndarray], np.ndarray]


def frames(step_s: float, sim_per_scene: int) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """(calibration, validation): alternate sampled frames go to one or the other."""
    calib: list[np.ndarray] = []
    val: list[np.ndarray] = []
    k = 0
    for clip in sorted((ROOT / "data/footage").glob("*.mp4")):
        cap = cv2.VideoCapture(str(clip))
        every = max(1, round((cap.get(cv2.CAP_PROP_FPS) or 25) * step_s))
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if i % every == 0:
                (calib if k % 2 == 0 else val).append(frame)
                k += 1
            i += 1
        cap.release()
    from jikimi_edge.sim.source import SimSource

    for j, scene in enumerate(SIM_SCENES):
        cam = "cam-street-02" if j % 2 else "cam-gate-01"
        src = SimSource(cam, scene, fps=1.0, realtime=False, loop=False, start_ts=0.0, seed=900 + j)
        n = 0
        while n < sim_per_scene and (f := src.read()) is not None:
            if f.image is not None:
                (calib if n % 2 == 0 else val).append(f.image)
                n += 1
    return calib, val


def _prep(frame: np.ndarray) -> np.ndarray:
    return to_tensor(letterbox(frame, 640)[0])


def quantize(onnx: Path, out_xml: Path, calib: list[np.ndarray]) -> None:
    import nncf
    import openvino as ov

    model = ov.Core().read_model(str(onnx))
    q = nncf.quantize(
        model,
        nncf.Dataset(calib, _prep),
        preset=nncf.QuantizationPreset.MIXED,
        subset_size=len(calib),
        ignored_scope=nncf.IgnoredScope(patterns=HEAD_DECODE, types=["Sigmoid"], validate=False),
    )
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    ov.save_model(q, str(out_xml))


def _ort(path: Path) -> Infer:
    import onnxruntime as ort

    s = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    name = s.get_inputs()[0].name
    return lambda x: s.run(None, {name: x})[0]


def _ov(path: Path) -> Infer:
    import openvino as ov

    c = ov.Core().compile_model(str(path), "CPU", {"PERFORMANCE_HINT": "LATENCY"})
    return lambda x: np.asarray(c(x)[c.outputs[0]])


def _iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    x1, y1 = np.maximum(a[:, None, 0], b[None, :, 0]), np.maximum(a[:, None, 1], b[None, :, 1])
    x2, y2 = np.minimum(a[:, None, 2], b[None, :, 2]), np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a, area_b = ((r[:, 2] - r[:, 0]) * (r[:, 3] - r[:, 1]) for r in (a, b))
    return inter / (area_a[:, None] + area_b[None, :] - inter + 1e-9)


def compare(ref: Infer, test: Infer, val: list[np.ndarray], pose: bool, conf: float = 0.3) -> dict[str, Any]:
    """``test`` against ``ref`` on the validation frames (``ref``'s boxes play ground truth)."""
    n_ref = n_test = matched = 0
    ious: list[float] = []
    kpt_px: list[float] = []
    for frame in val:
        x = _prep(frame)
        a, b = decode(ref(x), conf, 0.45, pose=pose), decode(test(x), conf, 0.45, pose=pose)
        n_ref, n_test = n_ref + len(a), n_test + len(b)
        if not len(a) or not len(b):
            continue
        iou = _iou(a, b) * (a[:, None, 5] == b[None, :, 5])
        used: list[int] = []
        for i in np.argsort(-a[:, 4]):
            row = iou[i].copy()
            row[used] = -1.0
            j = int(row.argmax())
            if row[j] < 0.5:
                continue
            used.append(j)
            matched += 1
            ious.append(float(row[j]))
            if pose:
                ka, kb = a[i, 6:].reshape(17, 3), b[j, 6:].reshape(17, 3)
                vis = (ka[:, 2] > 0.5) & (kb[:, 2] > 0.5)
                kpt_px.extend(np.hypot(*(ka[vis, :2] - kb[vis, :2]).T).tolist())
    out: dict[str, Any] = {
        "frames": len(val),
        "objects_fp32": n_ref,
        "objects_int8": n_test,
        "recall_vs_fp32": round(matched / max(n_ref, 1), 3),
        "precision_vs_fp32": round(matched / max(n_test, 1), 3),
        "mean_iou_of_matches": round(statistics.fmean(ious), 3) if ious else None,
    }
    if pose:
        out["keypoint_shift_px_median"] = round(statistics.median(kpt_px), 2) if kpt_px else None
    return out


def latency(fn: Infer, val: list[np.ndarray], n: int = 40) -> dict[str, float]:
    xs = [_prep(f) for f in val[:n]]
    for x in xs[:3]:
        fn(x)
    ms = []
    for x in xs:
        t0 = time.perf_counter()
        fn(x)
        ms.append((time.perf_counter() - t0) * 1000)
    ms.sort()
    return {"mean": round(statistics.fmean(ms), 1), "p95": round(ms[int(0.95 * (len(ms) - 1))], 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", choices=sorted(MODELS))
    ap.add_argument("--step-s", type=float, default=0.1, help="seconds between sampled clip frames")
    ap.add_argument("--sim-per-scene", type=int, default=40)
    ap.add_argument("--report", default="eval/reports/openvino_int8.json")
    args = ap.parse_args()

    calib, val = frames(args.step_s, args.sim_per_scene)
    report: dict[str, Any] = {"calibration_frames": len(calib), "validation_frames": len(val)}
    for name, (onnx, xml, pose) in MODELS.items():
        if args.only and name != args.only:
            continue
        src, dst = ROOT / onnx, ROOT / xml
        t0 = time.perf_counter()
        quantize(src, dst, calib)
        ref, fp32_ov, int8 = _ort(src), _ov(src), _ov(dst)
        report[name] = {
            "file": xml,
            "export_s": round(time.perf_counter() - t0, 1),
            "size_mb": {
                "onnx_fp32": round(src.stat().st_size / 1e6, 1),
                "int8": round(dst.with_suffix(".bin").stat().st_size / 1e6, 1),
            },
            "int8_vs_fp32": compare(ref, int8, val, pose),
            "ms_per_inference": {
                "onnxruntime_fp32": latency(ref, val),
                "openvino_fp32": latency(fp32_ov, val),
                "openvino_int8": latency(int8, val),
            },
        }
        print(json.dumps({name: report[name]}, indent=2))
    out = ROOT / args.report
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
