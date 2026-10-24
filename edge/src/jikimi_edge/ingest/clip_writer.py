"""Write browser-playable H.264 MP4 clips (ffmpeg), with an OpenCV fallback.

OpenCV wheels cannot encode H.264, and browsers cannot play MPEG-4 Part 2, so the system
``ffmpeg`` (libx264, ``+faststart``) is the primary path.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def write_mp4(frames: Sequence[np.ndarray], fps: float, path: str | Path, crf: int = 26) -> Path:
    if not frames:
        raise ValueError("no frames")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    h, w = frames[0].shape[:2]
    h2, w2 = h - h % 2, w - w % 2  # yuv420p needs even dimensions
    if ffmpeg_available():
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w2}x{h2}", "-r", f"{fps:.3f}", "-i", "-",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out),
        ]  # fmt: skip
        data = b"".join(np.ascontiguousarray(f[:h2, :w2]).tobytes() for f in frames)
        res = subprocess.run(cmd, input=data, capture_output=True, timeout=120, check=False)
        if res.returncode == 0 and out.exists():
            return out
        log.warning("ffmpeg failed, falling back to OpenCV mp4v", extra={"err": res.stderr.decode()[:200]})
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter.fourcc(*"mp4v"), fps, (w2, h2))
    for f in frames:
        writer.write(np.ascontiguousarray(f[:h2, :w2]))
    writer.release()
    return out
