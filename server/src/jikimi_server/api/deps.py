"""Request dependencies: DB session, current user/device, permissions, tenant + site scoping."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..context import AppContext
from ..core.rbac import can
from ..core.security import decode_jwt, token_hash
from ..db.models import Device, Site, User
from .errors import ProblemError

COOKIE = "jikimi_session"
CLIENT_HEADER = "x-jikimi-client"


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx  # type: ignore[no-any-return]


def get_db(ctx: Annotated[AppContext, Depends(get_ctx)]) -> Iterator[Session]:
    s = ctx.db.SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


Ctx = Annotated[AppContext, Depends(get_ctx)]
DB = Annotated[Session, Depends(get_db)]


@dataclass
class Principal:
    user: User
    sites: frozenset[str]
    via_cookie: bool

    @property
    def name(self) -> str:
        return self.user.username

    def can(self, perm: str) -> bool:
        return can(self.user.role, perm)


def _token(request: Request) -> tuple[str | None, bool]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip(), False
    cookie = request.cookies.get(COOKIE)
    return (cookie, True) if cookie else (None, False)


def user_sites(db: Session, user: User) -> frozenset[str]:
    tenant_sites = set(db.scalars(select(Site.id).where(Site.tenant_id == user.tenant_id)))
    if user.site_ids is None:
        return frozenset(tenant_sites)
    return frozenset(tenant_sites & {str(s) for s in user.site_ids})


def resolve_principal(request: Request, ctx: AppContext, db: Session) -> Principal | None:
    token, via_cookie = _token(request)
    if not token:
        return None
    claims = decode_jwt(ctx.settings.jwt_secret, token)
    if claims is None or claims.scope != "user":
        return None
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active or user.tenant_id != claims.tenant_id:
        return None
    return Principal(user=user, sites=user_sites(db, user), via_cookie=via_cookie)


def current_principal(request: Request, ctx: Ctx, db: DB) -> Principal:
    p = resolve_principal(request, ctx, db)
    if p is None:
        raise ProblemError(401, "Login required", "missing or expired session")
    # CSRF defence for cookie sessions: state-changing requests need a custom header (forces CORS preflight)
    if p.via_cookie and request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CLIENT_HEADER) is None:
        raise ProblemError(
            403, "Missing client header", f"send '{CLIENT_HEADER}: web' with cookie-authenticated writes"
        )
    return p


Me = Annotated[Principal, Depends(current_principal)]


def require(perm: str) -> Callable[[Principal], Principal]:
    def dep(p: Me) -> Principal:
        if not p.can(perm):
            raise ProblemError(403, "Not allowed", f"role '{p.user.role}' lacks '{perm}'")
        return p

    return dep


def check_site(p: Principal, site_id: str) -> None:
    """Tenant + site isolation. 404 (not 403) so other tenants' site ids are not disclosed."""
    if site_id not in p.sites:
        raise ProblemError(404, "Not found", "site not found")


def current_device(request: Request, db: DB) -> Device:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise ProblemError(401, "Device token required")
    dev = db.scalar(select(Device).where(Device.token_hash == token_hash(auth[7:].strip())))
    if dev is None or dev.status != "active":
        raise ProblemError(401, "Unknown or revoked device")
    return dev


EdgeDevice = Annotated[Device, Depends(current_device)]
