"""Tamper-evidence primitives for Jikimi AI evidence packs (F8)."""

from .canonical_json import canonicalize
from .hashing import json_digest, sha256_bytes, sha256_file, sha256_hex
from .merkle import inclusion_proof, leaf_hash, merkle_root, root_from_proof, verify_inclusion
from .signing import (
    Signer,
    b64d,
    b64e,
    generate_private_key,
    key_id_for,
    load_private_key,
    load_public_key,
    public_key_b64,
    save_private_key,
    sign_json,
    verify_json,
)

__all__ = [
    "Signer",
    "b64d",
    "b64e",
    "canonicalize",
    "generate_private_key",
    "inclusion_proof",
    "json_digest",
    "key_id_for",
    "leaf_hash",
    "load_private_key",
    "load_public_key",
    "merkle_root",
    "public_key_b64",
    "root_from_proof",
    "save_private_key",
    "sha256_bytes",
    "sha256_file",
    "sha256_hex",
    "sign_json",
    "verify_inclusion",
    "verify_json",
]
