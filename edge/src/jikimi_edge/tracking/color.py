"""Dominant colour naming for vehicle crops (feeds Roman Urdu search: "kaali bike").

Revised after real footage (a crowded junction clip, 32 hand-labelled bike crops), where the old
rule named every bike "black": tyres, shadows and riders' clothes fill most of a bike's box, and
near-black pixels carry random hue at full saturation. Now:

* a chromatic colour needs clearly saturated, visible pixels (S >= 140, V >= 60) in the body band
  (40-85 % of the box height: fairings and panels, mostly below the riders' torsos);
* otherwise white / silver / black is decided with the riders' upper bodies masked out (a white
  shirt is not a white bike), comparing light against dark pixels; "white" needs V >= 200;
* an infrared (grayscale) night frame names no colour at all: guessing would mislead search.

Per crop, same settings on both sets: simulator renders 81 % (old rule 72 %); the 32 real crops
66 % if a white bike named "silver" counts, 34 % exact (old rule 31 %: every bike "black"). In that
hazy clip white bikes are no brighter than the simulator's silver ones, so they come out silver,
which search scores as near-white. Both sets are small; re-check on each pilot site's footage.
"""

from __future__ import annotations

import cv2
import numpy as np

COLORS = ("black", "white", "gray", "silver", "red", "orange", "yellow", "green", "blue", "brown")
DEFAULT_REF_V = 230.0
_V_VISIBLE, _S_CHROMA, _CHROMA_MIN = 60, 140, 0.06
_LIGHT_VS_DARK, _WHITE_V = 0.3, 200


def frame_reference(frame_bgr: np.ndarray) -> tuple[float, bool]:
    """``(ref_v, grayscale)`` of a frame: its 90th-percentile brightness, and whether it is an
    infrared / monochrome night frame (no colour information at all)."""
    small = cv2.cvtColor(cv2.resize(frame_bgr, (160, 90), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2HSV)
    return max(float(np.percentile(small[..., 2], 90)), 40.0), float(small[..., 1].mean()) < 12.0


def color_name(
    crop_bgr: np.ndarray, mask: np.ndarray | None = None, ref_v: float = DEFAULT_REF_V, min_pixels: int = 40
) -> str | None:
    """Name the bike / vehicle body colour of ``crop_bgr`` (``None`` if too small).

    ``mask`` (same height and width) is False over riders' upper bodies; it is used only for the
    white / silver / black decision. ``ref_v`` is the frame brightness from :func:`frame_reference`.
    """
    if crop_bgr is None or crop_bgr.size == 0:
        return None
    h, w = crop_bgr.shape[:2]
    if h * w < min_pixels:
        return None
    x1, x2 = int(w * 0.10), max(int(w * 0.90), int(w * 0.10) + 1)
    cy1, cy2 = int(h * 0.40), max(int(h * 0.85), int(h * 0.40) + 1)
    hc = cv2.cvtColor(crop_bgr[cy1:cy2, x1:x2], cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.int32)
    hh, ss, vv = hc[:, 0], hc[:, 1], hc[:, 2]
    chroma = (vv >= _V_VISIBLE) & (ss >= _S_CHROMA)
    counts = {
        "red": int((chroma & ((hh < 8) | (hh >= 160))).sum()),
        "orange": int((chroma & (hh >= 8) & (hh < 22) & (vv >= 150)).sum()),
        "brown": int((chroma & (hh >= 8) & (hh < 22) & (vv < 150)).sum()),
        "yellow": int((chroma & (hh >= 22) & (hh < 35)).sum()),
        "green": int((chroma & (hh >= 35) & (hh < 85)).sum()),
        "blue": int((chroma & (hh >= 85) & (hh < 160)).sum()),
    }
    best = max(counts, key=lambda k: counts[k])
    if counts[best] >= _CHROMA_MIN * max(len(hc), 1):
        return best
    y1, y2 = int(h * 0.25), max(int(h * 0.85), int(h * 0.25) + 1)
    hsv = cv2.cvtColor(crop_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.int32)
    if mask is not None:
        keep = mask[y1:y2, x1:x2].reshape(-1)
        if int(keep.sum()) >= min_pixels:
            hsv = hsv[keep]
    ss, vv = hsv[:, 1], hsv[:, 2]
    n = max(len(hsv), 1)
    dark = int((vv < _V_VISIBLE).sum())
    light_px = (vv >= _V_VISIBLE) & (ss < _S_CHROMA) & (vv >= 0.6 * ref_v)
    light = int(light_px.sum())
    if light > _LIGHT_VS_DARK * dark and light >= 0.05 * n:
        return "white" if float(np.median(vv[light_px])) >= _WHITE_V else "silver"
    if dark >= 0.2 * n:
        return "black"
    return "gray"
