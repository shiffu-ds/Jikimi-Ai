"""Signed configuration bundles from the server: rules (F11) and the event calendar (F16).

Trust: the first accepted bundle pins the server's public key (``keys/server.pub``; trust on
first use over the authenticated device channel). After that, a bundle signed by any other key
is refused until an operator replaces the pin (``docs/runbooks/key_rotation.md``), and so is a
bundle signed before the one already applied (a replayed old bundle would roll rules back). The
last accepted bundle of each kind is stored, so the edge keeps its rules and calendar through a
reboot without internet.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from jikimi_contracts.commands import CommandBundle, EdgeCommand
from jikimi_contracts.modes import CalendarBundle, ModeWindow
from jikimi_contracts.network import NetworkBundle, NetworkShare
from jikimi_crypto import key_id_for, verify_json
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)


class SignedBundleSync[B: BaseModel]:
    kind: ClassVar[str] = "bundle"
    path: ClassVar[str] = ""
    model: ClassVar[type[BaseModel]]

    def __init__(self, folder: Path, pin_file: Path, site_id: str, apply: Callable[[Any], None]) -> None:
        self.folder = Path(folder)
        self.pin_file = Path(pin_file)
        self.site_id = site_id
        self.apply = apply
        self.version: str | None = None
        self.signed_at: datetime | None = None

    @property
    def bundle_file(self) -> Path:
        return self.folder / "bundle.json"

    def payload(self, b: B) -> Any:
        """What ``apply`` receives."""
        raise NotImplementedError

    def extra_refusal(self, b: B) -> str | None:
        return None

    def refusal(self, b: B) -> str | None:
        """Why ``b`` must not be applied, or ``None``."""
        d: Any = b
        if d.site_id != self.site_id:
            return f"bundle is for site '{d.site_id}'"
        if key_id_for(d.public_key, "server") != d.key_id:
            return "key id does not match the public key"
        if self.pin_file.exists() and self.pin_file.read_text(encoding="utf-8").strip() != d.public_key:
            return "signed by a server key other than the pinned one"
        if not verify_json(d.public_key, d.signing_payload(), d.signature):
            return "bad signature"
        if self.signed_at is not None and d.signed_at < self.signed_at:
            return "older than the bundle already applied (replayed)"
        return self.extra_refusal(b)

    def accept(self, b: B) -> bool:
        d: Any = b
        if d.version == self.version:
            return True
        why = self.refusal(b)
        if why is not None:
            log.error("%s bundle refused: %s", self.kind, why, extra={"version": d.version})
            return False
        if not self.pin_file.exists():
            self.pin_file.parent.mkdir(parents=True, exist_ok=True)
            self.pin_file.write_text(d.public_key + "\n", encoding="utf-8")
            log.warning("server key pinned", extra={"key_id": d.key_id})
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.bundle_file.with_suffix(".tmp")
        tmp.write_text(b.model_dump_json(by_alias=True), encoding="utf-8")
        os.replace(tmp, self.bundle_file)
        self.apply(self.payload(b))
        self.version, self.signed_at = d.version, d.signed_at
        log.warning("%s updated", self.kind, extra={"version": d.version})
        return True

    def parse(self, data: Any) -> B | None:
        try:
            return self.model.model_validate(data)  # type: ignore[return-value]
        except ValidationError:
            log.error("%s bundle from the server is malformed", self.kind)
            return None

    def load(self) -> None:
        """Start-up: re-apply the stored bundle (checked again) before the server is reachable."""
        if not self.bundle_file.exists():
            return
        try:
            b = self.model.model_validate_json(self.bundle_file.read_text(encoding="utf-8"))
        except (ValidationError, ValueError):
            log.error("stored %s bundle unreadable; waiting for the server", self.kind)
            return
        self.accept(b)  # type: ignore[arg-type]


class CalendarSync(SignedBundleSync[CalendarBundle]):
    kind = "calendar"
    path = "/v1/edge/calendar"
    model = CalendarBundle

    def payload(self, b: CalendarBundle) -> list[ModeWindow]:
        return b.windows


class NetworkSync(SignedBundleSync[NetworkBundle]):
    """Confirmed incidents of opted-in neighbours (F21): bike embeddings, matched on this edge."""

    kind = "network"
    path = "/v1/edge/network"
    model = NetworkBundle

    def payload(self, b: NetworkBundle) -> list[NetworkShare]:
        return b.shares


class CommandSync(SignedBundleSync[CommandBundle]):
    """Admin commands (accept a camera's new view): each runs once, also across restarts; the
    ids carried out go back to the server in the heartbeat (``extra.commands_done``)."""

    kind = "commands"
    path = "/v1/edge/commands"
    model = CommandBundle

    def __init__(self, folder: Path, pin_file: Path, site_id: str, execute: Callable[[EdgeCommand], bool]) -> None:
        super().__init__(folder, pin_file, site_id, self._run)
        self.execute = execute
        self.done_file = Path(folder) / "done.json"
        self.done: list[str] = json.loads(self.done_file.read_text(encoding="utf-8")) if self.done_file.exists() else []

    def payload(self, b: CommandBundle) -> list[EdgeCommand]:
        return b.commands

    def _run(self, commands: list[EdgeCommand]) -> None:
        for c in commands:
            if c.id not in self.done and self.execute(c):
                self.done.append(c.id)
                log.warning("command carried out", extra={"kind": c.kind, "camera": c.camera_id, "by": c.issued_by})
        self.done = self.done[-200:]
        self.done_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.done_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.done), encoding="utf-8")
        os.replace(tmp, self.done_file)
