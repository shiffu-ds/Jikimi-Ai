"""Low-light / smog enhancement for the detector's input only (F18, plan Section 8.18).

When a frame's mean brightness is below ``tau`` (dusk, a dark lane, winter smog), a brightened
640-pixel copy is what the detector and the pose model see; tracking, colour naming, clips and
evidence keep the original pixels. A frame with almost no colour (an infrared night picture) is
already lit by the camera and is left alone.

Off by default, by measurement (``eval.lowlight_check``, darkened frames the methods never saw):
CLAHE on the lightness channel changes nothing (dusk: 0.56 of the original objects found with and
without it; it looked like +0.10 on the frames it was chosen on), and Zero-DCE++, which the plan
names, brightens so much that it multiplies the sensor noise: the detector finds 0.25. Both stay
selectable (``low_light: {enabled: true, method: clahe | zero_dce}``) to re-test on a site's real
night footage, which synthetic darkness does not replace.
"""

from __future__ import annotations

import cv2
import numpy as np

WIDTH = 640


class LowLightEnhancer:
    def __init__(self, method: str = "clahe", model_path: str | None = None, tau: float = 0.25) -> None:
        self.method = method
        self.tau = tau
        self.applied = 0
        self._clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        self._s = None
        if method == "zero_dce":
            import onnxruntime as ort

            if not model_path:
                raise ValueError("zero_dce needs model_path")
            self._s = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])

    def needed(self, frame: np.ndarray) -> bool:
        small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        return float(hsv[..., 2].mean()) / 255.0 < self.tau and float(hsv[..., 1].mean()) >= 12.0

    def enhance(self, frame: np.ndarray) -> np.ndarray:
        if self._s is None:
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            lab[..., 0] = self._clahe.apply(lab[..., 0])
            return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        out = self._s.run(None, {"image": rgb})[0][0].transpose(1, 2, 0)
        return cv2.cvtColor((np.clip(out, 0.0, 1.0) * 255.0).astype(np.uint8), cv2.COLOR_RGB2BGR)

    def __call__(self, frame: np.ndarray) -> np.ndarray:
        if not self.needed(frame):
            return frame
        h, w = frame.shape[:2]
        if w > WIDTH:
            frame = cv2.resize(frame, (WIDTH, round(h * WIDTH / w)), interpolation=cv2.INTER_AREA)
        self.applied += 1
        return self.enhance(frame)
