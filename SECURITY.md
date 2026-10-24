# Security policy

Jikimi AI handles CCTV footage and evidence. Please report vulnerabilities privately.

- **How:** email the maintainers (see the repository profile) with "SECURITY" in the subject, or
  use GitHub private vulnerability reporting. Do not open a public issue.
- **What to include:** affected component (edge / server / dashboard / evidence), version or
  commit, steps to reproduce, impact.
- **Response:** acknowledgement within 3 working days; fix or mitigation plan within 14 days for
  high severity issues.

Security design (details in `docs/architecture/threat_model.md`):

| Area | Control in v0.1 |
|---|---|
| Edge -> server | device API token (hashed at rest) + Ed25519 signature on every alert and clip; WireGuard + mTLS at the proxy in production |
| Users | scrypt password hashes, short-lived JWT in an httpOnly SameSite=Strict cookie, custom header required on cookie writes (CSRF), login rate limit |
| Authorization | role permissions + tenant/site isolation on every query (404 for other sites), tested |
| Evidence | SHA-256 + two-layer Ed25519 signatures + RFC 6962 Merkle batches + OpenTimestamps; hash-chained audit log |
| Privacy | no face recognition (blocklisted plugins), head/face blur on every stored image, encrypted unblurred originals (AES-256-GCM) on the edge |
| Supply chain | pinned images and lockfiles; gitleaks + pip-audit + npm audit in CI |
