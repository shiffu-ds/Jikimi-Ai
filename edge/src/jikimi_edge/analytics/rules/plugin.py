"""Rules plugin (F11 edge side): runs admin-approved DSL rules.

Two sources: files in ``edge/config/rules/`` (shipped with the site config) and the server's
signed bundle (``RuleSync``), which wins for the same ``rule_id``. Only rules with
``approved_by`` set are ever loaded.

Condition semantics: ``dwell_seconds_gt`` alone fires once per track that stays longer;
``count_gt`` alone fires when more objects are present at once; both together fire when more
than ``count_gt`` objects have *each* stayed longer than ``dwell_seconds_gt``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from jikimi_contracts import AlertCandidate, AlertType, ObjectSummary
from jikimi_contracts.rules_dsl import Rule
from pydantic import ValidationError

from ..base import CameraConfig, FrameContext
from ..geometry import point_in_polygon
from .dsl_eval import schedule_active

log = logging.getLogger(__name__)
COUNT_REFRACTORY_S = 300.0  # a count rule fires at most once per 5 min


class RulesPlugin:
    name = "rules"
    version = "dsl-v1"
    needs = frozenset({"tracks"})

    def __init__(self) -> None:
        self.rules: list[Rule] = []
        self.static_rules: list[Rule] = []
        self.remote_rules: list[Rule] = []
        self._zones: dict[str, list[list[float]]] = {}
        self._fired: dict[tuple[str, int], float] = {}
        self._count_fired: dict[str, float] = {}
        self.camera_id = ""

    def configure(self, site_cfg: dict[str, Any], camera_cfg: CameraConfig) -> None:
        self.camera_id = camera_cfg.id
        self._zones = {z.id: z.polygon for z in camera_cfg.zones}
        rules_dir = Path((site_cfg.get("plugins") or {}).get(self.name, {}).get("dir", "edge/config/rules"))
        self.static_rules = []
        if rules_dir.exists():
            for path in sorted(rules_dir.glob("*.json")):
                try:
                    rule = Rule.model_validate(json.loads(path.read_text(encoding="utf-8")))
                except (ValidationError, json.JSONDecodeError):
                    log.warning("invalid rule file skipped", extra={"path": str(path)})
                    continue
                if rule.approved_by and camera_cfg.id in rule.when.camera_ids:
                    self.static_rules.append(rule)
        self._refresh()

    def add_rule(self, rule: Rule) -> None:
        self.static_rules.append(rule)
        self._refresh()

    def set_remote(self, rules: list[Rule]) -> None:
        """Server-approved rules (signed bundle); replaces the previous remote set."""
        self.remote_rules = [r for r in rules if r.approved_by and self.camera_id in r.when.camera_ids]
        self._refresh()

    def _refresh(self) -> None:
        remote = {r.rule_id for r in self.remote_rules}
        self.rules = self.remote_rules + [r for r in self.static_rules if r.rule_id not in remote]
        active = {r.rule_id for r in self.rules}
        self._fired = {k: v for k, v in self._fired.items() if k[0] in active}
        self._count_fired = {k: v for k, v in self._count_fired.items() if k in active}

    def on_step(self, ctx: FrameContext) -> list[AlertCandidate]:
        out: list[AlertCandidate] = []
        for rule in self.rules:
            if not schedule_active(rule, ctx.ts, ctx.tz_offset_s):
                continue
            w = rule.when
            poly = self._zones.get(w.zone) if w.zone else None
            if w.zone and poly is None:
                continue
            matching = [
                t
                for t in ctx.tracks
                if t.cls == w.object.type
                and (w.object.color is None or t.attributes.get("color") == w.object.color)
                and (poly is None or point_in_polygon(t.foot, poly))
            ]
            dwell_gt, count_gt = w.condition.dwell_seconds_gt, w.condition.count_gt
            dwell: dict[int, float] = {}
            if dwell_gt is not None:
                for t in matching:
                    hist = ctx.histories.get(t.track_id)
                    dwell[t.track_id] = (
                        hist.dwell(w.zone, ctx.ts) if (hist is not None and w.zone) else ctx.ts - t.first_seen
                    )
                matching = [t for t in matching if dwell[t.track_id] > dwell_gt]
            if count_gt is None:
                for t in matching:
                    key = (rule.rule_id, t.track_id)
                    if key not in self._fired:
                        self._fired[key] = ctx.ts
                        d = dwell[t.track_id]
                        out.append(self._alert(ctx, rule, [t.track_id], {"dwell_s": round(d, 1)}, ctx.ts - d))
            elif len(matching) > count_gt:
                last = self._count_fired.get(rule.rule_id, -1e18)
                if ctx.ts - last > COUNT_REFRACTORY_S:
                    self._count_fired[rule.rule_id] = ctx.ts
                    ids = [t.track_id for t in matching]
                    out.append(self._alert(ctx, rule, ids, {"count": len(matching)}, ctx.ts))
        return out

    def _alert(
        self, ctx: FrameContext, rule: Rule, track_ids: list[int], obs: dict[str, Any], start: float
    ) -> AlertCandidate:
        features = {
            "rule_id": rule.rule_id,
            "rule_name_ur": rule.name_ur,
            "rule_name_en": rule.name_en,
            "rule_severity": rule.then.alert.severity.value,
            "notify": list(rule.then.alert.notify),
            "object": rule.when.object.type,
            "dedupe_key": f"{rule.rule_id}:{track_ids[0] if track_ids else ''}",
            **obs,
        }
        return ctx.make_alert(
            AlertType.RULE,
            1.0,
            start,
            track_ids=track_ids,
            zone_id=rule.when.zone,
            features=features,
            objects=[ObjectSummary(type=rule.when.object.type, count=max(1, len(track_ids)))],
            model_versions={"rules": f"{rule.rule_id}@v{rule.version}"},
        )

    def state_dict(self) -> dict[str, Any]:
        return {}

    def load_state(self, state: dict[str, Any]) -> None:
        return None
