"""Capture README screenshots of the real web app.   pip install playwright && playwright install chromium"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets"
PORT = 8599

# The "Analyze a video" tab shows a "install the vision extras" notice on machines without YOLO.
# To screenshot its READY state without installing PyTorch, we launch the app with an empty stub
# `ultralytics` package on the path. The screenshot never clicks Analyze, so no analysis is faked.
stub = Path(tempfile.mkdtemp()) / "ultralytics"
stub.mkdir()
(stub / "__init__.py").write_text("")
env = dict(os.environ, PYTHONPATH=str(stub.parent) + os.pathsep + os.environ.get("PYTHONPATH", ""))

sample = Path(tempfile.mkdtemp()) / "food_court_cam1.mp4"  # a tiny clip to enable the Analyze button
vw = cv2.VideoWriter(str(sample), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 180))
for _ in range(10):
    vw.write(np.full((180, 320, 3), 60, np.uint8))
vw.release()

proc = subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run", str(ROOT / "crowdsense" / "dashboard.py"),
     "--server.port", str(PORT), "--server.headless", "true", "--browser.gatherUsageStats", "false"],
    cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
try:
    time.sleep(6)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 1500}, device_scale_factor=1.25)
        pg.goto(f"http://localhost:{PORT}")
        pg.wait_for_selector("text=What to do", timeout=60000)
        time.sleep(3)
        pg.screenshot(path=str(OUT / "ui_overview.png"))

        def tab(name, shot, wait=2.5, clip_h=None):
            pg.get_by_role("tab", name=name).click()
            time.sleep(wait)
            pg.screenshot(path=str(OUT / shot))

        tab("Alerts & actions", "ui_alerts.png")
        tab("Heatmap", "ui_heatmap.png", wait=4)
        pg.get_by_role("tab", name="Zone setup").click()
        time.sleep(1.5)
        pg.locator("input[type=file]").nth(1).set_input_files(str(OUT / "sample_frame.jpg"))
        time.sleep(4)
        pg.screenshot(path=str(OUT / "ui_setup.png"))
        pg.get_by_role("tab", name="Analyze a video").click()
        time.sleep(1.5)
        pg.locator("input[type=file]").nth(0).set_input_files(str(sample))
        time.sleep(3)
        pg.screenshot(path=str(OUT / "ui_video.png"))
        b.close()
finally:
    proc.terminate()
for f in OUT.glob("ui_*.png"):  # trim empty space at the bottom (ignoring the sidebar)
    im = Image.open(f).convert("RGB")
    main = im.crop((int(im.width * 0.27), 0, im.width, im.height))
    bbox = ImageChops.difference(main, Image.new("RGB", main.size, (248, 250, 252))).getbbox()
    if bbox:
        im.crop((0, 0, im.width, min(im.height, bbox[3] + 40))).save(f, optimize=True)
print("done")
