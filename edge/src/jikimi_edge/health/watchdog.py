"""systemd watchdog + readiness notifications (``Type=notify``, ``WatchdogSec=``).

If the pipeline stops producing frames, we stop pinging and systemd restarts the service
(FMEA #1/#5). Implemented without dependencies over the ``NOTIFY_SOCKET`` datagram socket.
"""

from __future__ import annotations

import os
import socket


def sd_notify(message: str) -> bool:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(addr)
            sock.sendall(message.encode())
        return True
    except OSError:
        return False


def ready() -> bool:
    return sd_notify("READY=1")


def ping() -> bool:
    return sd_notify("WATCHDOG=1")
