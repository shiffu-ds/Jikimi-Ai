"""Analytics plugin contract (plan Section 7.6).

Plugins are registered via the ``jikimi.analytics`` entry point group and switched on by name
in the site config. The runtime only computes what enabled plugins ``need`` (no pose model is
loaded if no plugin needs poses) - important for the 12 GB laptop.

Plugins must use ``ctx.ts`` (frame time), never the wall clock, so replays and golden tests run
faster than real time and give identical results.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import numpy as np
from jikimi_common.ids import uuid7
from jikimi_contracts import AlertCandidate, AlertType, ObjectSummary, Pose, Track


@dataclass
class ZoneConfig:
    id: str
    polygon: list[list[float]]
    name: str | None = None
    name_ur: str | None = None


@dataclass
class CameraConfig:
    id: str
    name: str | None = None
    name_ur: str | None = None
    name_roman: str | None = None
    source: str | None = None
    zones: list[ZoneConfig] = field(default_factory=list)
    audio: bool = False
    plugins: list[str] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class FrameContext:
    site_id: str
    camera_id: str
    ts: float
    frame: np.ndarray | None
    tracks: list[Track] = field(default_factory=list)
    poses: dict[int, Pose] = field(default_factory=dict)
    audio_scores: dict[str, float] = field(default_factory=dict)
    mode: str = "normal"
    riders_of: dict[int, list[int]] = field(default_factory=dict)
    """motorcycle track_id -> rider person track_ids (computed by the runtime)."""
    rider_ids: frozenset[int] = frozenset()
    histories: Mapping[int, Any] = field(default_factory=dict)
    """track_id -> ``TrackHistory`` (motion, zones, dwell) maintained by the runtime."""
    zone_events: list[tuple[int, str, str]] = field(default_factory=list)
    """``(track_id, zone_id, "enter" | "exit")`` that happened on this frame."""
    new_track_ids: frozenset[int] = frozenset()
    tz_offset_s: float = 18000.0
    """Site UTC offset (Asia/Karachi = +5 h) for schedule checks without tz lookups per frame."""

    @property
    def pedestrians(self) -> list[Track]:
        return [t for t in self.tracks if t.cls == "person" and t.track_id not in self.rider_ids]

    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.ts, UTC)

    def track(self, track_id: int) -> Track | None:
        for t in self.tracks:
            if t.track_id == track_id:
                return t
        return None

    def make_alert(
        self,
        type: AlertType,
        raw_score: float,
        ts_start: float,
        *,
        track_ids: list[int] | None = None,
        entity_id: str | None = None,
        zone_id: str | None = None,
        features: dict[str, Any] | None = None,
        objects: list[ObjectSummary] | None = None,
        model_versions: dict[str, str] | None = None,
    ) -> AlertCandidate:
        return AlertCandidate(
            alert_id=uuid7(),
            site_id=self.site_id,
            camera_id=self.camera_id,
            type=type,
            ts_start=datetime.fromtimestamp(min(ts_start, self.ts), UTC),
            ts_end=self.dt(),
            raw_score=float(raw_score),
            mode=self.mode,
            zone_id=zone_id,
            track_ids=track_ids or [],
            entity_id=entity_id,
            features=features or {},
            objects=objects or [],
            model_versions=model_versions or {},
        )


@runtime_checkable
class AnalyticsPlugin(Protocol):
    name: str
    version: str
    needs: frozenset[str]
    """Subset of ``{"frame", "tracks", "poses", "audio"}``."""

    def configure(self, site_cfg: dict[str, Any], camera_cfg: CameraConfig) -> None: ...
    def on_step(self, ctx: FrameContext) -> list[AlertCandidate]: ...
    def state_dict(self) -> dict[str, Any]: ...
    def load_state(self, state: dict[str, Any]) -> None: ...
