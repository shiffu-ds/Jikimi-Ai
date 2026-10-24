"""Blurred media for authorised users (cookie session works in <video>/<img> tags).

Originals (unblurred) never leave the edge vault in v0.1; break-glass retrieval is planned as
an owner-only flow with a written reason and owner notification (F19).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ...core import audit
from ...db.models import Alert, Camera, ClipIndex
from ..deps import DB, Ctx, Principal, require
from ..errors import ProblemError

router = APIRouter(prefix="/v1/media", tags=["media"])
CanRead = Annotated[Principal, Depends(require("alerts:read"))]
CACHE = {"Cache-Control": "private, max-age=3600"}


def _alert(db: DB, p: Principal, alert_id: UUID) -> Alert:
    a = db.get(Alert, alert_id)
    if a is None or a.site_id not in p.sites:
        raise ProblemError(404, "Not found")
    return a


@router.get("/clips/{alert_id}.mp4")
def clip(alert_id: UUID, p: CanRead, ctx: Ctx, db: DB) -> FileResponse:
    a = _alert(db, p, alert_id)
    if not a.clip_uri:
        raise ProblemError(404, "Clip not uploaded yet")
    audit.record(db, "clip.view", p.name, str(a.id), {"clip": a.clip_id}, p.user.tenant_id)
    db.commit()
    return FileResponse(ctx.store.path(a.clip_uri), media_type="video/mp4", headers=CACHE)


@router.get("/keyframes/{alert_id}/{n}.jpg")
def keyframe(alert_id: UUID, n: int, p: CanRead, ctx: Ctx, db: DB) -> FileResponse:
    a = _alert(db, p, alert_id)
    frames = a.keyframes or []
    if not 0 <= n < len(frames):
        raise ProblemError(404, "No such keyframe")
    return FileResponse(ctx.store.path(frames[n]["uri"]), media_type="image/jpeg", headers=CACHE)


@router.get("/thumbs/{index_id}.jpg")
def thumb(index_id: int, p: CanRead, ctx: Ctx, db: DB) -> FileResponse:
    row = db.get(ClipIndex, index_id)
    if row is None or row.site_id not in p.sites or not row.thumbnail_uri:
        raise ProblemError(404, "Not found")
    return FileResponse(ctx.store.path(row.thumbnail_uri), media_type="image/jpeg", headers=CACHE)


@router.get("/snapshots/{camera_id}.jpg")
def snapshot(camera_id: str, p: CanRead, ctx: Ctx, db: DB) -> FileResponse:
    cam = db.get(Camera, camera_id)
    if cam is None or cam.site_id not in p.sites:
        raise ProblemError(404, "Not found")
    path = ctx.store.path(f"snapshots/{cam.site_id}/{cam.id}.jpg")
    if not path.exists():
        raise ProblemError(404, "No snapshot yet")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
