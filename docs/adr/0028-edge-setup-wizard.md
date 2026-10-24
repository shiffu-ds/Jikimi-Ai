# ADR-0028: The camera setup wizard runs on the edge, not in the dashboard

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-24
- **Feature / gap:** F20, G07, G18

## Context
The plan asks for an Urdu wizard: find camera -> preview -> draw zone -> test -> done, usable by a
non-technical owner in under 10 minutes. Discovery (ONVIF multicast) and the stream test only work
on the cameras' LAN, and the RTSP URL holds the recorder's password, which must never leave the
site (ADR-0001). The edge has no web framework and should not get one.

## Decision
`jikimi-edge setup` (`make setup-wizard`) serves one Urdu-first page with Python's `http.server`
while the command runs. A one-time 6-digit PIN printed on the edge guards every API call (custom
header, so no cross-site requests; 5 wrong PINs lock it for a minute). Steps: ONVIF discovery or
brand + IP through the RTSP templates -> connection test with a preview (heads blurred when a
detector or YuNet is present) -> tap the zone's corners -> detector test -> save. The URL goes into
`.env` (mode 600), the camera and zone into `site.yaml` with its comments kept; both are backed up
and the new `site.yaml` is parsed before it is written.

## Consequences
No password reaches the server or the dashboard. The page works without internet. Over shared
Wi-Fi the PIN and password travel unencrypted on the LAN (no certificate on a fresh edge): the
runbook says to use a cable or `--host 127.0.0.1`. The < 10 min target is not measured yet: it
needs a real recorder and an owner who has not seen the page before.
