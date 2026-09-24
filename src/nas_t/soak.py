"""Steady-state ("soak") detection for a temperature series.

Soak means the least-squares trend over the last ``window_min`` minutes is no more than
``max_rise`` degrees per window, on ``confirm`` consecutive checks, after at least
``min_load_min`` minutes of load. A trend fit rather than first/last comparison keeps
1 C sensor quantisation from triggering or blocking it.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


def rise_per_window(points: list[tuple[datetime, float]], window_min: float) -> Optional[float]:
    """Least-squares slope of the points, scaled to degrees per ``window_min`` minutes."""
    if len(points) < 2:
        return None
    t0 = points[0][0]
    xs = [(t - t0).total_seconds() / 60 for t, _ in points]
    ys = [v for _, v in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den * window_min


@dataclass
class SoakDetector:
    load_start: datetime
    max_rise: float = 0.5
    window_min: float = 10.0
    min_load_min: float = 20.0
    confirm: int = 2
    min_points: int = 10
    hits: int = field(default=0, init=False)
    last_rise: Optional[float] = field(default=None, init=False)

    def check(self, points: list[tuple[datetime, float]], now: datetime) -> bool:
        """Feeds the full series seen so far; True once soak is confirmed."""
        if (now - self.load_start).total_seconds() / 60 < self.min_load_min:
            return False
        since = now - timedelta(minutes=self.window_min)
        window = [p for p in points if p[0] >= since and p[0] >= self.load_start]
        if len(window) < self.min_points:
            return False
        self.last_rise = rise_per_window(window, self.window_min)
        if self.last_rise is not None and self.last_rise <= self.max_rise:
            self.hits += 1
        else:
            self.hits = 0
        return self.hits >= self.confirm
