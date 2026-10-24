"""Voice replies (F12): intent accuracy on written replies, and speech-to-text on recordings.

    uv run python -m eval.voice_check            # intents on eval/voice/replies.tsv
    uv run python -m eval.voice_check --tts      # + English replies spoken by ffmpeg's flite voice, noise, silence
    uv run python -m eval.voice_check --audio D  # + your recordings, named <intent>__*.webm|ogg|wav|m4a|mp3
                                                 #   (intent: ack, false_alarm, need_help or none)

The written set was made while building the parser, so it is in-sample: an upper bound. The
plan's real test (Section 8.12) is 200 recordings by guards; ``--audio`` scores them. A missed
call for help is the costly error and is counted on its own. Needs ``uv sync --extra voice`` and
the model (models/README.md) for anything but the written set.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INTENTS = ("ack", "false_alarm", "need_help", "none")
TTS = [
    ("ack", "I have seen it"),
    ("ack", "Okay, I am coming"),
    ("false_alarm", "This is a false alarm"),
    ("false_alarm", "Nothing here, all clear"),
    ("need_help", "Need help, send the police"),
    ("need_help", "Help, there is a thief"),
]


def _script(text: str) -> str:
    for ch in text:
        name = unicodedata.name(ch, "")
        if name.startswith("ARABIC"):
            return "urdu"
        if name.startswith("DEVANAGARI"):
            return "devanagari"
    return "latin"


def _score(rows: list[tuple[str, str]]) -> dict[str, Any]:
    """rows: (truth, predicted) with "none" for no intent."""
    by: dict[str, list[int]] = {k: [0, 0] for k in INTENTS}
    confusion: Counter[str] = Counter()
    for truth, got in rows:
        by[truth][0] += truth == got
        by[truth][1] += 1
        if truth != got:
            confusion[f"{truth}->{got}"] += 1
    ok = sum(a for a, _ in by.values())
    return {
        "n": len(rows),
        "accuracy": round(ok / max(len(rows), 1), 3),
        "per_intent": {k: f"{a}/{n}" for k, (a, n) in by.items() if n},
        "help_missed": sum(1 for t, g in rows if t == "need_help" and g != "need_help"),
        "acted_on_unclear": sum(1 for t, g in rows if t == "none" and g != "none"),
        "errors": dict(confusion.most_common()),
    }


def written(path: Path) -> dict[str, Any]:
    from jikimi_common.intents import reply_intent

    rows, by_script, misses = [], {}, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        truth, text = line.split("\t", 1)
        got = reply_intent(text)[0] or "none"
        rows.append((truth, got))
        by_script.setdefault(_script(text), []).append((truth, got))
        if got != truth:
            misses.append({"text": text, "truth": truth, "got": got})
    out = _score(rows)
    out["per_script"] = {k: _score(v)["accuracy"] for k, v in sorted(by_script.items())}
    out["misses"] = misses
    return out


def _transcriber() -> Any:
    from jikimi_server.services.voice import Transcriber

    t = Transcriber(ROOT / "models/faster-whisper-small")
    if not t.available:
        raise SystemExit("speech model missing: `uv sync --extra voice` and models/README.md (faster-whisper-small)")
    t0 = time.perf_counter()
    t.warm()
    t.load_s = round(time.perf_counter() - t0, 1)  # type: ignore[attr-defined]
    return t


def recordings(files: list[tuple[str, Path]], lang: str, transcriber: Any) -> dict[str, Any]:
    rows, items = [], []
    for truth, f in files:
        r = transcriber.reply(f.read_bytes(), lang)
        got = r.intent or "none"
        rows.append((truth, got))
        items.append({"file": f.name, "truth": truth, "text": r.text, "got": got, "seconds": r.duration_s, "ms": r.ms})
    out = _score(rows)
    ms = sorted(i["ms"] for i in items if i["seconds"] > 0.5 and i["text"])
    out["ms_per_reply_p50"] = ms[len(ms) // 2] if ms else None
    out["items"] = items
    return out


def synth(tmp: Path) -> list[tuple[str, Path]]:
    """English replies in flite's voice (ffmpeg), pink noise and silence: plumbing and VAD check."""
    out = []
    for i, (intent, text) in enumerate(TTS):
        f = tmp / f"{intent}__{i}.webm"
        voice = f"flite=text='{text}':voice=slt"
        cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", voice, "-ar", "16000", "-ac", "1"]
        subprocess.run([*cmd, "-c:a", "libopus", "-b:a", "24k", str(f)], check=True)
        out.append((intent, f))
    for name, src in (("noise", "anoisesrc=d=4:c=pink:a=0.08"), ("silence", "anullsrc=r=16000:cl=mono")):
        f = tmp / f"none__{name}.webm"
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                src,
                "-t",
                "4",
                "-ac",
                "1",
                "-c:a",
                "libopus",
                str(f),
            ],
            check=True,
        )
        out.append(("none", f))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--replies", default=str(ROOT / "eval/voice/replies.tsv"))
    ap.add_argument("--tts", action="store_true", help="English replies spoken by ffmpeg's flite voice")
    ap.add_argument("--audio", help="folder of recordings named <intent>__*.webm|ogg|wav|m4a|mp3")
    ap.add_argument("--lang", default="ur", choices=["ur", "en"], help="language of the --audio recordings")
    ap.add_argument("--report", default="eval/reports/voice_check.json")
    args = ap.parse_args()

    report: dict[str, Any] = {"written": written(Path(args.replies))}
    if args.tts or args.audio:
        tr = _transcriber()
        report["model"] = {"name": "faster-whisper-small int8 (CPU)", "load_s": tr.load_s}
        if args.tts:
            with tempfile.TemporaryDirectory() as tmp:
                report["tts_en"] = recordings(synth(Path(tmp)), "en", tr)
        if args.audio:
            exts = {".webm", ".ogg", ".wav", ".m4a", ".mp3", ".opus"}
            files = [
                (f.name.split("__")[0], f)
                for f in sorted(Path(args.audio).iterdir())
                if f.suffix.lower() in exts and f.name.split("__")[0] in INTENTS
            ]
            report["recordings"] = recordings(files, args.lang, tr)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
