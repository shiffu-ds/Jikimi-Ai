"""ONVIF WS-Discovery: find cameras and recorders on the site LAN (plan Section 8.20).

One SOAP ``Probe`` for ``dn:NetworkVideoTransmitter`` goes to the multicast group; every ONVIF
device answers with a ``ProbeMatch`` carrying its device-service URL (``XAddrs``) and scopes
(name, hardware), from which the brand is guessed for the RTSP templates.
"""

from __future__ import annotations

import socket
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from .templates import guess_brand

MULTICAST = ("239.255.255.250", 3702)
MAX_REPLY = 64 * 1024

_PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
 xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <e:Header>
  <w:MessageID>uuid:{id}</w:MessageID>
  <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
  <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
 </e:Header>
 <e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>
</e:Envelope>"""


@dataclass
class OnvifDevice:
    ip: str
    xaddrs: list[str]
    scopes: list[str] = field(default_factory=list)
    address: str = ""

    def _scope(self, kind: str) -> str:
        prefix = f"onvif://www.onvif.org/{kind}/"
        return next((unquote(s[len(prefix) :]) for s in self.scopes if s.startswith(prefix)), "")

    @property
    def name(self) -> str:
        return self._scope("name")

    @property
    def hardware(self) -> str:
        return self._scope("hardware")

    @property
    def brand(self) -> str | None:
        return guess_brand(self.name, self.hardware, *self.scopes)


def probe_message(message_id: str | None = None) -> bytes:
    return _PROBE.format(id=message_id or uuid.uuid4()).encode()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_probe_matches(data: bytes, sender_ip: str) -> list[OnvifDevice]:
    """Devices in one WS-Discovery reply; malformed or oversized replies are ignored."""
    if len(data) > MAX_REPLY:
        return []
    try:
        root = ET.fromstring(data)  # noqa: S314 - size-capped; Python's expat refuses entity-expansion bombs
    except ET.ParseError:
        return []
    out = []
    for match in (el for el in root.iter() if _local(el.tag) == "ProbeMatch"):
        texts = {_local(el.tag): (el.text or "").strip() for el in match.iter()}
        xaddrs = texts.get("XAddrs", "").split()
        if not xaddrs:
            continue
        host = urlparse(xaddrs[0]).hostname or sender_ip
        out.append(
            OnvifDevice(
                ip=host, xaddrs=xaddrs, scopes=texts.get("Scopes", "").split(), address=texts.get("Address", "")
            )
        )
    return out


def discover(timeout_s: float = 3.0, interface_ip: str | None = None) -> list[OnvifDevice]:
    """Probe the LAN; ``interface_ip`` picks the network card on multi-homed edge boxes."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        if interface_ip:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface_ip))
        sock.settimeout(0.3)
        sock.sendto(probe_message(), MULTICAST)
        found: dict[str, OnvifDevice] = {}
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                data, (ip, _) = sock.recvfrom(MAX_REPLY + 1)
            except TimeoutError:
                continue
            for dev in parse_probe_matches(data, ip):
                found[dev.address or dev.ip] = dev
        return sorted(found.values(), key=lambda d: tuple(int(p) for p in d.ip.split(".") if p.isdigit()))
    finally:
        sock.close()
