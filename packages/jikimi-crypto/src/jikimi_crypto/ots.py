"""OpenTimestamps wrapper (F8 Tier 2): anchor the daily Merkle root in Bitcoin, for free.

Uses the official ``ots`` CLI (``pip install opentimestamps-client``) when present. Stamping
needs internet (public calendar servers); a fresh stamp is *pending* for a few hours until the
calendar's Bitcoin transaction confirms, then ``upgrade`` turns it into a complete proof.

The stamped file contains exactly the 64-character hex Merkle root (no newline), so a verifier
can recreate it from the root shown on the verify portal.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class OTSUnavailableError(RuntimeError):
    """The ``ots`` client is not installed."""


@dataclass(frozen=True)
class OTSResult:
    proof: bytes
    confirmed: bool
    message: str


def available() -> bool:
    return shutil.which("ots") is not None


def _ots(*args: str, cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    if not available():
        raise OTSUnavailableError("install opentimestamps-client to enable Bitcoin timestamps")
    return subprocess.run(["ots", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)


def stamp(root_hex: str, timeout: float = 30.0) -> OTSResult:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "root.txt").write_text(root_hex, encoding="ascii")
        res = _ots("stamp", "root.txt", cwd=d, timeout=timeout)
        proof_path = d / "root.txt.ots"
        if res.returncode != 0 or not proof_path.exists():
            raise RuntimeError(f"ots stamp failed: {res.stderr.strip() or res.stdout.strip()}")
        return OTSResult(proof=proof_path.read_bytes(), confirmed=False, message="pending")


def upgrade(root_hex: str, proof: bytes, timeout: float = 30.0) -> OTSResult:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "root.txt").write_text(root_hex, encoding="ascii")
        (d / "root.txt.ots").write_bytes(proof)
        res = _ots("upgrade", "root.txt.ots", cwd=d, timeout=timeout)
        new_proof = (d / "root.txt.ots").read_bytes()
        text = (res.stdout + res.stderr).lower()
        confirmed = res.returncode == 0 and "pending" not in text
        return OTSResult(proof=new_proof, confirmed=confirmed, message=(res.stdout + res.stderr).strip())
