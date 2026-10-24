"""Frame sources: RTSP cameras and local webcams (with reconnect + backoff), video files, and the
simulator."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import cv2
import numpy as np
from jikimi_contracts import Pose, Track

log = logging.getLogger(__name__)
OPEN_TIMEOUT_MS, READ_TIMEOUT_MS = 6000, 4000
WEBCAM_SIZE = (1280, 720)


def open_capture(url: str) -> cv2.VideoCapture:
    """``webcam:N`` opens local camera N (laptop / USB); anything else goes to FFmpeg, which gives
    up on an unreachable recorder after seconds instead of its default 30 s."""
    if url.startswith("webcam:"):
        cap = cv2.VideoCapture(int(url[7:] or 0))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WEBCAM_SIZE[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, WEBCAM_SIZE[1])
        return cap
    return cv2.VideoCapture(
        url,
        cv2.CAP_FFMPEG,
        [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS, cv2.CAP_PROP_READ_TIMEOUT_MSEC, READ_TIMEOUT_MS],
    )


@dataclass
class Frame:
    ts: float
    image: np.ndarray | None
    tracks: list[Track] | None = None
    """Ground-truth tracks (simulator). ``None`` means: run detector + tracker."""
    poses: dict[int, Pose] | None = None
    truth: dict[str, Any] = field(default_factory=dict)


class FrameSource(Protocol):
    camera_id: str

    def read(self) -> Frame | None: ...
    def close(self) -> None: ...
    @property
    def connected(self) -> bool: ...


class RtspSource:
    """Background thread keeps only the *latest* decoded frame (no growing lag). Also serves
    ``webcam:N`` sources, which behave the same way (a live camera that can drop out)."""

    def __init__(self, camera_id: str, url: str, fps: float = 5.0, max_backoff_s: float = 30.0) -> None:
        self.camera_id = camera_id
        self.url = url
        self.period = 1.0 / fps
        self.max_backoff_s = max_backoff_s
        self._latest: tuple[float, np.ndarray] | None = None
        self._returned_ts = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._connected = False
        self._thread = threading.Thread(target=self._run, name=f"rtsp-{camera_id}", daemon=True)
        self._thread.start()

    @property
    def connected(self) -> bool:
        return self._connected

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            cap = open_capture(self.url)
            if not cap.isOpened():
                self._connected = False
                log.warning("camera unreachable, retrying", extra={"camera": self.camera_id, "in_s": backoff})
                self._stop.wait(backoff)
                backoff = min(backoff * 2, self.max_backoff_s)
                continue
            self._connected = True
            backoff = 1.0
            while not self._stop.is_set():
                ok, img = cap.read()
                if not ok:
                    log.warning("stream dropped", extra={"camera": self.camera_id})
                    break
                with self._lock:
                    self._latest = (time.time(), img)
            cap.release()
            self._connected = False

    def read(self) -> Frame | None:
        deadline = time.monotonic() + self.period
        while not self._stop.is_set():
            with self._lock:
                latest = self._latest
            if (
                latest is not None
                and latest[0] > self._returned_ts
                and time.time() - self._returned_ts >= self.period * 0.9
            ):
                self._returned_ts = latest[0]
                return Frame(ts=latest[0], image=latest[1])
            if time.monotonic() > deadline + 1.0:
                return None
            time.sleep(0.01)
        return None

    def close(self) -> None:
        self._stop.set()


class VideoFileSource:
    """Replays a file at ``fps`` (sampled), optionally looping; timestamps start at ``start_ts``."""

    def __init__(
        self,
        camera_id: str,
        path: str,
        fps: float = 5.0,
        start_ts: float | None = None,
        realtime: bool = False,
        loop: bool = False,
    ) -> None:
        self.camera_id = camera_id
        self._cap = cv2.VideoCapture(path)
        self._src_fps = self._cap.get(cv2.CAP_PROP_FPS) or 25.0
        self._step = max(1, round(self._src_fps / fps))
        self._fps = fps
        self._t = 0.0
        self._start = time.time() if start_ts is None else start_ts
        self._realtime = realtime
        self._loop = loop
        self._path = path

    @property
    def connected(self) -> bool:
        return self._cap.isOpened()

    def read(self) -> Frame | None:
        img = None
        for _ in range(self._step):
            ok, img = self._cap.read()
            if not ok:
                if not self._loop:
                    return None
                self._cap.release()
                self._cap = cv2.VideoCapture(self._path)
                ok, img = self._cap.read()
                if not ok:
                    return None
        ts = self._start + self._t
        self._t += 1.0 / self._fps
        if self._realtime:
            delay = ts - time.time()
            if delay > 0:
                time.sleep(delay)
        return Frame(ts=ts, image=img)

    def close(self) -> None:
        self._cap.release()
