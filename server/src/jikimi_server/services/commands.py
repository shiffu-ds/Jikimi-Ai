"""Admin commands for edges (accept a camera's new view): stored, bundled, signed, marked done."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime, timedelta

from jikimi_contracts.commands import CommandBundle, EdgeCommand
from jikimi_crypto import Signer, canonicalize
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import EdgeCommandRow

EXPIRE = timedelta(hours=24)  # an edge offline for a day gets no stale "accept view"


def to_out(row: EdgeCommandRow) -> EdgeCommand:
    return EdgeCommand(
        id=row.id,
        kind=row.kind,  # type: ignore[arg-type]
        camera_id=row.camera_id,
        issued_by=row.issued_by,
        issued_at=row.issued_at,
    )


def pending(db: Session, site_id: str, now: datetime) -> list[EdgeCommand]:
    rows = db.scalars(
        select(EdgeCommandRow)
        .where(
            EdgeCommandRow.site_id == site_id,
            EdgeCommandRow.done_at.is_(None),
            EdgeCommandRow.issued_at >= now - EXPIRE,
        )
        .order_by(EdgeCommandRow.issued_at)
    ).all()
    return [to_out(r) for r in rows]


def bundle(db: Session, site_id: str, signer: Signer, now: datetime) -> CommandBundle:
    commands = pending(db, site_id, now)
    version = hashlib.sha256(canonicalize([c.model_dump(mode="json") for c in commands])).hexdigest()[:16]
    unsigned = CommandBundle(
        site_id=site_id,
        version=version,
        commands=commands,
        key_id=signer.key_id,
        public_key=signer.public_key,
        signed_at=now,
        signature="",
    )
    return unsigned.model_copy(update={"signature": signer.sign(unsigned.signing_payload())})


def mark_done(db: Session, site_id: str, ids: Iterable[object], now: datetime) -> int:
    """Called from the heartbeat: the edge lists the commands it has carried out."""
    wanted = [str(i) for i in ids][:100]
    if not wanted:
        return 0
    rows = db.scalars(
        select(EdgeCommandRow).where(
            EdgeCommandRow.site_id == site_id, EdgeCommandRow.id.in_(wanted), EdgeCommandRow.done_at.is_(None)
        )
    ).all()
    for r in rows:
        r.done_at = now
    return len(rows)
