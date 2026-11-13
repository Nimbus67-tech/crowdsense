from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

Point = Tuple[float, float]
Box = Tuple[float, float, float, float]


@dataclass(frozen=True)
class Track:
    """One tracked person in one frame. Anonymous: an integer id, a box, a confidence."""

    id: int
    box: Box  # x1, y1, x2, y2 in the reference frame (pixels)
    conf: float = 1.0

    @property
    def foot(self) -> Point:
        """Bottom-centre of the box: the point where the person touches the floor.

        Zones and lines are floor-plane concepts, so we use the foot point, not the box centre.
        """
        x1, _, x2, y2 = self.box
        return ((x1 + x2) / 2.0, y2)
