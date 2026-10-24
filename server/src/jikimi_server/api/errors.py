"""RFC 9457 problem details for every error response."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..services.alerts import TransitionError
from ..services.edge_ingest import IngestError

PROBLEM = "application/problem+json"
BASE = "https://jikimi.example/errors/"


def problem(
    status: int,
    title: str,
    detail: str | None = None,
    instance: str | None = None,
    type_: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "type": BASE + type_ if type_ else "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": instance,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM, headers=headers)


class ProblemError(HTTPException):
    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        type_: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status, detail=detail, headers=headers)
        self.title = title
        self.type_ = type_


def install(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem(
            exc.status_code,
            exc.title,
            exc.detail if isinstance(exc.detail, str) else None,
            request.url.path,
            exc.type_,
            exc.headers,
        )

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        titles = {
            401: "Login required",
            403: "Not allowed",
            404: "Not found",
            405: "Method not allowed",
            429: "Too many requests",
        }
        return problem(
            exc.status_code,
            titles.get(exc.status_code, "Error"),
            str(exc.detail) if exc.detail else None,
            request.url.path,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []))
        return problem(
            422, "Request did not validate", f"{loc}: {first.get('msg', 'invalid')}", request.url.path, "validation"
        )

    @app.exception_handler(IngestError)
    async def _ingest(request: Request, exc: IngestError) -> JSONResponse:
        return problem(exc.status, exc.title, exc.detail, request.url.path, "edge-ingest")

    @app.exception_handler(TransitionError)
    async def _transition(request: Request, exc: TransitionError) -> JSONResponse:
        return problem(409, "Alert state does not allow this", str(exc), request.url.path, "alert-state")
