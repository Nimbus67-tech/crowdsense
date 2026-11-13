"""Render the README figure from a simulation run:  python scripts/plot_demo.py runs/demo/metrics.db"""
import sqlite3
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

db = sys.argv[1] if len(sys.argv) > 1 else "runs/demo/metrics.db"
out = sys.argv[2] if len(sys.argv) > 2 else "docs/assets/demo_queue.png"
con = sqlite3.connect(db)
m = pd.read_sql("SELECT * FROM metrics", con)
alerts = pd.read_sql("SELECT * FROM alerts", con)


def s(scope, metric):
    d = m[(m.scope == scope) & (m.metric == metric)]
    return d["ts"] / 60, d["value"]


fig, ax = plt.subplots(3, 1, figsize=(10, 8.5), sharex=True)
x, y = s("queue:billing_queue", "length_smooth")
ax[0].plot(x, y, color="#2563eb", lw=2)
ax[0].axhline(40, color="#dc2626", ls="--", lw=1)
ax[0].text(0.5, 41, "capacity (40)", color="#dc2626", fontsize=9)
ax[0].set_ylabel("people in queue")
ax[0].set_title("CrowdSense on a simulated lunch rush: one counter, arrivals peaking at 7 per minute", fontsize=11, loc="left")

x, y = s("queue:billing_queue", "est_wait_min")
ax[1].plot(x, y, color="#ea580c", lw=2)
ax[1].axhline(10, color="#f59e0b", ls="--", lw=1)
ax[1].axhline(20, color="#dc2626", ls="--", lw=1)
ax[1].text(0.5, 10.6, "warning: 10 min", color="#b45309", fontsize=9)
ax[1].text(0.5, 20.6, "critical: 20 min", color="#dc2626", fontsize=9)
ax[1].set_ylabel("estimated wait (min)")

x, y = s("zone:billing_queue", "density_pm2")
ax[2].plot(x, y, color="#7c3aed", lw=2)
for lvl, name, c in [(3.33, "E (warning)", "#f59e0b"), (5.0, "F (crush risk)", "#dc2626")]:
    ax[2].axhline(lvl, color=c, ls="--", lw=1)
    ax[2].text(0.5, lvl + 0.08, f"level of service {name}", color=c, fontsize=9)
ax[2].set_ylabel("density (people/m²)")
ax[2].set_xlabel("minutes")
ax[2].set_ylim(0, 5.6)

for _, a in alerts[alerts.level != "OK"].iterrows():
    for axis in ax:
        axis.axvline(a.ts / 60, color="#dc2626" if a.level == "CRITICAL" else "#f59e0b", alpha=0.18, lw=6)
for axis in ax:
    axis.grid(alpha=0.25)
fig.text(0.99, 0.005, "shaded bands = alerts fired", ha="right", fontsize=8, color="#555")
fig.tight_layout()
fig.savefig(out, dpi=130)
print("wrote", out)
