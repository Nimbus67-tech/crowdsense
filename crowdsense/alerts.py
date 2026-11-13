"""Turn numbers into decisions.

An alert that says "density 4.3/m^2" helps nobody at 6 pm on a Saturday. Every alert here carries a
specific, plain-language ACTION for the person on duty. Alerts are debounced: a condition must hold
for `sustain_s` to fire and be absent for `clear_s` to resolve, so operators are not spammed.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .config import LOS_LETTERS, AlertCfg, ZoneCfg

LEVEL_NAMES = {0: "OK", 1: "WARNING", 2: "CRITICAL"}

ACTIONS = {
    ("density", 1): "Crowd is getting dense. Pause new entries to this area, open alternate routes, and send staff to guide people toward less crowded spaces.",
    ("density", 2): "Crush risk. Stop all inflow now, open every exit, calmly instruct people to keep moving out, and call security and first aid. Do not wait for confirmation.",
    ("wait", 1): "Queue wait is rising. Open one more counter or move a staff member to help with billing, and announce the expected wait.",
    ("wait", 2): "Wait time is excessive. Open all counters, offer a pre-order or self-checkout option, and split the queue into two lanes.",
    ("stalled", 1): "People are waiting but nobody is being served. Check the counter: staff away? POS or network down? Reassign someone immediately.",
    ("capacity", 1): "Approaching capacity. Switch to one-in-one-out at the entrance.",
    ("capacity", 2): "Over capacity. Stop entry until the area drops below the limit.",
}


@dataclass
class Alert:
    ts: float
    level: str
    rule: str
    scope: str
    message: str
    action: str

    def as_dict(self) -> dict:
        return asdict(self)


def _fmt_ts(ts: float) -> str:
    m, s = divmod(int(ts), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class AlertEngine:
    def __init__(self, cfg: AlertCfg, zones: Sequence[ZoneCfg]):
        self.cfg = cfg
        self._capacity = {z.name: z.capacity for z in zones if z.capacity}
        self._state: Dict[Tuple[str, str], dict] = {}

    # -- rules: each returns {(rule, scope): (level, message)} for the current snapshot -------------
    def _desired(self, snap: dict) -> Dict[Tuple[str, str], Tuple[int, str]]:
        c = self.cfg
        warn_i = LOS_LETTERS.index(c.density_warn_los)
        crit_i = LOS_LETTERS.index(c.density_critical_los)
        out: Dict[Tuple[str, str], Tuple[int, str]] = {}

        for zone, m in snap["zones"].items():
            lvl = 2 if m["los_index"] >= crit_i else 1 if m["los_index"] >= warn_i else 0
            out[("density", zone)] = (
                lvl,
                f"Crowd density {m['density_pm2']:.1f} people/m² (level of service {m['los']}), {m['occupancy']} people",
            )
            cap = self._capacity.get(zone)
            if cap:
                ratio = m["occupancy"] / cap
                lvl = 2 if ratio >= 1.0 else 1 if ratio >= c.capacity_warn_ratio else 0
                out[("capacity", zone)] = (lvl, f"{m['occupancy']} of {cap} people ({ratio:.0%} of capacity)")

        for zone, q in snap.get("queues", {}).items():
            w = q["est_wait_min"]
            if w is not None:
                lvl = 2 if w >= c.wait_critical_min else 1 if w >= c.wait_warn_min else 0
                out[("wait", zone)] = (lvl, f"Estimated wait {w:.0f} min with {q['length_smooth']:.0f} people queuing")
            out[("stalled", zone)] = (
                1 if q["stalled"] else 0,
                f"{q['length_smooth']:.0f} people waiting, no one served recently",
            )
        return out

    def evaluate(self, snap: dict) -> List[Alert]:
        t = snap["ts"]
        fired: List[Alert] = []
        for key, (lvl, msg) in self._desired(snap).items():
            st = self._state.setdefault(key, {"level": 0, "pending": None})
            if lvl == st["level"]:
                st["pending"] = None
                continue
            if st["pending"] is None or st["pending"][0] != lvl:
                st["pending"] = (lvl, t)
            need = self.cfg.sustain_s if lvl > st["level"] else self.cfg.clear_s
            if t - st["pending"][1] >= need:
                st["level"], st["pending"] = lvl, None
                rule, scope = key
                fired.append(
                    Alert(
                        ts=t,
                        level=LEVEL_NAMES[lvl],
                        rule=rule,
                        scope=scope,
                        message=msg if lvl else f"Resolved: {msg}",
                        action=ACTIONS.get((rule, lvl), ""),
                    )
                )
        return fired


# -- sinks: where alerts go ------------------------------------------------------------------------
class ConsoleSink:
    def send(self, a: Alert) -> None:
        icon = {"OK": "✅", "WARNING": "🟠", "CRITICAL": "🔴"}[a.level]
        print(f"[{_fmt_ts(a.ts)}] {icon} {a.level:<8} {a.scope}: {a.message}")
        if a.action:
            print(f"           → {a.action}")


class JsonlSink:
    def __init__(self, path: str):
        self._f = open(path, "a", encoding="utf-8")

    def send(self, a: Alert) -> None:
        self._f.write(json.dumps(a.as_dict()) + "\n")
        self._f.flush()


class WebhookSink:
    """Posts {"text": ...}, which Slack, Microsoft Teams and Discord-compatible endpoints accept."""

    def __init__(self, url: str, site: str = ""):
        self.url, self.site = url, site

    def send(self, a: Alert) -> None:
        if a.level == "OK":
            return
        text = f"[{a.level}] {self.site} {a.scope}: {a.message}\nAction: {a.action}"
        req = urllib.request.Request(
            self.url, data=json.dumps({"text": text}).encode(), headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:  # an unreachable webhook must never crash the monitor
            print(f"(webhook failed: {e})")
