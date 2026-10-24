"""Device signing (F8 layer 1): the edge key signs alerts and clip attestations at capture.

The private key lives only on the edge (``data/edge/keys/device.key``, mode 0600, optional
passphrase via ``JIKIMI_DEVICE_KEY_PASSPHRASE``). Its public key is registered on the server
(``jikimi-server register-device``); rotation: ``scripts/rotate_device_key.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

from jikimi_contracts import AlertCandidate, ClipAttestation
from jikimi_crypto import Signer
from jikimi_crypto.signing import load_or_create_private_key


class DeviceSigner:
    def __init__(self, key_path: str | Path) -> None:
        passphrase = os.environ.get("JIKIMI_DEVICE_KEY_PASSPHRASE")
        key = load_or_create_private_key(key_path, passphrase.encode() if passphrase else None)
        self._signer = Signer.from_key(key, prefix="edge")

    @property
    def key_id(self) -> str:
        return self._signer.key_id

    @property
    def public_key(self) -> str:
        return self._signer.public_key

    def sign_alert(self, alert: AlertCandidate) -> AlertCandidate:
        unsigned = alert.model_copy(update={"device_key_id": self.key_id, "signature": None})
        return unsigned.model_copy(update={"signature": self._signer.sign(unsigned.signing_payload())})

    def sign_attestation(self, att: ClipAttestation) -> ClipAttestation:
        unsigned = att.model_copy(update={"device_key_id": self.key_id, "signature": None})
        return unsigned.model_copy(update={"signature": self._signer.sign(unsigned.signing_payload())})
