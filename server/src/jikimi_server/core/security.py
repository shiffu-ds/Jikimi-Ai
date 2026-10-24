"""Passwords (scrypt, stdlib), JWTs (HS256, short-lived) and device tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)  # type: ignore[arg-type]
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, dk_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)  # type: ignore[arg-type]
    return hmac.compare_digest(dk, base64.b64decode(dk_b64))


def new_device_token() -> str:
    return "jkd_" + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    exp: int
    scope: str = "user"
    extra: dict[str, Any] | None = None


def issue_jwt(
    secret: str,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
    ttl_s: int,
    scope: str = "user",
    extra: dict[str, Any] | None = None,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": role,
        "scope": scope,
        "iat": now,
        "exp": now + ttl_s,
        "iss": "jikimi",
        **(extra or {}),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(secret: str, token: str) -> TokenClaims | None:
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"], issuer="jikimi", options={"require": ["exp", "sub"]})
        known = {"sub", "tid", "role", "scope", "iat", "exp", "iss"}
        return TokenClaims(
            user_id=uuid.UUID(data["sub"]),
            tenant_id=uuid.UUID(data["tid"]),
            role=str(data["role"]),
            exp=int(data["exp"]),
            scope=str(data.get("scope", "user")),
            extra={k: v for k, v in data.items() if k not in known},
        )
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
