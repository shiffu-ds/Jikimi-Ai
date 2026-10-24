# Contributing

Shukriya! Ye project ek team ya akele developer dono ke liye bana hai (plan Section 6.6).

## Setup
```bash
make setup    # uv + npm dependencies, pre-commit hooks
make env      # .env with random secrets
make demo     # API + dashboard + simulated edge on http://localhost:8000
```

## Rules (plan Section 7.20)
- **Trunk-based:** small `feat/…`, `fix/…`, `data/…`, `ml/…` branches, merged in 1-3 days.
- **Conventional Commits:** `feat(edge): add loitering plugin`, `fix(server): …`.
- **Definition of Done:** tests pass (`make test`), behaviour changes add/update a golden case
  (`eval/golden/expected_alerts.jsonl`), runs on the laptop profile, docs/ADR updated, no secrets
  (gitleaks), no new data without consent.
- **Contracts:** change `packages/jikimi-contracts`, then `make types`; CI fails on drift.
- **Privacy impact:** every PR answers "does this add data, exports or retention?" in the template.
- **Language:** code and comments in English; UI and user docs in Urdu + English.
