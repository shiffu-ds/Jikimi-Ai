"""SHA-256 helpers; files are streamed so large clips never load fully into RAM."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO

CHUNK = 1 << 20


def sha256_bytes(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_stream(fh: BinaryIO) -> str:
    h = hashlib.sha256()
    for block in iter(lambda: fh.read(CHUNK), b""):
        h.update(block)
    return h.hexdigest()


def sha256_file(path: str | Path) -> str:
    with open(path, "rb") as fh:
        return sha256_stream(fh)


def json_digest(obj: object) -> bytes:
    """SHA-256 of the canonical JSON of ``obj`` (what every signature in Jikimi covers)."""
    from .canonical_json import canonicalize

    return hashlib.sha256(canonicalize(obj)).digest()
