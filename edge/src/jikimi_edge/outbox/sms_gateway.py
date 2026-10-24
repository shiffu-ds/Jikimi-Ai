"""SMS gateways: USB GSM modem (AT commands), file-based fake modem for dev/demo, or none.

The modem path uses text mode (``AT+CMGF=1``) and the GSM character set; incoming replies are
polled with ``AT+CMGL="REC UNREAD"`` and deleted after reading. Check PTA/DIRBS registration and
use an organisation SIM (Section 13.3).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IncomingSms:
    number: str
    text: str
    at: float


class SmsGateway(Protocol):
    name: str

    def send(self, number: str, text: str) -> bool: ...
    def receive(self) -> list[IncomingSms]: ...
    def healthy(self) -> bool | None: ...


class NullSmsGateway:
    name = "none"

    def send(self, number: str, text: str) -> bool:
        log.warning("SMS gateway disabled; message dropped", extra={"to": number})
        return False

    def receive(self) -> list[IncomingSms]:
        return []

    def healthy(self) -> bool | None:
        return None


class FileSmsGateway:
    """Fake modem: outgoing SMS -> ``outbox.jsonl`` (and a box in the log); replies are read
    from ``inbox.jsonl`` (``make sms-reply TEXT="1 A7F2"`` appends one)."""

    name = "file"

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._out = self.folder / "outbox.jsonl"
        self._in = self.folder / "inbox.jsonl"
        self._offset_file = self.folder / ".inbox.offset"
        self._lock = threading.Lock()

    def send(self, number: str, text: str) -> bool:
        with self._lock, open(self._out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"to": number, "text": text, "at": time.time()}, ensure_ascii=False) + "\n")
        bar = "─" * min(len(text), 70)
        log.warning(f"\n┌{bar}┐\n  📱 SMS -> {number}\n  {text}\n└{bar}┘")
        return True

    def receive(self) -> list[IncomingSms]:
        if not self._in.exists():
            return []
        with self._lock:
            offset = int(self._offset_file.read_text() or 0) if self._offset_file.exists() else 0
            with open(self._in, encoding="utf-8") as fh:
                fh.seek(offset)
                lines = fh.readlines()
                new_offset = fh.tell()
            self._offset_file.write_text(str(new_offset))
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                out.append(
                    IncomingSms(
                        number=str(d.get("from", "unknown")), text=str(d["text"]), at=float(d.get("at", time.time()))
                    )
                )
            except (json.JSONDecodeError, KeyError):
                out.append(IncomingSms(number="unknown", text=line, at=time.time()))
        return out

    def healthy(self) -> bool | None:
        return True


_CMGL = re.compile(r'\+CMGL:\s*(\d+),"[^"]*","([^"]+)"[^\r\n]*\r?\n([^\r\n]*)')


class AtModemGateway:
    name = "modem"

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200, timeout: float = 5.0) -> None:
        import serial  # pyserial

        self._serial = serial.Serial(port, baudrate=baudrate, timeout=timeout)
        self._lock = threading.Lock()
        self._ok: bool | None = None
        self._cmd("AT")
        self._cmd("AT+CMGF=1")
        self._cmd('AT+CSCS="GSM"')

    def _cmd(self, cmd: str, wait: float = 1.0, expect: str = "OK") -> str:
        self._serial.reset_input_buffer()
        self._serial.write((cmd + "\r").encode())
        deadline = time.monotonic() + wait + self._serial.timeout
        buf = b""
        while time.monotonic() < deadline:
            chunk = self._serial.read(self._serial.in_waiting or 1)
            buf += chunk
            if expect.encode() in buf or b"ERROR" in buf:
                break
        return buf.decode(errors="replace")

    def send(self, number: str, text: str) -> bool:
        with self._lock:
            try:
                self._serial.write(f'AT+CMGS="{number}"\r'.encode())
                time.sleep(0.5)
                self._serial.write(text.encode("ascii", "replace") + bytes([26]))
                resp = b""
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline and b"OK" not in resp and b"ERROR" not in resp:
                    resp += self._serial.read(self._serial.in_waiting or 1)
                self._ok = b"+CMGS" in resp
                return self._ok
            except Exception:
                log.exception("modem send failed")
                self._ok = False
                return False

    def receive(self) -> list[IncomingSms]:
        with self._lock:
            try:
                resp = self._cmd('AT+CMGL="REC UNREAD"', wait=2.0)
            except Exception:
                log.exception("modem read failed")
                return []
            msgs = []
            for idx, number, text in _CMGL.findall(resp):
                msgs.append(IncomingSms(number=number, text=text.strip(), at=time.time()))
                self._cmd(f"AT+CMGD={idx}")
            return msgs

    def signal_quality(self) -> int | None:
        with self._lock:
            m = re.search(r"\+CSQ:\s*(\d+)", self._cmd("AT+CSQ"))
        return int(m.group(1)) if m else None

    def healthy(self) -> bool | None:
        q = self.signal_quality()
        return None if q is None else (0 < q < 99)


def make_gateway(kind: str, folder: str | Path, port: str | None = None) -> SmsGateway:
    if kind == "modem":
        try:
            return AtModemGateway(port or "/dev/ttyUSB0")
        except Exception:
            log.exception("GSM modem not available; falling back to file gateway")
            return FileSmsGateway(folder)
    if kind == "file":
        return FileSmsGateway(folder)
    return NullSmsGateway()
