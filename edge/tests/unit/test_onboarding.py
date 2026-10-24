from __future__ import annotations

import base64
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest
from jikimi_edge.onboarding.discovery import parse_probe_matches, probe_message
from jikimi_edge.onboarding.onvif import OnvifClient, OnvifError, media_xaddr, password_digest, profiles, stream_uri
from jikimi_edge.onboarding.probe import probe
from jikimi_edge.onboarding.templates import guess_brand, mask, urls

PROBE_MATCH = b"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
 xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
 <SOAP-ENV:Body><d:ProbeMatches><d:ProbeMatch>
  <wsa:EndpointReference><wsa:Address>urn:uuid:4a7e0f40-1dd2-11b2-a105-c056e34a51c1</wsa:Address></wsa:EndpointReference>
  <d:Types>dn:NetworkVideoTransmitter tds:Device</d:Types>
  <d:Scopes>onvif://www.onvif.org/type/video_encoder onvif://www.onvif.org/hardware/DS-2CD2043G0-I onvif://www.onvif.org/name/HIKVISION%20DS-2CD2043G0-I</d:Scopes>
  <d:XAddrs>http://192.168.1.64/onvif/device_service http://[fe80::1]/onvif/device_service</d:XAddrs>
 </d:ProbeMatch></d:ProbeMatches></SOAP-ENV:Body></SOAP-ENV:Envelope>"""

CAPS = b"""<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tt="http://www.onvif.org/ver10/schema"><s:Body>
<tds:GetCapabilitiesResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl"><tds:Capabilities>
<tt:Device><tt:XAddr>http://192.168.1.64/onvif/device_service</tt:XAddr></tt:Device>
<tt:Media><tt:XAddr>http://192.168.1.64/onvif/Media</tt:XAddr></tt:Media>
</tds:Capabilities></tds:GetCapabilitiesResponse></s:Body></s:Envelope>"""

PROFILES = b"""<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tt="http://www.onvif.org/ver10/schema"><s:Body>
<trt:GetProfilesResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
<trt:Profiles token="Profile_1" fixed="true"><tt:Name>mainStream</tt:Name><tt:VideoEncoderConfiguration token="V1">
 <tt:Name>VideoEncoder_1</tt:Name><tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution>
</tt:VideoEncoderConfiguration></trt:Profiles>
<trt:Profiles token="Profile_2" fixed="true"><tt:Name>subStream</tt:Name><tt:VideoEncoderConfiguration token="V2">
 <tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>640</tt:Width><tt:Height>360</tt:Height></tt:Resolution>
</tt:VideoEncoderConfiguration></trt:Profiles>
</trt:GetProfilesResponse></s:Body></s:Envelope>"""


def _uri_reply(uri: str) -> bytes:
    return f"""<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tt="http://www.onvif.org/ver10/schema"><s:Body>
<trt:GetStreamUriResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl"><trt:MediaUri><tt:Uri>{uri}</tt:Uri>
<tt:InvalidAfterConnect>false</tt:InvalidAfterConnect></trt:MediaUri></trt:GetStreamUriResponse></s:Body></s:Envelope>""".encode()


FAULT = b"""<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><s:Fault>
<s:Code><s:Value>s:Sender</s:Value></s:Code><s:Reason><s:Text xml:lang="en">Sender not Authorized</s:Text></s:Reason>
</s:Fault></s:Body></s:Envelope>"""


def test_rtsp_templates_quote_credentials_and_mask_them() -> None:
    main, sub = urls("hikvision", "192.168.1.64", channel=3, user="admin", password="p@ss:word")
    assert main == "rtsp://admin:p%40ss%3Aword@192.168.1.64:554/Streaming/Channels/301"
    assert sub.endswith("/Streaming/Channels/302")
    assert urls("dahua", "10.0.0.9", channel=2, placeholder=True)[1] == (
        "rtsp://USER:PASSWORD@10.0.0.9:554/cam/realmonitor?channel=2&subtype=1"
    )
    assert mask(main) == "rtsp://admin:***@192.168.1.64:554/Streaming/Channels/301"
    assert mask("rtsp://10.0.0.9/stream2") == "rtsp://10.0.0.9/stream2"


@pytest.mark.parametrize(
    ("text", "brand"),
    [
        ("onvif://www.onvif.org/hardware/DS-2CD2043G0-I", "hikvision"),
        ("IPC-HFW1230S-0280B", "dahua"),
        ("CP-UNC-TA21L3", "cpplus"),
        ("VIGI C340", "tplink"),
        ("SomeCam 9000", None),
    ],
)
def test_brand_is_guessed_from_scopes(text: str, brand: str | None) -> None:
    assert guess_brand(text) == brand


def test_ws_discovery_probe_and_reply() -> None:
    msg = probe_message("abc")
    assert b"NetworkVideoTransmitter" in msg and b"uuid:abc" in msg
    (dev,) = parse_probe_matches(PROBE_MATCH, "192.168.1.64")
    assert dev.ip == "192.168.1.64" and dev.brand == "hikvision"
    assert dev.name == "HIKVISION DS-2CD2043G0-I" and dev.hardware == "DS-2CD2043G0-I"
    assert parse_probe_matches(b"<not xml", "1.2.3.4") == []
    assert parse_probe_matches(b"<a>" + b" " * 70_000 + b"</a>", "1.2.3.4") == []  # oversized reply ignored


def test_ws_security_digest_matches_the_onvif_guide_example() -> None:
    nonce = base64.b64decode("LKqI6G/AikKCQrN0zqZFlg==")
    assert password_digest("userpassword", nonce, "2010-09-16T07:50:45Z") == "tuOSpGlFlIXsozq4HFNeeGeFLEI="


def test_onvif_replies_are_parsed_and_faults_raised() -> None:
    assert media_xaddr(CAPS) == "http://192.168.1.64/onvif/Media"
    main, sub = profiles(PROFILES)
    assert (main.token, main.width, main.height, main.encoding) == ("Profile_1", 1920, 1080, "H264")
    assert (sub.name, sub.pixels) == ("subStream", 640 * 360)
    assert stream_uri(_uri_reply("rtsp://192.168.1.64:554/Streaming/Channels/102")).endswith("/102")
    with pytest.raises(OnvifError, match="not Authorized"):
        profiles(FAULT)


def test_onvif_client_walks_device_media_and_stream_uri() -> None:
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content
        seen.append(body)
        if b"GetCapabilities" in body:
            return httpx.Response(200, content=CAPS)
        if b"GetProfiles" in body:
            return httpx.Response(200, content=PROFILES)
        token = b"Profile_1" if b"<ProfileToken>Profile_1" in body else b"Profile_2"
        return httpx.Response(200, content=_uri_reply(f"rtsp://192.168.1.64/{token.decode()}"))

    client = OnvifClient("http://192.168.1.64/onvif/device_service", "admin", "secret")
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    streams = client.streams()
    assert [s.uri for s in streams] == [
        "rtsp://192.168.1.64/Profile_1",
        "rtsp://192.168.1.64/Profile_2",
    ]  # largest first
    assert all(b"UsernameToken" in b and b"PasswordDigest" in b and b"secret" not in b for b in seen)


def test_probe_reports_resolution_and_frames(tmp_path: Path) -> None:
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 48))
    for i in range(12):
        writer.write(np.full((48, 64, 3), i * 20, np.uint8))
    writer.release()
    r = probe(str(path), seconds=5, live=False)
    assert r.ok and (r.width, r.height, r.frames, r.read_failures) == (64, 48, 12, 0)
    assert r.advice == ["ok: ready for site.yaml"]
    missing = probe(str(tmp_path / "nope.mp4"), seconds=1, live=False)
    assert not missing.ok and "did not open" in missing.advice[0]
