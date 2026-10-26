"""Person in danger (safety of anyone on foot): signs that someone is about to be, or is being,
hurt or taken - the moments before an assault, not only after it.

Patterns (``features.pattern``): ``following`` (kept a few steps behind, stopping and hurrying with
them), ``surrounded`` (closed in on from several sides at once), ``struggle`` (two bodies pushed
and pulled about), ``dragged`` (moved off while held low or fighting it), ``forced_into_vehicle``
(disappeared into a car after that, and it drove off) and ``fall`` (went from upright to lying in a
moment and stayed down).

Behaviour only, by design: nobody's gender, age, clothing or identity is estimated or used, so the
same patterns protect anyone, and a couple or a family walking together is not "suspicious". The
system cannot know intent; it points a human at a situation worth a look, early. Night and an
empty street raise the severity, not the score: the p-value says how unusual the behaviour is,
the context says how bad it would be.
"""

from __future__ import annotations

from typing import Any

from jikimi_contracts import AlertCandidate, AlertType, ObjectSummary

from ..base import CameraConfig, FrameContext
from ..people import People, is_night, others_near
from .patterns import Boarding, Contact, Fall, Finding, Following, Surrounded


class PersonSafetyPlugin:
    name = "person_safety"
    version = "safety-rules-v1"
    needs = frozenset({"tracks"})

    def __init__(self) -> None:
        self.min_score = 0.2
        self.patterns_on = {"following", "surrounded", "struggle", "dragged", "forced_into_vehicle", "fall"}
        self.people = People()
        self.following = Following()
        self.surrounded = Surrounded()
        self.contact = Contact()
        self.boarding = Boarding(self.contact)
        self.fall = Fall(self.contact)
        self.ignore_zones: set[str] = set()
        self._zones: dict[str, Any] = {}
        self.score_logs: dict[str, dict[str, float]] | None = None

    def configure(self, site_cfg: dict[str, Any], camera_cfg: CameraConfig) -> None:
        cfg = (site_cfg.get("plugins") or {}).get(self.name, {}) or {}
        self.min_score = float(cfg.get("min_score", self.min_score))
        if cfg.get("patterns"):
            self.patterns_on = set(cfg["patterns"])
        # e.g. a stall where customers stand all round the vendor: no "surrounded" there
        self.ignore_zones = set(cfg.get("ignore_surrounded_zones") or [])
        self._zones = {z.id: z.polygon for z in camera_cfg.zones if z.id in self.ignore_zones}

    def on_step(self, ctx: FrameContext) -> list[AlertCandidate]:
        if self.score_logs is not None and self.following.log is None:
            self._attach_logs(self.score_logs)
        ts = ctx.ts
        self.people.update(ctx.pedestrians, ctx.tracks, ts)
        findings: list[Finding] = []
        findings += self.contact.step(self.people, ts)  # first: boarding and falls read its contacts
        findings += self.following.step(self.people, ts)
        findings += self.surrounded.step(self.people, ts)
        findings += self.boarding.step(self.people, ts, ctx.tracks, ctx.new_track_ids)
        findings += self.fall.step(self.people, ts)
        out = []
        for f in findings:
            if f.pattern not in self.patterns_on or f.score < self.min_score:
                continue
            if f.pattern == "surrounded" and self._in_ignored_zone(f.centre):
                continue
            out.append(self._alert(ctx, f))
        return out

    def _attach_logs(self, logs: dict[str, dict[str, float]]) -> None:
        for p in (self.following, self.surrounded, self.contact, self.boarding, self.fall):
            p.log = logs.setdefault(f"person_in_danger_{p.name if p.name != 'contact' else 'struggle'}", {})
        self.contact.drag_log = logs.setdefault("person_in_danger_dragged", {})

    def _in_ignored_zone(self, track_id: int) -> bool:
        from ..geometry import point_in_polygon

        p = self.people.by_id.get(track_id)
        return p is not None and any(point_in_polygon(p.pos, poly) for poly in self._zones.values())

    def _alert(self, ctx: FrameContext, f: Finding) -> AlertCandidate:
        centre = self.people.by_id.get(f.centre)
        alone = centre is not None and others_near(self.people.current, centre, set(f.track_ids)) == 0
        features = {
            "pattern": f.pattern,
            **f.features,
            "people": len([t for t in f.track_ids if t in self.people.by_id]) or 1,
            "night": is_night(ctx.ts, ctx.tz_offset_s),
            "alone": alone,
            "calibration_key": f"person_in_danger_{f.pattern}",
            "dedupe_key": f.key,
        }
        objects = [ObjectSummary(type="person", count=max(1, features["people"]))]
        if f.pattern == "forced_into_vehicle":
            objects.append(ObjectSummary(type=str(f.features.get("vehicle") or "car")))
        return ctx.make_alert(
            AlertType.PERSON_DANGER,
            f.score,
            f.start_ts,
            track_ids=f.track_ids,
            features=features,
            objects=objects,
            model_versions={"person_in_danger": self.version},
        )

    def state_dict(self) -> dict[str, Any]:
        return {}

    def load_state(self, state: dict[str, Any]) -> None:
        return None
