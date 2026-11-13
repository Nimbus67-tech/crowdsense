"""Draw zones, lines, people and a status panel on a frame (OpenCV)."""
from __future__ import annotations

from typing import Sequence

from .config import Config
from .pipeline import Pipeline
from .types import Track

# BGR colours: green = fine ... red = dangerous
_LOS_COLOUR = {"A": (80, 200, 80), "B": (80, 200, 80), "C": (60, 200, 220), "D": (40, 160, 255), "E": (40, 80, 255), "F": (30, 30, 230)}


def draw(frame, cfg: Config, pipe: Pipeline, tracks: Sequence[Track]):
    import cv2
    import numpy as np

    snap = pipe.last_snapshot
    overlay = frame.copy()
    for z in cfg.zones:
        los = snap["zones"][z.name]["los"] if snap else "A"
        pts = np.array(z.polygon, dtype=np.int32)
        cv2.fillPoly(overlay, [pts], _LOS_COLOUR[los])
        cv2.polylines(frame, [pts], True, _LOS_COLOUR[los], 2)
        cv2.putText(frame, z.name, (int(z.polygon[0][0]) + 6, int(z.polygon[0][1]) + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    frame = cv2.addWeighted(overlay, 0.18, frame, 0.82, 0)

    for l in cfg.lines:
        cv2.line(frame, tuple(map(int, l.a)), tuple(map(int, l.b)), (255, 200, 0), 2)
    for tr in tracks:
        x1, y1, x2, y2 = map(int, tr.box)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 214, 120), 2)
        cv2.circle(frame, tuple(map(int, tr.foot)), 3, (0, 255, 255), -1)

    # status panel
    lines = [f"{cfg.site}  |  {len(tracks)} people in view"]
    if snap:
        for n, m in snap["zones"].items():
            lines.append(f"{n}: {m['occupancy']} ppl  {m['density_pm2']:.1f}/m2  LOS {m['los']}")
        for n, q in snap["queues"].items():
            w = q["est_wait_min"]
            lines.append(f"queue wait: {'--' if w is None else f'{w:.0f} min'}   served: {q['served_total']}")
        for n, l in snap["lines"].items():
            lines.append(f"{n}: in {l['in_total']}  out {l['out_total']}")
    for a in pipe.active_alerts.values():
        lines.append(f"! {a.level}: {a.scope} - {a.rule}")
    h = 26 * len(lines) + 12
    x0 = frame.shape[1] - 512  # top-right, so it never hides the zone labels
    cv2.rectangle(frame, (x0, 8), (frame.shape[1] - 8, 8 + h), (20, 20, 20), -1)
    for i, text in enumerate(lines):
        colour = (80, 80, 255) if text.startswith("!") else (255, 255, 255)
        cv2.putText(frame, text, (x0 + 8, 32 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 1, cv2.LINE_AA)
    return frame


def draw_setup(frame, cfg: Config, grid: int = 100):
    """Zone-setup helper: shows a pixel grid, every zone (with its real area) and an arrow for each
    line's "in" direction, so you can check your YAML against a real camera frame before running."""
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    for x in range(0, w, grid):
        cv2.line(frame, (x, 0), (x, h), (255, 255, 255), 1)
        cv2.putText(frame, str(x), (x + 3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
    for y in range(0, h, grid):
        cv2.line(frame, (0, y), (w, y), (255, 255, 255), 1)
        cv2.putText(frame, str(y), (3, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
    overlay = frame.copy()
    palette = [(80, 200, 80), (255, 160, 60), (200, 100, 255), (60, 200, 220)]
    for i, z in enumerate(cfg.zones):
        c = palette[i % len(palette)]
        pts = np.array(z.polygon, dtype=np.int32)
        cv2.fillPoly(overlay, [pts], c)
        cv2.polylines(frame, [pts], True, c, 3)
        label = f"{z.name}  ({z.area_m2:g} m2)"
        cv2.putText(frame, label, (int(z.polygon[0][0]) + 8, int(z.polygon[0][1]) + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    frame = cv2.addWeighted(overlay, 0.22, frame, 0.78, 0)
    for l in cfg.lines:
        a, b = tuple(map(int, l.a)), tuple(map(int, l.b))
        cv2.line(frame, a, b, (0, 215, 255), 3)
        mid = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
        dx, dy = l.in_direction
        n = (dx * dx + dy * dy) ** 0.5 or 1.0
        tip = (int(mid[0] + dx / n * 70), int(mid[1] + dy / n * 70))
        cv2.arrowedLine(frame, mid, tip, (0, 215, 255), 4, tipLength=0.35)
        cv2.putText(frame, f"{l.name}: IN", (mid[0] + 10, mid[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 215, 255), 2, cv2.LINE_AA)
    return frame
