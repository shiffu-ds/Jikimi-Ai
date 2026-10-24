"""Audio from a camera (its RTSP audio track) or a local microphone, as 16 kHz mono (F13).

Most CCTV cameras have no microphone: a camera's ``audio: true`` turns this on. A background
thread decodes with PyAV (``uv sync --extra audio`` on the edge) into a ring buffer of the last
10 seconds; the audio plugin takes the samples it has not seen yet. ``mic`` is the default ALSA
microphone (the laptop's own, for a live demo).
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from ..analytics.audio.features import RATE

log = logging.getLogger(__name__)


class AudioReader:
    def __init__(self, url: str, seconds: float = 10.0) -> None:
        self.url = url
        self._buf = np.zeros(int(seconds * RATE), np.float32)
        self._written = 0  # total samples ever written
        self._read = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.ok = False
        self._thread = threading.Thread(target=self._run, name="audio", daemon=True)
        self._thread.start()

    def _open(self):  # type: ignore[no-untyped-def]
        import av

        if self.url == "mic":
            return av.open("default", format="alsa")
        return av.open(
            self.url, options={"rtsp_transport": "tcp", "stimeout": "6000000"} if self.url.startswith("rtsp") else {}
        )

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                import av

                with self._open() as container:
                    if not container.streams.audio:
                        log.warning("no audio track: audio events off for this camera", extra={"source": self.url[:16]})
                        return
                    resampler = av.AudioResampler(format="flt", layout="mono", rate=RATE)
                    self.ok, backoff = True, 1.0
                    for frame in container.decode(audio=0):
                        for out in resampler.resample(frame):
                            self._push(out.to_ndarray().reshape(-1))
                        if self._stop.is_set():
                            return
            except Exception as exc:  # unreachable camera, no ALSA device, codec PyAV lacks
                log.warning("audio source failed, retrying", extra={"error": str(exc)[:120], "in_s": backoff})
            self.ok = False
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)

    def _push(self, x: np.ndarray) -> None:
        with self._lock:
            n = len(self._buf)
            for i in range(0, len(x), n):
                chunk = x[i : i + n]
                pos = self._written % n
                first = min(len(chunk), n - pos)
                self._buf[pos : pos + first] = chunk[:first]
                self._buf[: len(chunk) - first] = chunk[first:]
                self._written += len(chunk)

    def take(self) -> np.ndarray:
        """Samples written since the last call (at most the buffer's length)."""
        with self._lock:
            n = len(self._buf)
            start = max(self._read, self._written - n)
            idx = np.arange(start, self._written) % n
            self._read = self._written
            return self._buf[idx].copy()

    def close(self) -> None:
        self._stop.set()


def wait_ready(reader: AudioReader, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end and not reader.ok:
        time.sleep(0.05)
    return reader.ok
