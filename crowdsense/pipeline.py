"""Glue: tracks in -> metrics, alerts and storage out. No video or model code lives here."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .alerts import Alert, AlertEngine
from .analytics import Heatmap, LineCounter, QueueMonitor, ZoneAnalyzer
from .config import Config
from .storage import MetricsStore
from .types import Track


class Pipeline:
    def __init__(self, cfg: Config, store: Optional[MetricsStore] = None, sinks: Sequence = ()):
        self.cfg, self.store, self.sinks = cfg, store, list(sinks)
        self.zones: Dict[str, ZoneAnalyzer] = {
            z.name: ZoneAnalyzer(z.name, z.polygon, z.area_m2) for z in cfg.zones
        }
        self.lines: Dict[str, LineCounter] = {
            l.name: LineCounter(l.name, l.a, l.b, l.in_direction) for l in cfg.lines
        }
        self.queues: Dict[str, QueueMonitor] = {
            q.zone: QueueMonitor(self.zones[q.zone], q.window_s, q.stall_s) for q in cfg.queues
        }
        self._service_line = {q.zone: q.service_line for q in cfg.queues}
        self.heatmap = Heatmap(cfg.frame_w, cfg.frame_h)
        self.alert_engine = AlertEngine(cfg.alerts, cfg.zones)
        self.last_snapshot: Optional[dict] = None
        self.active_alerts: Dict[Tuple[str, str], Alert] = {}
        self._t0: Optional[float] = None
        self._next = 0.0
        self._peaks: Dict[str, float] = {}
        self.alert_log: List[Alert] = []

    def process(self, tracks: Sequence[Track], t: float) -> Tuple[Optional[dict], List[Alert]]:
        if self._t0 is None:
            self._t0, self._next = t, t
        crossings = {name: line.update(tracks, t) for name, line in self.lines.items()}
        for z in self.zones.values():
            z.update(tracks, t)
        for zone, q in self.queues.items():
            served = sum(1 for _, direction, _ in crossings[self._service_line[zone]] if direction == "in")
            q.update(t, served)
        self.heatmap.add(tracks)

        if t < self._next:
            return None, []
        self._next = t + self.cfg.snapshot_interval_s
        snap = self.snapshot(t - self._t0)
        alerts = self.alert_engine.evaluate(snap)
        self.last_snapshot = snap
        if self.store:
            self.store.write_snapshot(snap)
        for a in alerts:
            self.alert_log.append(a)
            if a.level == "OK":
                self.active_alerts.pop((a.rule, a.scope), None)
            else:
                self.active_alerts[(a.rule, a.scope)] = a
            if self.store:
                self.store.write_alert(a)
            for s in self.sinks:
                s.send(a)
        return snap, alerts

    def snapshot(self, ts: float) -> dict:
        snap = {
            "ts": ts,
            "zones": {n: z.snapshot() for n, z in self.zones.items()},
            "lines": {n: {"in_total": l.n_in, "out_total": l.n_out} for n, l in self.lines.items()},
            "queues": {n: q.snapshot() for n, q in self.queues.items()},
        }
        self._track_peaks(snap)
        return snap

    def _track_peaks(self, snap: dict) -> None:
        def bump(key: str, v) -> None:
            if v is not None and v > self._peaks.get(key, float("-inf")):
                self._peaks[key] = v

        for n, m in snap["zones"].items():
            bump(f"peak_occupancy:{n}", m["occupancy"])
            bump(f"peak_density_pm2:{n}", m["density_pm2"])
            bump(f"worst_los_index:{n}", m["los_index"])
        for n, q in snap["queues"].items():
            bump(f"peak_queue_length:{n}", q["length_smooth"])
            bump(f"peak_est_wait_min:{n}", q["est_wait_min"])

    def summary(self) -> dict:
        snap = self.last_snapshot or {}
        crit = sum(1 for a in self.alert_log if a.level == "CRITICAL")
        warn = sum(1 for a in self.alert_log if a.level == "WARNING")
        return {
            "site": self.cfg.site,
            "duration_s": snap.get("ts", 0),
            "line_totals": snap.get("lines", {}),
            "queue_served_total": {n: q.served_total for n, q in self.queues.items()},
            "dwell_mean_s": {n: s["dwell_mean_s"] for n, s in snap.get("zones", {}).items()},
            "peaks": self._peaks,
            "alerts": {"critical": crit, "warning": warn},
        }

    def close(self, out_dir: Optional[str] = None) -> dict:
        s = self.summary()
        if out_dir:
            out = Path(out_dir)
            np.save(out / "heatmap.npy", self.heatmap.grid)
            (out / "summary.json").write_text(json.dumps(s, indent=2))
        if self.store:
            self.store.set_meta(
                [
                    ("site", self.cfg.site),
                    ("camera", self.cfg.camera),
                    ("frame", json.dumps([self.cfg.frame_w, self.cfg.frame_h])),
                    ("zones", json.dumps([{"name": z.name, "polygon": z.polygon} for z in self.cfg.zones])),
                ]
            )
            self.store.close()
        return s
