from __future__ import annotations

import argparse
import json

from .config import load_config


def _cmd_run(a) -> None:
    from .runner import analyze_video

    cfg = load_config(a.config)
    try:
        summary = analyze_video(a.source, cfg, a.out, device=a.device, stride=a.stride, save_video=a.save_video, show=a.show)
    except RuntimeError as e:
        raise SystemExit(str(e))
    print(json.dumps(summary, indent=2))
    print(f"\nResults in {a.out}/ . View them with:\n  python -m crowdsense app --db {a.out}/metrics.db")


def _cmd_app(a) -> None:
    import subprocess
    import sys
    from pathlib import Path

    cmd = [sys.executable, "-m", "streamlit", "run", str(Path(__file__).with_name("dashboard.py"))]
    if a.db:
        cmd += ["--", "--db", a.db]
    raise SystemExit(subprocess.call(cmd))


def _cmd_simulate(a) -> None:
    from .simulate import simulate

    cfg = load_config(a.config)
    summary = simulate(cfg, a.out, minutes=a.minutes, seed=a.seed, peak_per_min=a.peak, quiet=a.quiet)
    print("\n" + json.dumps(summary, indent=2))
    print(f"\nOpen the web app:\n  python -m crowdsense app --db {a.out}/metrics.db")


def _cmd_evaluate(a) -> None:
    from .evaluate import evaluate_db

    res = evaluate_db(a.db, a.truth, a.tolerance)
    if not res:
        raise SystemExit("No ground-truth rows matched any snapshot. Check zone names and timestamps.")
    for zone, m in res.items():
        print(f"\nZone: {zone}  (n={int(m['n'])})")
        for k in ("mae", "rmse", "bias", "mape_pct", "within_1_pct", "within_10pct_pct"):
            print(f"  {k:<18}{m[k]:8.2f}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="crowdsense", description="Crowd-crush and queue-delay early warning from CCTV.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="analyse a video file, webcam index, or RTSP stream")
    r.add_argument("--source", required=True)
    r.add_argument("--config", required=True)
    r.add_argument("--out", default="runs/latest")
    r.add_argument("--device", default=None, help="e.g. cpu, 0, mps")
    r.add_argument("--stride", type=int, default=1, help="process every Nth frame")
    r.add_argument("--show", action="store_true")
    r.add_argument("--save-video", action="store_true")
    r.set_defaults(fn=_cmd_run)

    w = sub.add_parser("app", help="open the web app (dashboard, video upload, zone setup)")
    w.add_argument("--db", default=None, help="open a specific metrics.db instead of the demo")
    w.set_defaults(fn=_cmd_app)

    s = sub.add_parser("simulate", help="run the full pipeline on a synthetic venue (no video needed)")
    s.add_argument("--config", default="configs/food_court_counter.yaml")
    s.add_argument("--out", default="runs/demo")
    s.add_argument("--minutes", type=float, default=90)
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--peak", type=float, default=7.0, help="peak arrivals per minute")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(fn=_cmd_simulate)

    e = sub.add_parser("evaluate", help="compare counts with human-counted ground truth")
    e.add_argument("--db", required=True)
    e.add_argument("--truth", required=True)
    e.add_argument("--tolerance", type=float, default=5.0)
    e.set_defaults(fn=_cmd_evaluate)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
