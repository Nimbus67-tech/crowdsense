# Metrics reference

All spatial metrics use the **foot point**: the bottom-centre of a person's box, where they touch the floor. Floors are 2D; box centres are not.

## Density and Level of Service

`density = occupancy / area_m2`, `area_per_person = area_m2 / occupancy`

| Level | m² per person | Meaning (standing / queuing) |
|---|---|---|
| A | ≥ 1.2 | Free movement |
| B | 0.9 – 1.2 | Minor restriction |
| C | 0.65 – 0.9 | Comfortable but busy |
| D | 0.3 – 0.65 | Crowded, movement restricted |
| **E** | 0.2 – 0.3 | Very dense: **warning** |
| **F** | < 0.2 | About 5+ people/m²: **crush risk** |

Thresholds are adapted from Fruin's classic pedestrian level-of-service work and are common planning conventions. Check them against your local code. They are configurable (`density_warn_los`, `density_critical_los`).

`area_m2` must be the **real floor area** of the polygon. A wrong area gives a confidently wrong density.

## Queue wait (Little's Law)

`wait = L / λ`

- `L` is the median of the last 9 queue-zone occupancy readings (one missed detection cannot swing it).
- `λ` is the number of people who crossed the service line in the last `window_s` (default 300 s), divided by the window.
- Returns **0** for an empty queue, **unknown** (not a guess) until ≥ 60 s have elapsed and ≥ 3 people have been served.
- Little's Law holds for a roughly steady queue. In a sudden surge the estimate lags.

## Stalled queue

True when the smoothed queue length has been ≥ 3 for `stall_s` **and** nobody has been served for `stall_s`.

## Footfall

A crossing is detected when a track's movement between consecutive frames intersects the line segment. It is "in" if the movement has a positive dot product with `in_direction`. A person standing exactly on the line is never double-counted (half-open convention).

## Dwell time

Time from a track first appearing in a zone to leaving it. A track absent for more than 2 s is treated as having left. Visits under 1 s are discarded as flicker. Mean and P90 are reported only once at least 3 visits exist.

## Alert debouncing

A condition must persist `sustain_s` (default 10 s) to fire and be absent `clear_s` (default 30 s) to resolve. Each state change fires **once**, so operators get one message per event, not one per frame.
