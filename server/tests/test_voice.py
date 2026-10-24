from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from jikimi_server.services.voice import Transcriber, decode

from .conftest import Env


def _wav(seconds: float = 1.0, rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(seconds * rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 10))) for i in range(n)))
    return buf.getvalue()


class _Heard(Transcriber):
    """The real decoder and intent parser; the speech model replaced by a fixed transcript."""

    def __init__(self, text: str) -> None:
        super().__init__(Path("unused"))
        self.text = text
        self.calls: list[dict[str, Any]] = []

    @property
    def available(self) -> bool:
        return True

    def _load(self) -> Any:
        def transcribe(samples: Any, **kw: Any) -> tuple[Any, Any]:
            self.calls.append({"seconds": samples.size / 16000, **kw})
            return iter([SimpleNamespace(text=f" {self.text} ")]), SimpleNamespace(language=kw["language"])

        return SimpleNamespace(transcribe=transcribe)


def test_decoder_resamples_to_16k_and_cuts_long_recordings() -> None:
    assert abs(decode(_wav(1.0, 8000)).size - 16000) < 400
    assert decode(_wav(3.0, 16000), max_s=2.0).size == 32000


def test_guard_voice_reply_is_transcribed_but_not_applied(env: Env) -> None:
    guard = {**env.login("akram"), "Content-Type": "audio/wav"}
    assert env.client.post("/v1/voice/reply", content=_wav(), headers=guard).status_code == 503  # no model
    heard = _Heard("ہاں، دیکھ لیا")
    env.app.state.ctx.voice = heard
    r = env.client.post("/v1/voice/reply", content=_wav(), headers=guard)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == "ack" and body["matched"] == "ہاں" and body["text"] == "ہاں، دیکھ لیا"
    assert abs(body["duration_s"] - 1.0) < 0.05 and heard.calls[0]["vad_filter"] is True
    assert heard.calls[0]["language"] == "ur"
    assert env.client.post("/v1/voice/reply?lang=en", content=_wav(), headers=guard).json()["language"] == "en"
    assert env.client.post("/v1/voice/reply", content=b"not audio", headers=guard).status_code == 400
    assert env.client.post("/v1/voice/reply", content=b"", headers=guard).status_code == 400
    assert env.client.post("/v1/voice/reply", content=b"\0" * 2_000_001, headers=guard).status_code == 413
    police = {**env.login("police"), "Content-Type": "audio/wav"}
    assert env.client.post("/v1/voice/reply", content=_wav(), headers=police).status_code == 403
    alerts = env.client.get("/v1/alerts", headers=env.login("akram")).json()["items"]
    assert all(a["status"] != "acknowledged" for a in alerts)  # nothing applied without the guard's tap
