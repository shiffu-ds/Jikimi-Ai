# ADR-0031: The mohalla network shares only confirmed incidents, as embeddings, for 2 hours

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-25
- **Feature / gap:** F21 (G42), F19 privacy

## Context
Neighbouring sites want to know when a bike from a confirmed snatch is seen near them. Sharing
images, plates or unconfirmed alerts across sites would build a surveillance network nobody
agreed to. The signed alert is kept a year for evidence, and re-ID embeddings at most 24 h.

## Decision
- Only sites that opted in, with a recorded written agreement and their location, take part -
  both ways, within *both* sites' radius (1-2 km).
- A share needs a high-severity snatch / loitering / SOS that a reviewer marked **true**. It holds
  the bike's appearance embedding, rider count and colour - never an image - and expires after
  2 h; the embedding reaches the server separately from the signed alert, only at opted-in
  sites, and is deleted after 24 h. Expired rows are deleted, not hidden.
- Neighbours receive shares in a signed bundle (pinned server key) and match on their own edge.
  A match tells only their own guard ("watch and tell the supervisor, do not act"), medium
  severity, once per share; nothing is forwarded onwards. Every share is audited; opting out
  withdraws this site's shares at once.

## Consequences
Two sites in range can warn each other within the 2-hour window that matters. The sharing rules
are enforced and tested on the server; the written agreement itself is a human process the
dashboard only records.
