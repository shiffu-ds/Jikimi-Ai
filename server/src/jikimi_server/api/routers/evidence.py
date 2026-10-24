"""Evidence packs (F8): create, list, detail with chain of custody, PDF download."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from jikimi_contracts.api import CustodyEvent, EvidenceCreateRequest, EvidenceDetail, EvidenceSummary
from sqlalchemy import select

from ...core import audit
from ...db.models import Alert, AuditLog, Evidence, MerkleBatch
from ...evidence.service import EvidenceError
from ..deps import DB, Ctx, Principal, require
from ..errors import ProblemError

router = APIRouter(prefix="/v1", tags=["evidence"])
CanCreate = Annotated[Principal, Depends(require("evidence:create"))]
CanRead = Annotated[Principal, Depends(require("evidence:read"))]
CanAdmin = Annotated[Principal, Depends(require("admin"))]


def to_summary(ctx: Ctx, db: DB, ev: Evidence) -> EvidenceSummary:
    batch = db.get(MerkleBatch, ev.merkle_batch_id) if ev.merkle_batch_id else None
    return EvidenceSummary(
        id=ev.id,
        site_id=ev.site_id,
        created_at=ev.created_at,
        created_by=ev.created_by,
        case_reference=ev.case_reference,
        alert_count=len(ev.manifest.get("alerts", [])),
        clip_count=len(ev.manifest.get("clips", [])),
        manifest_sha256=ev.manifest_sha256,
        pdf_sha256=ev.pdf_sha256,
        pdf_url=f"/v1/evidence/{ev.id}/pdf" if ev.pdf_uri else None,
        verify_url=ctx.evidence.verify_url(ev.id),
        merkle_status="included" if batch else "pending",
        ots_status=batch.ots_status if batch else "pending",
    )


def load(db: DB, p: Principal, ev_id: str) -> Evidence:
    ev = db.get(Evidence, ev_id)
    if ev is None or ev.site_id not in p.sites:
        raise ProblemError(404, "Evidence not found")
    return ev


@router.post("/evidence", response_model=EvidenceSummary, status_code=201)
def create(body: EvidenceCreateRequest, p: CanCreate, ctx: Ctx, db: DB) -> EvidenceSummary:
    alerts = [db.get(Alert, aid) for aid in body.alert_ids]
    if any(a is None or a.site_id not in p.sites for a in alerts):
        raise ProblemError(404, "Alert not found")
    try:
        ev = ctx.evidence.create(db, [a for a in alerts if a is not None], p.name, body.case_reference, body.notes)
    except EvidenceError as exc:
        raise ProblemError(422, "Cannot build evidence", str(exc)) from exc
    audit.record(db, "evidence.create", p.name, ev.id, {"alerts": [str(a) for a in body.alert_ids]}, p.user.tenant_id)
    db.commit()
    ctx.hub.publish("evidence.created", ev.site_id, {"id": ev.id})
    return to_summary(ctx, db, ev)


@router.get("/evidence", response_model=list[EvidenceSummary])
def list_evidence(p: CanRead, ctx: Ctx, db: DB, site_id: str | None = None, limit: int = 50) -> list[EvidenceSummary]:
    sites = [site_id] if site_id and site_id in p.sites else sorted(p.sites)
    rows = db.scalars(
        select(Evidence).where(Evidence.site_id.in_(sites)).order_by(Evidence.created_at.desc()).limit(min(limit, 200))
    ).all()
    return [to_summary(ctx, db, e) for e in rows]


@router.get("/evidence/{ev_id}", response_model=EvidenceDetail)
def get_evidence(ev_id: str, p: CanRead, ctx: Ctx, db: DB) -> EvidenceDetail:
    ev = load(db, p, ev_id)
    audit.record(db, "evidence.view", p.name, ev.id, {}, p.user.tenant_id)
    custody = db.scalars(select(AuditLog).where(AuditLog.target == ev.id).order_by(AuditLog.id)).all()
    return EvidenceDetail(
        **to_summary(ctx, db, ev).model_dump(),
        manifest=ev.manifest,
        custody=[CustodyEvent(actor=r.actor, action=r.action, at=r.at, details=r.details or {}) for r in custody],
    )


@router.get("/evidence/{ev_id}/pdf")
def pdf(ev_id: str, p: CanRead, ctx: Ctx, db: DB) -> FileResponse:
    ev = load(db, p, ev_id)
    if not ev.pdf_uri:
        raise ProblemError(404, "No PDF")
    audit.record(db, "evidence.download", p.name, ev.id, {"sha256": ev.pdf_sha256}, p.user.tenant_id)
    db.commit()
    return FileResponse(ctx.store.path(ev.pdf_uri), media_type="application/pdf", filename=f"{ev.id}.pdf")


@router.post("/admin/merkle/close")
def close_merkle(p: CanAdmin, ctx: Ctx, db: DB) -> dict[str, object]:
    """Close the Merkle batch now (normally automatic at 00:05 site time)."""
    batch = ctx.evidence.close_batch(db, date.today())
    audit.record(db, "merkle.close", p.name, str(batch.id) if batch else None, {}, p.user.tenant_id)
    db.commit()
    if batch is None:
        return {"closed": False, "reason": "no pending evidence"}
    return {
        "closed": True,
        "batch_id": batch.id,
        "root": batch.root,
        "size": batch.tree_size,
        "ots_status": batch.ots_status,
    }
