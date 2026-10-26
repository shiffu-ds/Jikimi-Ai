"""Crowd panic: many people suddenly break into a run *away from one place* (firing, a fight, an
attack, a fire). People running *to* something (a rickshaw, shelter from rain) converge instead.

Each person's run onset is a jump from their own pace of the last seconds to running speed. Onsets
within three seconds form a burst - one calibration unit - scored from how many started running,
what share of the people in view that is, and whether they spread out from a common point
(divergence) or went one way together. A scream or firing heard by the audio plugin on the same
camera adds to it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from jikimi_contracts import AlertCandidate, AlertType, ObjectSummary

from ..base import CameraConfig, FrameContext
from ..people import DEPTH, RUN, People, is_night, unit


@dataclass
class _Onset:
    track_id: int
    ts: float
    pos: tuple[float, float]
    size: float
    heading: tuple[float, float]


@dataclass
class _Burst:
    since: float
    visible: int
    onsets: dict[int, _Onset] = field(default_factory=dict)


def features(b: _Burst) -> dict[str, float]:
    ons = list(b.onsets.values())
    n = len(ons)
    if n < 2:
        return {"runners": n, "share": 0.0, "divergence": 0.0, "same_way": 0.0}
    size = sum(o.size for o in ons) / n
    cx, cy = sum(o.pos[0] for o in ons) / n, sum(o.pos[1] for o in ons) / n
    div = 0.0
    for o in ons:  # heading against the direction from the group's centre (ground units)
        away = unit(((o.pos[0] - cx) / size, DEPTH * (o.pos[1] - cy) / size))
        div += o.heading[0] * away[0] + o.heading[1] * away[1]
    sx, sy = sum(o.heading[0] for o in ons), sum(o.heading[1] for o in ons)
    return {
        "runners": n,
        "share": round(min(1.0, n / max(b.visible, n)), 2),
        "divergence": round(div / n, 2),
        "same_way": round(math.hypot(sx, sy) / n, 2),
    }


def score(f: dict[str, float], audio: float = 0.0) -> float:
    z = (
        -6.0
        + 0.6 * min(f["runners"], 10)
        + 2.0 * f["share"]
        + 2.5 * f["divergence"]
        - 1.5 * f["same_way"]
        + 1.5 * audio
    )
    return 1.0 / (1.0 + math.exp(-z))


class CrowdPlugin:
    name = "crowd"
    version = "crowd-rules-v1"
    needs = frozenset({"tracks"})

    def __init__(self) -> None:
        self.min_score = 0.3
        self.min_runners = 3
        self.burst_s = 3.0
        self.people = People()
        self._last_onset: dict[int, float] = {}
        self._burst: _Burst | None = None
        self.score_logs: dict[str, dict[str, float]] | None = None

    def configure(self, site_cfg: dict[str, Any], camera_cfg: CameraConfig) -> None:
        cfg = (site_cfg.get("plugins") or {}).get(self.name, {}) or {}
        self.min_score = float(cfg.get("min_score", self.min_score))
        self.min_runners = int(cfg.get("min_runners", self.min_runners))

    def on_step(self, ctx: FrameContext) -> list[AlertCandidate]:
        ts = ctx.ts
        people = self.people.update(ctx.pedestrians, ctx.tracks, ts)
        for p in people:
            base = p.baseline_speed(ts, skip_s=1.5, span_s=8.0)
            if base is None or p.speed < RUN or p.speed < 2.2 * base + 0.3:
                continue
            if ts - self._last_onset.get(p.track_id, -1e9) < 10.0:
                continue
            self._last_onset[p.track_id] = ts
            if self._burst is None:
                self._burst = _Burst(ts, len(people))
            self._burst.onsets[p.track_id] = _Onset(p.track_id, ts, p.pos, p.size, unit(p.velocity()))
        b = self._burst
        if b is None or ts - b.since < self.burst_s:
            return []
        self._burst = None
        if len(b.onsets) < 2:
            return []
        f = features(b)
        audio = max((v for k, v in ctx.audio_scores.items() if k in ("firing", "scream")), default=0.0)
        s = score(f, audio)
        if self.score_logs is not None:
            self.score_logs.setdefault("crowd_panic", {})[f"{b.since:.1f}"] = s
        if f["runners"] < self.min_runners or s < self.min_score:
            return []
        heard = None
        if audio >= 0.5:
            heard = "firing" if ctx.audio_scores.get("firing", 0.0) >= ctx.audio_scores.get("scream", 0.0) else "scream"
        features_ = {
            **f,
            "heard": heard,
            "night": is_night(ts, ctx.tz_offset_s),
            "calibration_key": "crowd_panic",
            "dedupe_key": f"crowd-{b.since:.0f}",
        }
        return [
            ctx.make_alert(
                AlertType.CROWD_PANIC,
                s,
                b.since,
                track_ids=sorted(b.onsets),
                features=features_,
                objects=[ObjectSummary(type="person", count=int(f["runners"]))],
                model_versions={"crowd_panic": self.version},
            )
        ]

    def state_dict(self) -> dict[str, Any]:
        return {}

    def load_state(self, state: dict[str, Any]) -> None:
        return None
