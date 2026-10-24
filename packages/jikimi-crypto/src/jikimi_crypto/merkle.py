"""RFC 6962 (Certificate Transparency) Merkle trees.

Leaf and interior hashes are domain-separated (``0x00`` / ``0x01`` prefixes) so a leaf can never
be passed off as an interior node (second-preimage protection). The plan did not pin a scheme;
RFC 6962 is the well-reviewed default (see docs/PLAN_REVIEW.md).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Literal

Side = Literal["left", "right"]
ProofPath = list[tuple[Side, bytes]]


def leaf_hash(data: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + data).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _split(n: int) -> int:
    """Largest power of two strictly smaller than ``n`` (n >= 2)."""
    k = 1
    while k << 1 < n:
        k <<= 1
    return k


def _mth(leaves: Sequence[bytes]) -> bytes:
    n = len(leaves)
    if n == 0:
        return hashlib.sha256(b"").digest()
    if n == 1:
        return leaf_hash(leaves[0])
    k = _split(n)
    return node_hash(_mth(leaves[:k]), _mth(leaves[k:]))


def merkle_root(leaves: Sequence[bytes]) -> bytes:
    """Root over raw leaf data (Jikimi leaves are 32-byte manifest digests)."""
    return _mth(leaves)


def inclusion_proof(leaves: Sequence[bytes], index: int) -> ProofPath:
    """Audit path for ``leaves[index]``, ordered from the leaf up to the root."""
    n = len(leaves)
    if not 0 <= index < n:
        raise IndexError("leaf index out of range")
    if n == 1:
        return []
    k = _split(n)
    if index < k:
        return [*inclusion_proof(leaves[:k], index), ("right", _mth(leaves[k:]))]
    return [*inclusion_proof(leaves[k:], index - k), ("left", _mth(leaves[:k]))]


def root_from_proof(leaf: bytes, path: ProofPath) -> bytes:
    h = leaf_hash(leaf)
    for side, sibling in path:
        h = node_hash(sibling, h) if side == "left" else node_hash(h, sibling)
    return h


def verify_inclusion(leaf: bytes, path: ProofPath, root: bytes) -> bool:
    return root_from_proof(leaf, path) == root
