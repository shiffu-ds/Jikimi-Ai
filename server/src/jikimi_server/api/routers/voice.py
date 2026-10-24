"""Guard voice replies (F12): the guard app posts a short recording and gets the text and the
intent back. Nothing is applied here; the guard confirms, and the app sends the usual ack /
review / SOS with the text as its note."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from jikimi_contracts.api import VoiceReply

from ...services.voice import VoiceUnavailable
from ..deps import Ctx, Principal, require
from ..errors import ProblemError

router = APIRouter(prefix="/v1", tags=["voice"])
CanAck = Annotated[Principal, Depends(require("alerts:ack"))]
MAX_BYTES = 2_000_000  # ~15 s of webm/opus is ~40 kB; even 15 s of 16 kHz WAV fits


@router.post("/voice/reply", response_model=VoiceReply)
async def voice_reply(request: Request, p: CanAck, ctx: Ctx, lang: Literal["ur", "en"] = "ur") -> VoiceReply:
    if not ctx.voice.available:
        raise ProblemError(503, "Voice replies unavailable", "no speech model on this server; use the buttons")
    allowed, retry = ctx.voice_limiter.allow(f"voice:{p.user.id}")
    if not allowed:
        raise ProblemError(429, "Too many requests", headers={"Retry-After": str(int(retry) + 1)})
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise ProblemError(413, "Recording too long", "send at most 15 seconds")
    if not body:
        raise ProblemError(400, "Empty recording")
    try:
        return await run_in_threadpool(ctx.voice.reply, bytes(body), lang)
    except ValueError as e:
        raise ProblemError(400, "Not an audio recording", str(e)) from e
    except VoiceUnavailable as e:
        raise ProblemError(503, "Voice replies unavailable", str(e)) from e
