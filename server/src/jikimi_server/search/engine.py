"""Retrieval + score fusion over ``clip_index`` (F1, plan Section 8.6).

Improvement over v2.3: only the *object type* is a hard filter; colour, riders and helmet are
soft (an attribute classifier is noisy at night), so a slightly-off colour still ranks, below
exact matches. With an image/text embedder configured the plan's fusion is used
(``0.6 sim + 0.3 attr + 0.1 recency``); without one (laptop lite profile) attributes carry the
score.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from uuid import UUID

from jikimi_contracts.search import ClipRef, ObjectQuery, ParsedQuery, SearchResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Alert, Camera, ClipIndex
from .parser import QueryParser, SiteVocab

SIMILAR_COLORS = {
    frozenset({"black", "gray"}),
    frozenset({"gray", "silver"}),
    frozenset({"white", "silver"}),
    frozenset({"red", "orange"}),
    frozenset({"orange", "yellow"}),
    frozenset({"brown", "orange"}),
}


def _color_score(want: str | None, have: str | None) -> float | None:
    if want is None:
        return None
    if have is None:
        return 0.5
    if want == have:
        return 1.0
    return 0.45 if frozenset({want, have}) in SIMILAR_COLORS else 0.0


def _riders_score(want: int | None, have: int | None) -> float | None:
    if want is None:
        return None
    if have is None:
        return 0.5
    return 1.0 if want == have else 0.35 if abs(want - have) == 1 else 0.0


def _helmet_score(want: bool | None, have: bool | None) -> float | None:
    if want is None:
        return None
    if have is None:
        return 0.5
    return 1.0 if want == have else 0.0


def match_object(q: ObjectQuery, objs: list[dict[str, Any]]) -> tuple[float, list[str]] | None:
    """Best attribute score of ``objs`` against ``q`` (``None`` when the type does not match)."""
    best: tuple[float, list[str]] | None = None
    for o in objs:
        otype = o.get("type")
        if q.type not in ("any", otype) and not (q.type == "person" and otype == "person"):
            continue
        if q.type == "any" and otype == "person":
            continue
        parts = []
        reasons = [f"type:{otype}"]
        for name, score in (
            ("color", _color_score(q.color, o.get("color"))),
            ("riders", _riders_score(q.riders, o.get("riders"))),
            ("helmet", _helmet_score(q.helmet, o.get("helmet"))),
        ):
            if score is None:
                continue
            parts.append(score)
            if score >= 0.99:
                reasons.append(f"{name}:{o.get(name)}")
            elif score > 0.4 and o.get(name) is not None:
                reasons.append(f"{name}~{o.get(name)}")
        s = sum(parts) / len(parts) if parts else 1.0
        if best is None or s > best[0]:
            best = (s, reasons)
    return best


class SearchEngine:
    def __init__(self, parser: QueryParser | None = None) -> None:
        self.parser = parser or QueryParser()

    def site_vocab(self, db: Session, site_id: str) -> SiteVocab:
        cams = db.scalars(select(Camera).where(Camera.site_id == site_id)).all()
        return SiteVocab.build(
            [
                {"id": c.id, "name": c.name, "name_ur": c.name_ur, "name_roman": c.name_roman, "zones": c.zones}
                for c in cams
            ]
        )

    def search(
        self, db: Session, site_id: str, query: str, now: datetime, limit: int = 10, parsed: ParsedQuery | None = None
    ) -> SearchResponse:
        t0 = time.perf_counter()
        if parsed is None:
            parsed = self.parser.parse(query, now, self.site_vocab(db, site_id))
        assert parsed.time_range is not None
        start, end = parsed.time_range.from_, parsed.time_range.to
        stmt = select(ClipIndex).where(
            ClipIndex.site_id == site_id, ClipIndex.ts_end >= start, ClipIndex.ts_start <= end
        )
        if parsed.cameras:
            stmt = stmt.where(ClipIndex.camera_id.in_(parsed.cameras))
        if parsed.alert_types:
            stmt = stmt.where(ClipIndex.kind == "alert", ClipIndex.alert_type.in_(parsed.alert_types))
        rows = db.scalars(stmt.order_by(ClipIndex.ts_start.desc()).limit(4000)).all()
        cams = {c.id: c for c in db.scalars(select(Camera).where(Camera.site_id == site_id))}
        span = max((end - start).total_seconds(), 1.0)
        scored: list[tuple[float, ClipIndex, list[str]]] = []
        for row in rows:
            objs = row.objects or []
            if parsed.objects:
                matches = [match_object(q, objs) for q in parsed.objects]
                if any(m is None for m in matches):
                    continue  # hard filter: object type
                attr = sum(m[0] for m in matches if m) / len(matches)
                reasons = [r for m in matches if m for r in m[1]]
                if attr < 0.5:
                    continue
            else:
                attr, reasons = 1.0, []
            zone = 1.0
            if parsed.zones:
                hit = bool(set(row.zones or []) & set(parsed.zones))
                zone = 1.0 if hit else 0.35
                if hit:
                    reasons.extend(f"zone:{z}" for z in set(row.zones or []) & set(parsed.zones))
            recency = max(0.0, min(1.0, 1.0 - (end - row.ts_end).total_seconds() / span))
            kind = 1.0 if row.kind == "alert" else 0.6
            score = 0.62 * attr + 0.15 * zone + 0.1 * recency + 0.13 * kind
            if row.kind == "alert" and row.alert_type:
                reasons.append(f"alert:{row.alert_type}")
            scored.append((score, row, reasons))
        scored.sort(key=lambda x: (-x[0], -x[1].ts_start.timestamp()))
        results: list[ClipRef] = []
        per_entity: dict[str, int] = {}
        alerts_with_clip = {
            a.id: a
            for a in db.scalars(
                select(Alert).where(Alert.id.in_([r.alert_id for _, r, _ in scored[: limit * 4] if r.alert_id]))
            )
        }
        for score, row, reasons in scored:
            key = row.entity_id or row.ref
            if per_entity.get(key, 0) >= 2:
                continue  # don't let one loitering bike fill the page
            per_entity[key] = per_entity.get(key, 0) + 1
            alert = alerts_with_clip.get(row.alert_id) if row.alert_id else None
            cam = cams.get(row.camera_id)
            results.append(
                ClipRef(
                    clip_id=row.ref,
                    kind="alert" if row.kind == "alert" else "track",
                    alert_id=row.alert_id,
                    alert_type=row.alert_type,
                    camera_id=row.camera_id,
                    camera_name=cam.name if cam else None,
                    ts_start=row.ts_start,
                    ts_end=row.ts_end,
                    score=round(score, 3),
                    thumbnail_url=f"/v1/media/thumbs/{row.id}.jpg" if row.thumbnail_uri else None,
                    clip_url=f"/v1/media/clips/{alert.id}.mp4" if alert is not None and alert.clip_uri else None,
                    objects=row.objects or [],
                    matched=list(dict.fromkeys(reasons)),
                )
            )
            if len(results) >= limit:
                break
        return SearchResponse(parsed=parsed, results=results, took_ms=round((time.perf_counter() - t0) * 1000, 1))


def alert_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None
