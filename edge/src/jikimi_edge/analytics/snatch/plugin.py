"""Snatch detection plugin (F3). One candidate per (bike, pedestrian) encounter."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jikimi_contracts import AlertCandidate, AlertType, ObjectSummary

from ..base import CameraConfig, FrameContext
from . import heuristic
from .pair_builder import Pair, PairSample, build_samples

log = logging.getLogger(__name__)


class SnatchPlugin:
    name = "snatch"
    version = "heuristic-v1"
    needs = frozenset({"tracks", "poses"})

    def __init__(self) -> None:
        self.min_score = 0.3
        self.min_contact = 0.5
        """Gate: only encounters where a rider's hand reaches the pedestrian become candidates..."""
        self.min_close_s = 0.15
        """...and stays near for more than one frame: a single-frame brush is keypoint jitter or a
        drive-by, not contact (the one false alarm in the simulator F7 evaluation was exactly that)."""
        self.reach = 1.2
        self.release_after_s = 1.0
        self._pairs: dict[tuple[int, int], Pair] = {}
        self._model: Any = None
        self.score_log: dict[str, float] | None = None

    def configure(self, site_cfg: dict[str, Any], camera_cfg: CameraConfig) -> None:
        cfg = (site_cfg.get("plugins") or {}).get(self.name, {}) or {}
        self.min_score = float(cfg.get("min_score", self.min_score))
        self.min_contact = float(cfg.get("min_contact", self.min_contact))
        self.min_close_s = float(cfg.get("min_close_s", self.min_close_s))
        model_path = cfg.get("model")
        if model_path and Path(model_path).exists():
            from .stgcn_infer import StgcnScorer

            try:
                self._model = StgcnScorer(model_path, cfg.get("backend", "onnxruntime"))
                self.version = f"stgcn:{Path(model_path).stem}"
            except Exception:  # model optional: fall back to the B1 heuristic
                log.exception("ST-GCN model failed to load; using heuristic")

    def on_step(self, ctx: FrameContext) -> list[AlertCandidate]:
        out: list[AlertCandidate] = []
        seen: set[tuple[int, int]] = set()
        for bike, ped, rider, sample in build_samples(
            ctx.tracks, ctx.riders_of, ctx.pedestrians, ctx.poses, ctx.ts, self.reach
        ):
            key = (bike.track_id, ped.track_id)
            seen.add(key)
            pair = self._pairs.get(key)
            if pair is None:
                hist = ctx.histories.get(bike.track_id)
                pair = Pair(
                    bike_id=bike.track_id,
                    ped_id=ped.track_id,
                    rider_id=rider.track_id if rider else None,
                    entity_id=bike.entity_id,
                    first_ts=ctx.ts,
                    last_ts=ctx.ts,
                    bike_median_speed=hist.median_speed() if hist is not None else 0.0,
                )
                self._pairs[key] = pair
            pair.last_ts = ctx.ts
            pair.samples.append(sample)
            # departure while still visible: the bike pulled away fast after contact
            if not pair.emitted and len(pair.samples) >= 3:
                f = heuristic.extract(list(pair.samples), pair.bike_median_speed)
                if self._contact(f) and f.depart_accel > 0.8:  # clear getaway: alert without waiting
                    cand = self._evaluate(ctx, pair, bike)
                    if cand is not None:
                        out.append(cand)
        for key, pair in list(self._pairs.items()):
            if key in seen:
                continue
            # keep following the bike after the pair separates (departure speed matters)
            bike = ctx.track(pair.bike_id)
            if bike is not None and ctx.ts - pair.last_ts <= 2.0 and pair.samples:
                last = pair.samples[-1]
                pair.samples.append(
                    PairSample(
                        ts=ctx.ts,
                        hand_dist=max(last.hand_dist, 2.0),
                        gap=last.gap,
                        bike_speed=bike.speed,
                        ped_center=last.ped_center,
                        ped_height=last.ped_height,
                        rider_kpts=None,
                        ped_kpts=None,
                    )
                )
            if ctx.ts - pair.last_ts > self.release_after_s + 1.0:
                if not pair.emitted:
                    cand = self._evaluate(ctx, pair, bike)
                    if cand is not None:
                        out.append(cand)
                del self._pairs[key]
        return out

    def _contact(self, f: heuristic.SnatchFeatures) -> bool:
        return f.contact >= self.min_contact and f.close_duration_s >= self.min_close_s

    def _evaluate(self, ctx: FrameContext, pair: Pair, bike: Any) -> AlertCandidate | None:
        samples = list(pair.samples)
        feats = heuristic.extract(samples, pair.bike_median_speed)
        s = heuristic.score(feats)
        if self._model is not None:
            model_s = self._model(samples)
            if model_s is not None:
                s = model_s
        pair.emitted = True
        if self.score_log is not None:
            key = f"{pair.bike_id}-{pair.ped_id}"
            self.score_log[key] = max(s, self.score_log.get(key, 0.0))
        if s < self.min_score or not self._contact(feats):
            return None
        riders = len(ctx.riders_of.get(pair.bike_id, [])) or 2
        color = bike.attributes.get("color") if bike is not None else None
        features = {
            **feats.as_dict(),
            "riders": riders,
            "vehicle": "motorcycle",
            "color": color if isinstance(color, str) else None,
            "dedupe_key": f"{pair.bike_id}-{pair.ped_id}",
        }
        return ctx.make_alert(
            AlertType.SNATCH,
            s,
            pair.first_ts,
            track_ids=[t for t in (pair.bike_id, pair.rider_id, pair.ped_id) if t is not None],
            entity_id=pair.entity_id,
            features=features,
            objects=[ObjectSummary(type="motorcycle", color=features["color"], riders=riders)],
            model_versions={"snatch": self.version},
        )

    def state_dict(self) -> dict[str, Any]:
        return {}

    def load_state(self, state: dict[str, Any]) -> None:
        return None
