"""Ed25519 keys and signatures.

Convention used everywhere in Jikimi: ``signature = Ed25519(key, SHA256(canonical_json(obj)))``
(plan Section 8.9 step 2). Signatures and public keys are base64 (raw 64 / 32 bytes).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .hashing import json_digest


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"), validate=True)


def generate_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def public_key_b64(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    pub = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return b64e(raw)


def load_public_key(pub_b64: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(b64d(pub_b64))


def key_id_for(pub_b64: str, prefix: str = "ed25519") -> str:
    """Stable short id: ``ed25519:<first 16 hex of SHA-256(raw public key)>``."""
    return f"{prefix}:{hashlib.sha256(b64d(pub_b64)).hexdigest()[:16]}"


def save_private_key(key: Ed25519PrivateKey, path: str | Path, passphrase: bytes | None = None) -> None:
    """PKCS#8 PEM, file mode 0600, optionally encrypted with a passphrase."""
    enc: serialization.KeySerializationEncryption = (
        serialization.BestAvailableEncryption(passphrase) if passphrase else serialization.NoEncryption()
    )
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    os.chmod(p, 0o600)


def load_private_key(path: str | Path, passphrase: bytes | None = None) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=passphrase)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("not an Ed25519 private key")
    return key


def load_or_create_private_key(path: str | Path, passphrase: bytes | None = None) -> Ed25519PrivateKey:
    p = Path(path)
    if p.exists():
        return load_private_key(p, passphrase)
    key = generate_private_key()
    save_private_key(key, p, passphrase)
    return key


def sign_bytes(key: Ed25519PrivateKey, data: bytes) -> str:
    return b64e(key.sign(data))


def verify_bytes(pub_b64: str, data: bytes, sig_b64: str) -> bool:
    try:
        load_public_key(pub_b64).verify(b64d(sig_b64), data)
    except (InvalidSignature, ValueError, binascii.Error):
        return False
    return True


def sign_json(key: Ed25519PrivateKey, obj: object) -> str:
    return sign_bytes(key, json_digest(obj))


def verify_json(pub_b64: str, obj: object, sig_b64: str | None) -> bool:
    if not sig_b64:
        return False
    return verify_bytes(pub_b64, json_digest(obj), sig_b64)


@dataclass(frozen=True)
class Signer:
    """A private key bundled with its public identity."""

    key: Ed25519PrivateKey
    public_key: str
    key_id: str

    @classmethod
    def from_key(cls, key: Ed25519PrivateKey, prefix: str = "ed25519") -> Signer:
        pub = public_key_b64(key)
        return cls(key=key, public_key=pub, key_id=key_id_for(pub, prefix))

    @classmethod
    def from_file(cls, path: str | Path, prefix: str = "ed25519", create: bool = True) -> Signer:
        key = load_or_create_private_key(path) if create else load_private_key(path)
        return cls.from_key(key, prefix)

    def sign(self, obj: object) -> str:
        return sign_json(self.key, obj)
