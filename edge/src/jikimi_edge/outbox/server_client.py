"""HTTP client for the server's edge API (outbound only: the edge opens no ports).

Production runs this over WireGuard with mTLS client certificates terminated by the reverse
proxy; every request also carries the device token and every alert/clip an Ed25519 signature.
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .db import OutboxItem


@dataclass(frozen=True)
class SendResult:
    ok: bool
    permanent: bool = False
    status: int | None = None
    error: str = ""


class ServerClient:
    def __init__(self, base_url: str, device_token: str, timeout: float = 10.0, health_timeout: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.health_timeout = health_timeout
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {device_token}", "User-Agent": "jikimi-edge/0.1"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def healthy(self) -> bool:
        try:
            r = await self._client.get("/v1/health", timeout=self.health_timeout)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def send(self, item: OutboxItem) -> SendResult:
        try:
            r = await self._dispatch(item)
        except httpx.HTTPError as exc:
            return SendResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        except FileNotFoundError as exc:
            return SendResult(ok=False, permanent=True, error=f"file missing: {exc}")
        if r.status_code < 300 or r.status_code == 409:
            return SendResult(ok=True, status=r.status_code)
        permanent = 400 <= r.status_code < 500 and r.status_code not in (401, 403, 408, 425, 429)
        return SendResult(ok=False, permanent=permanent, status=r.status_code, error=r.text[:300])

    async def _dispatch(self, item: OutboxItem) -> httpx.Response:
        if item.kind == "alert":
            return await self._client.post(
                "/v1/edge/alerts", json=item.payload, headers={"Idempotency-Key": str(item.dedupe_key)}
            )
        if item.kind == "clip":
            files: list[tuple[str, tuple[str, bytes, str]]] = []
            for path in item.files:
                p = Path(path)
                ctype = "video/mp4" if p.suffix == ".mp4" else "image/jpeg"
                field = "clip" if p.suffix == ".mp4" else "keyframes"
                files.append((field, (p.name, await asyncio.to_thread(p.read_bytes), ctype)))
            return await self._client.post(
                "/v1/edge/clips", data={"attestation": json.dumps(item.payload)}, files=files
            )
        if item.kind == "heartbeat":
            return await self._client.post("/v1/edge/heartbeat", json=item.payload)
        if item.kind == "snapshot":
            jpeg = base64.b64decode(item.payload["jpeg_b64"])
            return await self._client.put(
                f"/v1/edge/snapshots/{item.payload['camera_id']}", content=jpeg, headers={"Content-Type": "image/jpeg"}
            )
        if item.kind == "track":
            return await self._client.post("/v1/edge/tracks", json=item.payload)
        if item.kind == "ack":
            return await self._client.post("/v1/edge/acks", json=item.payload)
        if item.kind == "embedding":
            return await self._client.post("/v1/edge/embeddings", json=item.payload)
        raise ValueError(f"unknown outbox kind {item.kind}")

    async def post_json(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        return await self._client.post(path, json=payload)

    async def get_json(self, path: str) -> Any | None:
        """GET -> parsed JSON; ``None`` if the server is unreachable or does not answer 2xx."""
        try:
            r = await self._client.get(path)
        except httpx.HTTPError:
            return None
        return r.json() if r.status_code < 300 else None
