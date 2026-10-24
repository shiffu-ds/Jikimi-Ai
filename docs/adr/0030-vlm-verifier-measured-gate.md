# ADR-0030: The VLM verifier speaks only where it was measured to help

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-25
- **Feature / gap:** F5, F6 (G05, G20, G36); results in `docs/results.md` ("VLM verifier")

## Context
The plan sends VERIFY-band alerts to a VLM and distils its labels into the edge models. The only
VLM that fits this laptop is SmolVLM-256M (~5 s per frame on the CPU). Measured on labelled
simulator frames and the real clip, it does not know a snatch (AUC 0.40) or a covered camera
(0.53) from normal scenes, and it answers "yes" more readily to normal frames than to the event.
A wrong "looks normal" next to a real alert would mislead the guard more than no opinion.

## Decision
- The verifier asks A/B questions (both orders, P(A) from one forward pass), and
  `eval.vlm_check` writes `verifier.json` next to the model with each alert type's AUC and
  threshold. The server gives a verdict only for types with AUC >= 0.8; today: none.
- Mode **advisory** by default: the alert opens as before and a passed type's verdict is attached
  as an opinion. **Gate** mode (a "normal" verdict logs a VERIFY alert) is opt-in, and "unclear"
  never suppresses.
- Distillation keeps the plan's guards: teacher votes below 2/3 agreement are dropped, and a
  student is promoted only if AUC and calibration do not get worse on the fixed test set.

## Consequences
With SmolVLM-256M the whole path runs and is tested, but adds nothing: all 48 teacher calls of a
distillation round were "unclear". A larger VLM on a server GPU drops into the same folder and is
used once its own `vlm_check` passes - no code change.
