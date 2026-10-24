"""Guard voice replies (F12): speech -> text with faster-whisper (CPU, int8) -> intent.

Optional: ``uv sync --extra voice`` and a CTranslate2 Whisper model in ``models/faster-whisper-small``
(models/README.md). Without them the endpoint answers 503 and the guard app keeps its buttons.

* The audio is decoded in memory (PyAV, any browser format: webm/opus, ogg, mp4/aac, wav), cut
  to 15 s, transcribed and dropped; only the text the guard confirms is kept (in the ack note).
* Silero VAD (inside faster-whisper) drops silence and noise first, so a pocket recording gives an
  empty text, not an invented "dekh liya". No initial prompt either: it would bias unclear speech
  towards exactly the phrases that change an alert.
* One transcription at a time: two CPU-bound ones in parallel would only both be slow.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from jikimi_common.intents import reply_intent
from jikimi_contracts.api import VoiceReply

log = logging.getLogger(__name__)
RATE = 16000
MAX_SECONDS = 15.0
LANGUAGES = ("ur", "en")


class VoiceUnavailable(RuntimeError):
    """No speech model on this server (the guard app falls back to its buttons)."""


def decode(audio: bytes, max_s: float = MAX_SECONDS) -> np.ndarray:
    """Any container / codec PyAV can read -> 16 kHz mono float32, at most ``max_s`` seconds."""
    import av

    resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
    chunks: list[np.ndarray] = []
    have, limit = 0, int(max_s * RATE)
    try:
        with av.open(io.BytesIO(audio), mode="r") as container:
            for frame in container.decode(audio=0):
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray().reshape(-1))
                    have += chunks[-1].size
                if have >= limit:
                    break
            else:
                chunks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(None))
    except Exception as e:  # untrusted upload: not audio, no audio stream, truncated, ...
        raise ValueError(f"could not decode the audio: {e}") from e
    pcm = np.concatenate(chunks)[:limit] if chunks else np.zeros(0, np.int16)
    return pcm.astype(np.float32) / 32768.0


class Transcriber:
    def __init__(self, model_dir: Path | None, threads: int = 2) -> None:
        self.model_dir = model_dir
        self.threads = threads
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        if self.model_dir is None or not (self.model_dir / "model.bin").exists():
            return False
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self) -> Any:
        if self._model is None:
            if not self.available:
                raise VoiceUnavailable("no speech model: `uv sync --extra voice` + models/faster-whisper-small")
            from faster_whisper import WhisperModel

            try:
                self._model = WhisperModel(
                    str(self.model_dir), device="cpu", compute_type="int8", cpu_threads=self.threads
                )
            except Exception as e:  # incomplete download, other CTranslate2 version, ...
                raise VoiceUnavailable(f"speech model could not be loaded: {e}") from e
        return self._model

    def warm(self) -> None:
        """Load the model ahead of the first reply (~10 s from a cold disk)."""
        try:
            with self._lock:
                self._load()
        except VoiceUnavailable as e:
            log.warning("voice replies off: %s", e)

    def reply(self, audio: bytes, lang: str = "ur") -> VoiceReply:
        t0 = time.perf_counter()
        samples = decode(audio)
        with self._lock:
            segments, info = self._load().transcribe(
                samples,
                language=lang if lang in LANGUAGES else "ur",
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
        intent, matched = reply_intent(text)
        return VoiceReply(
            text=text,
            language=info.language,
            intent=intent,
            matched=matched,
            duration_s=round(samples.size / RATE, 2),
            ms=int((time.perf_counter() - t0) * 1000),
        )
