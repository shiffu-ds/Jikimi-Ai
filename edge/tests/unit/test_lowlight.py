from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from jikimi_edge.inference.lowlight import LowLightEnhancer

REPO = Path(__file__).resolve().parents[3]


def test_only_dark_colour_frames_are_brightened_and_only_for_the_detector() -> None:
    enh = LowLightEnhancer("clahe", tau=0.25)
    day = np.full((360, 640, 3), (90, 140, 180), np.uint8)
    dusk = (day * 0.2).astype(np.uint8)
    dusk[100:200, 100:300] = (40, 30, 20)
    ir = np.repeat(np.random.default_rng(0).integers(0, 50, (360, 640, 1), dtype=np.uint8), 3, axis=2)
    assert enh(day) is day and enh(ir) is ir  # bright, or infrared (no colour): untouched
    out = enh(dusk)
    assert out is not dusk and out.shape == dusk.shape and enh.applied == 1
    assert dusk.max() <= 50  # the original frame is never modified (clips, evidence)


@pytest.mark.skipif(not (REPO / "models/zero_dce_pp.onnx").exists(), reason="train_lowlight not run")
def test_zero_dce_brightens_a_dark_frame() -> None:
    enh = LowLightEnhancer("zero_dce", str(REPO / "models/zero_dce_pp.onnx"), tau=0.25)
    dark = (np.random.default_rng(1).random((180, 320, 3)) * 40).astype(np.uint8)
    dark[..., 2] = dark[..., 2] // 2  # some colour, so it is not taken for infrared
    assert enh(dark).mean() > 2 * dark.mean()
