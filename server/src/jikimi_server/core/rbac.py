"""Roles and permissions (F19, plan Section 8.19). Least privilege; tested in CI."""

from __future__ import annotations

ROLES = ("owner", "admin", "supervisor", "guard", "police_viewer")

_GUARD = {"alerts:read", "alerts:ack", "alerts:review", "sites:read", "sos:create"}
_SUPERVISOR = _GUARD | {
    "search",
    "evidence:create",
    "evidence:read",
    "health:read",
    "stats:read",
    "rules:read",
    "rules:propose",
}
_ADMIN = _SUPERVISOR | {"audit:read", "users:manage", "rules:manage", "evidence:share", "admin"}
PERMISSIONS: dict[str, frozenset[str]] = {
    "guard": frozenset(_GUARD),
    "supervisor": frozenset(_SUPERVISOR),
    "admin": frozenset(_ADMIN),
    "owner": frozenset(_ADMIN | {"break_glass"}),
    "police_viewer": frozenset({"evidence:read"}),
}


def can(role: str, perm: str) -> bool:
    return perm in PERMISSIONS.get(role, frozenset())


def permissions(role: str) -> list[str]:
    return sorted(PERMISSIONS.get(role, frozenset()))
