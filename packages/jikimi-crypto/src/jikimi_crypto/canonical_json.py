"""Canonical JSON for signing, aligned with RFC 8785 (JCS).

- object keys sorted, no insignificant whitespace, UTF-8 output
- numbers serialized like ECMAScript ``Number.prototype.toString`` (so ``1.0`` -> ``1``,
  ``1e-07`` -> ``1e-7``); NaN and Infinity are rejected
- datetimes, UUIDs, enums and Pydantic models are converted to their JSON form first

Keys are sorted by Unicode code point; JCS sorts by UTF-16 code unit. The two only differ for
astral-plane characters in keys, which our manifests never use (keys are ASCII).
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


def _es6_number(x: float) -> str:
    if not math.isfinite(x):
        raise ValueError("NaN/Infinity cannot be canonicalized")
    if x == 0:
        return "0"
    if x.is_integer() and abs(x) < 1e21:
        return str(int(x))
    sign = "-" if x < 0 else ""
    digits_t = Decimal(repr(abs(x))).normalize().as_tuple()
    digits = "".join(str(d) for d in digits_t.digits)
    k = len(digits)
    n = int(digits_t.exponent) + k  # decimal point position relative to the digit string
    if k <= n <= 21:
        out = digits + "0" * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + digits
    else:
        exp = n - 1
        mant = digits[0] + ("." + digits[1:] if k > 1 else "")
        out = f"{mant}e{'+' if exp >= 0 else '-'}{abs(exp)}"
    return sign + out


def _normalize(obj: Any) -> Any:
    # local import keeps pydantic optional for this package
    try:
        from pydantic import BaseModel
    except ImportError:  # pragma: no cover
        BaseModel = ()  # type: ignore[assignment,misc]
    if isinstance(obj, BaseModel):
        return _normalize(obj.model_dump(mode="json"))
    if isinstance(obj, Enum):
        return _normalize(obj.value)
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            raise ValueError("naive datetime in signed payload")
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if not isinstance(k, str):
                raise TypeError(f"object keys must be strings, got {type(k).__name__}")
            out[k] = _normalize(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if obj is None or isinstance(obj, (str, bool, int, float)):
        return obj
    raise TypeError(f"cannot canonicalize {type(obj).__name__}")


def _serialize(obj: Any) -> str:
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return _es6_number(obj)
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, list):
        return "[" + ",".join(_serialize(v) for v in obj) + "]"
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: kv[0])
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + _serialize(v) for k, v in items) + "}"
    raise TypeError(type(obj).__name__)  # pragma: no cover


def canonicalize(obj: Any) -> bytes:
    """Deterministic UTF-8 bytes for ``obj``; identical input -> identical bytes, everywhere."""
    return _serialize(_normalize(obj)).encode("utf-8")
