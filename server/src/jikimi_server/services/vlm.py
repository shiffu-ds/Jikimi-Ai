"""VLM verifier for alerts (F5) and teacher for distillation (F6).

A small local vision-language model (SmolVLM-256M, ``uv sync --extra vlm`` + models/README.md)
picks which of two descriptions fits a keyframe ("A: the camera is covered ... B: a clear view
..."), asked in both orders to cancel its order bias. One forward pass per order gives P(A) for
the next token - the distribution the plan's three samples at temperature 0.3 would be drawn
from - so "unclear" (agreement below 2/3) comes from the probability itself.

It only speaks for alert types it has *passed*: ``eval.vlm_check`` measures it on labelled frames
and writes ``verifier.json`` next to the model with each type's AUC and decision threshold. A
type below AUC 0.8 (SmolVLM-256M on snatch: 0.42) gets no verdict at all, because a wrong
"looks normal" next to a real snatch would mislead the guard. Default mode is **advisory** (the
alert opens as before, the verdict is attached); **gate** mode lets a "normal" verdict keep a
VERIFY alert out of the guard's queue.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

CHOICES = {  # (what the alert claims, the normal alternative)
    "snatch": (
        "a person on a motorcycle is grabbing a phone or a bag from a pedestrian",
        "people and vehicles are moving normally and nobody is grabbing anything",
    ),
    "loitering": (
        "a motorcycle with riders is waiting or moving slowly near the people or the gate",
        "vehicles and people are passing by normally",
    ),
    "tamper": (
        "the camera is covered, blocked or so blurred that the scene cannot be seen",
        "a clear, normal view of a street or a building",
    ),
}
PASS_AUC = 0.8
UNCLEAR_BELOW = 2 / 3  # the plan's self-consistency rule: less than 2 of 3 votes agree -> unclear
MAX_SIDE = 512


class VlmUnavailable(RuntimeError):
    """No vision-language model on this server."""


@dataclass(frozen=True)
class VlmAnswer:
    p_yes: float
    verdict: str  # "yes" | "no" | "unclear"
    confidence: float
    frames: int
    ms: int


def verdict_of(p_yes: float) -> tuple[str, float]:
    conf = max(p_yes, 1.0 - p_yes)
    if conf < UNCLEAR_BELOW:
        return "unclear", conf
    return ("yes" if p_yes >= 0.5 else "no"), conf


class VlmVerifier:
    def __init__(self, model_dir: Path | None, threads: int = 4) -> None:
        self.model_dir = model_dir
        self.threads = threads
        self._model: Any = None
        self._proc: Any = None
        self._lock = threading.Lock()
        self.calibration: dict[str, dict[str, float]] = {}
        """Per alert type from ``eval.vlm_check``: auc, threshold, spread (mean pos - mean neg)."""
        cal = model_dir / "verifier.json" if model_dir else None
        if cal is not None and cal.exists():
            import json

            data = json.loads(cal.read_text(encoding="utf-8"))
            self.calibration = {k: v for k, v in data.get("types", {}).items() if v.get("auc", 0) >= PASS_AUC}

    def types(self) -> list[str]:
        """Alert types this model has passed (and may give a verdict on)."""
        return sorted(t for t in self.calibration if t in CHOICES)

    @property
    def available(self) -> bool:
        if self.model_dir is None or not (self.model_dir / "model.safetensors").exists():
            return False
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def name(self) -> str:
        return self.model_dir.name if self.model_dir else "none"

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self.available:
            raise VlmUnavailable("no VLM: `uv sync --extra vlm` + models/smolvlm-256m-instruct (models/README.md)")
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        torch.set_num_threads(self.threads)
        try:
            self._proc = AutoProcessor.from_pretrained(str(self.model_dir))
            self._model = AutoModelForImageTextToText.from_pretrained(str(self.model_dir), dtype=torch.float32).eval()
        except Exception as e:  # incomplete download, other transformers version, ...
            raise VlmUnavailable(f"VLM could not be loaded: {e}") from e

    def warm(self) -> None:
        try:
            with self._lock:
                self._load()
        except VlmUnavailable as e:
            log.warning("VLM verifier off: %s", e)

    def _first_ids(self, words: tuple[str, ...]) -> list[int]:
        tok = self._proc.tokenizer
        return sorted({ids[0] for w in words if (ids := tok.encode(w, add_special_tokens=False))})

    def _prob(self, images: list[np.ndarray], text: str, pos: tuple[str, ...], neg: tuple[str, ...]) -> VlmAnswer:
        """P(next token starts ``pos``) / P(``pos`` or ``neg``) after the images and ``text``."""
        import cv2
        import torch
        from PIL import Image

        if not images:
            raise ValueError("no images to verify")
        t0 = time.perf_counter()
        pics = []
        for img in images:
            h, w = img.shape[:2]
            s = MAX_SIDE / max(h, w)
            small = (
                cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
                if s < 1
                else img
            )
            pics.append(Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB)))
        content: list[dict[str, str]] = [{"type": "image"} for _ in pics]
        content.append({"type": "text", "text": text})
        with self._lock:
            self._load()
            prompt = self._proc.apply_chat_template([{"role": "user", "content": content}], add_generation_prompt=True)
            inputs = self._proc(text=prompt, images=pics, return_tensors="pt", do_image_splitting=False)
            with torch.no_grad():
                logits = self._model(**inputs).logits[0, -1]
            probs = torch.softmax(logits.float(), dim=-1)
            p_pos, p_neg = float(probs[self._first_ids(pos)].sum()), float(probs[self._first_ids(neg)].sum())
        p = p_pos / max(p_pos + p_neg, 1e-9)
        verdict, conf = verdict_of(p)
        return VlmAnswer(round(p, 4), verdict, round(conf, 4), len(pics), int((time.perf_counter() - t0) * 1000))

    def ask(self, images: list[np.ndarray], question: str) -> VlmAnswer:
        """P(yes) for a yes/no ``question`` about BGR ``images`` (one forward pass)."""
        text = f"These are CCTV frames. {question} Answer yes or no."
        return self._prob(images, text, ("Yes", " Yes", "yes", " yes"), ("No", " No", "no", " no"))

    def choose(self, images: list[np.ndarray], a: str, b: str) -> VlmAnswer:
        """P(description ``a``) against ``b`` (``p_yes`` = P(A)); ask both orders to cancel order bias."""
        text = f"These are CCTV frames. Which is true? A: {a}. B: {b}. Answer A or B."
        return self._prob(images, text, ("A", " A"), ("B", " B"))

    def score(self, alert_type: str, image: np.ndarray) -> float:
        """P(the alert's description) for one frame, both orders averaged."""
        a, b = CHOICES[alert_type]
        return (self.choose([image], a, b).p_yes + 1.0 - self.choose([image], b, a).p_yes) / 2.0

    def verify(self, alert_type: str, images: list[np.ndarray]) -> VlmAnswer | None:
        """Verdict over keyframes for a passed alert type, else ``None`` (no opinion)."""
        cal = self.calibration.get(alert_type)
        if cal is None or alert_type not in CHOICES or not images:
            return None
        t0 = time.perf_counter()
        s = float(np.mean([self.score(alert_type, img) for img in images]))
        thr, spread = float(cal["threshold"]), max(float(cal.get("spread", 0.1)), 1e-3)
        conf = min(1.0, 0.5 + abs(s - thr) / spread)  # half the class gap away from the threshold = sure
        verdict = "unclear" if conf < UNCLEAR_BELOW else ("yes" if s >= thr else "no")
        return VlmAnswer(round(s, 4), verdict, round(conf, 4), len(images), int((time.perf_counter() - t0) * 1000))
