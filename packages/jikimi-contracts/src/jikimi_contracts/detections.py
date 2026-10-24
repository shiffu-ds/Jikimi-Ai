"""Per-frame perception contracts: detections, tracks and poses.

Coordinates are always *normalized* to the frame (0..1, x right, y down) so that edge, server
and dashboard never disagree about resolution.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

Unit = Annotated[float, Field(ge=0.0, le=1.0)]
BBox = tuple[float, float, float, float]
"""Normalized ``(x1, y1, x2, y2)``."""


class ObjectClass(StrEnum):
    """Canonical object classes (PakRoads, Section 9.2) plus the COCO ones we reuse."""

    PERSON = "person"
    MOTORCYCLE = "motorcycle"
    BICYCLE = "bicycle"
    CAR = "car"
    VAN = "van"
    BUS = "bus"
    TRUCK = "truck"
    RICKSHAW = "rickshaw"
    QINGQI = "qingqi"
    LOADER_RICKSHAW = "loader_rickshaw"
    DONKEY_CART = "donkey_cart"
    HELMET = "helmet"
    NO_HELMET = "no_helmet"


VEHICLE_CLASSES: frozenset[str] = frozenset(
    {
        ObjectClass.MOTORCYCLE,
        ObjectClass.BICYCLE,
        ObjectClass.CAR,
        ObjectClass.VAN,
        ObjectClass.BUS,
        ObjectClass.TRUCK,
        ObjectClass.RICKSHAW,
        ObjectClass.QINGQI,
        ObjectClass.LOADER_RICKSHAW,
        ObjectClass.DONKEY_CART,
    }
)
TWO_WHEELERS: frozenset[str] = frozenset({ObjectClass.MOTORCYCLE, ObjectClass.BICYCLE})

# COCO class index -> canonical class (YOLO COCO checkpoints, baseline B0)
COCO_TO_JIKIMI: dict[int, str] = {
    0: ObjectClass.PERSON,
    1: ObjectClass.BICYCLE,
    2: ObjectClass.CAR,
    3: ObjectClass.MOTORCYCLE,
    5: ObjectClass.BUS,
    7: ObjectClass.TRUCK,
}

# COCO-17 keypoint layout used by YOLO-Pose and the ST-GCN input tensor (Section 8.2)
KEYPOINT_NAMES: tuple[str, ...] = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)
NUM_KEYPOINTS = len(KEYPOINT_NAMES)
KP = {name: i for i, name in enumerate(KEYPOINT_NAMES)}
# Left/right pairs swapped by horizontal-flip augmentation
FLIP_PAIRS: tuple[tuple[int, int], ...] = ((1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12), (13, 14), (15, 16))
HEAD_KEYPOINTS: tuple[int, ...] = (0, 1, 2, 3, 4)


class Detection(BaseModel):
    """One detector output, before or after tracking."""

    track_id: int | None = None
    cls: str
    conf: Unit
    bbox: BBox


class Pose(BaseModel):
    """COCO-17 pose of one tracked person; each keypoint is ``(x, y, conf)`` normalized."""

    track_id: int
    keypoints: list[tuple[float, float, float]]

    @field_validator("keypoints")
    @classmethod
    def _seventeen(cls, v: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
        if len(v) != NUM_KEYPOINTS:
            raise ValueError(f"expected {NUM_KEYPOINTS} keypoints, got {len(v)}")
        return v


class Track(BaseModel):
    """A tracked object at one instant.

    ``entity_id`` links re-entries of the *same* object (appearance re-ID). It is an anonymous
    session identifier: never a name, never a face template (ADR-003).
    """

    track_id: int
    cls: str
    conf: Unit
    bbox: BBox
    velocity: tuple[float, float] = (0.0, 0.0)
    first_seen: float
    last_seen: float
    entity_id: str | None = None
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @property
    def foot(self) -> tuple[float, float]:
        """Bottom-centre point: where the object touches the ground (used for zones)."""
        x1, _, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, y2)

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def speed(self) -> float:
        vx, vy = self.velocity
        return float((vx * vx + vy * vy) ** 0.5)
