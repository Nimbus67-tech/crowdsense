"""Render camera-style frames and an animated GIF from the simulated venue.

These are SIMULATED scenes (stick-figure people on a dark floor), drawn through CrowdSense's real
overlay code, so they show exactly what the live view looks like on a real camera.
    python scripts/render_scene.py
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crowdsense.config import load_config  # noqa: E402
from crowdsense.overlay import draw  # noqa: E402
from crowdsense.simulate import simulate  # noqa: E402

cfg = load_config(str(ROOT / "configs" / "food_court_counter.yaml"))
OUT = ROOT / "docs" / "assets"
OUT.mkdir(parents=True, exist_ok=True)


def background():
    img = np.full((cfg.frame_h, cfg.frame_w, 3), (58, 52, 48), np.uint8)
    for x in range(0, cfg.frame_w, 80):  # floor tiles
        cv2.line(img, (x, 0), (x, cfg.frame_h), (66, 60, 56), 1)
    for y in range(0, cfg.frame_h, 80):
        cv2.line(img, (0, y), (cfg.frame_w, y), (66, 60, 56), 1)
    cv2.rectangle(img, (380, 60), (820, 140), (40, 36, 34), -1)  # billing counter
    cv2.rectangle(img, (380, 60), (820, 140), (120, 110, 100), 2)
    cv2.putText(img, "BILLING COUNTER", (530, 108), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (170, 160, 150), 2, cv2.LINE_AA)
    cv2.putText(img, "ENTRANCE", (560, 712), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 140, 130), 2, cv2.LINE_AA)
    return img


BG = background()
PALETTE = [(180, 120, 60), (90, 150, 200), (110, 170, 110), (140, 110, 190), (80, 130, 210), (170, 170, 90)]


def person_glyph(img, tr):
    x1, y1, x2, y2 = map(int, tr.box)
    cx, col = (x1 + x2) // 2, PALETTE[tr.id % len(PALETTE)]
    cv2.ellipse(img, (cx, y2 - 38), (15, 34), 0, 0, 360, col, -1)  # body
    cv2.circle(img, (cx, y1 + 22), 12, (205, 190, 175), -1)  # head
    cv2.ellipse(img, (cx, y2 - 2), (14, 5), 0, 0, 360, (30, 28, 26), -1)  # shadow


def frame_for(tracks, pipe):
    img = BG.copy()
    for tr in sorted(tracks, key=lambda t: t.box[3]):
        person_glyph(img, tr)
    return draw(img, cfg, pipe, tracks)


gif, stills = [], {}
WANT = {"calm": 14 * 60, "busy": 52 * 60, "peak": 62 * 60, "clean": 40 * 60}


def on_step(i, t, tracks, pipe):
    for name, when in WANT.items():
        if abs(t - when) < 0.5 and name not in stills:
            if name == "clean":  # people only, no overlay: used to demo the zone-setup helper
                img = BG.copy()
                for tr in sorted(tracks, key=lambda t: t.box[3]):
                    person_glyph(img, tr)
                stills[name] = img
            else:
                stills[name] = frame_for(tracks, pipe)
    if 30 * 60 <= t <= 78 * 60 and int(t) % 30 == 0 and pipe.last_snapshot:
        small = cv2.resize(frame_for(tracks, pipe), (800, 450), interpolation=cv2.INTER_AREA)
        gif.append(Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB)))


simulate(cfg, str(ROOT / "runs" / "demo"), quiet=True, on_step=on_step)
for name, fr in stills.items():
    cv2.imwrite(str(OUT / ("sample_frame.jpg" if name == "clean" else f"scene_{name}.jpg")), fr, [cv2.IMWRITE_JPEG_QUALITY, 90])
pal = [im.convert("P", palette=Image.ADAPTIVE, colors=128) for im in gif]
pal[0].save(OUT / "demo.gif", save_all=True, append_images=pal[1:], duration=110, loop=0, optimize=True)
print("stills:", list(stills), "| gif frames:", len(gif))
