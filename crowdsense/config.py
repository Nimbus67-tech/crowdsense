"""Configuration: one YAML file describes one camera and the places we care about in its view."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .types import Point

LOS_LETTERS = "ABCDEF"


@dataclass
class ZoneCfg:
    name: str
    polygon: List[Point]
    area_m2: float  # real-world floor area. Measure it with a tape; this is what makes density meaningful.
    capacity: Optional[int] = None  # optional safe maximum number of people


@dataclass
class LineCfg:
    name: str
    a: Point
    b: Point
    in_direction: Point  # image-space direction that counts as "in", e.g. [0, -1] = moving up the image


@dataclass
class QueueCfg:
    zone: str  # zone where people wait
    service_line: str  # line people cross when they reach the counter (its "in" direction = served)
    window_s: float = 300.0  # window for measuring service throughput
    stall_s: float = 120.0  # queue with nobody served for this long is flagged "stalled"


@dataclass
class AlertCfg:
    density_warn_los: str = "E"
    density_critical_los: str = "F"
    wait_warn_min: float = 10.0
    wait_critical_min: float = 20.0
    capacity_warn_ratio: float = 0.8
    sustain_s: float = 10.0  # a condition must hold this long before we alert (kills one-frame spikes)
    clear_s: float = 30.0  # and be gone this long before we say "resolved" (kills flapping)
    webhook_url: Optional[str] = None


@dataclass
class Config:
    site: str
    camera: str
    frame_w: int
    frame_h: int
    zones: List[ZoneCfg]
    lines: List[LineCfg] = field(default_factory=list)
    queues: List[QueueCfg] = field(default_factory=list)
    alerts: AlertCfg = field(default_factory=AlertCfg)
    model: str = "yolov8n.pt"
    conf: float = 0.35
    imgsz: int = 960
    tracker: str = "bytetrack.yaml"
    snapshot_interval_s: float = 5.0


def _pt(p) -> Point:
    if len(p) != 2:
        raise ValueError(f"point must have 2 numbers, got {p!r}")
    return (float(p[0]), float(p[1]))


def parse_config(d: dict) -> Config:
    try:
        zones = [
            ZoneCfg(
                name=z["name"],
                polygon=[_pt(p) for p in z["polygon"]],
                area_m2=float(z["area_m2"]),
                capacity=z.get("capacity"),
            )
            for z in d["zones"]
        ]
        lines = [
            LineCfg(
                name=l["name"], a=_pt(l["a"]), b=_pt(l["b"]), in_direction=_pt(l["in_direction"])
            )
            for l in d.get("lines", [])
        ]
        queues = [QueueCfg(**q) for q in d.get("queues", [])]
        alerts = AlertCfg(**d.get("alerts", {}))
        frame = d["frame"]
        cfg = Config(
            site=d["site"],
            camera=d.get("camera", "cam-1"),
            frame_w=int(frame["width"]),
            frame_h=int(frame["height"]),
            zones=zones,
            lines=lines,
            queues=queues,
            alerts=alerts,
            model=d.get("model", "yolov8n.pt"),
            conf=float(d.get("conf", 0.35)),
            imgsz=int(d.get("imgsz", 960)),
            tracker=d.get("tracker", "bytetrack.yaml"),
            snapshot_interval_s=float(d.get("snapshot_interval_s", 5.0)),
        )
    except KeyError as e:
        raise ValueError(f"missing required config key: {e}") from e
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    names = [z.name for z in cfg.zones]
    if len(set(names)) != len(names):
        raise ValueError("zone names must be unique")
    for z in cfg.zones:
        if len(z.polygon) < 3:
            raise ValueError(f"zone '{z.name}' needs at least 3 polygon points")
        if z.area_m2 <= 0:
            raise ValueError(f"zone '{z.name}' needs area_m2 > 0 (real floor area in square metres)")
    line_names = {l.name for l in cfg.lines}
    for q in cfg.queues:
        if q.zone not in names:
            raise ValueError(f"queue zone '{q.zone}' is not defined in zones")
        if q.service_line not in line_names:
            raise ValueError(f"queue service_line '{q.service_line}' is not defined in lines")
    for lv in (cfg.alerts.density_warn_los, cfg.alerts.density_critical_los):
        if lv not in LOS_LETTERS:
            raise ValueError(f"LOS must be one of {LOS_LETTERS}, got {lv!r}")


def load_config(path: str) -> Config:
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        return parse_config(yaml.safe_load(f))
