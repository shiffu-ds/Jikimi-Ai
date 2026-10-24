"""Trajectory transformer for cross-camera loitering (F2 Tier 2, plan Section 8.3).

A global trajectory is a sequence of segments ``(camera, dwell, dt, speed, turns, time-of-day)``.
Trained self-supervised on *normal* trajectories with masked-segment modelling (15 % masked);
the anomaly score is the mean reconstruction NLL of masked segments, then calibrated with the
same split-conformal machinery as the edge plugins.
"""

from __future__ import annotations

import math

import torch
from torch import nn

NUM_CONT = 6  # dwell_s, dt_s, speed, turn_count, sin(tod), cos(tod)


class TrajectoryTransformer(nn.Module):
    def __init__(self, num_cameras: int, d_model: int = 128, heads: int = 4, layers: int = 4, max_len: int = 64) -> None:
        super().__init__()
        self.cam = nn.Embedding(num_cameras + 1, d_model)  # last index = [MASK]
        self.cont = nn.Linear(NUM_CONT, d_model)
        self.pos = nn.Parameter(torch.zeros(1, max_len, d_model))
        enc = nn.TransformerEncoderLayer(d_model, heads, dim_feedforward=4 * d_model, dropout=0.1, batch_first=True)
        self.encoder = nn.TransformerEncoder(enc, layers)
        self.cam_head = nn.Linear(d_model, num_cameras)
        self.cont_head = nn.Linear(d_model, 2 * NUM_CONT)  # Gaussian mean + log-variance
        self.mask_id = num_cameras
        nn.init.normal_(self.pos, std=0.02)

    def forward(self, cams: torch.Tensor, cont: torch.Tensor, pad: torch.Tensor | None = None) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        h = self.cam(cams) + self.cont(cont) + self.pos[:, : cams.shape[1]]
        h = self.encoder(h, src_key_padding_mask=pad)
        mu, logvar = self.cont_head(h).chunk(2, dim=-1)
        return self.cam_head(h), mu, logvar.clamp(-6, 6)


def masked_nll(
    model: TrajectoryTransformer,
    cams: torch.Tensor,
    cont: torch.Tensor,
    mask: torch.Tensor,
    pad: torch.Tensor | None = None,
) -> torch.Tensor:
    """Per-trajectory mean NLL over masked segments (training loss and anomaly score); ``pad``
    marks the padding of shorter trajectories in a batch (never attended to, never scored)."""
    cams_in = cams.masked_fill(mask, model.mask_id)
    cont_in = cont.masked_fill(mask.unsqueeze(-1), 0.0)
    logits, mu, logvar = model(cams_in, cont_in, pad)
    ce = nn.functional.cross_entropy(logits.transpose(1, 2), cams, reduction="none")
    gauss = 0.5 * (logvar + (cont - mu) ** 2 / logvar.exp() + math.log(2 * math.pi)).sum(-1)
    per_seg = (ce + gauss) * mask
    return per_seg.sum(1) / mask.sum(1).clamp(min=1)


def random_mask(shape: tuple[int, int], ratio: float = 0.15, generator: torch.Generator | None = None) -> torch.Tensor:
    m = torch.rand(shape, generator=generator) < ratio
    m[:, 0] |= ~m.any(dim=1)  # at least one masked segment per trajectory
    return m
