"""Synthetic venue simulator.

Generates anonymous people walking through the example food-court layout and feeds them through the
exact same Pipeline the real camera path uses. Two purposes:
  1. Anyone can try CrowdSense and see the dashboard in 30 seconds, with no video, GPU or model.
  2. It is an integration test: if the analytics are wrong, this scenario's numbers stop making sense.

The scenario ties to configs/food_court_counter.yaml: customers arrive through the entrance, ~65% join
the billing queue (one counter), ~35% browse the floor and leave. Arrivals ramp up to a rush and back
down, so you will see the queue build, the wait estimate climb, and alerts fire and clear.
"""
from __future__ import annotations

import math
import random
from pathlib import Path
from typing import List, Optional

from .alerts import ConsoleSink, JsonlSink
from .config import Config
from .pipeline import Pipeline
from .storage import MetricsStore
from .types import Track

SPEED_PX_S = 110.0  # about 1.1 m/s at ~100 px/m


class _Agent:
    def __init__(self, aid: int, x: float, y: float, kind: str):
        self.id, self.x, self.y, self.kind = aid, x, y, kind
        self.target = (x, y)
        self.state = "walking"
        self.timer = 0.0
        self.slot_x = 0.0
        self.fresh = True  # first frame: observed where it spawned, before it moves


def _step_toward(a: _Agent, tx: float, ty: float, dt: float, rng: random.Random) -> bool:
    dx, dy = tx - a.x, ty - a.y
    dist = math.hypot(dx, dy)
    stride = SPEED_PX_S * dt * rng.uniform(0.7, 1.1)
    if dist <= stride:
        a.x, a.y = tx, ty
        return True
    a.x += dx / dist * stride + rng.uniform(-1.5, 1.5)
    a.y += dy / dist * stride
    return False


def simulate(
    cfg: Config,
    out_dir: str,
    minutes: float = 90.0,
    seed: int = 7,
    peak_per_min: float = 7.0,
    service_s: float = 25.0,
    step_s: float = 1.0,
    quiet: bool = False,
    on_step=None,
) -> dict:
    rng = random.Random(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    db = out / "metrics.db"
    if db.exists():
        db.unlink()

    q_cfg = cfg.queues[0]
    qz = next(z for z in cfg.zones if z.name == q_cfg.zone)
    xs, ys = [p[0] for p in qz.polygon], [p[1] for p in qz.polygon]
    qx0, qx1, qy0, qy1 = min(xs), max(xs), min(ys), max(ys)
    floor = next((z for z in cfg.zones if z.name == "food_court_floor"), None)
    fy0 = min(p[1] for p in floor.polygon) if floor else qy1
    entrance = next(l for l in cfg.lines if l.name == "entrance")
    entrance_y = entrance.a[1]
    exit_y = qy0 - 90.0

    sinks = [] if quiet else [ConsoleSink()]
    sinks.append(JsonlSink(str(out / "alerts.jsonl")))
    pipe = Pipeline(cfg, MetricsStore(str(db)), sinks)

    agents: List[_Agent] = []
    queue: List[_Agent] = []
    next_id, steps = 1, int(minutes * 60 / step_s)

    for i in range(steps):
        t = i * step_s
        frac = t / (minutes * 60)
        rate = 1.0 + (peak_per_min - 1.0) * (1.0 - abs(2 * frac - 1.0))  # triangular rush
        if rng.random() < rate * step_s / 60.0:
            kind = "queue" if rng.random() < 0.65 else "browse"
            a = _Agent(next_id, rng.uniform(qx0 - 150, qx1 + 150), entrance_y + 30, kind)
            next_id += 1
            if kind == "queue":
                a.slot_x = rng.uniform(-6, 6)  # personal jitter so the queue is not a perfect grid
                queue.append(a)
            else:
                a.target = (rng.uniform(80, cfg.frame_w - 80), rng.uniform(fy0 + 40, entrance_y - 15))
            agents.append(a)

        for a in list(agents):
            if a.fresh:
                a.fresh = False
                continue
            if a.kind == "browse":
                if a.state == "walking" and _step_toward(a, *a.target, step_s, rng):
                    a.state, a.timer = "dwelling", rng.uniform(20, 150)
                elif a.state == "dwelling":
                    a.timer -= step_s
                    if a.timer <= 0:
                        a.state = "leaving"
                elif a.state == "leaving":
                    if a.y > entrance_y + 25:  # already observed beyond the line last frame
                        agents.remove(a)
                        continue
                    _step_toward(a, a.x, entrance_y + 40, step_s, rng)
            else:
                if a.state == "leaving":
                    if a.y <= exit_y + 2:  # already observed beyond the service line last frame
                        agents.remove(a)
                        continue
                    _step_toward(a, a.x, exit_y, step_s, rng)
                    continue
                idx = queue.index(a)
                row, col = divmod(idx, 8)  # people queue in rows of up to 8, front row nearest the counter
                slot_x = qx0 + 40 + col * (qx1 - qx0 - 80) / 7 + a.slot_x
                slot_y = min(qy0 + 25 + 45 * row, qy1 - 10)
                arrived = _step_toward(a, slot_x, slot_y, step_s, rng)
                if idx == 0 and arrived:
                    if a.state != "serving":
                        a.state, a.timer = "serving", rng.lognormvariate(math.log(service_s), 0.35)
                    a.timer -= step_s
                    if a.timer <= 0:
                        queue.remove(a)
                        a.state = "leaving"

        tracks = [Track(a.id, (a.x - 20, a.y - 110, a.x + 20, a.y), 0.9) for a in agents]
        pipe.process(tracks, t)
        if on_step:
            on_step(i, t, tracks, pipe)

    return pipe.close(str(out))
