"""Rule storage, validation against the site, and the signed bundle the edge pulls (F11)."""

from __future__ import annotations

import hashlib
from datetime import datetime

from jikimi_contracts.rules_dsl import Rule, RuleBacktest, RuleBundle, RuleOut
from jikimi_crypto import Signer, canonicalize
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Camera
from ..db.models import Rule as RuleRow


def place_labels(db: Session, site_id: str) -> dict[str, str]:
    """zone / camera id -> label shown in the Urdu rule name (``name_ur``, else ``name``)."""
    names: dict[str, str] = {}
    for cam in db.scalars(select(Camera).where(Camera.site_id == site_id)):
        names[cam.id] = cam.name_ur or cam.name or cam.id
        for z in cam.zones or []:
            names[z["id"]] = z.get("name_ur") or z.get("name") or z["id"]
    return names


def site_problems(db: Session, rule: Rule) -> list[str]:
    """A rule may only name cameras of its site, and a zone that lies on one of those cameras."""
    cams = {c.id: c for c in db.scalars(select(Camera).where(Camera.site_id == rule.site_id))}
    problems = [f"camera '{cid}' is not on site '{rule.site_id}'" for cid in rule.when.camera_ids if cid not in cams]
    zone = rule.when.zone
    if zone and not any(zone in {z["id"] for z in cams[c].zones or []} for c in rule.when.camera_ids if c in cams):
        problems.append(f"zone '{zone}' is not on cameras {', '.join(rule.when.camera_ids)}")
    return problems


def to_out(row: RuleRow, on_edge: bool | None = None) -> RuleOut:
    return RuleOut(
        rule_id=row.id,
        site_id=row.site_id,
        status=row.status,
        rule=Rule.model_validate(row.dsl),
        created_by=row.created_by,
        approved_by=row.approved_by,
        version=row.version,
        created_at=row.created_at,
        backtest=RuleBacktest.model_validate(row.backtest) if row.backtest else None,
        on_edge=on_edge if row.status == "active" else None,
    )


def _active(db: Session, site_id: str) -> list[Rule]:
    rows = db.scalars(
        select(RuleRow).where(RuleRow.site_id == site_id, RuleRow.status == "active").order_by(RuleRow.id)
    ).all()
    return [Rule.model_validate(r.dsl) for r in rows]


def bundle_version(rules: list[Rule]) -> str:
    """Depends on the rules only, so the edge re-applies a bundle exactly when something changed."""
    return hashlib.sha256(canonicalize([r.model_dump(mode="json", by_alias=True) for r in rules])).hexdigest()[:16]


def active_version(db: Session, site_id: str) -> str:
    return bundle_version(_active(db, site_id))


def bundle(db: Session, site_id: str, signer: Signer, now: datetime) -> RuleBundle:
    """Active rules of the site, signed."""
    rules = _active(db, site_id)
    version = bundle_version(rules)
    unsigned = RuleBundle(
        site_id=site_id,
        version=version,
        rules=rules,
        key_id=signer.key_id,
        public_key=signer.public_key,
        signed_at=now,
        signature="",
    )
    return unsigned.model_copy(update={"signature": signer.sign(unsigned.signing_payload())})
