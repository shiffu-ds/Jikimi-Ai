"""Admin commands for the edge, delivered like rules and the calendar: a bundle signed by the
server key, pulled by the edge (which opens no ports) and checked against its pinned key."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel

CommandKind = Literal["accept_view"]


class EdgeCommand(BaseModel):
    """``accept_view``: the camera was moved on purpose; take its current view as the reference."""

    id: str
    kind: CommandKind
    camera_id: str
    issued_by: str
    issued_at: AwareDatetime


class CommandBundle(BaseModel):
    site_id: str
    version: str
    commands: list[EdgeCommand]
    key_id: str
    public_key: str
    signed_at: AwareDatetime
    signature: str

    def signing_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"signature"})
