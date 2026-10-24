"""Structured logging with a ``trace_id`` that follows an alert across every hop.

JSON lines when not attached to a TTY (containers, systemd) or ``JIKIMI_LOG_JSON=1``;
readable colour-less console lines otherwise.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
from collections.abc import Iterator
from contextvars import ContextVar
from datetime import UTC, datetime

trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

_STD_ATTRS = frozenset(
    vars(logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)).keys() | {"message", "asctime", "taskName"}
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        trace = trace_id_var.get()
        if trace:
            payload["trace_id"] = trace
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        extras = {k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS and not k.startswith("_")}
        trace = trace_id_var.get()
        if trace:
            extras["trace"] = trace[:8]
        tail = " ".join(f"{k}={v}" for k, v in extras.items())
        line = f"{ts} {record.levelname[:4]:<4} {record.name}: {record.getMessage()}"
        if tail:
            line += f"  [{tail}]"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def setup_logging(level: str | None = None, json_logs: bool | None = None) -> None:
    level = (level or os.environ.get("JIKIMI_LOG_LEVEL", "INFO")).upper()
    if json_logs is None:
        env = os.environ.get("JIKIMI_LOG_JSON")
        json_logs = env == "1" if env is not None else not sys.stderr.isatty()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if json_logs else ConsoleFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "multipart", "fontTools", "weasyprint", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@contextlib.contextmanager
def bind_trace(trace_id: str | None) -> Iterator[None]:
    token = trace_id_var.set(trace_id)
    try:
        yield
    finally:
        trace_id_var.reset(token)
