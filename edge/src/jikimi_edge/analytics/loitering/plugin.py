"""Bike loitering early-warning plugin (F2 Tier 1: per-camera, rule-based).

Counts *passes* of the same two-wheeler (re-entries are linked by appearance re-ID), pillion
riders, slow-downs next to pedestrians and dwell, inside a sliding window (15 min default).
A candidate is emitted whenever a new event raises the score above ``min_score``; the conformal
router decides whether it is an alert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jikimi_contracts import TWO_WHEELERS, AlertCandidate, AlertType, ObjectSummary

from ..base import CameraConfig, FrameContext
from ..geometry import dist
from .score import loitering_score


@dataclass
class _Entity:
    entity_id: str
    cls: str
    passes: list[float] = field(default_factory=list)
    slowdowns: list[float] = field(default_factory=list)
    riders: list[int] = field(default_factory=list)
    track_ids: list[int] = field(default_factory=list)
    dwell_s: float = 0.0
    color: str | None = None
    zone_id: str | None = None
    last_seen: float = 0.0
    last_score: float = 0.0


class LoiteringPlugin:
    name = "loitering"
    version = "rule-v1"
    needs = frozenset({"tracks"})

    def __init__(self) -> None:
        self.window_s = 900.0
        self.min_score = 0.45
        self.min_passes = 2
        """Gate: a single pass is never loitering (keeps the candidate rate, and so FA/hour, low)."""
        self.slow_ratio = 0.3
        self.near_ped_heights = 1.8
        self.zone_ids: list[str] = []
        self._entities: dict[str, _Entity] = {}
        self.score_log: dict[str, float] | None = None
        """When set (calibration runs), the max score of every entity is recorded here."""

    def configure(self, site_cfg: dict[str, Any], camera_cfg: CameraConfig) -> None:
        cfg = (site_cfg.get("plugins") or {}).get(self.name, {}) or {}
        self.window_s = float(cfg.get("window_min", 15)) * 60.0
        self.min_score = float(cfg.get("min_score", self.min_score))
        self.min_passes = int(cfg.get("min_passes", self.min_passes))
        self.zone_ids = [z.id for z in camera_cfg.zones]
        wanted = cfg.get("zones")
        if wanted:
            self.zone_ids = [z for z in self.zone_ids if z in wanted]

    def on_step(self, ctx: FrameContext) -> list[AlertCandidate]:
        out: list[AlertCandidate] = []
        entries = {(tid, zid) for tid, zid, kind in ctx.zone_events if kind == "enter"}
        peds = ctx.pedestrians
        for t in ctx.tracks:
            if t.cls not in TWO_WHEELERS or t.entity_id is None:
                continue
            ent = self._entities.get(t.entity_id)
            if ent is None:
                ent = self._entities[t.entity_id] = _Entity(t.entity_id, t.cls)
            ent.last_seen = ctx.ts
            if t.track_id not in ent.track_ids:
                ent.track_ids.append(t.track_id)
            color = t.attributes.get("color")
            if isinstance(color, str):
                ent.color = color
            ent.riders.append(len(ctx.riders_of.get(t.track_id, [])))
            event = False
            if self.zone_ids:
                for zid in self.zone_ids:
                    if (t.track_id, zid) in entries:
                        ent.passes.append(ctx.ts)
                        ent.zone_id = zid
                        event = True
            elif t.track_id in ctx.new_track_ids:
                ent.passes.append(ctx.ts)
                event = True
            hist = ctx.histories.get(t.track_id)
            if hist is not None:
                med = hist.median_speed()
                if (
                    med > 0.02
                    and t.speed < self.slow_ratio * med
                    and self._near_pedestrian(t, peds)
                    and (not ent.slowdowns or ctx.ts - ent.slowdowns[-1] > 4.0)
                ):
                    ent.slowdowns.append(ctx.ts)
                    event = True
                if self.zone_ids:
                    ent.dwell_s = max(ent.dwell_s, max(hist.dwell(z, ctx.ts) for z in self.zone_ids))
            self._prune(ent, ctx.ts)
            if event:
                cand = self._candidate(ctx, ent)
                if cand is not None:
                    out.append(cand)
        self._forget(ctx.ts)
        return out

    def _near_pedestrian(self, bike: Any, peds: list[Any]) -> bool:
        bc = bike.center
        return any(dist(bc, p.center) < self.near_ped_heights * max(p.height, 0.05) for p in peds)

    def _prune(self, ent: _Entity, now: float) -> None:
        lo = now - self.window_s
        ent.passes = [t for t in ent.passes if t >= lo]
        ent.slowdowns = [t for t in ent.slowdowns if t >= lo]
        ent.riders = ent.riders[-600:]

    def _forget(self, now: float) -> None:
        for k in [k for k, e in self._entities.items() if now - e.last_seen > self.window_s]:
            del self._entities[k]

    def _candidate(self, ctx: FrameContext, ent: _Entity) -> AlertCandidate | None:
        riders = sorted(ent.riders)[len(ent.riders) // 2] if ent.riders else 0
        passes = len(ent.passes)
        score = loitering_score(passes, riders, len(ent.slowdowns), ent.dwell_s)
        if self.score_log is not None:
            self.score_log[ent.entity_id] = max(score, self.score_log.get(ent.entity_id, 0.0))
        if passes < self.min_passes or score < self.min_score or score <= ent.last_score:
            return None
        ent.last_score = score
        start = min(ent.passes + ent.slowdowns) if (ent.passes or ent.slowdowns) else ctx.ts
        features = {
            "passes": passes,
            "window_min": round(self.window_s / 60),
            "riders": riders,
            "slowdowns_near_ped": len(ent.slowdowns),
            "dwell_s": round(ent.dwell_s, 1),
            "vehicle": ent.cls,
            "color": ent.color,
        }
        return ctx.make_alert(
            AlertType.LOITERING,
            score,
            start,
            track_ids=list(ent.track_ids[-8:]),
            entity_id=ent.entity_id,
            zone_id=ent.zone_id,
            features=features,
            objects=[ObjectSummary(type=ent.cls, color=ent.color, riders=riders)],
            model_versions={"loitering": self.version},
        )

    def state_dict(self) -> dict[str, Any]:
        return {
            "entities": {
                k: {
                    "cls": e.cls,
                    "passes": e.passes,
                    "slowdowns": e.slowdowns,
                    "riders": e.riders[-50:],
                    "track_ids": e.track_ids[-8:],
                    "dwell_s": e.dwell_s,
                    "color": e.color,
                    "zone_id": e.zone_id,
                    "last_seen": e.last_seen,
                    "last_score": e.last_score,
                }
                for k, e in self._entities.items()
            }
        }

    def load_state(self, state: dict[str, Any]) -> None:
        self._entities = {}
        for k, v in (state.get("entities") or {}).items():
            self._entities[k] = _Entity(entity_id=k, **v)
