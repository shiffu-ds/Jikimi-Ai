"""Camera health / tamper checks (F10, plan Section 8.10). Cheap OpenCV statistics."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class FrameStats:
    sharpness: float
    """Variance of the Laplacian (blur / defocus)."""
    brightness: float
    contrast: float
    entropy: float
    """Histogram entropy in bits (a covered lens is close to uniform)."""


def small_gray(frame_bgr: np.ndarray, width: int = 320) -> np.ndarray:
    h, w = frame_bgr.shape[:2]
    if w > width:
        frame_bgr = cv2.resize(frame_bgr, (width, max(1, int(h * width / w))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)


def frame_stats(gray: np.ndarray) -> FrameStats:
    lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    hist = cv2.calcHist([gray], [0], None, [64], [0, 256]).ravel()
    p = hist / max(float(hist.sum()), 1.0)
    p = p[p > 0]
    entropy = float(-(p * np.log2(p)).sum())
    return FrameStats(lap, float(gray.mean()), float(gray.std()), entropy)


def is_covered(s: FrameStats) -> bool:
    return (s.brightness < 25 and s.contrast < 10) or s.entropy < 1.5


def frozen_diff(prev: np.ndarray | None, cur: np.ndarray) -> float:
    if prev is None or prev.shape != cur.shape:
        return 255.0
    return float(cv2.absdiff(prev, cur).mean())


class EgoMotion:
    """How much the camera itself moved between two consecutive checks (vehicle-mounted,
    handheld or swaying). RANSAC keeps the largest consistent set of ORB matches, normally the
    static background, so traffic in front of a fixed camera does not count. A camera knocked
    to a new position and then still reads ~0 here (that is the ``moved`` check's job)."""

    def __init__(self, n_features: int = 400) -> None:
        self._orb = cv2.ORB_create(nfeatures=n_features)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

    def between(self, prev: np.ndarray | None, cur: np.ndarray) -> float | None:
        """max(translation / width, |scale - 1|, |rotation|), or ``None`` when unmeasurable."""
        if prev is None or prev.shape != cur.shape:
            return None
        kp1, d1 = self._orb.detectAndCompute(prev, None)
        kp2, d2 = self._orb.detectAndCompute(cur, None)
        if d1 is None or d2 is None or len(kp1) < 20 or len(kp2) < 20:
            return None
        matches = self._matcher.match(d1, d2)
        if len(matches) < 12:
            return None
        src = np.float32([kp1[m.queryIdx].pt for m in matches])
        dst = np.float32([kp2[m.trainIdx].pt for m in matches])
        m, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
        if m is None or inliers is None or int(inliers.sum()) < 10:
            return None
        scale = float(np.hypot(m[0, 0], m[1, 0]))
        angle = float(np.arctan2(m[1, 0], m[0, 0]))
        return max(float(np.hypot(m[0, 2], m[1, 2])) / cur.shape[1], abs(scale - 1.0), abs(angle))


class MotionReference:
    """ORB keypoints of a reference view; low RANSAC inlier ratio => camera was moved."""

    def __init__(self, n_features: int = 500) -> None:
        self._orb = cv2.ORB_create(nfeatures=n_features)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.kp: list[cv2.KeyPoint] | None = None
        self.des: np.ndarray | None = None

    def set(self, gray: np.ndarray) -> bool:
        kp, des = self._orb.detectAndCompute(gray, None)
        if des is None or len(kp) < 40:
            return False
        self.kp, self.des = list(kp), des
        return True

    @property
    def ready(self) -> bool:
        return self.des is not None

    def inlier_ratio(self, gray: np.ndarray) -> float | None:
        if self.des is None or self.kp is None:
            return None
        kp, des = self._orb.detectAndCompute(gray, None)
        if des is None or len(kp) < 10:
            return 0.0
        matches = self._matcher.match(self.des, des)
        if len(matches) < 8:
            return 0.0
        src = np.float32([self.kp[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst = np.float32([kp[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
        _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
        if mask is None:
            return 0.0
        # identity check: a static camera maps points onto themselves
        inl = mask.ravel().astype(bool)
        if not inl.any():
            return 0.0
        shift = np.linalg.norm((dst - src).reshape(-1, 2)[inl], axis=1)
        still = float((shift < 6.0).sum())
        return still / max(len(self.kp), 1)
