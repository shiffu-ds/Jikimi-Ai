"""FastAPI application factory: ``uvicorn jikimi_server.main:create_app --factory``."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import __version__
from .api import errors
from .api.routers import alerts, auth, calendar, edge, evidence, media, rules, search, sites, verify, voice, ws
from .context import AppContext
from .settings import ServerSettings
from .workers import Workers

log = logging.getLogger(__name__)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(self), geolocation=()",
}


def create_app(settings: ServerSettings | None = None) -> FastAPI:
    settings = settings or ServerSettings.from_env()
    settings.validate()
    ctx = AppContext.build(settings)
    # creates missing tables only (fresh SQLite or PostgreSQL); schema changes after v0.1 ship as
    # Alembic migrations (`alembic upgrade head`) before the app starts
    ctx.db.create_all()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ctx.hub.bind(asyncio.get_running_loop())
        stop = asyncio.Event()
        task = asyncio.create_task(Workers(ctx).run(stop)) if settings.workers_inprocess else None
        if ctx.voice.available:
            ctx.executor.submit(ctx.voice.warm)  # the first guard reply should not wait ~10 s
        if ctx.verifier.available and ctx.verifier.types():  # a VLM that passed no type is never used
            ctx.executor.submit(ctx.verifier.warm)
        log.info(
            "Jikimi server %s ready (db=%s, dashboard=%s)",
            __version__,
            ctx.db.url.split("://")[0],
            settings.dashboard_dir.exists(),
        )
        try:
            yield
        finally:
            stop.set()
            if task is not None:
                await task
            ctx.executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(
        title="Jikimi AI",
        version=__version__,
        summary="Edge-first AI guard for existing CCTV - Roman Urdu search, offline alerts, tamper-evident evidence",
        lifespan=lifespan,
    )
    app.state.ctx = ctx
    errors.install(app)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    for r in (
        auth.router,
        edge.router,
        alerts.router,
        search.router,
        evidence.router,
        verify.router,
        sites.router,
        rules.router,
        calendar.router,
        media.router,
        voice.router,
        ws.router,
    ):
        app.include_router(r)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    if settings.dashboard_dir.exists():
        app.mount("/", StaticFiles(directory=settings.dashboard_dir, html=True), name="dashboard")
    else:

        @app.get("/", include_in_schema=False)
        def root() -> dict[str, str]:
            return {"name": "Jikimi AI", "docs": "/docs", "dashboard": "not built - run `make web`"}

    return app
