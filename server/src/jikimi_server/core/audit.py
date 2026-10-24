"""Hash-chained audit log (chain of custody, STRIDE "repudiation").

Every view/export/share of evidence, every ack, review, login and break-glass access is an
append-only row whose hash covers the previous row's hash. Editing or deleting any row breaks
the chain, which ``verify_chain`` reports.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import datetime
from typing import Any

from jikimi_crypto import canonicalize
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import AuditLog, now_utc

_lock = threading.Lock()  # one writer at a time keeps the chain linear (PG: advisory lock)


def _row_hash(
    prev: str | None, actor: str | None, action: str, target: str | None, details: dict[str, Any], at: datetime
) -> str:
    body = canonicalize({"actor": actor, "action": action, "target": target, "details": details, "at": at.isoformat()})
    return hashlib.sha256((prev or "").encode() + body).hexdigest()


def record(
    db: Session,
    action: str,
    actor: str | None,
    target: str | None = None,
    details: dict[str, Any] | None = None,
    tenant_id: uuid.UUID | None = None,
) -> AuditLog:
    details = details or {}
    with _lock:
        prev = db.scalar(select(AuditLog.row_hash).order_by(AuditLog.id.desc()).limit(1))
        at = now_utc().replace(microsecond=0)
        row = AuditLog(
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            target=target,
            details=details,
            prev_hash=prev,
            row_hash=_row_hash(prev, actor, action, target, details, at),
            at=at,
        )
        db.add(row)
        db.flush()
    return row


def verify_chain(db: Session) -> tuple[bool, int, int | None]:
    """``(ok, rows_checked, first_bad_id)``."""
    prev: str | None = None
    n = 0
    for row in db.scalars(select(AuditLog).order_by(AuditLog.id)):
        n += 1
        expected = _row_hash(prev, row.actor, row.action, row.target, row.details or {}, row.at)
        if row.prev_hash != prev or row.row_hash != expected:
            return False, n, row.id
        prev = row.row_hash
    return True, n, None
