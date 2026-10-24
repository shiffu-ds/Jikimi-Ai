"""Torch-free YOLO pre/post-processing (Ultralytics YOLO11 and YOLO26 exports).

Supports both output layouts:
- **YOLO11 / v8** (``nms=False`` export): ``(1, 4 + nc, N)`` raw anchors -> confidence filter -> NMS
- **YOLO26 / end-to-end**: ``(1, max_det, 6)`` rows ``[x1, y1, x2, y2, score, cls]`` (NMS-free)

Pose models append 17 x (x, y, conf) keypoints to every row.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

NUM_KPT_VALUES = 17 * 3


@dataclass(frozen=True)
class Letterbox:
    ratio: float
    pad: tuple[float, float]
    orig_w: int
    orig_h: int
    size: int


def letterbox(
    img: np.ndarray, size: int = 640, color: tuple[int, int, int] = (114, 114, 114)
) -> tuple[np.ndarray, Letterbox]:
    """Resize keeping aspect ratio and pad to ``size x size`` (BGR uint8 in, BGR uint8 out)."""
    import cv2

    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nw, nh = round(w * r), round(h * r)
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR) if (nw, nh) != (w, h) else img
    dw, dh = (size - nw) / 2.0, (size - nh) / 2.0
    top, bottom = round(dh - 0.1), round(dh + 0.1)
    left, right = round(dw - 0.1), round(dw + 0.1)
    out = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return out, Letterbox(ratio=r, pad=(left, top), orig_w=w, orig_h=h, size=size)


def to_tensor(img_bgr: np.ndarray) -> np.ndarray:
    """BGR uint8 HWC -> RGB float32 NCHW in [0, 1]."""
    rgb = img_bgr[..., ::-1]
    chw = np.ascontiguousarray(rgb.transpose(2, 0, 1), dtype=np.float32) / 255.0
    return chw[None]


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thres: float) -> np.ndarray:
    if boxes.size == 0:
        return np.empty(0, dtype=np.int64)
    x1, y1, x2, y2 = boxes.T
    areas = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_thres]
    return np.asarray(keep, dtype=np.int64)


def _is_end_to_end(out: np.ndarray, extra: int) -> bool:
    return out.ndim == 2 and out.shape[1] == 6 + extra and out.shape[0] <= 1000


def decode(
    output: np.ndarray,
    conf_thres: float = 0.25,
    iou_thres: float = 0.45,
    max_det: int = 300,
    pose: bool = False,
) -> np.ndarray:
    """Return ``(M, 6 [+51])`` rows ``[x1, y1, x2, y2, score, cls, (kpts...)]`` in input pixels."""
    out = output[0] if output.ndim == 3 else output
    extra = NUM_KPT_VALUES if pose else 0
    if _is_end_to_end(out, extra):
        rows = out[out[:, 4] >= conf_thres]
        return rows[np.argsort(-rows[:, 4])][:max_det].astype(np.float32)

    if out.shape[0] < out.shape[1]:
        out = out.T  # (N, 4 + nc [+51])
    boxes_cxcywh = out[:, :4]
    if pose:
        scores = out[:, 4]
        cls = np.zeros_like(scores)
        kpts = out[:, 5 : 5 + NUM_KPT_VALUES]
    else:
        cls_scores = out[:, 4:]
        cls = cls_scores.argmax(axis=1).astype(np.float32)
        scores = cls_scores.max(axis=1)
        kpts = np.empty((out.shape[0], 0), dtype=np.float32)
    mask = scores >= conf_thres
    if not mask.any():
        return np.empty((0, 6 + extra), dtype=np.float32)
    b, s, c, k = boxes_cxcywh[mask], scores[mask], cls[mask], kpts[mask]
    xyxy = np.empty_like(b)
    xyxy[:, 0] = b[:, 0] - b[:, 2] / 2
    xyxy[:, 1] = b[:, 1] - b[:, 3] / 2
    xyxy[:, 2] = b[:, 0] + b[:, 2] / 2
    xyxy[:, 3] = b[:, 1] + b[:, 3] / 2
    offset = c[:, None] * 4096.0  # class-aware NMS in one pass
    keep = nms(xyxy + offset, s, iou_thres)[:max_det]
    rows = np.concatenate([xyxy[keep], s[keep, None], c[keep, None], k[keep]], axis=1)
    return rows.astype(np.float32)


def to_normalized(rows: np.ndarray, lb: Letterbox) -> np.ndarray:
    """Undo letterboxing; boxes (and keypoints) become normalized to the original frame."""
    if rows.size == 0:
        return rows
    out = rows.copy()
    px, py = lb.pad
    out[:, [0, 2]] = ((out[:, [0, 2]] - px) / lb.ratio) / lb.orig_w
    out[:, [1, 3]] = ((out[:, [1, 3]] - py) / lb.ratio) / lb.orig_h
    out[:, :4] = np.clip(out[:, :4], 0.0, 1.0)
    if out.shape[1] > 6:
        k = out[:, 6:].reshape(len(out), -1, 3)
        k[..., 0] = ((k[..., 0] - px) / lb.ratio) / lb.orig_w
        k[..., 1] = ((k[..., 1] - py) / lb.ratio) / lb.orig_h
        out[:, 6:] = k.reshape(len(out), -1)
    return out
