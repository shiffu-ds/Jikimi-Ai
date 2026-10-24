"""Event-mode calendar (F16): Hijri estimates, admin-confirmed windows, removal.

Anyone on the site sees today's mode; only admins confirm or remove windows (after moon sighting
for the Hijri ones). The edge pulls the confirmed windows from ``/v1/edge/calendar``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from jikimi_contracts.modes import CalendarOut, ModeWindow, ModeWindowCreate

from ...core import audit
from ...db.models import ModeWindowRow, Site
from ...services import calendar as cal
from ..deps import DB, Ctx, Principal, check_site, require
from ..errors import ProblemError

router = APIRouter(prefix="/v1/sites", tags=["calendar"])
CanSites = Annotated[Principal, Depends(require("sites:read"))]
CanAdmin = Annotated[Principal, Depends(require("admin"))]


def site_today(db: DB, site_id: str) -> date:
    site = db.get(Site, site_id)
    return datetime.now(ZoneInfo(site.timezone if site else "Asia/Karachi")).date()


@router.get("/{site_id}/calendar", response_model=CalendarOut)
def get_calendar(site_id: str, p: CanSites, db: DB) -> CalendarOut:
    check_site(p, site_id)
    return cal.calendar(db, site_id, site_today(db, site_id))


@router.post("/{site_id}/calendar", response_model=ModeWindow, status_code=201)
def confirm_window(site_id: str, body: ModeWindowCreate, p: CanAdmin, ctx: Ctx, db: DB) -> ModeWindow:
    check_site(p, site_id)
    site = db.get(Site, site_id)
    assert site is not None
    row = ModeWindowRow(
        tenant_id=site.tenant_id,
        site_id=site_id,
        name=body.name,
        mode=body.mode,
        starts=body.starts,
        ends=body.ends,
        confirmed_by=p.name,
    )
    db.add(row)
    db.flush()
    details = {"name": body.name, "mode": body.mode, "starts": body.starts.isoformat(), "ends": body.ends.isoformat()}
    audit.record(
        db, "calendar.confirmed", p.name, target=f"{site_id}:{row.id}", details=details, tenant_id=site.tenant_id
    )
    db.commit()
    ctx.hub.publish("calendar.updated", site_id, {"id": row.id})
    return cal.to_out(row)


@router.delete("/{site_id}/calendar/{window_id}", status_code=204)
def remove_window(site_id: str, window_id: int, p: CanAdmin, ctx: Ctx, db: DB) -> Response:
    check_site(p, site_id)
    row = db.get(ModeWindowRow, window_id)
    if row is None or row.site_id != site_id:
        raise ProblemError(404, "Not found", "mode window not found")
    audit.record(
        db,
        "calendar.removed",
        p.name,
        target=f"{site_id}:{window_id}",
        details={"name": row.name},
        tenant_id=row.tenant_id,
    )
    db.delete(row)
    db.commit()
    ctx.hub.publish("calendar.updated", site_id, {"id": window_id})
    return Response(status_code=204)
