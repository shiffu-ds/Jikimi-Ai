"""Sites, cameras, health overview, statistics and the audit log."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from jikimi_contracts.api import CameraInfo, DeviceStatus, HealthOverview, Hotspots, SiteInfo, StatsOut
from jikimi_contracts.api import ZoneInfo as ZoneOut
from jikimi_contracts.commands import EdgeCommand
from jikimi_contracts.network import NetworkSettings, NetworkStatus
from sqlalchemy import select

from ...core import audit
from ...db.models import AuditLog, Camera, Device, EdgeCommandRow, Site
from ...services import commands as commands_svc
from ...services import network as network_svc
from ...services import stats as stats_svc
from ...services.hotspots import site_hotspots
from ..deps import DB, Ctx, Principal, check_site, require
from ..errors import ProblemError

router = APIRouter(prefix="/v1", tags=["sites"])
CanSites = Annotated[Principal, Depends(require("sites:read"))]
CanHealth = Annotated[Principal, Depends(require("health:read"))]
CanStats = Annotated[Principal, Depends(require("stats:read"))]
CanAudit = Annotated[Principal, Depends(require("audit:read"))]
CanAdmin = Annotated[Principal, Depends(require("admin"))]


def camera_info(c: Camera, ctx: Ctx | None = None) -> CameraInfo:
    snap = None
    if ctx is not None and ctx.store.exists(f"snapshots/{c.site_id}/{c.id}.jpg"):
        snap = f"/v1/media/snapshots/{c.id}.jpg"
    return CameraInfo(
        id=c.id,
        site_id=c.site_id,
        name=c.name,
        name_ur=c.name_ur,
        name_roman=c.name_roman,
        zones=[
            ZoneOut(
                id=z["id"],
                name=z.get("name"),
                name_ur=z.get("name_ur"),
                polygon=[tuple(pt) for pt in z.get("polygon", [])],
            )
            for z in c.zones or []
        ],
        status=c.status,
        fps=c.fps,
        last_seen=c.last_seen,
        health=c.health or {},
        snapshot_url=snap,
    )


@router.get("/health")
def health() -> dict[str, str]:
    """Public liveness probe (the edge sync agent's connectivity check)."""
    return {"status": "ok", "time": datetime.now(UTC).isoformat(timespec="seconds")}


@router.get("/sites", response_model=list[SiteInfo])
def sites(p: CanSites, ctx: Ctx, db: DB) -> list[SiteInfo]:
    rows = db.scalars(select(Site).where(Site.id.in_(sorted(p.sites))).order_by(Site.id)).all()
    return [
        SiteInfo(
            id=s.id,
            name=s.name,
            name_ur=s.name_ur,
            timezone=s.timezone,
            cameras=[camera_info(c, ctx) for c in s.cameras],
        )
        for s in rows
    ]


@router.get("/health/overview", response_model=HealthOverview)
def overview(p: CanHealth, ctx: Ctx, db: DB) -> HealthOverview:
    now = datetime.now(UTC)
    devices = []
    for d in db.scalars(select(Device).where(Device.site_id.in_(sorted(p.sites)))):
        hb = d.last_heartbeat or {}
        power = hb.get("power") or {}
        online = d.last_seen is not None and now - d.last_seen < timedelta(seconds=90)
        devices.append(
            DeviceStatus(
                id=d.id,
                site_id=d.site_id,
                name=d.name,
                status=d.status,
                online=online,
                last_seen=d.last_seen,
                outbox_backlog=int(hb.get("outbox_backlog", 0)),
                outbox_dead=int(hb.get("outbox_dead", 0)),
                power_source=str(power.get("source", "unknown")),
                battery_pct=power.get("battery_pct"),
                power_profile=str(power.get("profile", "normal")),
                sms_gateway=str(hb.get("sms_gateway", "none")),
                versions={k: str(v) for k, v in (hb.get("versions") or {}).items()},
                drift={k: bool(v) for k, v in (hb.get("drift") or {}).items()},
            )
        )
    cams = db.scalars(select(Camera).where(Camera.site_id.in_(sorted(p.sites))).order_by(Camera.id)).all()
    return HealthOverview(devices=devices, cameras=[camera_info(c, ctx) for c in cams], server_time=now)


@router.post("/sites/{site_id}/cameras/{camera_id}/accept-view", response_model=EdgeCommand, status_code=201)
def accept_view(site_id: str, camera_id: str, p: CanAdmin, ctx: Ctx, db: DB) -> EdgeCommand:
    """The camera was moved on purpose: its current view becomes the new reference (F10).
    Zones drawn on the old view may need redrawing afterwards."""
    check_site(p, site_id)
    cam = db.get(Camera, camera_id)
    if cam is None or cam.site_id != site_id:
        raise ProblemError(404, "Not found", "camera not found")
    site = db.get(Site, site_id)
    assert site is not None
    row = EdgeCommandRow(
        id=uuid.uuid4().hex,
        tenant_id=site.tenant_id,
        site_id=site_id,
        camera_id=camera_id,
        kind="accept_view",
        issued_by=p.name,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        "camera.accept_view",
        p.name,
        target=f"{site_id}:{camera_id}",
        details={"command": row.id},
        tenant_id=site.tenant_id,
    )
    db.commit()
    ctx.hub.publish("health.updated", site_id, {"camera_id": camera_id, "command": row.id})
    return commands_svc.to_out(row)


@router.get("/sites/{site_id}/network", response_model=NetworkStatus)
def network_status(site_id: str, p: CanAdmin, db: DB) -> NetworkStatus:
    """F21 mohalla network: this site's opt-in, neighbours in range and shares."""
    check_site(p, site_id)
    site = db.get(Site, site_id)
    assert site is not None
    return network_svc.status(db, site, datetime.now(UTC))


@router.put("/sites/{site_id}/network", response_model=NetworkStatus)
def network_update(site_id: str, body: NetworkSettings, p: CanAdmin, db: DB) -> NetworkStatus:
    check_site(p, site_id)
    site = db.get(Site, site_id)
    assert site is not None
    now = datetime.now(UTC)
    try:
        network_svc.update_settings(db, site, body, p.name, now)
    except ValueError as e:
        raise ProblemError(422, "Cannot opt in", str(e)) from e
    db.flush()
    return network_svc.status(db, site, now)


@router.get("/sites/{site_id}/hotspots", response_model=Hotspots)
def hotspots(site_id: str, p: CanStats, db: DB, hours: float = 4.0, budget_min: float = 30.0) -> Hotspots:
    """F15 risk estimate for the next ``hours`` and a patrol route of ``budget_min`` minutes."""
    check_site(p, site_id)
    return site_hotspots(db, site_id, datetime.now(UTC), min(max(hours, 1.0), 24.0), min(max(budget_min, 5.0), 120.0))


@router.get("/stats", response_model=StatsOut)
def stats(p: CanStats, db: DB, site_id: str | None = None, days: int = 7) -> StatsOut:
    if site_id:
        check_site(p, site_id)
    site = db.get(Site, site_id) if site_id else None
    tz = ZoneInfo(site.timezone if site else "Asia/Karachi")
    return stats_svc.compute(db, sorted(p.sites), site_id, max(1, min(days, 90)), datetime.now(UTC), tz)


@router.get("/audit")
def audit_log(p: CanAudit, db: DB, limit: int = 100, target: str | None = None) -> list[dict[str, object]]:
    stmt = select(AuditLog).where(AuditLog.tenant_id == p.user.tenant_id)
    if target:
        stmt = stmt.where(AuditLog.target == target)
    rows = db.scalars(stmt.order_by(AuditLog.id.desc()).limit(min(limit, 500))).all()
    return [
        {
            "id": r.id,
            "actor": r.actor,
            "action": r.action,
            "target": r.target,
            "details": r.details,
            "at": r.at.isoformat(),
            "row_hash": r.row_hash,
        }
        for r in rows
    ]


@router.get("/audit/verify")
def audit_verify(_: CanAudit, db: DB) -> dict[str, object]:
    ok, n, bad = audit.verify_chain(db)
    return {"ok": ok, "rows": n, "first_bad_id": bad}
