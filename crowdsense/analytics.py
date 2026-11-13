"""The metrics engine. Pure Python + numpy: no camera, no model, fully unit-testable.

Everything here answers a question a human operator actually has:
  * How crowded is it, and is that dangerous?          -> ZoneAnalyzer  (density, level of service)
  * How many people came in / went out?                -> LineCounter   (footfall)
  * How long do people stay?                           -> ZoneAnalyzer  (dwell time)
  * How long will the person joining the queue wait?   -> QueueMonitor  (Little's Law)
  * Where do people actually walk?                     -> Heatmap
"""
from __future__ import annotations

import math
from collections import deque
from statistics import mean, median
from typing import Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .config import LOS_LETTERS
from .geometry import point_in_polygon, segments_intersect
from .types import Point, Track

# Level of Service for standing / queuing areas, after Fruin (1971).
# Lower bound of "area per person" (m^2) for each level. These are widely used planning
# thresholds, but they are conventions, not physics: adapt them to your venue and local code.
_LOS_MIN_AREA = [(1.2, "A"), (0.9, "B"), (0.65, "C"), (0.3, "D"), (0.2, "E")]


def level_of_service(area_per_person_m2: Optional[float]) -> str:
    """A = free movement ... F = breakdown. Below ~0.2 m^2/person (about 5 people per m^2)
    movement is dominated by the crowd, the regime in which crowd-crush injuries occur."""
    if area_per_person_m2 is None:  # empty zone
        return "A"
    for lower, letter in _LOS_MIN_AREA:
        if area_per_person_m2 >= lower:
            return letter
    return "F"


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    k = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return float(sorted_vals[int(k)])
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo))


class LineCounter:
    """Counts people crossing a virtual tripwire, with direction.

    A crossing is "in" if the person's movement points along `in_direction`
    (dot product > 0), otherwise "out".
    """

    def __init__(self, name: str, a: Point, b: Point, in_direction: Point, forget_s: float = 10.0):
        self.name, self.a, self.b, self.in_dir = name, a, b, in_direction
        self.n_in = 0
        self.n_out = 0
        self._prev: Dict[int, Point] = {}
        self._seen: Dict[int, float] = {}
        self._forget_s = forget_s

    def update(self, tracks: Sequence[Track], t: float) -> List[Tuple[int, str, float]]:
        events: List[Tuple[int, str, float]] = []
        for tr in tracks:
            cur = tr.foot
            prev = self._prev.get(tr.id)
            if prev is not None and segments_intersect(prev, cur, self.a, self.b):
                move = (cur[0] - prev[0], cur[1] - prev[1])
                d = move[0] * self.in_dir[0] + move[1] * self.in_dir[1]
                if d > 0:
                    self.n_in += 1
                    events.append((tr.id, "in", t))
                elif d < 0:
                    self.n_out += 1
                    events.append((tr.id, "out", t))
            self._prev[tr.id] = cur
            self._seen[tr.id] = t
        for tid in [k for k, ts in self._seen.items() if t - ts > self._forget_s]:
            self._prev.pop(tid, None)
            self._seen.pop(tid, None)
        return events


class ZoneAnalyzer:
    """Occupancy, density, level of service and dwell time for one area of the floor."""

    def __init__(
        self,
        name: str,
        polygon: Sequence[Point],
        area_m2: float,
        lost_grace_s: float = 2.0,
        min_dwell_s: float = 1.0,
        history: int = 2000,
    ):
        self.name, self.polygon, self.area_m2 = name, list(polygon), area_m2
        self.lost_grace_s, self.min_dwell_s = lost_grace_s, min_dwell_s
        self.occupancy = 0
        self._entered: Dict[int, float] = {}
        self._last_in: Dict[int, float] = {}
        self.dwell_times: Deque[float] = deque(maxlen=history)
        self._now = 0.0

    def update(self, tracks: Sequence[Track], t: float) -> int:
        self._now = t
        inside = {tr.id for tr in tracks if point_in_polygon(tr.foot, self.polygon)}
        for tid in inside:
            self._entered.setdefault(tid, t)
            self._last_in[tid] = t
        # A track that has been gone longer than the grace period has left (or the tracker lost it).
        for tid in [k for k in self._entered if k not in inside]:
            if t - self._last_in[tid] > self.lost_grace_s:
                dwell = self._last_in[tid] - self._entered[tid]
                if dwell >= self.min_dwell_s:
                    self.dwell_times.append(dwell)
                del self._entered[tid]
                del self._last_in[tid]
        self.occupancy = len(inside)
        return self.occupancy

    @property
    def density_pm2(self) -> float:
        return self.occupancy / self.area_m2

    @property
    def area_per_person_m2(self) -> Optional[float]:
        return None if self.occupancy == 0 else self.area_m2 / self.occupancy

    @property
    def los(self) -> str:
        return level_of_service(self.area_per_person_m2)

    def longest_current_dwell_s(self) -> float:
        return max((self._now - e for e in self._entered.values()), default=0.0)

    def snapshot(self) -> dict:
        d = sorted(self.dwell_times)
        enough = len(d) >= 3  # do not report statistics from one or two people
        return {
            "occupancy": self.occupancy,
            "density_pm2": round(self.density_pm2, 3),
            "area_per_person_m2": None if self.area_per_person_m2 is None else round(self.area_per_person_m2, 3),
            "los": self.los,
            "los_index": LOS_LETTERS.index(self.los),
            "dwell_mean_s": round(mean(d), 1) if enough else None,
            "dwell_p90_s": round(_percentile(d, 0.9), 1) if enough else None,
            "longest_current_dwell_s": round(self.longest_current_dwell_s(), 1),
        }


class QueueMonitor:
    """Estimates how long a person joining the queue right now will wait.

    Little's Law: average wait W = L / lambda, where L is people in the queue and lambda is the
    rate at which people are served. L comes from the queue zone (median-smoothed so one missed
    detection cannot swing it). lambda is measured, not assumed: the number of people who crossed
    the service line within the last `window_s`.

    Caveat (documented in the README): Little's Law assumes a roughly steady state. During a sudden
    surge the estimate lags, so it is best read as a trend plus a reasonable estimate.
    """

    def __init__(
        self, zone: ZoneAnalyzer, window_s: float = 300.0, stall_s: float = 120.0, smooth_n: int = 9, min_served: int = 3
    ):
        self.zone, self.window_s, self.stall_s = zone, window_s, stall_s
        self.min_served = min_served  # a rate from 1-2 people is noise, so report "unknown" instead
        self._served: Deque[float] = deque()
        self._lengths: Deque[int] = deque(maxlen=smooth_n)
        self.served_total = 0
        self._t0: Optional[float] = None
        self._last_served_t: Optional[float] = None
        self._queue_nonempty_since: Optional[float] = None
        self._now = 0.0

    def update(self, t: float, served_now: int) -> None:
        if self._t0 is None:
            self._t0 = t
        for _ in range(served_now):
            self._served.append(t)
            self.served_total += 1
            self._last_served_t = t
        while self._served and t - self._served[0] > self.window_s:
            self._served.popleft()
        self._lengths.append(self.zone.occupancy)
        if self.length_smooth >= 3:
            if self._queue_nonempty_since is None:
                self._queue_nonempty_since = t
        else:
            self._queue_nonempty_since = None
        self._now = t

    @property
    def length_smooth(self) -> float:
        return float(median(self._lengths)) if self._lengths else 0.0

    def throughput_per_min(self) -> Optional[float]:
        if self._t0 is None:
            return None
        elapsed = self._now - self._t0
        if elapsed < 60.0 or len(self._served) < self.min_served:  # too little data to measure a rate
            return None
        span_min = min(self.window_s, elapsed) / 60.0
        return len(self._served) / span_min

    def est_wait_min(self) -> Optional[float]:
        L = self.length_smooth
        if L < 1:
            return 0.0
        lam = self.throughput_per_min()
        if not lam:  # None (warming up) or 0 (nobody served)
            return None
        return L / lam

    def stalled(self) -> bool:
        """People are waiting, but nobody has been served for `stall_s`: counter closed, POS down, staff away."""
        if self._queue_nonempty_since is None:
            return False
        since_wait = self._now - self._queue_nonempty_since
        since_served = self._now - (self._last_served_t if self._last_served_t is not None else self._t0)
        return since_wait >= self.stall_s and since_served >= self.stall_s

    def snapshot(self) -> dict:
        w = self.est_wait_min()
        tp = self.throughput_per_min()
        return {
            "length": self.zone.occupancy,
            "length_smooth": self.length_smooth,
            "throughput_per_min": None if tp is None else round(tp, 2),
            "est_wait_min": None if w is None else round(w, 1),
            "stalled": 1.0 if self.stalled() else 0.0,
            "served_total": self.served_total,
        }


class Heatmap:
    """Where do people actually stand and walk? Accumulated on a coarse grid."""

    def __init__(self, width: int, height: int, cell: int = 20):
        self.cell = cell
        self.grid = np.zeros((height // cell + 1, width // cell + 1), dtype=np.float32)

    def add(self, tracks: Sequence[Track]) -> None:
        h, w = self.grid.shape
        for tr in tracks:
            x, y = tr.foot
            ix, iy = int(x // self.cell), int(y // self.cell)
            if 0 <= ix < w and 0 <= iy < h:
                self.grid[iy, ix] += 1.0

    def normalized(self) -> np.ndarray:
        m = float(self.grid.max())
        return self.grid / m if m > 0 else self.grid
