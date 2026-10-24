"""Encrypted storage for *unblurred* originals (Restricted data class, Section 7.12).

AES-256-GCM with a per-site key (``data/edge/keys/vault.key``, mode 0600). Originals stay on
the edge; access is break-glass only (reason + audit + owner notification on the server).
File format: ``b"JKV1" | 12-byte nonce | ciphertext+tag`` with the clip id as associated data.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"JKV1"


def load_or_create_key(path: str | Path) -> bytes:
    p = Path(path)
    if p.exists():
        key = p.read_bytes()
        if len(key) != 32:
            raise ValueError("vault key must be 32 bytes")
        return key
    p.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return key


class Vault:
    def __init__(self, key: bytes) -> None:
        self._aead = AESGCM(key)

    def seal(self, data: bytes, aad: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return MAGIC + nonce + self._aead.encrypt(nonce, data, aad.encode())

    def open(self, blob: bytes, aad: str) -> bytes:
        if not blob.startswith(MAGIC):
            raise ValueError("not a Jikimi vault file")
        nonce, ct = blob[4:16], blob[16:]
        return self._aead.decrypt(nonce, ct, aad.encode())

    def seal_file(self, src: Path, dst: Path, aad: str) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(self.seal(src.read_bytes(), aad))
