"""Audio events with video late fusion (F13, plan Section 8.13).

Per camera with ``audio: true``: 0.96 s log-mel windows -> a small CNN (``models/audio_events.onnx``,
trained by ``jikimi_ml.train.train_audio`` on the site's own labelled recordings) -> class
probabilities ``background | firing | scream | glass_break | firecracker``. Firecrackers are the
hard negative (weddings): they are a class of their own, so a bang that sounds like them does not
count as firing. Late fusion with what the camera sees, noisy-OR:

    p = 1 - (1 - w_a * p_audio) (1 - w_v * p_flash) (1 - w_m * p_crowd_run)

``p_flash``: a sudden brightness jump in a dark frame (muzzle flash); ``p_crowd_run``: pedestrians
suddenly much faster than the last minute's median. Firing uses all three, a scream audio and
running, glass audio alone. Weights are config (``plugins.audio``) until the pilot's labelled
recordings fit them.
"""

from __future__ import annotations

import json
import logging
import statistics
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
from jikimi_contracts import AlertCandidate, AlertType

from ..base import CameraConfig, FrameContext
from .features import HOP, WINDOW, log_mel

log = logging.getLogger(__name__)
CLASSES = ["background", "firing", "scream", "glass_break", "firecracker"]
CUES = {"firing": ("flash", "run"), "scream": ("run",), "glass_break": ()}


def fuse(p_audio: float, cues: dict[str, float], weights: dict[str, float]) -> float:
    q = 1.0 - weights.get("audio", 0.9) * p_audio
    for name, p in cues.items():
        q *= 1.0 - weights.get(name, 0.5) * p
    return 1.0 - q


class AudioPlugin:
    name = "audio"
    version = "audio-cnn-v1"
    needs = frozenset({"frame"})

    def __init__(self) -> None:
        self.reader: Any = None
        self.session: Any = None
        self.classes = list(CLASSES)
        self.weights = {"audio": 0.9, "flash": 0.5, "run": 0.5}
        self.threshold = 0.6
        self.cooldown_s = 10.0
        self._pending = np.zeros(0, np.float32)
        self._last: dict[str, float] = {}
        self._prev_brightness: float | None = None
        self._speeds: deque[tuple[float, float]] = deque(maxlen=600)

    def configure(self, site_cfg: dict[str, Any], camera_cfg: CameraConfig) -> None:
        cfg = (site_cfg.get("plugins") or {}).get(self.name, {}) or {}
        self.weights.update({k: float(v) for k, v in (cfg.get("weights") or {}).items()})
        self.threshold = float(cfg.get("threshold", self.threshold))
        if not camera_cfg.audio:
            return
        model = Path(str(cfg.get("model", "models/audio_events.onnx")))
        if not model.exists():
            log.warning("audio: no model at %s (jikimi_ml.train.train_audio); audio events off", model)
            return
        import onnxruntime as ort

        self.session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
        meta = model.with_suffix(".json")
        if meta.exists():
            self.classes = list(json.loads(meta.read_text(encoding="utf-8"))["classes"])
        source = str(camera_cfg.extra.get("audio_source") or camera_cfg.source or "")
        if source.startswith("file:"):
            source = source[5:]
        if source and not source.startswith(("sim:", "webcam:")):
            from ...ingest.audio_source import AudioReader

            self.reader = AudioReader(source)

    def probabilities(self, window: np.ndarray) -> dict[str, float]:
        logits = self.session.run(None, {"mel": log_mel(window)[None, None]})[0][0]
        e = np.exp(logits - logits.max())
        p = e / e.sum()
        return {c: float(v) for c, v in zip(self.classes, p, strict=True)}

    def _flash(self, frame: np.ndarray | None) -> float:
        if frame is None:
            return 0.0
        b = float(frame[::8, ::8].mean())
        prev, self._prev_brightness = self._prev_brightness, b
        if prev is None or prev > 90:  # a flash is only visible in the dark
            return 0.0
        return float(np.clip((b - prev - 15.0) / 40.0, 0.0, 1.0))

    def _run(self, ctx: FrameContext) -> float:
        peds = ctx.pedestrians
        if len(peds) < 3:
            return 0.0
        now = float(np.mean([t.speed for t in peds]))
        base = [s for t, s in self._speeds if ctx.ts - t <= 60.0]
        self._speeds.append((ctx.ts, now))
        if len(base) < 20:
            return 0.0
        ratio = now / max(statistics.median(base), 1e-3)
        return float(np.clip((ratio - 1.5) / 2.0, 0.0, 1.0))

    def on_step(self, ctx: FrameContext) -> list[AlertCandidate]:
        cues = {"flash": self._flash(ctx.frame), "run": self._run(ctx)}
        if self.session is None or self.reader is None:
            return []
        x = np.concatenate([self._pending, self.reader.take()])
        if len(x) < WINDOW:
            self._pending = x
            return []
        n = 1 + (len(x) - WINDOW) // HOP
        out: list[AlertCandidate] = []
        for k in range(n):
            probs = self.probabilities(x[k * HOP : k * HOP + WINDOW])
            ctx.audio_scores.update(probs)
            best, score, p_audio = None, 0.0, 0.0
            for cls, uses in CUES.items():
                p = fuse(probs.get(cls, 0.0), {c: cues[c] for c in uses}, self.weights)
                if p > score:
                    best, score, p_audio = cls, p, probs.get(cls, 0.0)
            if best is None or score < self.threshold or ctx.ts - self._last.get(best, -1e18) < self.cooldown_s:
                continue
            self._last[best] = ctx.ts
            out.append(
                ctx.make_alert(
                    AlertType.AUDIO,
                    score,
                    ctx.ts - WINDOW / 16000.0,
                    features={
                        "sound": best,
                        "p_audio": round(p_audio, 3),
                        "p_flash": round(cues["flash"], 3),
                        "p_crowd_run": round(cues["run"], 3),
                        "p_firecracker": round(probs.get("firecracker", 0.0), 3),
                        "dedupe_key": f"audio:{best}",
                    },
                    model_versions={"audio_event": self.version},
                )
            )
        self._pending = x[n * HOP :]
        return out

    def state_dict(self) -> dict[str, Any]:
        return {}

    def load_state(self, state: dict[str, Any]) -> None:
        return None
