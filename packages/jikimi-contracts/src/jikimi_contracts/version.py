"""Schema version carried by every edge <-> server message (plan Section 7.12).

Rules:
- Backward-compatible change (new optional field) -> bump the minor version.
- Breaking change -> new stream / endpoint name (``edge.alerts.v2``, ``/v2``) and both run in
  parallel until every edge is updated.
"""

SCHEMA_VERSION = "1.0"
