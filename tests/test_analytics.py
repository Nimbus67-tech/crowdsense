import pytest

from crowdsense.analytics import Heatmap, LineCounter, QueueMonitor, ZoneAnalyzer, level_of_service
from crowdsense.types import Track


def person(i, x, y):  # foot point is (x, y)
    return Track(i, (x - 10, y - 100, x + 10, y))


def test_foot_point_is_bottom_centre():
    assert Track(1, (0, 0, 20, 100)).foot == (10, 100)


@pytest.mark.parametrize(
    "area,los",
    [(None, "A"), (2.0, "A"), (1.0, "B"), (0.7, "C"), (0.4, "D"), (0.25, "E"), (0.19, "F"), (0.05, "F")],
)
def test_level_of_service(area, los):
    assert level_of_service(area) == los


def test_line_counter_direction():
    lc = LineCounter("door", (0, 100), (200, 100), in_direction=(0, -1))  # up = in
    lc.update([person(1, 50, 120), person(2, 80, 80)], 0)
    ev = lc.update([person(1, 50, 80), person(2, 80, 120)], 1)  # 1 goes up (in), 2 goes down (out)
    assert (lc.n_in, lc.n_out) == (1, 1)
    assert {(i, d) for i, d, _ in ev} == {(1, "in"), (2, "out")}


def test_line_counter_ignores_walking_past_the_end():
    lc = LineCounter("door", (0, 100), (200, 100), (0, -1))
    lc.update([person(1, 300, 120)], 0)
    lc.update([person(1, 300, 80)], 1)
    assert lc.n_in == 0


def test_zone_density_and_dwell():
    z = ZoneAnalyzer("hall", [(0, 0), (100, 0), (100, 100), (0, 100)], area_m2=10.0)
    for t in range(0, 11):  # 3 people stand inside for 10 seconds
        z.update([person(i, 50, 50) for i in range(3)], float(t))
    assert z.occupancy == 3
    assert z.density_pm2 == pytest.approx(0.3)
    assert z.area_per_person_m2 == pytest.approx(10 / 3)
    assert z.los == "A"
    for t in range(11, 16):  # they leave; after the grace period dwell is recorded
        z.update([], float(t))
    assert len(z.dwell_times) == 3
    assert all(d == pytest.approx(10.0) for d in z.dwell_times)
    assert z.snapshot()["dwell_mean_s"] == pytest.approx(10.0)


def test_zone_crush_density_is_level_F():
    z = ZoneAnalyzer("gate", [(0, 0), (100, 0), (100, 100), (0, 100)], area_m2=10.0)
    z.update([person(i, 50, 50) for i in range(60)], 0.0)  # 6 people per m2
    assert z.los == "F"


def test_dwell_ignores_one_frame_flicker():
    z = ZoneAnalyzer("hall", [(0, 0), (100, 0), (100, 100), (0, 100)], 10.0)
    z.update([person(1, 50, 50)], 0.0)
    for t in range(1, 6):
        z.update([], float(t))
    assert len(z.dwell_times) == 0  # present for 0 s: not a real visit


def test_queue_wait_matches_littles_law():
    """12 people waiting, 2 served per minute for 5 minutes  ->  wait = 12 / 2 = 6 minutes."""
    zone = ZoneAnalyzer("q", [(0, 0), (100, 0), (100, 100), (0, 100)], 12.0)
    qm = QueueMonitor(zone, window_s=300)
    crowd = [person(i, 50, 50) for i in range(12)]
    for t in range(0, 301):
        zone.update(crowd, float(t))
        qm.update(float(t), served_now=1 if t % 30 == 0 and t > 0 else 0)
    snap = qm.snapshot()
    assert snap["throughput_per_min"] == pytest.approx(2.0, abs=0.05)
    assert snap["est_wait_min"] == pytest.approx(6.0, abs=0.3)


def test_queue_wait_unknown_while_warming_up_and_empty_queue_is_zero():
    zone = ZoneAnalyzer("q", [(0, 0), (100, 0), (100, 100), (0, 100)], 12.0)
    qm = QueueMonitor(zone)
    zone.update([person(i, 50, 50) for i in range(5)], 0.0)
    qm.update(0.0, 0)
    assert qm.est_wait_min() is None  # no data yet: do not invent a number
    zone.update([], 10.0)
    for t in range(10, 20):
        zone.update([], float(t))
        qm.update(float(t), 0)
    assert qm.est_wait_min() == 0.0


def test_stalled_queue_detected():
    zone = ZoneAnalyzer("q", [(0, 0), (100, 0), (100, 100), (0, 100)], 12.0)
    qm = QueueMonitor(zone, stall_s=60)
    crowd = [person(i, 50, 50) for i in range(6)]
    for t in range(0, 100):
        zone.update(crowd, float(t))
        qm.update(float(t), 0)
    assert qm.stalled()
    assert qm.est_wait_min() is None  # waiting, but a service rate of zero cannot give a wait time


def test_heatmap_accumulates():
    h = Heatmap(200, 200, cell=20)
    h.add([person(1, 50, 50)] * 3)
    assert h.grid.max() == 3
    assert h.normalized().max() == 1.0


def test_no_wait_estimate_from_a_single_served_customer():
    zone = ZoneAnalyzer("q", [(0, 0), (100, 0), (100, 100), (0, 100)], 12.0)
    qm = QueueMonitor(zone, min_served=3)
    crowd = [person(i, 50, 50) for i in range(8)]
    for t in range(0, 120):
        zone.update(crowd, float(t))
        qm.update(float(t), served_now=1 if t == 30 else 0)
    assert qm.est_wait_min() is None  # one data point is not a rate
