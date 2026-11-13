"""Run the full pipeline on a video file, webcam or stream. Shared by the CLI and the web app."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

from .alerts import ConsoleSink, JsonlSink, WebhookSink
from .config import Config
from .pipeline import Pipeline
from .storage import MetricsStore


def analyze_video(
    source: str,
    cfg: Config,
    out_dir: str,
    device: Optional[str] = None,
    stride: int = 1,
    save_video: bool = False,
    show: bool = False,
    console: bool = True,
    progress: Optional[Callable[[float], None]] = None,
    detector=None,
) -> dict:
    """Returns the run summary. `detector` can be injected (used by the tests)."""
    import cv2

    from .overlay import draw

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    db = out / "metrics.db"
    if db.exists():
        db.unlink()  # one run per folder: never mix two analyses in one database
    sinks = [JsonlSink(str(out / "alerts.jsonl"))]
    if console:
        sinks.insert(0, ConsoleSink())
    if cfg.alerts.webhook_url:
        sinks.append(WebhookSink(cfg.alerts.webhook_url, cfg.site))
    pipe = Pipeline(cfg, MetricsStore(str(db)), sinks)
    if detector is None:
        from .detector import PersonTracker

        detector = PersonTracker(cfg.model, cfg.conf, cfg.imgsz, cfg.tracker, device)

    src = int(source) if str(source).isdigit() else source
    live = isinstance(src, int) or str(src).startswith(("rtsp://", "http://", "https://"))
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video source: {source}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    writer = None
    if save_video:
        writer = cv2.VideoWriter(
            str(out / "annotated.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), max(fps / stride, 1.0), (cfg.frame_w, cfg.frame_h)
        )

    t0, idx = time.time(), 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            idx += 1
            if idx % stride:
                continue
            t = (time.time() - t0) if live else idx / fps
            frame = cv2.resize(frame, (cfg.frame_w, cfg.frame_h))
            tracks = detector.track(frame)
            pipe.process(tracks, t)
            if writer or show:
                vis = draw(frame, cfg, pipe, tracks)
                if writer:
                    writer.write(vis)
                if show:
                    cv2.imshow("CrowdSense (q to quit)", vis)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
            if progress and total and idx % 10 == 0:
                progress(min(idx / total, 1.0))
    finally:
        cap.release()
        if writer:
            writer.release()
    if progress:
        progress(1.0)
    return pipe.close(str(out))
