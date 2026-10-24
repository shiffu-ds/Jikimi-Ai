## What & why
<!-- feature id (F1-F22) / gap id (G01-G45) / issue -->

## Checklist (Definition of Done, plan 17.7)
- [ ] `make test` passes (unit + API + contracts + typecheck)
- [ ] Alert behaviour changed? -> golden case added/updated (`eval/golden/expected_alerts.jsonl`) and `make replay` passes
- [ ] Runs in the laptop profile within the RAM budget
- [ ] Docs / ADR / Urdu user guide updated where needed
- [ ] No secrets (gitleaks), no model weights or raw video in git

## Privacy impact
- [ ] Adds new data, exports, retention or sharing? If yes, explain and link the DPIA note.
- [ ] Never adds face recognition or demographic inference.
