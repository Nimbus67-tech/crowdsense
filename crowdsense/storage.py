"""SQLite time-series store. Only aggregate numbers are saved: never frames, faces or identities."""
from __future__ import annotations

import sqlite3
from typing import Iterable, List, Tuple

from .alerts import Alert

SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (ts REAL NOT NULL, scope TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_metrics ON metrics (scope, metric, ts);
CREATE TABLE IF NOT EXISTS alerts (ts REAL, level TEXT, rule TEXT, scope TEXT, message TEXT, action TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def flatten(snap: dict) -> List[Tuple[float, str, str, float]]:
    ts, rows = snap["ts"], []
    sections = (("zone", snap["zones"]), ("line", snap["lines"]), ("queue", snap.get("queues", {})))
    for kind, group in sections:
        for name, metrics in group.items():
            for k, v in metrics.items():
                if isinstance(v, (int, float)) and v == v:  # skip None, strings, NaN
                    rows.append((ts, f"{kind}:{name}", k, float(v)))
    return rows


class MetricsStore:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def write_snapshot(self, snap: dict) -> None:
        self.db.executemany("INSERT INTO metrics VALUES (?,?,?,?)", flatten(snap))
        self.db.commit()

    def write_alert(self, a: Alert) -> None:
        self.db.execute(
            "INSERT INTO alerts VALUES (?,?,?,?,?,?)", (a.ts, a.level, a.rule, a.scope, a.message, a.action)
        )
        self.db.commit()

    def set_meta(self, items: Iterable[Tuple[str, str]]) -> None:
        self.db.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", list(items))
        self.db.commit()

    def close(self) -> None:
        self.db.close()
