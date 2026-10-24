"""Edge API (``/v1/edge/*``): device token + Ed25519 signatures; mTLS at the proxy in prod."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, File, Form, Header, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from jikimi_contracts import ClipAttestation, EdgeAlertEnvelope, TrackSummary
from jikimi_contracts.commands import CommandBundle
from jikimi_contracts.events import EdgeAck, EdgeHeartbeat
from jikimi_contracts.modes import CalendarBundle
from jikimi_contracts.network import BikeEmbedding, NetworkBundle
from jikimi_contracts.rules_dsl import RuleBundle
from pydantic import ValidationError

from ...db.models import Site
from ...rules import service as rule_service
from ...services import calendar as cal
from ...services import commands as commands_svc
from ...services import network as network_svc
from ...services.effects import Effects
from ..deps import DB, Ctx, EdgeDevice
from ..errors import ProblemError
from .calendar import site_today

router = APIRouter(prefix="/v1/edge", tags=["edge"])
MAX_CLIP = 60 * 1024 * 1024


@router.post("/alerts", status_code=202)
def post_alert(
    body: EdgeAlertEnvelope, device: EdgeDevice, ctx: Ctx, db: DB, idempotency_key: str | None = Header(default=None)
) -> JSONResponse:
    if idempotency_key and idempotency_key != str(body.alert.alert_id):
        raise ProblemError(422, "Idempotency-Key must equal alert_id")
    effects = Effects()
    alert, created = ctx.ingest.ingest_alert(db, device, body, effects)
    db.commit()
    ctx.dispatch(effects)
    return JSONResponse({"alert_id": str(alert.id), "status": "queued"}, status_code=202 if created else 200)


@router.post("/clips", status_code=201)
async def post_clip(
    device: EdgeDevice,
    ctx: Ctx,
    db: DB,
    attestation: str = Form(...),
    clip: UploadFile = File(...),
    keyframes: list[UploadFile] = File(default_factory=list),
) -> dict[str, str]:
    try:
        att = ClipAttestation.model_validate(json.loads(attestation))
    except (ValueError, ValidationError) as exc:
        raise ProblemError(422, "Invalid attestation", str(exc)[:300]) from exc
    data = await clip.read()
    if len(data) > MAX_CLIP:
        raise ProblemError(413, "Clip too large")
    frames = [(kf.filename or "", await kf.read()) for kf in keyframes]
    effects = Effects()
    alert = ctx.ingest.ingest_clip(db, device, att, data, frames, effects)
    db.commit()
    ctx.dispatch(effects)
    return {"alert_id": str(alert.id), "clip_id": att.clip_id}


@router.post("/tracks", status_code=201)
def post_track(body: TrackSummary, device: EdgeDevice, ctx: Ctx, db: DB) -> dict[str, bool]:
    return {"indexed": ctx.ingest.ingest_track(db, device, body)}


@router.post("/heartbeat")
def heartbeat(body: EdgeHeartbeat, device: EdgeDevice, ctx: Ctx, db: DB) -> dict[str, str]:
    effects = Effects()
    ctx.ingest.heartbeat(db, device, body, effects)
    db.commit()
    ctx.dispatch(effects)
    return {"status": "ok"}


@router.put("/snapshots/{camera_id}", status_code=204)
async def put_snapshot(camera_id: str, request: Request, device: EdgeDevice, ctx: Ctx) -> Response:
    data = await request.body()
    if not data.startswith(b"\xff\xd8") or len(data) > 2_000_000:
        raise ProblemError(422, "Expected a JPEG under 2 MB")
    ctx.ingest.snapshot(device, camera_id, data)
    ctx.hub.publish("snapshot.updated", device.site_id, {"camera_id": camera_id})
    return Response(status_code=204)


@router.post("/acks")
def post_ack(body: EdgeAck, device: EdgeDevice, ctx: Ctx, db: DB) -> dict[str, str]:
    effects = Effects()
    result = ctx.ingest.edge_ack(db, device, body, effects)
    db.commit()
    ctx.dispatch(effects)
    return {"result": result}


@router.get("/rules", response_model=RuleBundle)
def rules(device: EdgeDevice, ctx: Ctx, db: DB) -> RuleBundle:
    """Signed bundle of the site's active rules (F11); the edge applies it when ``version`` changes."""
    return rule_service.bundle(db, device.site_id, ctx.evidence.signer, datetime.now(UTC))


@router.get("/calendar", response_model=CalendarBundle)
def calendar_bundle(device: EdgeDevice, ctx: Ctx, db: DB) -> CalendarBundle:
    """Signed confirmed event-mode windows (F16); the edge switches mode at site-local midnight."""
    today = site_today(db, device.site_id)
    return cal.bundle(db, device.site_id, today, ctx.evidence.signer, datetime.now(UTC))


@router.get("/commands", response_model=CommandBundle)
def commands(device: EdgeDevice, ctx: Ctx, db: DB) -> CommandBundle:
    """Signed admin commands not yet carried out (e.g. accept a camera's new view)."""
    return commands_svc.bundle(db, device.site_id, ctx.evidence.signer, datetime.now(UTC))


@router.post("/embeddings", status_code=202)
def embedding(body: BikeEmbedding, device: EdgeDevice, db: DB) -> dict[str, bool]:
    """A bike alert's appearance embedding (F21): kept 24 h at an opted-in site, else dropped."""
    site = db.get(Site, device.site_id)
    if site is None or body.site_id != device.site_id:
        raise ProblemError(403, "Wrong site")
    return {"kept": network_svc.keep_embedding(db, site, body, datetime.now(UTC))}


@router.get("/network", response_model=NetworkBundle)
def network(device: EdgeDevice, ctx: Ctx, db: DB) -> NetworkBundle:
    """Signed shares from opted-in neighbours (F21) that have not expired."""
    return network_svc.bundle(db, device.site_id, ctx.evidence.signer, datetime.now(UTC))
