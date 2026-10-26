"""Parked two-wheeler theft: a bike that stood for a while is worked on, then taken.

A bike that stands still without riders for ``parked_min_s`` is parked. Every person at it is
timed (and how long they crouch), as is any other bike that waits nearby with its rider on it
while someone is at the parked one. When the parked bike moves off, that departure is one
calibration unit, scored from: how long the person who took it spent at it first, how long they
crouched (breaking a lock vs. opening a disc lock), a waiting accomplice bike, and whether it was
pushed instead of ridden (the steering lock would not open). Owners come back, open the lock in a
few seconds and ride off: that is the everyday case, and a stuck lock the honest hard one. The
alert asks the guard to check whether it is the owner; it never says it is not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from jikimi_contracts import TWO_WHEELERS, AlertCandidate, AlertType, ObjectSummary, Track

from ..base import CameraConfig, FrameContext
from ..geometry import box_gap
from ..people import People, is_night


@dataclass
class _Bike:
    track_id: int
    still_since: float
    x: float
    y: float
    last_ts: float
    color: str | None = None
    near_s: dict[int, float] = field(default_factory=dict)
    low_s: dict[int, float] = field(default_factory=dict)
    near_last: dict[int, float] = field(default_factory=dict)
    accomplice_s: float = 0.0
    left_at: float | None = None
    pushed_s: float = 0.0
    ridden_s: float = 0.0
    done: bool = False


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def score(tamper_s: float, low_s: float, accomplice: bool, pushed: bool) -> float:
    z = -4.5 + 0.12 * min(tamper_s, 40.0) + 1.2 * min(low_s / 10.0, 1.5) + 2.0 * accomplice + 1.2 * pushed
    return 1.0 / (1.0 + math.exp(-z))


class VehicleTheftPlugin:
    name = "vehicle_theft"
    version = "theft-rules-v1"
    needs = frozenset({"tracks"})

    def __init__(self) -> None:
        self.min_score = 0.3
        self.parked_min_s = 60.0
        self.people = People()
        self._bikes: dict[int, _Bike] = {}
        self.score_logs: dict[str, dict[str, float]] | None = None

    def configure(self, site_cfg: dict[str, Any], camera_cfg: CameraConfig) -> None:
        cfg = (site_cfg.get("plugins") or {}).get(self.name, {}) or {}
        self.min_score = float(cfg.get("min_score", self.min_score))
        self.parked_min_s = float(cfg.get("parked_min_s", self.parked_min_s))

    def on_step(self, ctx: FrameContext) -> list[AlertCandidate]:
        ts = ctx.ts
        # everyone, riders included: crouching at a parked bike looks like sitting on it to the
        # rider association, and a parked bike has no riders that matter
        persons = [t for t in ctx.tracks if t.cls == "person"]
        people = self.people.update(persons, ctx.tracks, ts)
        bikes = [t for t in ctx.tracks if t.cls in TWO_WHEELERS]
        out: list[AlertCandidate] = []
        for t in bikes:
            riders = ctx.riders_of.get(t.track_id, [])
            fx, fy = t.foot
            b = self._bikes.get(t.track_id)
            if b is None:
                b = self._bikes[t.track_id] = _Bike(t.track_id, ts, fx, fy, ts)
            b.last_ts = ts
            if isinstance(t.attributes.get("color"), str):
                b.color = str(t.attributes["color"])
            moved = math.hypot(fx - b.x, fy - b.y) > 0.6 * max(t.width, 1e-3)
            if not self._parked(b, ts):
                if moved or riders:  # in traffic or someone on it: the still clock restarts
                    b.still_since, b.x, b.y = ts, fx, fy
                continue
            if b.left_at is None:
                self._watch(b, t, people, bikes, ctx, ts)
                if moved:
                    b.left_at = ts
                continue
            if b.done:
                continue
            if riders:
                b.ridden_s += 0.2
            elif any(p.track is not None and box_gap(p.track.bbox, t.bbox) <= 0.4 * p.size for p in people):
                b.pushed_s += 0.2
            if ts - b.left_at >= 1.5:
                cand = self._evaluate(ctx, b)
                if cand is not None:
                    out.append(cand)
        for tid, b in list(self._bikes.items()):
            if ts - b.last_ts > 2.0:
                if b.left_at is not None and not b.done:  # left the view right after moving
                    cand = self._evaluate(ctx, b)
                    if cand is not None:
                        out.append(cand)
                del self._bikes[tid]
        return out

    def _parked(self, b: _Bike, ts: float) -> bool:
        return (b.left_at or ts) - b.still_since >= self.parked_min_s

    def _watch(
        self, b: _Bike, bike: Track, people: list[Any], bikes: list[Track], ctx: FrameContext, ts: float
    ) -> None:
        if b.left_at is not None:
            return
        anyone = False
        for p in people:
            if p.track is None or not 1.3 <= p.size / max(bike.height, 1e-3) <= 3.2:
                continue
            if box_gap(p.track.bbox, bike.bbox) > 0.35 * p.size:
                continue
            last = b.near_last.get(p.track_id)
            dt = min(ts - last, 0.5) if last is not None else 0.2
            b.near_last[p.track_id] = ts
            b.near_s[p.track_id] = b.near_s.get(p.track_id, 0.0) + dt
            if p.posture != "upright":
                b.low_s[p.track_id] = b.low_s.get(p.track_id, 0.0) + dt
            anyone = True
        if not anyone:
            return
        w = max(bike.width, 1e-3)
        for o in bikes:  # another bike waiting close by with its rider on, engine running
            if o.track_id == bike.track_id or not ctx.riders_of.get(o.track_id):
                continue
            ox, oy = o.foot
            if abs(ox - b.x) <= 6 * w and abs(oy - b.y) <= 1.5 * bike.height and o.speed < 0.15 * w:
                b.accomplice_s += 0.2
                break

    def _evaluate(self, ctx: FrameContext, b: _Bike) -> AlertCandidate | None:
        b.done = True
        recent = {pid: s for pid, s in b.near_s.items() if (b.left_at or ctx.ts) - b.near_last[pid] <= 90.0}
        taker = max(recent, key=lambda k: recent[k]) if recent else None
        tamper = recent.get(taker, 0.0) if taker is not None else 0.0
        low = b.low_s.get(taker, 0.0) if taker is not None else 0.0
        accomplice = b.accomplice_s >= 4.0
        pushed = b.pushed_s > b.ridden_s and b.pushed_s >= 0.6
        s = score(tamper, low, accomplice, pushed)
        if self.score_logs is not None:
            self.score_logs.setdefault("vehicle_theft", {})[f"{b.track_id}-{b.still_since:.0f}"] = s
        if s < self.min_score:
            return None
        hist = ctx.histories.get(b.track_id)
        features = {
            "vehicle": "motorcycle",
            "color": b.color,
            "parked_min": max(1, round(((b.left_at or ctx.ts) - b.still_since) / 60)),
            "tamper_s": round(tamper),
            "crouched_s": round(low),
            "accomplice": accomplice,
            "pushed": pushed,
            "night": is_night(ctx.ts, ctx.tz_offset_s),
            "calibration_key": "vehicle_theft",
            "dedupe_key": f"theft-{b.track_id}",
        }
        return ctx.make_alert(
            AlertType.VEHICLE_THEFT,
            s,
            b.left_at - tamper if b.left_at is not None else ctx.ts,
            track_ids=[b.track_id] + ([taker] if taker is not None else []),
            entity_id=getattr(hist, "entity_id", None),
            features=features,
            objects=[ObjectSummary(type="motorcycle", color=b.color, riders=0 if pushed else 1)],
            model_versions={"vehicle_theft": self.version},
        )

    def state_dict(self) -> dict[str, Any]:
        return {}

    def load_state(self, state: dict[str, Any]) -> None:
        return None
