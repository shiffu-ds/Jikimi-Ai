"""Privacy blur for every stored/exported clip, thumbnail and snapshot (F19).

Improvement over plan v2.3: at CCTV distances faces are often 10-20 px and face detectors miss
them, so the *head region of every tracked person* is blurred as well (top ~20 % of the person
box, or the pose head keypoints). A face detector (YuNet when the model file exists, otherwise
nothing by default; Haar on request) adds faces outside person boxes. This union is what makes
the >= 98 % blur target (US8) reachable.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

NormBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class BlurStats:
    heads: int
    faces: int
    method: str


def head_region(person: NormBox, frac: float = 0.22) -> NormBox:
    x1, y1, x2, y2 = person
    h, w = y2 - y1, x2 - x1
    hh = h * frac
    side = max(hh, w * 0.7)
    cx = (x1 + x2) / 2
    return (cx - side / 2 - 0.15 * side, y1 - 0.1 * hh, cx + side / 2 + 0.15 * side, y1 + hh * 1.05)


def rider_head_proxy(bike: NormBox) -> NormBox:
    """A person box whose ``head_region`` covers the band where riders' heads are above a
    two-wheeler (from ~0.9 bike heights above its top edge down into it). On real footage of a
    crowded junction many riders are never detected as persons; their heads still get blurred.
    Blurring some background as well is the safe side of this trade-off."""
    x1, y1, x2, y2 = bike
    bh = y2 - y1
    top = y1 - 0.8 * bh
    return (x1, top, x2, top + 3.9 * bh)


def _blur_rect(img: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> None:
    h, w = img.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return
    roi = img[y1:y2, x1:x2]
    # pixelate then smooth: irreversible at these sizes and cheap on CPU
    small = cv2.resize(roi, (max(1, (x2 - x1) // 8), max(1, (y2 - y1) // 8)), interpolation=cv2.INTER_LINEAR)
    k = max(3, ((min(x2 - x1, y2 - y1) // 3) | 1))
    img[y1:y2, x1:x2] = cv2.GaussianBlur(
        cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST), (k, k), 0
    )


class PrivacyBlur:
    def __init__(
        self, face_detector: str = "auto", yunet_model: str | Path | None = "models/face_detection_yunet_2023mar.onnx"
    ) -> None:
        self._yunet = None
        self._haar = None
        self.method = "head"
        if face_detector in ("auto", "yunet") and yunet_model and Path(yunet_model).exists():
            try:
                self._yunet = cv2.FaceDetectorYN.create(str(yunet_model), "", (320, 320), 0.6, 0.3, 50)
                self.method = "head+yunet"
            except cv2.error:
                log.warning("YuNet model could not be loaded; head-region blur only")
        elif face_detector == "haar":
            if hasattr(cv2, "CascadeClassifier"):  # OpenCV 5 moved Haar cascades out of the main package
                self._haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
                self.method = "head+haar"
            else:
                log.warning("this OpenCV has no Haar cascades; head-region blur only")

    def _faces(self, img: np.ndarray) -> list[tuple[int, int, int, int]]:
        if self._yunet is not None:
            h, w = img.shape[:2]
            self._yunet.setInputSize((w, h))
            _, faces = self._yunet.detect(img)
            if faces is None:
                return []
            return [(int(f[0]), int(f[1]), int(f[0] + f[2]), int(f[1] + f[3])) for f in faces]
        if self._haar is not None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            return [(x, y, x + w, y + h) for (x, y, w, h) in self._haar.detectMultiScale(gray, 1.1, 4)]
        return []

    def apply(
        self, frame: np.ndarray, person_boxes: Sequence[NormBox], inplace: bool = False
    ) -> tuple[np.ndarray, BlurStats]:
        img = frame if inplace else frame.copy()
        h, w = img.shape[:2]
        for box in person_boxes:
            hx1, hy1, hx2, hy2 = head_region(box)
            _blur_rect(img, int(hx1 * w), int(hy1 * h), int(hx2 * w) + 1, int(hy2 * h) + 1)
        faces = self._faces(frame)
        for fx1, fy1, fx2, fy2 in faces:
            pad = int(0.15 * (fx2 - fx1))
            _blur_rect(img, fx1 - pad, fy1 - pad, fx2 + pad, fy2 + pad)
        return img, BlurStats(heads=len(person_boxes), faces=len(faces), method=self.method)
