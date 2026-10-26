"""OpenCV renderer for the simulated CCTV view (textured background so ORB/tamper checks work)."""

from __future__ import annotations

from datetime import datetime

import cv2
import numpy as np

from .world import PersonLook, VehicleLook, WorldState

W, H = 640, 360


def _px(x: float, y: float) -> tuple[int, int]:
    return round(x * W), round(y * H)


def _background(layout: str, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.zeros((H, W, 3), np.uint8)
    # sky gradient + buildings
    for yy in range(int(0.36 * H)):
        c = 200 - yy // 2
        img[yy, :] = (c, c - 10, c - 30)
    x = 0
    while x < W:
        bw = int(rng.integers(60, 130))
        bh = int(rng.integers(50, 110))
        top = int(0.36 * H) - bh
        color = tuple(int(v) for v in rng.integers(90, 190, 3))
        cv2.rectangle(img, (x, top), (x + bw, int(0.36 * H)), color, -1)
        for wy in range(top + 8, int(0.36 * H) - 10, 16):
            for wx in range(x + 6, x + bw - 10, 14):
                lit = rng.random() < 0.35
                cv2.rectangle(img, (wx, wy), (wx + 7, wy + 9), (120, 200, 230) if lit else (60, 60, 70), -1)
        x += bw + int(rng.integers(0, 6))
    # wall / shopfronts strip
    cv2.rectangle(img, (0, int(0.30 * H)), (W, int(0.38 * H)), (150, 160, 170), -1)
    if layout == "gate":
        cv2.rectangle(img, _px(0.56, 0.22), _px(0.76, 0.38), (70, 70, 80), -1)  # gate opening
        for gx in range(int(0.565 * W), int(0.755 * W), 9):
            cv2.line(img, (gx, int(0.23 * H)), (gx, int(0.38 * H)), (40, 90, 140), 2)
        cv2.rectangle(img, _px(0.55, 0.15), _px(0.77, 0.21), (40, 110, 30), -1)
        cv2.putText(
            img,
            "JIKIMI HOMES  GATE 2",
            _px(0.565, 0.195),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.36,
            (240, 240, 240),
            1,
            cv2.LINE_AA,
        )
        cv2.rectangle(img, _px(0.80, 0.24), _px(0.87, 0.38), (60, 130, 160), -1)  # guard booth
        cv2.putText(img, "GUARD", _px(0.803, 0.27), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (20, 20, 20), 1, cv2.LINE_AA)
    else:
        names = ["AL-NOOR MOBILE", "BAKERS", "PHARMACY", "GENERAL STORE", "TAILOR"]
        sx = 0.02
        for i, name in enumerate(names):
            w = 0.18
            col = [(40, 40, 160), (30, 120, 200), (120, 60, 30), (40, 130, 40), (110, 40, 110)][i]
            cv2.rectangle(img, _px(sx, 0.24), _px(sx + w, 0.29), col, -1)
            cv2.putText(
                img, name, _px(sx + 0.008, 0.275), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (250, 250, 250), 1, cv2.LINE_AA
            )
            cv2.rectangle(img, _px(sx + 0.01, 0.29), _px(sx + w - 0.01, 0.38), (60, 70, 80), -1)
            sx += w + 0.015
    # electric poles and wires
    for px in (0.12, 0.47, 0.9):
        cv2.line(img, _px(px, 0.05), _px(px, 0.42), (50, 50, 50), 3)
    cv2.line(img, _px(0.0, 0.08), _px(1.0, 0.1), (40, 40, 40), 1)
    cv2.line(img, _px(0.0, 0.12), _px(1.0, 0.11), (40, 40, 40), 1)
    # far sidewalk, road, near sidewalk
    cv2.rectangle(img, _px(0, 0.38), _px(1, 0.47), (165, 170, 175), -1)
    for tx in range(0, W, 24):
        cv2.line(img, (tx, int(0.38 * H)), (tx - 8, int(0.47 * H)), (140, 145, 150), 1)
    cv2.rectangle(img, _px(0, 0.47), _px(1, 0.84), (78, 80, 84), -1)
    for dx in range(0, W, 46):
        cv2.line(img, (dx, int(0.655 * H)), (dx + 24, int(0.655 * H)), (200, 210, 220), 2)
    cv2.rectangle(img, _px(0, 0.84), _px(1, 1.0), (150, 155, 160), -1)
    for tx in range(0, W, 30):
        cv2.line(img, (tx, int(0.84 * H)), (tx + 12, H), (130, 135, 140), 1)
    noise = rng.integers(-6, 7, img.shape, dtype=np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _draw_person(
    img: np.ndarray,
    box: tuple[float, float, float, float],
    kps: list[tuple[float, float, float]],
    look: PersonLook,
    phone: bool,
    sitting: bool = False,
    stand_h: float | None = None,
) -> None:
    h = (stand_h if stand_h else box[3] - box[1]) * H  # a crouching or lying body keeps its size
    th = max(1, int(h * 0.09))
    p = [_px(k[0], k[1]) for k in kps]
    # legs and arms
    for a, b, col in ((11, 13, look.pants), (13, 15, look.pants), (12, 14, look.pants), (14, 16, look.pants)):
        cv2.line(img, p[a], p[b], col, th + 1, cv2.LINE_AA)
    torso = np.array([p[5], p[6], p[12], p[11]], np.int32)
    cv2.fillConvexPoly(img, torso, look.shirt, cv2.LINE_AA)
    for a, b in ((5, 7), (7, 9), (6, 8), (8, 10)):
        cv2.line(img, p[a], p[b], look.shirt, th, cv2.LINE_AA)
    for w in (9, 10):
        cv2.circle(img, p[w], max(1, th // 2 + 1), look.skin, -1, cv2.LINE_AA)
    r = max(2, int(h * 0.075 if not sitting else h * 0.085))
    if stand_h and box[3] - box[1] < 0.5 * stand_h:  # lying: the head is at the end of the body
        cv2.circle(img, p[0], r, look.skin, -1, cv2.LINE_AA)
        cv2.ellipse(img, p[0], (r, max(1, r // 2)), 90, 0, 180, look.hair, -1, cv2.LINE_AA)
        return
    hx, hy = p[0][0] - (p[0][0] - (p[3][0] + p[4][0]) // 2) // 2, p[0][1]
    cv2.circle(img, (hx, hy), r, look.skin, -1, cv2.LINE_AA)
    if look.helmet is not None:
        cv2.ellipse(img, (hx, hy - r // 4), (r + 1, r), 0, 180, 360, look.helmet, -1, cv2.LINE_AA)
    else:
        cv2.ellipse(img, (hx, hy - r // 3), (r, max(1, r // 2)), 0, 180, 360, look.hair, -1, cv2.LINE_AA)
    if phone:
        cv2.rectangle(img, (p[10][0] - 1, p[10][1] - 3), (p[10][0] + 2, p[10][1] + 2), (30, 30, 30), -1)


def _draw_bike(img: np.ndarray, d: dict[str, object]) -> None:
    box = d["box"]
    look: VehicleLook = d["look"]  # type: ignore[assignment]
    facing = int(d["facing"])  # type: ignore[call-overload]
    x1, y1, x2, y2 = box  # type: ignore[misc]
    w = (x2 - x1) * W
    r = max(2, int(w * 0.17))
    back = _px(x1 + (x2 - x1) * (0.2 if facing > 0 else 0.8), y2 - (y2 - y1) * 0.25)
    front = _px(x1 + (x2 - x1) * (0.8 if facing > 0 else 0.2), y2 - (y2 - y1) * 0.25)
    for c in (back, front):
        cv2.circle(img, c, r, (25, 25, 25), -1, cv2.LINE_AA)
        cv2.circle(img, c, max(1, r // 2), (150, 150, 150), 1, cv2.LINE_AA)
    body = np.array(
        [
            (back[0], back[1] - r),
            (front[0] - facing * r, front[1] - int(1.6 * r)),
            (front[0], front[1] - r),
            ((back[0] + front[0]) // 2, back[1]),
        ],
        np.int32,
    )
    cv2.fillConvexPoly(img, body, look.body, cv2.LINE_AA)
    cv2.line(
        img, (front[0], front[1] - int(1.6 * r)), (front[0] + facing * r // 2, front[1] - int(2.4 * r)), (40, 40, 40), 2
    )
    if look.delivery_box is not None:
        cv2.rectangle(img, (back[0] - r, back[1] - 3 * r), (back[0] + r, back[1] - r), look.delivery_box, -1)
    for rd in d.get("riders", []):  # type: ignore[attr-defined]
        _draw_person(img, rd["box"], rd["kps"], rd["look"], phone=False, sitting=True)


def _draw_car(img: np.ndarray, d: dict[str, object]) -> None:
    x1, y1, x2, y2 = d["box"]  # type: ignore[misc]
    look: VehicleLook = d["look"]  # type: ignore[assignment]
    p1, p2 = _px(x1, y1 + (y2 - y1) * 0.25), _px(x2, y2 - (y2 - y1) * 0.15)
    cv2.rectangle(img, p1, p2, look.body, -1, cv2.LINE_AA)
    roof1, roof2 = _px(x1 + (x2 - x1) * 0.2, y1), _px(x2 - (x2 - x1) * 0.2, y1 + (y2 - y1) * 0.3)
    cv2.rectangle(img, roof1, roof2, look.body, -1)
    cv2.rectangle(
        img,
        _px(x1 + (x2 - x1) * 0.25, y1 + (y2 - y1) * 0.05),
        _px(x2 - (x2 - x1) * 0.25, y1 + (y2 - y1) * 0.28),
        (200, 190, 150),
        -1,
    )
    r = max(2, int((x2 - x1) * W * 0.09))
    for wx in (x1 + (x2 - x1) * 0.2, x2 - (x2 - x1) * 0.2):
        cv2.circle(img, _px(wx, y2 - (y2 - y1) * 0.12), r, (20, 20, 20), -1, cv2.LINE_AA)


def render(
    state: WorldState,
    layout: str,
    camera_label: str,
    local_time: datetime,
    seed: int = 7,
    night: bool = False,
    covered: bool = False,
    rng: np.random.Generator | None = None,
    _cache: dict[tuple[str, int], np.ndarray] = {},  # noqa: B006 - deliberate per-process cache
) -> np.ndarray:
    rng = rng or np.random.default_rng()
    key = (layout, seed)
    if key not in _cache:
        _cache[key] = _background(layout, seed)
    img = _cache[key].copy()
    if covered:
        img = np.full((H, W, 3), 8, np.uint8)
    else:
        for d in state.draw:
            if d["kind"] == "person":
                _draw_person(
                    img,
                    d["box"],  # type: ignore[arg-type]
                    d["kps"],  # type: ignore[arg-type]
                    d["look"],  # type: ignore[arg-type]
                    bool(d["phone"]),
                    stand_h=d.get("stand_h"),  # type: ignore[arg-type]
                )
            elif d["kind"] == "motorcycle":
                _draw_bike(img, d)
            else:
                _draw_car(img, d)
        if night:
            img = (img.astype(np.float32) * 0.42).astype(np.uint8)
            for lx in (0.12, 0.47, 0.9):
                cv2.circle(img, _px(lx, 0.06), 10, (190, 230, 250), -1, cv2.LINE_AA)
    sigma = 7 if night else 3
    noise = rng.normal(0, sigma, img.shape).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    stamp = local_time.strftime("%Y-%m-%d %H:%M:%S")
    for text, (ox, oy) in ((camera_label, (8, 18)), (stamp, (W - 168, 18))):
        # thick strokes change glyph advance in Hershey fonts, so outline with offset copies
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            cv2.putText(img, text, (ox + dx, oy + dy), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(img, text, (ox, oy), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    if int(local_time.timestamp()) % 2 == 0:
        cv2.circle(img, (W - 12, 30), 5, (0, 0, 230), -1, cv2.LINE_AA)
    return img
