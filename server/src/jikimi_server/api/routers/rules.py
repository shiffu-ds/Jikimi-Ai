"""Rule builder (F11): Roman Urdu text -> draft + backtest -> proposal -> admin approval -> edge.

Supervisors may propose; only admins and owners approve (``rules:manage``). The edge pulls the
signed bundle of *active* rules from ``/v1/edge/rules``: nothing unapproved reaches a camera.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from jikimi_contracts.rules_dsl import RuleCreate, RuleDraft, RuleDraftRequest, RuleOut
from sqlalchemy import select

from ...core import audit
from ...db.models import Rule as RuleRow
from ...db.models import Site
from ...rules import service
from ...rules.backtest import backtest
from ...rules.parser import parse_rule
from ...services.devices import edge_reports
from ..deps import DB, Ctx, Principal, check_site, require
from ..errors import ProblemError

router = APIRouter(prefix="/v1/rules", tags=["rules"])
CanRead = Annotated[Principal, Depends(require("rules:read"))]
CanPropose = Annotated[Principal, Depends(require("rules:propose"))]
CanManage = Annotated[Principal, Depends(require("rules:manage"))]


def _site_tz(db: DB, site_id: str) -> ZoneInfo:
    site = db.get(Site, site_id)
    return ZoneInfo(site.timezone if site else "Asia/Karachi")


def _row(db: DB, p: Principal, rule_id: str) -> RuleRow:
    row = db.get(RuleRow, rule_id)
    if row is None or row.site_id not in p.sites:
        raise ProblemError(404, "Not found", "rule not found")
    return row


@router.post("/draft", response_model=RuleDraft)
def draft(body: RuleDraftRequest, p: CanRead, ctx: Ctx, db: DB) -> RuleDraft:
    """Parse only: nothing is stored. Unclear text comes back as questions, not as a guess."""
    check_site(p, body.site_id)
    vocab = ctx.search.site_vocab(db, body.site_id)
    d = parse_rule(body.text, body.site_id, vocab, p.name, service.place_labels(db, body.site_id))
    if d.rule is not None:
        d.backtest = backtest(db, d.rule, _site_tz(db, body.site_id), datetime.now(UTC))
    return d


@router.get("", response_model=list[RuleOut])
def list_rules(p: CanRead, db: DB, site_id: str | None = None) -> list[RuleOut]:
    if site_id is not None:
        check_site(p, site_id)
    sites = [site_id] if site_id else sorted(p.sites)
    rows = db.scalars(select(RuleRow).where(RuleRow.site_id.in_(sites)).order_by(RuleRow.created_at.desc())).all()
    now = datetime.now(UTC)
    synced: dict[str, bool | None] = {}
    for sid in {r.site_id for r in rows}:
        reported = edge_reports(db, sid, "rules_bundle", now)
        synced[sid] = None if reported is None else service.active_version(db, sid) in reported
    return [service.to_out(r, synced.get(r.site_id)) for r in rows]


@router.post("", response_model=RuleOut, status_code=201)
def propose(body: RuleCreate, p: CanPropose, ctx: Ctx, db: DB) -> RuleOut:
    rule = body.rule
    check_site(p, rule.site_id)
    problems = service.site_problems(db, rule)
    if problems:
        raise ProblemError(422, "Rule does not fit this site", "; ".join(problems))
    rule = rule.model_copy(update={"created_by": p.name, "approved_by": None})
    row = db.get(RuleRow, rule.rule_id)
    if row is not None and row.site_id != rule.site_id:
        raise ProblemError(409, "Rule id taken", "choose another rule id")  # do not reveal other sites
    if row is not None and row.status == "active":
        raise ProblemError(409, "Already active", "this rule is already running")
    bt = backtest(db, rule, _site_tz(db, rule.site_id), datetime.now(UTC))
    if row is None:
        tenant_id = db.get(Site, rule.site_id).tenant_id  # type: ignore[union-attr]
        row = RuleRow(id=rule.rule_id, tenant_id=tenant_id, site_id=rule.site_id, version=1)
        db.add(row)
    else:
        row.version += 1  # re-proposing a disabled or pending rule
    rule = rule.model_copy(update={"version": row.version})
    row.dsl = rule.model_dump(mode="json", by_alias=True)
    row.source_text = rule.source_text
    row.status = "pending"
    row.created_by = p.name
    row.approved_by = None
    row.backtest = bt.model_dump(mode="json")
    audit.record(
        db,
        "rule.proposed",
        p.name,
        target=rule.rule_id,
        details={"site_id": rule.site_id, "text": rule.source_text, "matches_7d": bt.matches},
        tenant_id=row.tenant_id,
    )
    db.commit()
    ctx.hub.publish("rules.updated", rule.site_id, {"rule_id": rule.rule_id, "status": "pending"})
    return service.to_out(row)


@router.post("/{rule_id}/approve", response_model=RuleOut)
def approve(rule_id: str, p: CanManage, ctx: Ctx, db: DB) -> RuleOut:
    row = _row(db, p, rule_id)
    if row.status != "pending":
        raise ProblemError(409, f"Rule is {row.status}", "only a pending rule can be approved")
    row.status = "active"
    row.approved_by = p.name
    row.dsl = {**row.dsl, "approved_by": p.name, "version": row.version}
    audit.record(db, "rule.approved", p.name, target=rule_id, details={"site_id": row.site_id}, tenant_id=row.tenant_id)
    db.commit()
    ctx.hub.publish("rules.updated", row.site_id, {"rule_id": rule_id, "status": "active"})
    return service.to_out(row)


@router.post("/{rule_id}/disable", response_model=RuleOut)
def disable(rule_id: str, p: CanManage, ctx: Ctx, db: DB) -> RuleOut:
    row = _row(db, p, rule_id)
    if row.status == "disabled":
        return service.to_out(row)
    row.status = "disabled"
    audit.record(db, "rule.disabled", p.name, target=rule_id, details={"site_id": row.site_id}, tenant_id=row.tenant_id)
    db.commit()
    ctx.hub.publish("rules.updated", row.site_id, {"rule_id": rule_id, "status": "disabled"})
    return service.to_out(row)
