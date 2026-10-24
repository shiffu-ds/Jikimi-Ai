# Runbook: incident response (security or privacy)

1. Contain: revoke affected device tokens / user accounts; rotate `JIKIMI_JWT_SECRET` (logs everyone out).
2. Preserve: export the audit log (`GET /v1/audit`), check `GET /v1/audit/verify` (chain intact?).
3. Assess: which clips/evidence were accessed (`clip.view`, `evidence.download` rows).
4. Notify the site owner within 24 h; residents if their data was exposed.
5. Fix, add a regression test, write a short post-mortem (what, impact, fix, prevention).
