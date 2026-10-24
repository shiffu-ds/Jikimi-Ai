"""RTSP URL templates for the DVR/NVR brands common in Pakistan (plan Section 8.20).

Used when a recorder has no ONVIF (or ONVIF is switched off). The sub-stream is preferred: the
edge runs at 5 fps on 720p or less, and the main stream only costs decode time.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True)
class Template:
    brand: str
    main: str
    sub: str
    note: str = ""


# {auth} is "user:pass@" (URL-quoted) or "", {ch} is the 1-based channel number
TEMPLATES: dict[str, Template] = {
    "hikvision": Template(
        "hikvision",
        "rtsp://{auth}{ip}:{port}/Streaming/Channels/{ch}01",
        "rtsp://{auth}{ip}:{port}/Streaming/Channels/{ch}02",
        "also HiWatch and Hikvision-OEM recorders",
    ),
    "dahua": Template(
        "dahua",
        "rtsp://{auth}{ip}:{port}/cam/realmonitor?channel={ch}&subtype=0",
        "rtsp://{auth}{ip}:{port}/cam/realmonitor?channel={ch}&subtype=1",
        "also Imou and most Dahua-OEM recorders",
    ),
    "cpplus": Template(
        "cpplus",
        "rtsp://{auth}{ip}:{port}/cam/realmonitor?channel={ch}&subtype=0",
        "rtsp://{auth}{ip}:{port}/cam/realmonitor?channel={ch}&subtype=1",
        "CP Plus firmware is Dahua-based",
    ),
    "uniview": Template(
        "uniview",
        "rtsp://{auth}{ip}:{port}/unicast/c{ch}/s0/live",
        "rtsp://{auth}{ip}:{port}/unicast/c{ch}/s1/live",
    ),
    "tplink": Template("tplink", "rtsp://{auth}{ip}:{port}/stream1", "rtsp://{auth}{ip}:{port}/stream2", "VIGI / Tapo"),
}

_HINTS = {
    "hikvision": ("hikvision", "hikvison", "hiwatch", "ds-2cd", "ds-7", "ds-2de"),
    "dahua": ("dahua", "dh-", "ipc-hfw", "ipc-hdw", "nvr4", "imou"),
    "cpplus": ("cp plus", "cpplus", "cp-u", "cp-v"),  # CP-UNC (cameras), CP-UVR / CP-UNR (recorders)
    "uniview": ("uniview", "unv", "ipc2"),
    "tplink": ("tp-link", "tplink", "vigi", "tapo"),
}


def guess_brand(*texts: str) -> str | None:
    """Brand from ONVIF scopes / hardware / name strings, e.g. ``onvif://www.onvif.org/hardware/DS-2CD2043``."""
    blob = " ".join(texts).lower()
    for brand, hints in _HINTS.items():
        if any(h in blob for h in hints):
            return brand
    return None


PLACEHOLDER = "USER:PASSWORD@"


def urls(
    brand: str,
    ip: str,
    channel: int = 1,
    user: str = "",
    password: str = "",
    port: int = 554,
    placeholder: bool = False,
) -> tuple[str, str]:
    """``(main, sub)`` RTSP URLs. Keep the result in ``.env``, never in ``site.yaml``: it holds the
    password. ``placeholder=True`` prints ``USER:PASSWORD@`` instead, for screens and docs."""
    t = TEMPLATES[brand]
    auth = PLACEHOLDER if placeholder else (f"{quote(user, safe='')}:{quote(password, safe='')}@" if user else "")
    fields = {"auth": auth, "ip": ip, "port": port, "ch": channel}
    return t.main.format(**fields), t.sub.format(**fields)


def mask(url: str) -> str:
    """Hide the password in an RTSP URL for logs and screens."""
    head, sep, rest = url.partition("://")
    if "@" not in rest:
        return url
    creds, at, tail = rest.rpartition("@")
    user = creds.split(":", 1)[0]
    return f"{head}{sep}{user}:***{at}{tail}"
