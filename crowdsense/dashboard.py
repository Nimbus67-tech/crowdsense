"""CrowdSense web app.

    streamlit run crowdsense/dashboard.py

Opens with a simulated lunch rush so there is something to look at immediately. Use the sidebar to
open your own results, and the tabs to analyse a video or check your zone setup, all without
touching the command line.
"""
import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # lets `streamlit run crowdsense/dashboard.py` work without installing

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=str(ROOT / "runs" / "demo" / "metrics.db"))
args, _ = ap.parse_known_args()

st.set_page_config(page_title="CrowdSense", page_icon="👥", layout="wide")

st.markdown(
    """
<style>
.block-container {padding-top: 2.2rem; max-width: 1250px;}
.kpi {border:1px solid #e2e8f0; border-radius:14px; padding:14px 18px; background:#fff; border-left:6px solid #94a3b8;}
.kpi .l {font-size:.74rem; color:#64748b; text-transform:uppercase; letter-spacing:.05em; font-weight:600;}
.kpi .v {font-size:2.1rem; font-weight:750; line-height:1.15; color:#0f172a;}
.kpi .s {font-size:.8rem; color:#64748b;}
.kpi.green {border-left-color:#16a34a;} .kpi.amber {border-left-color:#f59e0b;} .kpi.red {border-left-color:#dc2626;}
.banner {border-radius:14px; padding:16px 22px; margin:4px 0 18px; border:1px solid;}
.banner h3 {margin:0 0 4px; font-size:1.15rem;} .banner p {margin:0; font-size:.98rem;}
.banner.green {background:#ecfdf5; border-color:#a7f3d0; color:#065f46;}
.banner.amber {background:#fffbeb; border-color:#fde68a; color:#92400e;}
.banner.red {background:#fef2f2; border-color:#fecaca; color:#991b1b;}
.chip {display:inline-block; padding:2px 10px; border-radius:999px; font-weight:700; font-size:.8rem; color:#fff; margin-right:6px;}
.alertcard {border:1px solid #e2e8f0; border-left:6px solid #94a3b8; border-radius:12px; padding:12px 16px; background:#fff; margin-bottom:10px;}
.alertcard.CRITICAL {border-left-color:#dc2626;} .alertcard.WARNING {border-left-color:#f59e0b;} .alertcard.OK {border-left-color:#16a34a;}
.alertcard .t {color:#64748b; font-size:.8rem;} .alertcard .a {margin-top:6px; font-size:.95rem;}
</style>
""",
    unsafe_allow_html=True,
)

LOS = "ABCDEF"
LOS_TONE = {"A": "green", "B": "green", "C": "green", "D": "amber", "E": "red", "F": "red"}
LOS_MEANING = {
    "A": "free movement", "B": "minor restriction", "C": "busy but comfortable",
    "D": "crowded", "E": "very dense (warning)", "F": "crush risk",
}


def fmt_clock(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def kpi(label, value, sub="", tone="neutral"):
    return f'<div class="kpi {tone}"><div class="l">{label}</div><div class="v">{value}</div><div class="s">{sub}</div></div>'


# ---------------------------------------------------------------------------------------- data ----
def ensure_demo() -> str:
    demo = ROOT / "runs" / "demo"
    if not (demo / "metrics.db").exists():
        from crowdsense.config import load_config
        from crowdsense.simulate import simulate

        with st.spinner("Generating a simulated 90-minute lunch rush (a few seconds)..."):
            simulate(load_config(str(ROOT / "configs" / "food_court_counter.yaml")), str(demo), quiet=True)
    return str(demo / "metrics.db")


@st.cache_data(show_spinner=False)
def load(db: str, mtime: float):
    con = sqlite3.connect(db)
    m = pd.read_sql("SELECT * FROM metrics", con)
    a = pd.read_sql("SELECT * FROM alerts ORDER BY ts", con)
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    con.close()
    return m, a, meta


# -------------------------------------------------------------------------------------- sidebar ----
st.sidebar.markdown("## 👥 CrowdSense")
st.sidebar.caption("Early warning for crowd-crush risk and queue delays.")
source = st.sidebar.radio("Data", ["Demo: simulated lunch rush", "My results"], index=0 if "demo" in args.db or not Path(args.db).exists() else 1)
if source.startswith("Demo"):
    db_path = ensure_demo()
else:
    db_path = st.sidebar.text_input("Path to metrics.db", st.session_state.get("db", args.db))
st.session_state["db"] = db_path
if not Path(db_path).exists():
    st.error(f"No database at `{db_path}`. Use the **Analyze a video** tab, or run `python -m crowdsense simulate`.")
    st.stop()

m, alerts, meta = load(db_path, Path(db_path).stat().st_mtime)
if m.empty:
    st.warning("This database has no measurements yet.")
    st.stop()
m["minute"] = m["ts"] / 60.0
scopes = sorted(m["scope"].unique())
zones = [s.split(":", 1)[1] for s in scopes if s.startswith("zone:")]
queues = [s.split(":", 1)[1] for s in scopes if s.startswith("queue:")]
lines = [s.split(":", 1)[1] for s in scopes if s.startswith("line:")]
zone = st.sidebar.selectbox("Area to inspect", zones, index=zones.index(queues[0]) if queues and queues[0] in zones else 0)

st.sidebar.markdown("---")
st.sidebar.markdown("**Crowd level of service**")
chips = "".join(
    f'<div style="margin:3px 0"><span class="chip" style="background:{ {"green":"#16a34a","amber":"#f59e0b","red":"#dc2626"}[LOS_TONE[l]] }">{l}</span>{LOS_MEANING[l]}</div>'
    for l in LOS
)
st.sidebar.markdown(chips, unsafe_allow_html=True)
st.sidebar.caption("E and F are alert levels. F is about 5+ people per m².")

wide = m.pivot_table(index="ts", columns=["scope", "metric"], values="value").sort_index()
times = wide.index.to_numpy()
step_min = max(float(np.median(np.diff(times))) / 60.0, 0.01) if len(times) > 1 else 1.0


def val(scope, metric, t, default=None):
    if (scope, metric) not in wide.columns:
        return default
    s = wide[(scope, metric)].loc[:t].dropna()
    return float(s.iloc[-1]) if len(s) else default


def active_alerts(t):
    if alerts.empty:
        return alerts
    cur = alerts[alerts.ts <= t].drop_duplicates(["rule", "scope"], keep="last")
    cur = cur[cur.level != "OK"].copy()
    # most severe first; within a level, life-safety (crowd density) before capacity before waiting times
    cur["rank"] = cur["level"].map({"CRITICAL": 0, "WARNING": 1})
    cur["prio"] = cur["rule"].map({"density": 0, "capacity": 1, "stalled": 2, "wait": 3})
    return cur.sort_values(["rank", "prio"])


def line_chart(series, ylabel, color, rules=(), t_min=None, height=250):
    df = series.dropna().rename("value").reset_index()
    df.columns = ["minute", "value"]
    layers = [
        alt.Chart(df).mark_line(color=color, strokeWidth=2.6).encode(
            x=alt.X("minute:Q", title="minutes"), y=alt.Y("value:Q", title=ylabel)
        )
    ]
    for y, label, col in rules:
        rdf = pd.DataFrame({"y": [y], "label": [label]})
        layers.append(alt.Chart(rdf).mark_rule(color=col, strokeDash=[6, 4]).encode(y="y:Q"))
        layers.append(
            alt.Chart(rdf).mark_text(align="left", dx=6, dy=-7, color=col, fontSize=11).encode(y="y:Q", text="label:N", x=alt.value(4))
        )
    if t_min is not None:
        layers.append(alt.Chart(pd.DataFrame({"x": [t_min]})).mark_rule(color="#0f172a", strokeWidth=1.6).encode(x="x:Q"))
    return alt.layer(*layers).properties(height=height)


# ---------------------------------------------------------------------------------------- header ----
st.title("👥 CrowdSense")
st.caption(f"{meta.get('site', 'Site')}  ·  camera {meta.get('camera', '?')}  ·  {len(times)} measurements over {times[-1] / 60:.0f} min")

# default the scrubber to the busiest moment so the first impression is meaningful
focus = f"zone:{zone}"
peak_t = float(wide[(focus, "occupancy")].idxmax()) if (focus, "occupancy") in wide.columns else float(times[-1])
t_min = st.slider(
    "⏱  Scrub through time (minutes into the recording)",
    min_value=float(times[0] / 60), max_value=float(times[-1] / 60),
    value=float(peak_t / 60), step=float(step_min),
)
t = float(times[np.searchsorted(times, t_min * 60, side="right") - 1]) if t_min * 60 >= times[0] else float(times[0])

# ------------------------------------------------------------------------------------ status banner ----
act = active_alerts(t)
if act.empty:
    st.markdown('<div class="banner green"><h3>✅ All clear</h3><p>Crowd density and queue waits are within safe limits at this moment.</p></div>', unsafe_allow_html=True)
else:
    top = act.iloc[0]
    tone = "red" if top.level == "CRITICAL" else "amber"
    icon = "🔴" if top.level == "CRITICAL" else "🟠"
    more = f" (+{len(act) - 1} more active)" if len(act) > 1 else ""
    st.markdown(
        f'<div class="banner {tone}"><h3>{icon} {top.level}: {top.scope.replace("_", " ")}{more}</h3>'
        f'<p><b>{top.message}</b><br>👉 <b>What to do:</b> {top.action}</p></div>',
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------------------- KPIs ----
z = f"zone:{zone}"
occ = int(val(z, "occupancy", t, 0))
dens = val(z, "density_pm2", t, 0.0)
los = LOS[int(val(z, "los_index", t, 0))]
cols = st.columns(5)
cols[0].markdown(kpi("People in area", occ, zone.replace("_", " "), "neutral"), unsafe_allow_html=True)
cols[1].markdown(kpi("Crowd density", f"{dens:.1f}", f"people per m² · level {los}: {LOS_MEANING[los]}", LOS_TONE[los]), unsafe_allow_html=True)
if queues:
    q = f"queue:{queues[0]}"
    w = val(q, "est_wait_min", t)
    wtone = "neutral" if w is None else "red" if w >= 20 else "amber" if w >= 10 else "green"
    cols[2].markdown(kpi("Estimated wait", "n/a" if w is None else f"{w:.0f} min", "for someone joining the queue now", wtone), unsafe_allow_html=True)
    tp = val(q, "throughput_per_min", t)
    cols[3].markdown(kpi("Served per minute", "n/a" if tp is None else f"{tp:.1f}", "measured over last 5 min", "neutral"), unsafe_allow_html=True)
if lines:
    cols[4].markdown(kpi("Entered so far", int(val(f"line:{lines[0]}", "in_total", t, 0)), f"through “{lines[0]}”", "neutral"), unsafe_allow_html=True)

# ---------------------------------------------------------------------------------------- tabs ----
tab_over, tab_alerts, tab_heat, tab_video, tab_setup = st.tabs(
    ["📈 Overview", "🔔 Alerts & actions", "🔥 Heatmap", "🎥 Analyze a video", "📐 Zone setup"]
)

with tab_over:
    c1, c2 = st.columns(2)
    series = lambda sc, mt: wide[(sc, mt)] / 1 if (sc, mt) in wide.columns else pd.Series(dtype=float)
    idx_min = lambda s: s.set_axis(s.index / 60.0)
    with c1:
        if queues:
            st.markdown("##### Estimated queue wait")
            st.altair_chart(
                line_chart(idx_min(series(q, "est_wait_min")), "minutes", "#ea580c", [(10, "warning: 10 min", "#b45309"), (20, "critical: 20 min", "#dc2626")], t_min),
                width="stretch",
            )
            st.caption("Little's Law: people waiting ÷ the rate people are actually being served.")
    with c2:
        st.markdown("##### Crowd density")
        st.altair_chart(
            line_chart(idx_min(series(z, "density_pm2")), "people per m²", "#7c3aed", [(3.33, "level E: warning", "#b45309"), (5.0, "level F: crush risk", "#dc2626")], t_min),
            width="stretch",
        )
        st.caption("Computed from real floor area, so it means the same thing in every venue.")
    c3, c4 = st.columns(2)
    with c3:
        if queues:
            st.markdown("##### People waiting")
            st.altair_chart(line_chart(idx_min(series(q, "length_smooth")), "people", "#2563eb", [], t_min), width="stretch")
    with c4:
        if lines:
            st.markdown("##### Footfall (cumulative)")
            ff = pd.DataFrame({f"{ln} {d}": idx_min(series(f"line:{ln}", f"{d}_total")) for ln in lines for d in ("in", "out")})
            long = ff.reset_index().melt("ts", var_name="line", value_name="people").rename(columns={"ts": "minute"})
            st.altair_chart(
                alt.Chart(long).mark_line(strokeWidth=2.2).encode(x=alt.X("minute:Q", title="minutes"), y=alt.Y("people:Q"), color="line:N").properties(height=250),
                width="stretch",
            )

with tab_alerts:
    st.markdown("Every alert comes with a specific instruction for the person on duty.")
    full = st.checkbox("Show the full timeline (including alerts after the selected moment)", value=False)
    shown = alerts if full else alerts[alerts.ts <= t]
    if shown.empty:
        st.success("No alerts so far. Conditions stayed within safe limits.")
    else:
        def card(a):
            icon = {"CRITICAL": "🔴", "WARNING": "🟠", "OK": "✅"}[a.level]
            action = f'<div class="a">👉 {a.action}</div>' if a.action else ""
            return (
                f'<div class="alertcard {a.level}"><div class="t">{fmt_clock(a.ts)}  ·  {a.scope.replace("_", " ")}  ·  {a.rule}</div>'
                f"<b>{icon} {a.level}</b>  {a.message}{action}</div>"
            )

        recent = shown.iloc[::-1]
        for _, a in recent.head(5).iterrows():
            st.markdown(card(a), unsafe_allow_html=True)
        if len(recent) > 5:
            with st.expander(f"Show {len(recent) - 5} earlier alerts"):
                for _, a in recent.iloc[5:].iterrows():
                    st.markdown(card(a), unsafe_allow_html=True)
        st.download_button("⬇️ Download alerts as CSV", shown.to_csv(index=False), "alerts.csv", "text/csv")

with tab_heat:
    hm = Path(db_path).parent / "heatmap.npy"
    if not hm.exists():
        st.info("No heatmap saved for this run.")
    else:
        import matplotlib.pyplot as plt

        g = np.load(hm)
        W, H = json.loads(meta.get("frame", "[1280, 720]"))
        fig, ax = plt.subplots(figsize=(10, 10 * H / W))
        ax.imshow(np.log1p(g), cmap="inferno", extent=[0, W, H, 0], interpolation="bilinear", aspect="auto")
        for zz in json.loads(meta.get("zones", "[]")):
            pts = np.array(zz["polygon"] + [zz["polygon"][0]])
            ax.plot(pts[:, 0], pts[:, 1], color="#38bdf8", lw=1.8)
            ax.text(pts[0, 0] + 8, pts[0, 1] + 24, zz["name"].replace("_", " "), color="white", fontsize=10, weight="bold")
        ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
        fig.tight_layout(pad=0)
        st.pyplot(fig)
        st.caption("Brighter = people spent more time (or queued) there. Useful for placing signage, counters and staff.")

with tab_video:
    st.markdown("Upload a video and CrowdSense measures crowds and queues in it. Nothing is uploaded anywhere: it runs on your machine.")
    try:
        import cv2  # noqa: F401
        import ultralytics  # noqa: F401

        ready = True
    except ImportError:
        ready = False
        st.info("Video analysis needs the vision extras:  `pip install -e \".[vision]\"`  then restart this app.")
    cfgs = sorted((ROOT / "configs").glob("*.yaml"))
    cfg_name = st.selectbox("Venue configuration", [c.name for c in cfgs], key="cfg_video")
    up = st.file_uploader("Video file", type=["mp4", "mov", "avi", "mkv"], key="video_up")
    stride = st.slider("Speed vs. accuracy: analyse every Nth frame", 1, 10, 3, help="Higher = faster, slightly less precise.")
    if st.button("▶️ Analyze", type="primary", disabled=not (ready and up)):
        from crowdsense.config import load_config
        from crowdsense.runner import analyze_video

        tmp = Path(tempfile.mkdtemp())
        vid = tmp / up.name
        vid.write_bytes(up.getvalue())
        bar = st.progress(0.0, text="Analysing…")
        out = ROOT / "runs" / "uploaded"
        analyze_video(str(vid), load_config(str(ROOT / "configs" / cfg_name)), str(out), stride=stride, console=False, progress=lambda f: bar.progress(f, text=f"Analysing… {f:.0%}"))
        st.session_state["db"] = str(out / "metrics.db")
        st.success("Done. Pick **My results** in the sidebar and enter:  " + str(out / "metrics.db"))

with tab_setup:
    st.markdown("Check your zones on a real camera frame **before** trusting any numbers. The grid shows pixel coordinates; arrows show which direction counts as “in”.")
    try:
        import cv2
    except ImportError:
        cv2 = None
        st.info("Needs OpenCV:  `pip install opencv-python`")
    if cv2 is not None:
        from crowdsense.config import load_config
        from crowdsense.overlay import draw_setup

        cfgs = sorted((ROOT / "configs").glob("*.yaml"))
        cfg_name = st.selectbox("Configuration to preview", [c.name for c in cfgs], key="cfg_setup")
        img = st.file_uploader("A frame or short clip from your camera (optional)", type=["png", "jpg", "jpeg", "mp4", "mov"], key="setup_up")
        cfg = load_config(str(ROOT / "configs" / cfg_name))
        frame = np.full((cfg.frame_h, cfg.frame_w, 3), 52, np.uint8)
        if img is not None:
            raw = img.getvalue()
            if img.name.lower().endswith((".mp4", ".mov")):
                tmpf = Path(tempfile.mkdtemp()) / img.name
                tmpf.write_bytes(raw)
                cap = cv2.VideoCapture(str(tmpf)); ok, fr = cap.read(); cap.release()
                frame = cv2.resize(fr, (cfg.frame_w, cfg.frame_h)) if ok else frame
            else:
                dec = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                frame = cv2.resize(dec, (cfg.frame_w, cfg.frame_h)) if dec is not None else frame
        vis = draw_setup(frame.copy(), cfg)
        st.image(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB), width="stretch")
        st.caption(f"Reference frame {cfg.frame_w}×{cfg.frame_h}. Edit the YAML, save, and reselect to refresh. Zone areas shown are the real-world m² you entered.")
