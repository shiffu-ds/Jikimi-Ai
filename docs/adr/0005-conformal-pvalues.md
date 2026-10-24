# ADR-0005: Split-conformal p-values instead of fixed thresholds

- **Status:** accepted
- **Date:** 2026-10-23
- **Feature / gap:** F7, G29, G44

## Context
Fixed thresholds do not transfer between sites; guards stop trusting noisy alerts.

## Decision
Each candidate gets p = (1 + #cal >= s) / (n + 1) against the site's normal calibration set; routes: ALERT_NOW p <= alpha_alert, VERIFY p <= alpha_verify.

## Consequences
A per-unit false-alarm guarantee (under exchangeability). See ADR-0021: alpha must be chosen from the candidate rate.
