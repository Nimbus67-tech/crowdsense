"""Small, dependency-free geometry helpers."""
from __future__ import annotations

from typing import Sequence

from .types import Point


def polygon_area(poly: Sequence[Point]) -> float:
    """Shoelace formula (pixel area, only used for sanity checks)."""
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def point_in_polygon(p: Point, poly: Sequence[Point]) -> bool:
    """Ray casting. Points exactly on an edge may fall either way, which is fine for people."""
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def _orient(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_intersect(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    """True if segment p1-p2 crosses segment q1-q2.

    Uses a half-open convention (a point exactly on the line counts as the 'positive' side)
    so a person standing exactly on a line is never counted twice.
    """
    s1 = _orient(q1, q2, p1) >= 0
    s2 = _orient(q1, q2, p2) >= 0
    if s1 == s2:
        return False
    s3 = _orient(p1, p2, q1) >= 0
    s4 = _orient(p1, p2, q2) >= 0
    return s3 != s4
