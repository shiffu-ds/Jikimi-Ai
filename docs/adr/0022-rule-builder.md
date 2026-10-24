# ADR-0022: Rule builder: deterministic parser, backtest, approval, pinned signed bundle

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-24
- **Feature / gap:** F11, plan Section 8.11

## Context
The plan turns a Roman Urdu sentence into a rule with "LLM structured output", then validates, backtests and asks an admin to approve. A rule runs unattended on cameras, so a hallucinated zone, time or threshold is a silent false-alarm generator (or a silent hole). The plan also says "signed config on the edge" without saying which key signs it or how the edge knows that key.

## Decision
- **Parser first, LLM optional:** a deterministic lexicon parser (`server/.../rules/parser.py`, sharing the F1 search lexicon) produces the `Rule` DSL. Anything it cannot pin down (no place, unknown zone, "11 baje" without subah/raat, "der tak" without a number) becomes a clarification question, never a guess. An LLM may later sit behind the same `RuleDraft` output.
- **Validated against the site:** cameras must belong to the site and the zone must lie on those cameras; the rule id is a hash of the rule's meaning, so proposing the same rule twice updates it.
- **Backtest before approval:** 7 days of indexed track summaries; dwell is time on camera (an upper bound), so the estimate errs towards "noisy".
- **Two people:** supervisors propose (`rules:propose`), admins/owners approve (`rules:manage`); every step is in the hash-chained audit log.
- **Signed bundle, pinned key:** the edge pulls `/v1/edge/rules` (active rules only), signed by the server key. The first accepted bundle pins that key in `keys/server.pub` (trust on first use over the authenticated device channel); later bundles from another key are refused, and so are bundles signed before the one already applied (a replayed old bundle would roll rules back). The last bundle is stored, so rules survive a reboot without internet.
- **Condition semantics:** dwell alone = once per track; count alone = more objects at once (5 min refractory); both = more than N objects that *each* stayed longer than T.

## Consequences
No unapproved or tampered rule reaches a camera, and every rule an admin approves has a plain Urdu name, its source sentence and a backtest attached. Free-form wording the lexicon does not know needs either a lexicon entry or the optional LLM path. Rotating the server key needs the pin replaced on each edge (`docs/runbooks/key_rotation.md`).
