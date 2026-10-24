"""Log-mel patches, YAMNet-shaped: 16 kHz mono, 0.96 s windows (hop 0.48 s), 25 ms frames every
10 ms, 64 mel bands from 125 Hz to 7.5 kHz. Plain numpy so the edge needs no audio library for
features; training (``jikimi_ml.train.train_audio``) uses this same function."""

from __future__ import annotations

import numpy as np

RATE = 16000
WINDOW = int(0.96 * RATE)
HOP = int(0.48 * RATE)
N_FFT, FRAME, STEP, MELS = 512, 400, 160, 64


def _mel(f: np.ndarray) -> np.ndarray:
    return 1127.0 * np.log1p(f / 700.0)


def mel_filters(lo: float = 125.0, hi: float = 7500.0) -> np.ndarray:
    freqs = np.linspace(0, RATE / 2, N_FFT // 2 + 1)
    edges = np.linspace(_mel(np.asarray(lo)), _mel(np.asarray(hi)), MELS + 2)
    m = _mel(freqs)
    fb = np.zeros((MELS, len(freqs)), np.float32)
    for i in range(MELS):
        left, mid, right = edges[i], edges[i + 1], edges[i + 2]
        fb[i] = np.clip(np.minimum((m - left) / (mid - left), (right - m) / (right - mid)), 0, None)
    return fb


_FB = mel_filters()
_WIN = np.hanning(FRAME).astype(np.float32)


def log_mel(window: np.ndarray) -> np.ndarray:
    """``(96, 64)`` log-mel patch of one 0.96 s window (float32 samples in [-1, 1])."""
    x = np.asarray(window, np.float32)[:WINDOW]
    x = np.pad(x, (STEP, STEP + WINDOW - len(x)))  # centred frames: 96 of them, as in YAMNet
    n = 1 + (len(x) - FRAME) // STEP
    idx = np.arange(FRAME)[None, :] + STEP * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * _WIN, n=N_FFT)) ** 2
    return np.log(spec @ _FB.T + 1e-6).astype(np.float32)


def windows(samples: np.ndarray) -> list[np.ndarray]:
    """0.96 s windows every 0.48 s."""
    return [samples[i : i + WINDOW] for i in range(0, max(len(samples) - WINDOW, 0) + 1, HOP)]
