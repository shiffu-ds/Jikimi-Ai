from __future__ import annotations

from typing import Any

import numpy as np
from jikimi_contracts import AlertType
from jikimi_edge.analytics.audio.features import HOP, RATE, WINDOW, log_mel, windows
from jikimi_edge.analytics.audio.plugin import CLASSES, AudioPlugin, fuse
from jikimi_edge.analytics.base import FrameContext


def test_log_mel_is_yamnet_shaped_and_windows_overlap() -> None:
    x = np.random.default_rng(0).normal(0, 0.1, 3 * RATE).astype(np.float32)
    assert log_mel(x[:WINDOW]).shape == (96, 64)
    ws = windows(x)
    assert len(ws) == 1 + (len(x) - WINDOW) // HOP and all(len(w) == WINDOW for w in ws)


def test_noisy_or_fusion() -> None:
    w = {"audio": 0.9, "flash": 0.5, "run": 0.5}
    assert fuse(0.0, {}, w) == 0.0
    assert abs(fuse(0.5, {}, w) - 0.45) < 1e-9
    assert fuse(0.5, {"flash": 1.0}, w) > fuse(0.5, {}, w)  # a muzzle flash adds evidence
    assert fuse(1.0, {"flash": 1.0, "run": 1.0}, w) <= 1.0


class _Reader:
    def __init__(self, seconds: float) -> None:
        self.x = np.zeros(int(seconds * RATE), np.float32)

    def take(self) -> np.ndarray:
        x, self.x = self.x, np.zeros(0, np.float32)
        return x


class _Session:
    def __init__(self, cls: str) -> None:
        self.logits = np.full((1, len(CLASSES)), -4.0, np.float32)
        self.logits[0, CLASSES.index(cls)] = 4.0

    def run(self, _: Any, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
        assert feeds["mel"].shape == (1, 1, 96, 64)
        return [self.logits]


def _plugin(cls: str) -> AudioPlugin:
    p = AudioPlugin()
    p.session, p.reader = _Session(cls), _Reader(2.0)
    return p


def test_a_gunshot_raises_one_audio_alert_and_a_firecracker_none() -> None:
    dark = np.full((90, 160, 3), 30, np.uint8)
    ctx = FrameContext(site_id="s", camera_id="cam", ts=100.0, frame=dark)
    alerts = _plugin("firing").on_step(ctx)
    assert len(alerts) == 1 and alerts[0].type == AlertType.AUDIO  # several windows, one alert (cooldown)
    assert alerts[0].features["sound"] == "firing" and alerts[0].raw_score >= 0.6
    assert ctx.audio_scores["firing"] > 0.9
    quiet = FrameContext(site_id="s", camera_id="cam", ts=100.0, frame=dark)
    assert _plugin("firecracker").on_step(quiet) == []  # the wedding is not an incident
    assert _plugin("background").on_step(FrameContext(site_id="s", camera_id="cam", ts=1.0, frame=dark)) == []
