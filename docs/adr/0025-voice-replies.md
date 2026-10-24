# ADR-0025: Guard voice replies are transcribed, shown, and sent only on a tap

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-24
- **Feature / gap:** F12, G03; results in `docs/results.md` ("Guard voice replies")

## Context
Many guards read neither English nor long Urdu text comfortably; speaking is easier than typing.
But a speech model that mishears "madad chahiye" as "dekh liya" would silently close a call for
help, and Whisper is known to invent text in noise. The plan's real test (200 guard recordings)
does not exist yet, and the laptop CPU needs ~4-5 s per reply with Whisper small.

## Decision
- The guard app records a short reply (<= 8 s) and posts it to `/v1/voice/reply`; the server
  transcribes it with faster-whisper small (int8, CPU, Silero VAD on, no initial prompt) and
  returns the text and the intent. **Nothing is applied by the server**: the app shows "you said
  ... -> Seen / False alarm / Need help" and sends the usual ack / review / SOS only when the guard
  taps it, with the text as the note. Audio is decoded in memory and dropped.
- One intent parser for voice and SMS (`jikimi_common.intents`): phrases in Roman Urdu, Urdu
  script, Devanagari and English; help beats false alarm beats seen; a phrase negated in its
  clause does not count, but help only by the word right after it; anything else is "ask again".
- Optional on the server (`uv sync --extra voice` + a local model folder); without it the endpoint
  answers 503 and the app keeps its buttons. Nothing is downloaded at run time.

## Consequences
A misheard reply costs one more tap, never a wrong action. ~5 s per reply on the laptop is slow
but acceptable next to walking to the gate; a server CPU or the base model is faster. The written
test set is in-sample (93 % before tuning, 99 % after); the real number needs the guard
recordings (`eval.voice_check --audio`). Urdu TTS for alert voice notes is still the browser's
speech (many Android phones have no Urdu voice): recorded templates are the fallback the plan names.
