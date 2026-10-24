"""Minimal ONVIF client: device service -> media service -> profiles -> RTSP stream URIs.

Only three calls (``GetCapabilities``, ``GetProfiles``, ``GetStreamUri``), authenticated with a
WS-Security UsernameToken digest. The digest includes a timestamp that most recorders check
against their own clock, so a DVR with a wrong date answers "NotAuthorized": fix the DVR time
(or use the RTSP templates) when that happens.
"""

from __future__ import annotations

import base64
import hashlib
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from xml.sax.saxutils import escape

import httpx

_WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
_WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
_DIGEST = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
_B64 = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"
_DEVICE = "http://www.onvif.org/ver10/device/wsdl"
_MEDIA = "http://www.onvif.org/ver10/media/wsdl"
_SCHEMA = "http://www.onvif.org/ver10/schema"


class OnvifError(RuntimeError):
    pass


@dataclass(frozen=True)
class StreamProfile:
    token: str
    name: str
    width: int | None
    height: int | None
    encoding: str | None
    uri: str | None = None

    @property
    def pixels(self) -> int:
        return (self.width or 0) * (self.height or 0)


def password_digest(password: str, nonce: bytes, created: str) -> str:
    """WS-Security: Base64(SHA-1(nonce + created + password))."""
    return base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()  # noqa: S324 - mandated by the ONVIF/WS-Security spec


def envelope(
    body: str, user: str = "", password: str = "", nonce: bytes | None = None, created: str | None = None
) -> str:
    header = ""
    if user:
        nonce = nonce or os.urandom(16)
        created = created or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        header = (
            f'<s:Header><wsse:Security xmlns:wsse="{_WSSE}" xmlns:wsu="{_WSU}" s:mustUnderstand="1">'
            f"<wsse:UsernameToken><wsse:Username>{escape(user)}</wsse:Username>"
            f'<wsse:Password Type="{_DIGEST}">{password_digest(password, nonce, created)}</wsse:Password>'
            f'<wsse:Nonce EncodingType="{_B64}">{base64.b64encode(nonce).decode()}</wsse:Nonce>'
            f"<wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security></s:Header>"
        )
    return f'<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">{header}<s:Body>{body}</s:Body></s:Envelope>'


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse(xml: bytes) -> ET.Element:
    if len(xml) > 1_000_000:
        raise OnvifError("reply too large")
    root = ET.fromstring(xml)  # noqa: S314 - size-capped; Python's expat refuses entity-expansion bombs
    fault = next((el for el in root.iter() if _local(el.tag) == "Fault"), None)
    if fault is not None:
        reason = " ".join(t.strip() for t in fault.itertext() if t.strip())
        raise OnvifError(f"ONVIF fault: {reason[:200]}")
    return root


def media_xaddr(capabilities: bytes) -> str:
    root = _parse(capabilities)
    for media in (el for el in root.iter() if _local(el.tag) == "Media"):
        x = next((el.text for el in media if _local(el.tag) == "XAddr" and el.text), None)
        if x:
            return x.strip()
    raise OnvifError("device has no media service")


def profiles(reply: bytes) -> list[StreamProfile]:
    out = []
    for p in (el for el in _parse(reply).iter() if _local(el.tag) == "Profiles"):
        name = next((el.text or "" for el in p if _local(el.tag) == "Name"), "")
        enc = next((el for el in p if _local(el.tag) == "VideoEncoderConfiguration"), None)
        width = height = encoding = None
        if enc is not None:
            vals = {_local(el.tag): (el.text or "").strip() for el in enc.iter()}
            width = int(vals["Width"]) if vals.get("Width", "").isdigit() else None
            height = int(vals["Height"]) if vals.get("Height", "").isdigit() else None
            encoding = vals.get("Encoding") or None
        out.append(StreamProfile(token=p.get("token", ""), name=name, width=width, height=height, encoding=encoding))
    return out


def stream_uri(reply: bytes) -> str:
    uri = next((el.text for el in _parse(reply).iter() if _local(el.tag) == "Uri" and el.text), None)
    if not uri:
        raise OnvifError("no stream URI in reply")
    return uri.strip()


class OnvifClient:
    def __init__(self, device_xaddr: str, user: str = "", password: str = "", timeout: float = 5.0) -> None:
        self.device_xaddr = device_xaddr
        self.user, self.password = user, password
        self._http = httpx.Client(timeout=timeout, headers={"Content-Type": "application/soap+xml; charset=utf-8"})

    def close(self) -> None:
        self._http.close()

    def _call(self, url: str, body: str) -> bytes:
        try:
            r = self._http.post(url, content=envelope(body, self.user, self.password).encode())
        except httpx.HTTPError as exc:
            raise OnvifError(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code >= 400 and b"Fault" not in r.content:
            raise OnvifError(f"HTTP {r.status_code}")
        return r.content

    def streams(self) -> list[StreamProfile]:
        """Every media profile with its RTSP URI, largest first."""
        caps = self._call(
            self.device_xaddr, f'<GetCapabilities xmlns="{_DEVICE}"><Category>All</Category></GetCapabilities>'
        )
        media = media_xaddr(caps)
        out = []
        for p in profiles(self._call(media, f'<GetProfiles xmlns="{_MEDIA}"/>')):
            body = (
                f'<GetStreamUri xmlns="{_MEDIA}"><StreamSetup><Stream xmlns="{_SCHEMA}">RTP-Unicast</Stream>'
                f'<Transport xmlns="{_SCHEMA}"><Protocol>RTSP</Protocol></Transport></StreamSetup>'
                f"<ProfileToken>{escape(p.token)}</ProfileToken></GetStreamUri>"
            )
            out.append(
                StreamProfile(p.token, p.name, p.width, p.height, p.encoding, stream_uri(self._call(media, body)))
            )
        return sorted(out, key=lambda s: -s.pixels)
