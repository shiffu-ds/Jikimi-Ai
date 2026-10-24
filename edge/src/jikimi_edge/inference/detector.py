"""Real-camera perception: YOLO detection (+ pose) through ``jikimi-ml-runtime`` (no torch).

Export once (laptop or Kaggle, needs Ultralytics):
``yolo export model=yolo11n.pt format=openvino int8=True imgsz=640`` (or ``yolo26n.pt``) and
point ``edge/config/models.yaml`` at the result. ``make bench`` compares the two on your CPU.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml
from jikimi_contracts import COCO_TO_JIKIMI, Detection, Pose, Track
from jikimi_ml_runtime import ModelSpec, load_engine
from jikimi_ml_runtime.yolo import decode, letterbox, to_normalized, to_tensor

from ..analytics.geometry import iou


def class_map(spec: ModelSpec, repo_root: Path) -> dict[int, str]:
    if spec.classes == "coco":
        return {k: str(v) for k, v in COCO_TO_JIKIMI.items()}
    path = Path(spec.classes)
    if not path.is_absolute():
        path = repo_root / path
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    names = data.get("names", data)
    if isinstance(names, list):
        return dict(enumerate(str(n) for n in names))
    return {int(k): str(v) for k, v in names.items()}


class YoloDetector:
    def __init__(self, spec: ModelSpec, repo_root: Path, threads: int | None = None) -> None:
        self.spec = spec
        self.engine = load_engine(spec.resolve(repo_root), spec.backend, spec.device, threads)
        self.names = class_map(spec, repo_root)
        self.version = f"{Path(spec.path).stem}-{spec.backend}"

    def __call__(self, frame: np.ndarray) -> list[Detection]:
        img, lb = letterbox(frame, self.spec.imgsz)
        out = self.engine.infer(to_tensor(img))[0]
        rows = to_normalized(decode(out, self.spec.conf, self.spec.iou), lb)
        dets = []
        for r in rows:
            name = self.names.get(int(r[5]))
            if name is None:
                continue
            dets.append(
                Detection(
                    cls=name,
                    conf=float(min(max(r[4], 0.0), 1.0)),
                    bbox=(float(r[0]), float(r[1]), float(r[2]), float(r[3])),
                )
            )
        return dets


class YoloPose:
    """Pose only for persons that matter (near a two-wheeler), matched to tracks by IoU."""

    def __init__(self, spec: ModelSpec, repo_root: Path, threads: int | None = None) -> None:
        self.spec = spec
        self.engine = load_engine(spec.resolve(repo_root), spec.backend, spec.device, threads)

    def __call__(self, frame: np.ndarray, persons: list[Track]) -> dict[int, Pose]:
        if not persons:
            return {}
        img, lb = letterbox(frame, self.spec.imgsz)
        out = self.engine.infer(to_tensor(img))[0]
        rows = to_normalized(decode(out, self.spec.conf, self.spec.iou, pose=True), lb)
        poses: dict[int, Pose] = {}
        for t in persons:
            best, best_iou = None, 0.3
            for r in rows:
                v = iou(t.bbox, (float(r[0]), float(r[1]), float(r[2]), float(r[3])))
                if v > best_iou:
                    best, best_iou = r, v
            if best is not None:
                k = best[6:].reshape(17, 3)
                poses[t.track_id] = Pose(
                    track_id=t.track_id, keypoints=[(float(a), float(b), float(c)) for a, b, c in k]
                )
        return poses
