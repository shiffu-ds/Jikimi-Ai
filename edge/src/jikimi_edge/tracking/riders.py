"""Rider / pillion association: which persons are *on* which two-wheeler."""

from __future__ import annotations

from collections.abc import Sequence

from jikimi_contracts import TWO_WHEELERS, Track

from ..analytics.geometry import intersection_over


class RiderMemory:
    """Riders keep their status through association flicker in dense traffic.

    On real footage of a crowded junction, riders squeezed between bikes are associated in most
    frames but not all; in the frames they drop out they look like pedestrians standing right
    next to a bike, which is exactly the snatch pattern. A person counts as a rider once they
    were associated in at least ``min_fraction`` of the frames since they were first seen. A
    snatch victim is associated for a frame or two at the moment of contact at most.
    """

    def __init__(self, min_frames: int = 3, min_fraction: float = 0.4, forget_s: float = 10.0) -> None:
        self.min_frames, self.min_fraction, self.forget_s = min_frames, min_fraction, forget_s
        self._seen: dict[int, int] = {}
        self._hits: dict[int, int] = {}
        self._last: dict[int, float] = {}

    def update(self, persons: Sequence[int], riders: Sequence[int], ts: float) -> frozenset[int]:
        for p in persons:
            self._seen[p] = self._seen.get(p, 0) + 1
            self._last[p] = ts
        for r in riders:
            self._hits[r] = self._hits.get(r, 0) + 1
        for p in [p for p, t in self._last.items() if ts - t > self.forget_s]:
            self._seen.pop(p, None)
            self._hits.pop(p, None)
            self._last.pop(p, None)
        sticky = {
            p
            for p in persons
            if self._seen.get(p, 0) >= self.min_frames and self._hits.get(p, 0) / self._seen[p] >= self.min_fraction
        }
        return frozenset(riders) | sticky


def associate_riders(tracks: Sequence[Track], min_overlap: float = 0.25) -> dict[int, list[int]]:
    """Map motorcycle/bicycle track_id -> rider person track_ids.

    A person rides a bike when a good part of their box overlaps the bike box (extended
    upwards by one bike height, where riders' torsos are) and their feet are not below the
    wheels.
    """
    bikes = [t for t in tracks if t.cls in TWO_WHEELERS]
    persons = [t for t in tracks if t.cls == "person"]
    out: dict[int, list[int]] = {b.track_id: [] for b in bikes}
    for p in persons:
        best_id, best = None, min_overlap
        px1, _, px2, py2 = p.bbox
        for b in bikes:
            bx1, by1, bx2, by2 = b.bbox
            bh = by2 - by1
            extended = (bx1 - 0.15 * (bx2 - bx1), by1 - 1.3 * bh, bx2 + 0.15 * (bx2 - bx1), by2)
            if py2 > by2 + 0.35 * bh:  # feet clearly below the wheels -> standing next to it
                continue
            if py2 < by1 + 0.3 * bh:  # feet above the bike -> standing behind it, further away
                continue
            cx = (px1 + px2) / 2
            if not (bx1 - 0.1 * (bx2 - bx1) <= cx <= bx2 + 0.1 * (bx2 - bx1)):
                continue
            ov = intersection_over(p.bbox, extended)
            if ov > best:
                best_id, best = b.track_id, ov
        if best_id is not None:
            out[best_id].append(p.track_id)
    return out
