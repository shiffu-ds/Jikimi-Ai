from __future__ import annotations

from fastapi import APIRouter, Request, Response
from jikimi_contracts.api import LoginRequest, UserInfo
from sqlalchemy import select

from ...core import audit
from ...core.rbac import permissions
from ...core.security import issue_jwt, verify_password
from ...db.models import User
from ..deps import COOKIE, DB, Ctx, Me
from ..errors import ProblemError

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def user_info(u: User) -> UserInfo:
    return UserInfo(
        id=u.id,
        username=u.username,
        name=u.name,
        role=u.role,  # type: ignore[arg-type]
        tenant_id=u.tenant_id,
        site_ids=[str(s) for s in u.site_ids] if u.site_ids is not None else None,
        permissions=permissions(u.role),
    )


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, ctx: Ctx, db: DB) -> dict[str, object]:
    ip = request.client.host if request.client else "?"
    allowed, retry = ctx.login_limiter.allow(f"login:{ip}")
    if not allowed:
        raise ProblemError(429, "Too many login attempts", headers={"Retry-After": str(int(retry) + 1)})
    user = db.scalar(select(User).where(User.username == body.username.strip().lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        audit.record(db, "login.failed", body.username[:64], None, {"ip": ip})
        raise ProblemError(401, "Wrong username or password")
    token = issue_jwt(ctx.settings.jwt_secret, user.id, user.tenant_id, user.role, ctx.settings.jwt_ttl_s)
    response.set_cookie(
        COOKIE,
        token,
        max_age=ctx.settings.jwt_ttl_s,
        httponly=True,
        samesite="strict",
        secure=ctx.settings.cookie_secure,
        path="/",
    )
    audit.record(db, "login", user.username, None, {"ip": ip}, user.tenant_id)
    return {"user": user_info(user).model_dump(mode="json"), "token": token}


@router.post("/logout", status_code=204)
def logout(response: Response) -> Response:
    response.delete_cookie(COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=UserInfo)
def me(p: Me) -> UserInfo:
    return user_info(p.user)
