import json
import sqlite3
from pathlib import Path

import pytest

from crowdsense.config import load_config, parse_config
from crowdsense.evaluate import count_error_metrics, evaluate_db
from crowdsense.simulate import simulate

CFG = str(Path(__file__).resolve().parent.parent / "configs" / "food_court_counter.yaml")


def test_example_config_loads():
    cfg = load_config(CFG)
    assert {z.name for z in cfg.zones} == {"billing_queue", "food_court_floor"}
    assert cfg.queues[0].service_line == "service_line"


def test_config_rejects_missing_area():
    with pytest.raises(ValueError, match="area_m2"):
        parse_config(
            {"site": "x", "frame": {"width": 10, "height": 10}, "zones": [{"name": "a", "polygon": [[0, 0], [1, 0], [1, 1]], "area_m2": 0}]}
        )


def test_simulation_end_to_end(tmp_path):
    cfg = load_config(CFG)
    s = simulate(cfg, str(tmp_path), minutes=60, seed=3, quiet=True)

    assert s["line_totals"]["entrance"]["in_total"] > 50  # people really did arrive
    assert s["queue_served_total"]["billing_queue"] > 20  # and the counter served some of them
    # you cannot serve more people than entered
    assert s["queue_served_total"]["billing_queue"] <= s["line_totals"]["entrance"]["in_total"]
    assert s["peaks"]["peak_est_wait_min:billing_queue"] > 3  # the rush built a visible wait

    db = sqlite3.connect(tmp_path / "metrics.db")
    assert db.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] > 500
    assert (tmp_path / "heatmap.npy").exists()
    assert json.loads((tmp_path / "summary.json").read_text())["site"] == cfg.site


def test_simulation_is_deterministic(tmp_path):
    cfg = load_config(CFG)
    a = simulate(cfg, str(tmp_path / "a"), minutes=20, seed=5, quiet=True)
    b = simulate(cfg, str(tmp_path / "b"), minutes=20, seed=5, quiet=True)
    assert a["line_totals"] == b["line_totals"]


def test_error_metrics():
    m = count_error_metrics([10, 12, 8], [10, 10, 10])
    assert m["mae"] == pytest.approx(4 / 3)
    assert m["bias"] == pytest.approx(0.0)
    assert m["within_1_pct"] == pytest.approx(100 / 3)


def test_evaluate_db_against_ground_truth(tmp_path):
    cfg = load_config(CFG)
    simulate(cfg, str(tmp_path), minutes=15, seed=1, quiet=True)
    db = sqlite3.connect(tmp_path / "metrics.db")
    rows = db.execute("SELECT ts, value FROM metrics WHERE scope='zone:billing_queue' AND metric='occupancy' ORDER BY ts LIMIT 5").fetchall()
    truth = tmp_path / "truth.csv"
    truth.write_text("ts,zone,count\n" + "\n".join(f"{ts},billing_queue,{v}" for ts, v in rows))
    res = evaluate_db(str(tmp_path / "metrics.db"), str(truth))
    assert res["billing_queue"]["mae"] == 0.0  # truth copied from predictions, so error must be zero


def test_video_runner_end_to_end_with_stand_in_detector(tmp_path):
    """Real OpenCV video path, with a stand-in for YOLO that returns known positions."""
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    from crowdsense.runner import analyze_video
    from crowdsense.types import Track

    cfg = load_config(CFG)
    video = str(tmp_path / "walk.mp4")
    vw = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"mp4v"), 10, (cfg.frame_w, cfg.frame_h))
    for _ in range(120):
        vw.write(np.zeros((cfg.frame_h, cfg.frame_w, 3), np.uint8))
    vw.release()

    class Walkers:  # 3 people walking up through the entrance line, one every 10 frames
        def __init__(self):
            self.f = 0

        def track(self, frame):
            f, self.f = self.f, self.f + 1
            return [
                Track(i + 1, (480 + 120 * i - 20, 740 - (f - 10 * i) * 12 - 110, 480 + 120 * i + 20, 740 - (f - 10 * i) * 12))
                for i in range(3)
                if f >= 10 * i
            ]

    s = analyze_video(video, cfg, str(tmp_path / "out"), console=False, detector=Walkers())
    assert s["line_totals"]["entrance"]["in_total"] == 3


def test_setup_overlay_draws_without_error():
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    from crowdsense.overlay import draw_setup

    cfg = load_config(CFG)
    frame = np.full((cfg.frame_h, cfg.frame_w, 3), 50, np.uint8)
    out = draw_setup(frame.copy(), cfg)
    assert out.shape == frame.shape and (out != frame).any()
