"""Measure how accurate the counts are, against a human-counted ground truth.

CrowdSense does not ship a claimed accuracy number, because accuracy depends on YOUR camera angle,
lighting and crowd density. Instead this gives you the tool to measure it in an afternoon:

  1. Pick 20-30 moments in a recorded video. Count the people in a zone by eye.
  2. Write them to a CSV:  ts,zone,count   (ts = seconds from start of the video)
  3. python -m crowdsense evaluate --db runs/x/metrics.db --truth truth.csv
"""
from __future__ import annotations

import csv
import math
import sqlite3
from typing import Dict, List, Sequence


def count_error_metrics(pred: Sequence[float], truth: Sequence[float]) -> Dict[str, float]:
    if len(pred) != len(truth) or not pred:
        raise ValueError("pred and truth must be non-empty and the same length")
    errs = [p - t for p, t in zip(pred, truth)]
    n = len(errs)
    nz = [(abs(e) / t) for e, t in zip(errs, truth) if t > 0]
    return {
        "n": n,
        "mae": sum(abs(e) for e in errs) / n,
        "rmse": math.sqrt(sum(e * e for e in errs) / n),
        "bias": sum(errs) / n,  # > 0: over-counting, < 0: under-counting
        "mape_pct": 100.0 * sum(nz) / len(nz) if nz else float("nan"),
        "within_1_pct": 100.0 * sum(1 for e in errs if abs(e) <= 1) / n,
        "within_10pct_pct": 100.0
        * sum(1 for e, t in zip(errs, truth) if abs(e) <= max(1.0, 0.1 * t))
        / n,
    }


def load_truth(path: str) -> List[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return [{"ts": float(r["ts"]), "zone": r["zone"], "count": float(r["count"])} for r in csv.DictReader(f)]


def evaluate_db(db_path: str, truth_csv: str, tolerance_s: float = 5.0) -> Dict[str, Dict[str, float]]:
    db = sqlite3.connect(db_path)
    truth = load_truth(truth_csv)
    by_zone: Dict[str, Dict[str, List[float]]] = {}
    for row in truth:
        hit = db.execute(
            "SELECT ts, value FROM metrics WHERE scope=? AND metric='occupancy' "
            "ORDER BY ABS(ts-?) LIMIT 1",
            (f"zone:{row['zone']}", row["ts"]),
        ).fetchone()
        if hit is None or abs(hit[0] - row["ts"]) > tolerance_s:
            continue
        d = by_zone.setdefault(row["zone"], {"pred": [], "truth": []})
        d["pred"].append(hit[1])
        d["truth"].append(row["count"])
    return {z: count_error_metrics(d["pred"], d["truth"]) for z, d in by_zone.items()}
