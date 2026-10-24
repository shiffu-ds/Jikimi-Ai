"""Public verification portal API (Boundary 3: read-only, rate-limited, no video)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from jikimi_contracts.evidence import FileMatch, VerificationReport

from ...db.models import Device, Evidence
from ..deps import DB, Ctx
from ..errors import ProblemError

router = APIRouter(tags=["verify"])
_EV = re.compile(r"^EV-\d{4}-\d{2}-\d{2}-\d{4}$")
_SHA = re.compile(r"^[0-9a-fA-F]{64}$")


def _limit(ctx: Ctx, request: Request) -> None:
    ip = request.client.host if request.client else "?"
    ok, retry = ctx.verify_limiter.allow(f"verify:{ip}")
    if not ok:
        raise ProblemError(429, "Too many requests", headers={"Retry-After": str(int(retry) + 1)})


def _load(db: DB, ev_id: str) -> Evidence:
    if not _EV.match(ev_id):
        raise ProblemError(404, "Evidence not found")
    ev = db.get(Evidence, ev_id)
    if ev is None:
        raise ProblemError(404, "Evidence not found")
    return ev


@router.get("/verify/{ev_id}", include_in_schema=False)
def verify_page(ev_id: str) -> RedirectResponse:
    """QR codes point here; the static portal page reads ``?id=``."""
    return RedirectResponse(f"/verify/?id={ev_id}", status_code=307)


@router.get("/v1/verify/{ev_id}", response_model=VerificationReport)
def verify(ev_id: str, request: Request, ctx: Ctx, db: DB) -> VerificationReport:
    _limit(ctx, request)
    return ctx.evidence.verify(db, _load(db, ev_id))


@router.get("/v1/verify/{ev_id}/match", response_model=FileMatch)
def match(ev_id: str, sha256: str, request: Request, ctx: Ctx, db: DB) -> FileMatch:
    """Does a file (by its SHA-256, computed in the browser) belong to this pack?"""
    _limit(ctx, request)
    if not _SHA.match(sha256):
        raise ProblemError(422, "sha256 must be 64 hex characters")
    ev = _load(db, ev_id)
    report = ctx.evidence.verify(db, ev)
    return ctx.evidence.match(ev, report, sha256)


@router.get("/v1/keys/server")
def server_key(ctx: Ctx) -> dict[str, str]:
    return {"key_id": ctx.evidence.signer.key_id, "public_key": ctx.evidence.signer.public_key, "algorithm": "Ed25519"}


@router.get("/v1/keys/devices/{key_id}")
def device_key(key_id: str, db: DB) -> dict[str, str]:
    dev = db.query(Device).filter(Device.key_id == key_id).one_or_none()
    if dev is None:
        raise ProblemError(404, "Unknown key")
    return {"key_id": dev.key_id, "public_key": dev.public_key, "status": dev.status, "algorithm": "Ed25519"}
