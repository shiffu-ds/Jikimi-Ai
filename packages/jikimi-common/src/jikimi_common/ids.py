"""Identifiers: UUIDv7 (RFC 9562), evidence/clip IDs and short SMS codes.

Python 3.12 has no ``uuid.uuid7`` (added in 3.14), so we implement it here.
"""

from __future__ import annotations

import secrets
import threading
import time
import uuid
from datetime import date, datetime

_lock = threading.Lock()
_last_ms = 0
_seq = 0


def uuid7() -> uuid.UUID:
    """Time-ordered UUID: 48-bit unix ms + 12-bit monotonic sequence + 62 random bits."""
    global _last_ms, _seq
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms <= _last_ms:
            _seq = (_seq + 1) & 0x0FFF
            if _seq == 0:  # sequence exhausted inside one ms: borrow the next ms
                _last_ms += 1
            ms = _last_ms
        else:
            _last_ms = ms
            _seq = secrets.randbits(11)  # random start keeps IDs hard to guess
    rand = secrets.randbits(62)
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= _seq << 64
    value |= 0b10 << 62
    value |= rand
    return uuid.UUID(int=value)


def uuid7_time_ms(u: uuid.UUID) -> int:
    return u.int >> 80


def short_code(u: uuid.UUID | str, length: int = 4) -> str:
    """Short, upper-case code for SMS replies ("Code A7F2"). Taken from the random tail."""
    hexs = (u.hex if isinstance(u, uuid.UUID) else uuid.UUID(str(u)).hex).upper()
    return hexs[-length:]


def evidence_id(day: date, seq: int) -> str:
    """``EV-2026-10-22-0007`` (plan Section 8.9)."""
    return f"EV-{day:%Y-%m-%d}-{seq:04d}"


def clip_id_for(alert_id: uuid.UUID, ts: datetime) -> str:
    """``CL-2026-11-21-7F3A9C21``: date of the clip + 32 random bits of the alert id."""
    return f"CL-{ts:%Y-%m-%d}-{alert_id.hex[-8:].upper()}"


def new_trace_id() -> str:
    """W3C trace-context compatible 128-bit trace id (32 hex chars)."""
    return secrets.token_hex(16)
