"""Two-person ST-GCN for snatch detection (plan Section 8.2, ADR-004).

Input ``(N, C=3, T=32, V=17, M=2)``: COCO-17 keypoints ``(x, y, conf)`` of the rider closest to
the pedestrian (M=0) and the pedestrian (M=1), centred on the rider's hips and scaled by the
pedestrian's height (same tensor as ``edge/.../snatch/stgcn_infer.py``).

Graph convolution uses the spatial-configuration partition of Yan et al. (2018): self, inward
(towards the body centre) and outward edges. Both persons share the graph; an extra
inter-person edge set connects rider and pedestrian wrists, so the model "sees" hand contact.
Optional extra features (relative velocity, hand distance, ...) are concatenated before the head.
"""

from __future__ import annotations

import numpy as np
import torch
from torch import nn

COCO_EDGES = [
    (0, 1), (0, 2), (1, 3), (2, 4), (0, 5), (0, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (5, 6),
]  # fmt: skip
CENTER = 0  # nose as the hop-0 reference; hips are equally fine
V = 17


def _hops(num_v: int, edges: list[tuple[int, int]], center: int) -> np.ndarray:
    adj = np.full((num_v, num_v), np.inf)
    np.fill_diagonal(adj, 0)
    for a, b in edges:
        adj[a, b] = adj[b, a] = 1
    for k in range(num_v):  # Floyd-Warshall, tiny graph
        adj = np.minimum(adj, adj[:, k : k + 1] + adj[k : k + 1, :])
    return adj[center]


def spatial_partition(num_v: int = V, edges: list[tuple[int, int]] | None = None, center: int = CENTER) -> np.ndarray:
    """``(3, V, V)`` normalized adjacency: self, inward (closer to centre), outward."""
    edges = edges or COCO_EDGES
    dist = _hops(num_v, edges, center)
    a = np.zeros((3, num_v, num_v), dtype=np.float32)
    for i in range(num_v):
        a[0, i, i] = 1
    for i, j in edges:
        for src, dst in ((i, j), (j, i)):
            part = 1 if dist[dst] < dist[src] else 2
            a[part, dst, src] = 1
    deg = a.sum(axis=(0, 1)) + 1e-6
    return a / deg[None, None, :]


class GraphConv(nn.Module):
    def __init__(self, c_in: int, c_out: int, adj: torch.Tensor) -> None:
        super().__init__()
        self.register_buffer("adj", adj)
        self.edge_importance = nn.Parameter(torch.ones_like(adj))
        self.conv = nn.Conv2d(c_in, c_out * adj.shape[0], kernel_size=1)
        self.k = adj.shape[0]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        n, _, t, v = x.shape
        y = self.conv(x).view(n, self.k, -1, t, v)
        return torch.einsum("nkctv,kvw->nctw", y, self.adj * self.edge_importance)


class STGCNBlock(nn.Module):
    def __init__(self, c_in: int, c_out: int, adj: torch.Tensor, stride: int = 1, dropout: float = 0.1) -> None:
        super().__init__()
        self.gcn = GraphConv(c_in, c_out, adj)
        self.tcn = nn.Sequential(
            nn.BatchNorm2d(c_out),
            nn.ReLU(inplace=True),
            nn.Conv2d(c_out, c_out, kernel_size=(9, 1), stride=(stride, 1), padding=(4, 0)),
            nn.BatchNorm2d(c_out),
            nn.Dropout(dropout),
        )
        self.residual = (
            nn.Identity() if c_in == c_out and stride == 1 else nn.Sequential(nn.Conv2d(c_in, c_out, 1, stride=(stride, 1)), nn.BatchNorm2d(c_out))
        )
        self.act = nn.ReLU(inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.act(self.tcn(self.gcn(x)) + self.residual(x))


class TwoPersonSTGCN(nn.Module):
    """Small (6-block) ST-GCN, ~0.4 M parameters: runs on the laptop CPU via ONNX/OpenVINO."""

    def __init__(self, in_channels: int = 3, num_persons: int = 2, extra_features: int = 0, widths: tuple[int, ...] = (32, 32, 64, 64, 96, 96)) -> None:
        super().__init__()
        adj = torch.tensor(spatial_partition())
        self.num_persons = num_persons
        self.data_bn = nn.BatchNorm1d(in_channels * V * num_persons)
        layers = []
        c = in_channels
        for i, w in enumerate(widths):
            layers.append(STGCNBlock(c, w, adj, stride=2 if i in (2, 4) else 1))
            c = w
        self.blocks = nn.Sequential(*layers)
        # persons are fused after pooling: rider and pedestrian embeddings are concatenated
        self.head = nn.Sequential(nn.Linear(c * num_persons + extra_features, 64), nn.ReLU(inplace=True), nn.Dropout(0.2), nn.Linear(64, 1))
        self.extra_features = extra_features

    def forward(self, x: torch.Tensor, extra: torch.Tensor | None = None) -> torch.Tensor:
        n, c, t, v, m = x.shape
        x = x.permute(0, 4, 3, 1, 2).reshape(n, m * v * c, t)
        x = self.data_bn(x)
        x = x.view(n, m, v, c, t).permute(0, 1, 3, 4, 2).reshape(n * m, c, t, v)
        x = self.blocks(x)
        x = x.mean(dim=(2, 3)).view(n, m * x.shape[1])
        if self.extra_features:
            assert extra is not None
            x = torch.cat([x, extra], dim=1)
        return self.head(x).squeeze(1)  # logits


class FocalLoss(nn.Module):
    """Binary focal loss (gamma = 2): positives are rare (plan Section 8.2)."""

    def __init__(self, gamma: float = 2.0, alpha: float = 0.25) -> None:
        super().__init__()
        self.gamma = gamma
        self.alpha = alpha

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        p = torch.sigmoid(logits)
        ce = nn.functional.binary_cross_entropy_with_logits(logits, target, reduction="none")
        pt = p * target + (1 - p) * (1 - target)
        w = self.alpha * target + (1 - self.alpha) * (1 - target)
        return (w * (1 - pt) ** self.gamma * ce).mean()
