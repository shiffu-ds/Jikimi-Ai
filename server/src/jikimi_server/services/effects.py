"""Side effects collected inside a DB transaction and dispatched only after commit.

Prevents a WebSocket client from fetching an alert that is not committed yet, and keeps slow
network calls (Telegram, VLM) out of the transaction.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass, field
from typing import Any

from .hub import Hub

log = logging.getLogger(__name__)


@dataclass
class Effects:
    events: list[tuple[str, str | None, dict[str, Any], set[str] | None]] = field(default_factory=list)
    tasks: list[Callable[[], None]] = field(default_factory=list)

    def publish(self, event: str, site_id: str | None, data: dict[str, Any], roles: set[str] | None = None) -> None:
        self.events.append((event, site_id, data, roles))

    def later(self, fn: Callable[[], None]) -> None:
        self.tasks.append(fn)

    def extend(self, other: Effects) -> None:
        self.events.extend(other.events)
        self.tasks.extend(other.tasks)

    def dispatch(self, hub: Hub, executor: Executor | None) -> None:
        for event, site, data, roles in self.events:
            hub.publish(event, site, data, roles)
        for task in self.tasks:
            if executor is None:
                task()
            else:
                executor.submit(_safe, task)
        self.events.clear()
        self.tasks.clear()


def _safe(fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception:
        log.exception("background task failed")
