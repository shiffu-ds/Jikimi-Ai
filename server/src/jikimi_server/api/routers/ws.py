"""Live updates over WebSocket (alerts, escalations, health). Cookie or ``?token=`` auth."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket

from ...core.security import decode_jwt
from ...db.models import User
from ..deps import COOKIE, user_sites

router = APIRouter(tags=["live"])


@router.websocket("/v1/ws")
async def live(ws: WebSocket) -> None:
    ctx = ws.app.state.ctx
    token = ws.cookies.get(COOKIE) or ws.query_params.get("token")
    claims = decode_jwt(ctx.settings.jwt_secret, token) if token else None
    if claims is None:
        await ws.close(code=4401)
        return
    with ctx.db.session() as db:
        user = db.get(User, claims.user_id)
        if user is None or not user.is_active:
            await ws.close(code=4401)
            return
        sites = user_sites(db, user)
        role, name = user.role, user.username
    await ctx.hub.serve(ws, role, sites, name)
