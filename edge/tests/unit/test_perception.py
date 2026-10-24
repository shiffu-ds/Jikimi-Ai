import numpy as np
import pytest
from cryptography.exceptions import InvalidTag
from jikimi_contracts import Detection, Track
from jikimi_edge.analytics.base import CameraConfig, FrameContext, ZoneConfig
from jikimi_edge.analytics.camera_health.plugin import CameraHealthPlugin
from jikimi_edge.analytics.loitering.plugin import LoiteringPlugin
from jikimi_edge.analytics.loitering.score import loitering_score
from jikimi_edge.analytics.registry import BlockedPluginError, build_plugins
from jikimi_edge.privacy.face_blur import PrivacyBlur, head_region
from jikimi_edge.privacy.vault import Vault
from jikimi_edge.tracking.bytetrack import ByteTracker
from jikimi_edge.tracking.color import color_name
from jikimi_edge.tracking.riders import associate_riders
from jikimi_edge.tracking.track_store import TrackStore


def _t(tid: int, cls: str, box: tuple[float, float, float, float], ts: float = 0.0) -> Track:
    return Track(track_id=tid, cls=cls, conf=0.9, bbox=box, first_seen=ts, last_seen=ts)


def test_loitering_score_matches_plan() -> None:
    assert loitering_score(1, 1, 0, 0) == pytest.approx(0.4 / 3)
    assert loitering_score(3, 2, 2, 120) == pytest.approx(1.0)
    assert loitering_score(4, 2, 0, 0) == pytest.approx(0.6)


def test_rider_association() -> None:
    bike = _t(1, "motorcycle", (0.40, 0.50, 0.50, 0.56))
    rider = _t(2, "person", (0.43, 0.42, 0.47, 0.55))
    pillion = _t(3, "person", (0.41, 0.42, 0.45, 0.55))
    walker = _t(4, "person", (0.43, 0.48, 0.47, 0.62))  # feet below the wheels
    behind = _t(5, "person", (0.44, 0.36, 0.48, 0.45))  # standing on the sidewalk behind
    riders = associate_riders([bike, rider, pillion, walker, behind])
    assert sorted(riders[1]) == [2, 3]


def test_bytetrack_keeps_ids_through_motion_and_a_miss() -> None:
    tr = ByteTracker()
    ids = set()
    for i in range(20):
        x = 0.1 + 0.02 * i
        dets = [] if i == 10 else [Detection(cls="motorcycle", conf=0.9, bbox=(x, 0.5, x + 0.08, 0.56))]
        for t in tr.update(dets, ts=i * 0.2):
            ids.add(t.track_id)
    assert ids == {1}


def test_color_naming() -> None:
    red = np.zeros((40, 60, 3), np.uint8)
    red[:] = (40, 40, 200)
    assert color_name(red) == "red"
    black = np.full((40, 60, 3), 20, np.uint8)
    assert color_name(black) == "black"


def test_loitering_plugin_counts_linked_passes() -> None:
    cam = CameraConfig(
        id="cam", zones=[ZoneConfig(id="gate", polygon=[[0.4, 0.4], [0.6, 0.4], [0.6, 0.9], [0.4, 0.9]])]
    )
    store = TrackStore(cam)
    plugin = LoiteringPlugin()
    plugin.configure({}, cam)
    alerts = []
    for p, tid in enumerate(range(1, 5)):  # same "entity" passes 4 times
        for k in range(12):
            ts = p * 60 + k * 0.5
            x = 0.1 + 0.07 * k
            bike = _t(tid, "motorcycle", (x, 0.5, x + 0.08, 0.6), ts)
            r1 = _t(100 + tid, "person", (x + 0.02, 0.43, x + 0.05, 0.59), ts)
            r2 = _t(200 + tid, "person", (x + 0.0, 0.43, x + 0.03, 0.59), ts)
            riders = associate_riders([bike, r1, r2])
            tracks, zev, new = store.update([bike, r1, r2], ts, None, riders)
            for t in tracks:  # emulate re-ID linking the re-entries of one bike
                if t.cls == "motorcycle":
                    t.entity_id = "cam:mot:1"
            ctx = FrameContext(
                site_id="s",
                camera_id="cam",
                ts=ts,
                frame=None,
                tracks=tracks,
                riders_of=riders,
                rider_ids=frozenset(riders[tid]),
                histories=store.histories,
                zone_events=zev,
                new_track_ids=new,
            )
            alerts += plugin.on_step(ctx)
        store.pop_finished(p * 60 + 20)
    assert alerts, "expected loitering candidates"
    # pass 2 crosses min_score, pass 3 saturates the pass term; pass 4 adds nothing new
    assert [a.features["passes"] for a in alerts] == [2, 3]
    assert alerts[-1].features["riders"] == 2
    assert alerts[-1].raw_score == pytest.approx(0.6, abs=0.01)


def test_camera_health_detects_covered_lens() -> None:
    plugin = CameraHealthPlugin()
    plugin.configure({}, CameraConfig(id="cam"))
    rng = np.random.default_rng(0)
    scene = rng.integers(0, 255, (180, 320, 3), dtype=np.uint8)
    out = []
    for i in range(60):
        ts = float(i)
        frame = scene.copy() if i < 30 else np.full((180, 320, 3), 6, np.uint8)
        frame = np.clip(frame.astype(np.int16) + rng.integers(-3, 4, frame.shape), 0, 255).astype(np.uint8)
        out += plugin.on_step(FrameContext(site_id="s", camera_id="cam", ts=ts, frame=frame))
    assert [a.features["check"] for a in out] == ["covered"]
    assert out[0].ts_end.timestamp() - 30 >= 8  # held for the configured time first


def test_camera_health_detects_frozen_stream() -> None:
    plugin = CameraHealthPlugin()
    plugin.configure({}, CameraConfig(id="cam"))
    rng = np.random.default_rng(0)
    frozen = rng.integers(0, 255, (180, 320, 3), dtype=np.uint8)
    out = []
    for i in range(70):
        frame = rng.integers(0, 255, (180, 320, 3), dtype=np.uint8) if i < 20 else frozen
        out += plugin.on_step(FrameContext(site_id="s", camera_id="cam", ts=float(i), frame=frame))
    assert "frozen" in [a.features["check"] for a in out]


def test_face_recognition_plugins_are_blocked() -> None:
    with pytest.raises(BlockedPluginError):
        build_plugins(["face_recognition"], {}, CameraConfig(id="cam"))


def test_head_blur_changes_only_head_region() -> None:
    rng = np.random.default_rng(1)
    img = rng.integers(0, 255, (360, 640, 3), dtype=np.uint8)
    person = (0.4, 0.2, 0.46, 0.6)
    out, stats = PrivacyBlur(face_detector="none").apply(img, [person])
    hx1, hy1, hx2, hy2 = head_region(person)
    head = (slice(int(hy1 * 360) + 2, int(hy2 * 360) - 2), slice(int(hx1 * 640) + 2, int(hx2 * 640) - 2))
    assert np.abs(out[head].astype(int) - img[head].astype(int)).mean() > 20  # head pixels destroyed
    assert np.array_equal(out[300:, :], img[300:, :])  # legs/background untouched
    assert stats.heads == 1


def test_vault_roundtrip_and_tamper() -> None:
    v = Vault(b"k" * 32)
    blob = v.seal(b"original clip bytes", aad="CL-1")
    assert v.open(blob, aad="CL-1") == b"original clip bytes"
    with pytest.raises(InvalidTag):
        v.open(blob[:-1] + bytes([blob[-1] ^ 1]), aad="CL-1")
    with pytest.raises(InvalidTag):
        v.open(blob, aad="CL-2")


def test_rider_heads_above_bikes_are_blurred_even_without_a_person_box() -> None:
    from jikimi_edge.privacy.face_blur import head_region, rider_head_proxy

    bike = (0.40, 0.55, 0.60, 0.75)  # bike box 0.2 high; riders' heads ~0.1-0.16 above its top
    x1, y1, x2, y2 = head_region(rider_head_proxy(bike))
    assert y1 <= 0.55 - 0.8 * 0.2 and y2 >= 0.55  # band from well above the bike into its top
    assert x1 <= 0.45 and x2 >= 0.55  # centred on the bike


def test_colour_ignores_riders_noise_and_judges_white_against_the_frame() -> None:
    from jikimi_edge.tracking.color import frame_reference

    bike = np.full((80, 120, 3), (25, 25, 25), np.uint8)  # black bike
    bike[0:40, 20:100] = (235, 235, 235)  # rider in a white shirt over its top half
    mask = np.ones(bike.shape[:2], bool)
    mask[0:40, 20:100] = False
    assert color_name(bike) == "white" and color_name(bike, mask) == "black"
    red = np.full((80, 120, 3), (20, 20, 20), np.uint8)
    red[35:70, 10:110] = (30, 30, 200)  # red fairing in the body band, tyres / shadows around it
    assert color_name(red) == "red"

    rng = np.random.default_rng(0)
    dark = rng.integers(0, 45, (80, 120, 3)).astype(np.uint8)  # near-black: hue is noise at full saturation
    assert color_name(dark) == "black"

    dusk = np.full((80, 120, 3), (120, 120, 112), np.uint8)  # a pale body in an evening frame
    assert color_name(dusk, ref_v=150.0) == "silver" and color_name(dusk) == "gray"  # judged against the frame

    ir = np.repeat(rng.integers(0, 255, (90, 160, 1)).astype(np.uint8), 3, axis=2)  # infrared night frame
    assert frame_reference(ir)[1] is True and frame_reference(red)[1] is False


def test_moved_camera_view_is_accepted_when_still_or_by_an_admin() -> None:
    import cv2

    plugin = CameraHealthPlugin()
    plugin.configure({"plugins": {"camera_health": {"reanchor_after_s": 60}}}, CameraConfig(id="cam"))
    rng = np.random.default_rng(0)
    old_view, new_view = (
        cv2.GaussianBlur(rng.integers(0, 255, (180, 320, 3), dtype=np.uint8), (3, 3), 0) for _ in range(2)
    )
    out = []

    def run(t0: int, t1: int, view: np.ndarray) -> None:
        for i in range(t0, t1):
            img = np.clip(view.astype(np.int16) + rng.integers(-3, 4, view.shape), 0, 255).astype(np.uint8)
            out.extend(plugin.on_step(FrameContext(site_id="s", camera_id="cam", ts=float(i), frame=img)))

    run(0, 20, old_view)  # warm-up: reference view learned
    run(20, 140, new_view)  # knocked to a new position, then standing still there
    checks = [(a.features["check"], a.features.get("how"), a.features.get("severity")) for a in out]
    assert checks == [("moved", None, None), ("view_accepted", "auto", "low")]
    assert plugin.status["moved"] == "ok"
    run(140, 150, old_view)  # turned again; this time the admin accepts the view at once
    plugin.request_reanchor("admin")
    run(150, 152, old_view)
    assert out[-1].features["check"] == "view_accepted" and out[-1].features["how"] == "admin"
