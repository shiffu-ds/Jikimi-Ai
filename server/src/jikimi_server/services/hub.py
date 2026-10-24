"""WebSocket fan-out for live alerts. Thread-safe publish from sync request handlers/workers.

Multi-replica deployments put Redis pub/sub between replicas; the interface stays the same.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)


@dataclass(eq=False)
class _Client:
    ws: WebSocket
    role: str
    sites: frozenset[str]
    username: str
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=200))


class Hub:
    def __init__(self) -> None:
        self._clients: set[_Client] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.published = 0

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def publish(self, event: str, site_id: str | None, data: dict[str, Any], roles: set[str] | None = None) -> None:
        """Safe to call from any thread."""
        if self._loop is None or self._loop.is_closed():
            return
        msg = {"event": event, "site_id": site_id, "data": data}
        self._loop.call_soon_threadsafe(self._fanout, msg, roles)

    def _fanout(self, msg: dict[str, Any], roles: set[str] | None) -> None:
        self.published += 1
        for c in list(self._clients):
            if msg["site_id"] is not None and msg["site_id"] not in c.sites:
                continue
            if roles is not None and c.role not in roles and c.role not in ("owner", "admin"):
                continue
            with contextlib.suppress(asyncio.QueueFull):
                c.queue.put_nowait(msg)

    async def serve(self, ws: WebSocket, role: str, sites: frozenset[str], username: str) -> None:
        await ws.accept()
        client = _Client(ws=ws, role=role, sites=sites, username=username)
        self._clients.add(client)
        await ws.send_json(
            {"event": "hello", "site_id": None, "data": {"user": username, "role": role, "sites": sorted(sites)}}
        )

        async def sender() -> None:
            while True:
                msg = await client.queue.get()
                await ws.send_json(msg)

        task = asyncio.create_task(sender())
        try:
            while True:
                text = await ws.receive_text()
                if text == "ping":
                    await ws.send_json({"event": "pong", "site_id": None, "data": {}})
        except WebSocketDisconnect:
            pass
        except Exception:  # client vanished mid-send
            log.debug("websocket closed", exc_info=True)
        finally:
            task.cancel()
            self._clients.discard(client)
