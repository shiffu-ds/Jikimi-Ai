"""Per-camera track histories: motion, zones, colour, riders and anonymous entity linking."""

from __future__ import annotations

import statistics
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from jikimi_contracts import TWO_WHEELERS, ObjectSummary, Track

from ..analytics.base import CameraConfig
from ..analytics.geometry import point_in_polygon, union
from .color import color_name, frame_reference
from .reid import EntityLinker, _blend, descriptor

ThumbFn = Callable[[np.ndarray, tuple[float, float, float, float]], bytes | None]


@dataclass
class TrackHistory:
    track_id: int
    cls: str
    first_seen: float
    last_seen: float
    points: deque[tuple[float, float, float]] = field(default_factory=lambda: deque(maxlen=900))
    speeds: deque[float] = field(default_factory=lambda: deque(maxlen=900))
    entity_id: str | None = None
    observations: int = 0
    desc: np.ndarray | None = None
    color_votes: Counter[str] = field(default_factory=Counter)
    rider_counts: list[int] = field(default_factory=list)
    zone_inside: dict[str, float | None] = field(default_factory=dict)
    zone_entries: list[tuple[float, str]] = field(default_factory=list)
    max_dwell: dict[str, float] = field(default_factory=dict)
    best_area: float = 0.0
    thumb_jpeg: bytes | None = None
    velocity: tuple[float, float] = (0.0, 0.0)

    def observe(self, ts: float, cx: float, cy: float) -> None:
        self.last_seen = ts
        self.observations += 1
        self.points.append((ts, cx, cy))
        self.velocity = self._estimate_velocity()
        self.speeds.append(float(np.hypot(*self.velocity)))

    def _estimate_velocity(self, window_s: float = 1.0) -> tuple[float, float]:
        if len(self.points) < 2:
            return (0.0, 0.0)
        ts, cx, cy = self.points[-1]
        ref = self.points[0]
        for p in reversed(self.points):
            if ts - p[0] >= window_s:
                ref = p
                break
        dt = ts - ref[0]
        if dt <= 1e-6:
            return (0.0, 0.0)
        return ((cx - ref[1]) / dt, (cy - ref[2]) / dt)

    def median_speed(self) -> float:
        moving = [s for s in self.speeds if s > 1e-4]
        return statistics.median(moving) if moving else 0.0

    def riders(self) -> int:
        return round(statistics.median(self.rider_counts)) if self.rider_counts else 0

    def color(self) -> str | None:
        return self.color_votes.most_common(1)[0][0] if self.color_votes else None

    def dwell(self, zone_id: str, now: float) -> float:
        start = self.zone_inside.get(zone_id)
        current = now - start if start is not None else 0.0
        return max(current, self.max_dwell.get(zone_id, 0.0))

    def summary(self) -> ObjectSummary:
        riders = self.riders() if self.cls in TWO_WHEELERS else None
        return ObjectSummary(type=self.cls, color=self.color(), riders=riders)


class TrackStore:
    """Enriches raw tracks (velocity, entity_id, colour, riders) and reports zone events."""

    def __init__(
        self,
        camera: CameraConfig,
        linker: EntityLinker | None = None,
        lost_after_s: float = 2.0,
        thumb_fn: ThumbFn | None = None,
    ) -> None:
        self.camera = camera
        self.linker = linker or EntityLinker(camera.id)
        self.lost_after_s = lost_after_s
        self.thumb_fn = thumb_fn
        self.histories: dict[int, TrackHistory] = {}

    def update(
        self,
        tracks: list[Track],
        ts: float,
        frame: np.ndarray | None,
        riders_of: dict[int, list[int]],
    ) -> tuple[list[Track], list[tuple[int, str, str]], frozenset[int]]:
        """Returns ``(enriched_tracks, zone_events, new_track_ids)``."""
        by_id = {t.track_id: t for t in tracks}
        ref: tuple[float, bool] | None = None  # frame brightness for colour naming, computed once
        zone_events: list[tuple[int, str, str]] = []
        new_ids: set[int] = set()
        enriched: list[Track] = []
        for t in tracks:
            h = self.histories.get(t.track_id)
            if h is None:
                h = TrackHistory(track_id=t.track_id, cls=t.cls, first_seen=ts, last_seen=ts)
                self.histories[t.track_id] = h
                new_ids.add(t.track_id)
            cx, cy = t.center
            h.observe(ts, cx, cy)
            foot = t.foot
            for z in self.camera.zones:
                inside = point_in_polygon(foot, z.polygon)
                was = h.zone_inside.get(z.id)
                if inside and was is None:
                    h.zone_inside[z.id] = ts
                    h.zone_entries.append((ts, z.id))
                    zone_events.append((t.track_id, z.id, "enter"))
                elif not inside and was is not None:
                    h.max_dwell[z.id] = max(h.max_dwell.get(z.id, 0.0), ts - was)
                    h.zone_inside[z.id] = None
                    zone_events.append((t.track_id, z.id, "exit"))
            if t.cls in TWO_WHEELERS:
                h.rider_counts.append(len(riders_of.get(t.track_id, [])))
            if frame is not None and (h.observations <= 3 or h.observations % 3 == 0):
                if ref is None:
                    ref = frame_reference(frame)
                self._appearance(h, t, frame, riders_of, by_id, ref)
            if h.entity_id is None and (h.observations >= 3 or frame is None):
                h.entity_id = self.linker.assign(t.cls, h.desc, ts, riders=h.riders())
            attrs: dict[str, str | int | float | bool | None] = dict(t.attributes)
            if h.color():
                attrs["color"] = h.color()
            if t.cls in TWO_WHEELERS:
                attrs["riders"] = h.riders()
            enriched.append(
                t.model_copy(
                    update={
                        "velocity": h.velocity,
                        "entity_id": h.entity_id,
                        "first_seen": h.first_seen,
                        "last_seen": ts,
                        "attributes": attrs,
                    }
                )
            )
        return enriched, zone_events, frozenset(new_ids)

    def _appearance(
        self,
        h: TrackHistory,
        t: Track,
        frame: np.ndarray,
        riders_of: dict[int, list[int]],
        by_id: dict[int, Track],
        ref: tuple[float, bool],
    ) -> None:
        fh, fw = frame.shape[:2]
        rider_boxes = [by_id[pid].bbox for pid in riders_of.get(t.track_id, []) if pid in by_id]
        d = descriptor(frame, t.bbox, rider_boxes, is_person=t.cls == "person")
        if d is not None:
            h.desc = d if h.desc is None else _blend(h.desc, d)
        bx1, by1 = int(t.bbox[0] * fw), int(t.bbox[1] * fh)
        bx2, by2 = int(t.bbox[2] * fw), int(t.bbox[3] * fh)
        body = frame[max(by1, 0) : max(by2, by1 + 1), max(bx1, 0) : max(bx2, bx1 + 1)]
        ref_v, monochrome = ref
        name = None
        if t.cls != "person" and not monochrome and body.size:
            # riders' shirts are not the bike's colour: mask their upper bodies (the box's top half)
            mask = np.ones(body.shape[:2], dtype=bool)
            half = body.shape[0] // 2
            for rx1, ry1, rx2, ry2 in rider_boxes:
                mx1, my1 = int(rx1 * fw) - max(bx1, 0), int(ry1 * fh) - max(by1, 0)
                mx2, my2 = int(rx2 * fw) - max(bx1, 0), min(int(ry2 * fh) - max(by1, 0), half)
                mask[max(my1, 0) : max(my2, 0), max(mx1, 0) : max(mx2, 0)] = False
            name = color_name(body, mask, ref_v)
        if name:
            h.color_votes[name] += 1
        box = t.bbox
        for rb in rider_boxes:
            box = union(box, rb)
        area = (box[2] - box[0]) * (box[3] - box[1]) * fw * fh
        if area > h.best_area and self.thumb_fn is not None:
            h.best_area = area
            h.thumb_jpeg = self.thumb_fn(frame, box)

    def pop_finished(self, ts: float, force: bool = False) -> list[TrackHistory]:
        done = [h for h in self.histories.values() if force or ts - h.last_seen > self.lost_after_s]
        for h in done:
            for zid, start in h.zone_inside.items():
                if start is not None:
                    h.max_dwell[zid] = max(h.max_dwell.get(zid, 0.0), h.last_seen - start)
                    h.zone_inside[zid] = None
            if h.entity_id is not None:
                self.linker.release(h.entity_id, h.desc, h.last_seen, riders=h.riders())
            del self.histories[h.track_id]
        return done


def _norm(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v
