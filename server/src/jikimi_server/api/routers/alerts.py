"""Alerts: queue, detail, ack, review, SOS (plan Section 11.2)."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from jikimi_common.explain import CameraNames, explain_alert
from jikimi_contracts.api import AckRequest, AlertDetail, AlertPage, AlertSummary, ReviewRequest, SosRequest
from sqlalchemy import and_, or_, select

from ...core import audit
from ...db.models import Alert, AlertEvent, Camera, Site
from ...services.alerts import detail, new_alert_id, summary
from ...services.effects import Effects
from ..deps import DB, Ctx, Principal, check_site, require
from ..errors import ProblemError

router = APIRouter(prefix="/v1", tags=["alerts"])
CanRead = Annotated[Principal, Depends(require("alerts:read"))]
CanAck = Annotated[Principal, Depends(require("alerts:ack"))]
CanReview = Annotated[Principal, Depends(require("alerts:review"))]
CanSos = Annotated[Principal, Depends(require("sos:create"))]


def _cursor(a: Alert) -> str:
    return base64.urlsafe_b64encode(f"{a.created_at.isoformat()}|{a.id}".encode()).decode()


def _uncursor(c: str) -> tuple[datetime, UUID]:
    raw = base64.urlsafe_b64decode(c.encode()).decode()
    ts, aid = raw.split("|")
    return datetime.fromisoformat(ts), UUID(aid)


def load_alert(db: DB, p: Principal, alert_id: UUID) -> Alert:
    a = db.get(Alert, alert_id)
    if a is None or a.site_id not in p.sites:
        raise ProblemError(404, "Alert not found")
    return a


@router.get("/alerts", response_model=AlertPage)
def list_alerts(
    p: CanRead,
    db: DB,
    site_id: str | None = None,
    status: Annotated[list[str] | None, Query()] = None,
    type: Annotated[list[str] | None, Query()] = None,
    include_logged: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> AlertPage:
    sites = [site_id] if site_id else sorted(p.sites)
    if site_id:
        check_site(p, site_id)
    stmt = select(Alert).where(Alert.site_id.in_(sites))
    if status:
        stmt = stmt.where(Alert.status.in_(status))
    elif not include_logged:
        stmt = stmt.where(Alert.status != "logged_only", Alert.superseded_by.is_(None))
    if type:
        stmt = stmt.where(Alert.type.in_(type))
    if cursor:
        ts, aid = _uncursor(cursor)
        stmt = stmt.where(or_(Alert.created_at < ts, and_(Alert.created_at == ts, Alert.id < aid)))
    rows = db.scalars(stmt.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit + 1)).all()
    cams = {c.id: c for c in db.scalars(select(Camera).where(Camera.site_id.in_(sites)))}
    items = [summary(a, cams.get(a.camera_id or "")) for a in rows[:limit]]
    return AlertPage(items=items, next_cursor=_cursor(rows[limit - 1]) if len(rows) > limit else None)


@router.get("/alerts/{alert_id}", response_model=AlertDetail)
def get_alert(alert_id: UUID, p: CanRead, db: DB) -> AlertDetail:
    a = load_alert(db, p, alert_id)
    audit.record(db, "alert.view", p.name, str(a.id), {}, p.user.tenant_id)
    return detail(db, a)


@router.post("/alerts/{alert_id}/ack", response_model=AlertSummary)
def ack(alert_id: UUID, body: AckRequest, p: CanAck, ctx: Ctx, db: DB) -> AlertSummary:
    a = load_alert(db, p, alert_id)
    effects = Effects()
    ctx.alerts.ack(db, a, p.name, "app", effects, note=body.note)
    audit.record(db, "alert.ack", p.name, str(a.id), {"note": body.note}, p.user.tenant_id)
    db.commit()
    ctx.dispatch(effects)
    return summary(a, db.get(Camera, a.camera_id) if a.camera_id else None)


@router.post("/alerts/{alert_id}/review", response_model=AlertSummary)
def review(alert_id: UUID, body: ReviewRequest, p: CanReview, ctx: Ctx, db: DB) -> AlertSummary:
    a = load_alert(db, p, alert_id)
    effects = Effects()
    ctx.alerts.review(db, a, p.name, body.verdict.value, effects, notes=body.notes)
    audit.record(db, "alert.review", p.name, str(a.id), {"verdict": body.verdict.value}, p.user.tenant_id)
    db.commit()
    ctx.dispatch(effects)
    return summary(a, db.get(Camera, a.camera_id) if a.camera_id else None)


@router.post("/sos", response_model=AlertSummary, status_code=201)
def sos(body: SosRequest, p: CanSos, ctx: Ctx, db: DB) -> AlertSummary:
    """F22: panic button -> high-severity alert -> escalation chain starts immediately."""
    check_site(p, body.site_id)
    site = db.get(Site, body.site_id)
    assert site is not None
    cam = db.get(Camera, body.camera_id) if body.camera_id else None
    if body.camera_id and (cam is None or cam.site_id != site.id):
        raise ProblemError(422, "Unknown camera")
    now = datetime.now(UTC)
    names = (
        CameraNames(id=cam.id, name=cam.name, name_ur=cam.name_ur, name_roman=cam.name_roman)
        if cam
        else CameraNames(id=site.id, name=site.name, name_ur=site.name_ur, name_roman=site.name)
    )
    from zoneinfo import ZoneInfo

    expl = explain_alert("sos", {}, names, now.astimezone(ZoneInfo(site.timezone)))
    payload = {
        "source": "guard_app",
        "by": p.name,
        "note": body.note,
        "camera_id": body.camera_id,
        "at": now.isoformat(),
    }
    a = Alert(
        id=new_alert_id(),
        tenant_id=site.tenant_id,
        site_id=site.id,
        camera_id=cam.id if cam else None,
        type="sos",
        severity="high",
        route="ALERT_NOW",
        status="open",
        raw_score=1.0,
        features={"note": body.note, "by": p.name},
        explanation_ur=expl.ur,
        explanation_en=expl.en,
        explanation_roman=expl.roman,
        ts_start=now,
        ts_end=now,
        payload=payload,
    )
    db.add(a)
    db.flush()
    db.add(AlertEvent(alert_id=a.id, kind="sos", actor=p.name, channel="app", payload={"note": body.note}, at=now))
    effects = Effects()
    ctx.alerts.open(db, a, effects, now, reason="sos")
    ctx.alerts.changed(db, a, effects, "alert.created")
    audit.record(db, "sos", p.name, str(a.id), {"site": site.id}, p.user.tenant_id)
    db.commit()
    ctx.dispatch(effects)
    return summary(a, cam)
