from crowdsense.alerts import AlertEngine
from crowdsense.config import AlertCfg, ZoneCfg

ZONES = [ZoneCfg("hall", [(0, 0), (1, 0), (1, 1)], 10.0, capacity=50)]


def snap(ts, los_index=0, occ=5, wait=None, stalled=0.0):
    return {
        "ts": ts,
        "zones": {"hall": {"los_index": los_index, "los": "ABCDEF"[los_index], "density_pm2": occ / 10, "occupancy": occ}},
        "lines": {},
        "queues": {"hall": {"est_wait_min": wait, "length_smooth": 12, "stalled": stalled}},
    }


def test_critical_density_alert_has_an_action():
    eng = AlertEngine(AlertCfg(sustain_s=0), ZONES)
    out = eng.evaluate(snap(0, los_index=5, occ=60))
    crit = [a for a in out if a.rule == "density"]
    assert crit and crit[0].level == "CRITICAL"
    assert "Stop all inflow" in crit[0].action


def test_one_frame_spike_does_not_alert():
    eng = AlertEngine(AlertCfg(sustain_s=10), ZONES)
    assert eng.evaluate(snap(0, los_index=5, occ=60)) == []  # spike begins
    assert eng.evaluate(snap(5, los_index=0)) == []  # gone before 10 s elapsed
    assert eng.evaluate(snap(20, los_index=0)) == []


def test_sustained_condition_fires_once_then_resolves():
    eng = AlertEngine(AlertCfg(sustain_s=10, clear_s=30), ZONES)
    fired = []
    for t in range(0, 60, 5):
        fired += [a for a in eng.evaluate(snap(t, los_index=4, occ=30)) if a.rule == "density"]
    assert [a.level for a in fired] == ["WARNING"]  # exactly once, not every snapshot
    resolved = []
    for t in range(60, 140, 5):
        resolved += [a for a in eng.evaluate(snap(t, los_index=0, occ=3)) if a.rule == "density"]
    assert [a.level for a in resolved] == ["OK"]
    assert resolved[0].message.startswith("Resolved")


def test_wait_time_thresholds():
    eng = AlertEngine(AlertCfg(sustain_s=0, wait_warn_min=10, wait_critical_min=20), ZONES)
    assert [a.level for a in eng.evaluate(snap(0, wait=12)) if a.rule == "wait"] == ["WARNING"]
    assert [a.level for a in eng.evaluate(snap(5, wait=25)) if a.rule == "wait"] == ["CRITICAL"]


def test_capacity_alert():
    eng = AlertEngine(AlertCfg(sustain_s=0), ZONES)
    levels = {a.rule: a.level for a in eng.evaluate(snap(0, occ=55))}
    assert levels["capacity"] == "CRITICAL"


def test_stalled_queue_alert():
    eng = AlertEngine(AlertCfg(sustain_s=0), ZONES)
    out = [a for a in eng.evaluate(snap(0, stalled=1.0)) if a.rule == "stalled"]
    assert out and "POS" in out[0].action
