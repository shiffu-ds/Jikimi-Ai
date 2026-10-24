# Threat model (STRIDE) - controls as implemented

| Threat | Example | Control in code | Test |
|---|---|---|---|
| Spoofing | fake edge posts alerts | device token (hashed) + Ed25519 signature checked against the registered key; wrong site/camera rejected | `server/tests/test_api.py::test_signatures_are_enforced` |
| Tampering | clip, PDF or DB row edited | SHA-256 in signed manifests, two-layer signatures, RFC 6962 Merkle, OTS; verify re-hashes stored files | `test_evidence_pack_verify_and_tamper` |
| Tampering | rule pushed to cameras without approval, or edited on the way | only `active` rules leave the server; bundle signed by the server key, edge pins the key (TOFU) and checks site + signature + `approved_by`, and refuses a bundle older than the applied one (replay / rollback) | `edge/tests/unit/test_rules_edge.py::test_bad_bundles_are_refused` |
| Tampering | a fake "Eid" calendar pushed to make the edge compare a quiet night with a festival crowd | only admin-confirmed windows (audited) leave the server; calendar signed and checked against the same pinned key as rules; without a mode's own calibration the edge falls back to `normal` | `test_sync_agent_pulls_rules_and_calendar_only_while_online` |
| Tampering | server key rotated, old evidence now "invalid" | retired public keys kept (`retire-key`), verify picks the key by id | `test_evidence_stays_verifiable_after_server_key_rotation` |
| Repudiation | "I never exported it" | hash-chained audit log (view, download, search, ack, review, login) | `GET /v1/audit/verify` |
| Information disclosure | other tenant's clips; faces in stored media | role permissions + site scoping (404), httpOnly cookie, blurred media only: every detected person's head plus the riders' band above every two-wheeler (ADR-0024); undetected people (bike hidden, tiny far figures) remain a known gap | `test_rbac_and_site_isolation` |
| Denial of service | alert flood, verify scraping | per-entity alert gate + cooldown, rate limits on login and /verify, edge works without server | unit + API tests |
| Elevation of privilege | guard acts as admin | least-privilege permission sets, CSRF header on cookie writes | `test_cookie_writes_need_client_header` |
| Prompt injection | text in a clip steers the agent | LLM only parses queries (no tools); query passed as data; cameras whitelisted | `search/llm_fallback.py` |
| Model / data poisoning | bad labels | consent-checked loader, calibration bound to scorer version, golden replay gate | `eval/tests/test_golden.py` |
| Physical theft of edge | key stolen | key files 0600 (+ optional passphrase), LUKS disk (runbook), key revocation in the device registry | `docs/runbooks/key_rotation.md` |
