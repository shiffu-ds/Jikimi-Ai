"""Zero-DCE++ low-light enhancement (F18, plan Section 8.18; Li, Guo & Loy, TPAMI 2021).

A ~10 k-parameter network predicts per-pixel curve parameters A on a downscaled copy; the image
is brightened by iterating LE(x) = x + A * x * (1 - x). It learns without reference images, from
four losses on dark inputs alone: spatial consistency, exposure control, colour constancy and
smoothness of A. Used only on the detector's input; recorded clips stay original.
"""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


class _DSConv(nn.Module):
    def __init__(self, cin: int, cout: int) -> None:
        super().__init__()
        self.depth = nn.Conv2d(cin, cin, 3, padding=1, groups=cin)
        self.point = nn.Conv2d(cin, cout, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.point(self.depth(x))


class ZeroDCEpp(nn.Module):
    def __init__(self, channels: int = 32, scale: int = 4, iterations: int = 8) -> None:
        super().__init__()
        self.scale = scale
        self.iterations = iterations
        c = channels
        self.e1, self.e2, self.e3, self.e4 = _DSConv(3, c), _DSConv(c, c), _DSConv(c, c), _DSConv(c, c)
        self.e5, self.e6, self.e7 = _DSConv(2 * c, c), _DSConv(2 * c, c), _DSConv(2 * c, 3)

    def curves(self, x: torch.Tensor) -> torch.Tensor:
        small = F.interpolate(x, scale_factor=1 / self.scale, mode="bilinear", align_corners=False) if self.scale > 1 else x
        x1 = F.relu(self.e1(small))
        x2 = F.relu(self.e2(x1))
        x3 = F.relu(self.e3(x2))
        x4 = F.relu(self.e4(x3))
        x5 = F.relu(self.e5(torch.cat([x3, x4], 1)))
        x6 = F.relu(self.e6(torch.cat([x2, x5], 1)))
        a = torch.tanh(self.e7(torch.cat([x1, x6], 1)))
        return F.interpolate(a, size=x.shape[2:], mode="bilinear", align_corners=False) if self.scale > 1 else a

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        a = self.curves(x)
        y = x
        for _ in range(self.iterations):
            y = y + a * (y - y * y)
        return y.clamp(0.0, 1.0), a


def spatial_consistency(org: torch.Tensor, enh: torch.Tensor) -> torch.Tensor:
    """Neighbouring 4x4 regions keep their contrast (left/right/up/down differences)."""
    o, e = F.avg_pool2d(org.mean(1, keepdim=True), 4), F.avg_pool2d(enh.mean(1, keepdim=True), 4)
    loss = torch.zeros((), device=org.device)
    for dy, dx in ((0, 1), (1, 0)):
        do = o[:, :, dy:, dx:] - o[:, :, : o.shape[2] - dy, : o.shape[3] - dx]
        de = e[:, :, dy:, dx:] - e[:, :, : e.shape[2] - dy, : e.shape[3] - dx]
        loss = loss + ((do - de) ** 2).mean()
    return loss


def exposure(enh: torch.Tensor, level: float = 0.6, patch: int = 16) -> torch.Tensor:
    return ((F.avg_pool2d(enh.mean(1, keepdim=True), patch) - level) ** 2).mean()


def color_constancy(enh: torch.Tensor) -> torch.Tensor:
    r, g, b = enh.mean((2, 3)).unbind(1)
    return ((r - g) ** 2 + (r - b) ** 2 + (g - b) ** 2).mean()


def smoothness(a: torch.Tensor) -> torch.Tensor:
    return ((a[:, :, 1:, :] - a[:, :, :-1, :]) ** 2).mean() + ((a[:, :, :, 1:] - a[:, :, :, :-1]) ** 2).mean()


def zero_reference_loss(org: torch.Tensor, enh: torch.Tensor, a: torch.Tensor) -> torch.Tensor:
    """The Zero-DCE++ reference implementation's weights."""
    return spatial_consistency(org, enh) + 10 * exposure(enh) + 5 * color_constancy(enh) + 1600 * smoothness(a)
