# Evaluating CrowdSense on your own footage

A system that watches for danger should be validated before it is trusted. This takes about an hour.

## 1. Record
Capture 10 to 30 minutes from the real camera position, covering a quiet period **and** a busy one.

## 2. Make ground truth
Pick 20 to 30 timestamps spread across the video, **including crowded moments**. At each, pause the video and count the people inside the zone by eye. Save as CSV (see `docs/truth_template.csv`):

```csv
ts,zone,count
60,billing_queue,4
120,billing_queue,7
```

`ts` is seconds from the start of the video; `zone` must match your config.

## 3. Run and compare
```bash
python -m crowdsense run --source clip.mp4 --config my_venue.yaml --out runs/clip
python -m crowdsense evaluate --db runs/clip/metrics.db --truth truth.csv
```

## 4. Read the result
| Metric | Meaning |
|---|---|
| MAE | Average people off per snapshot |
| RMSE | Like MAE, punishes big misses |
| **Bias** | **Negative = under-counting** (the dangerous direction in a crowd) |
| MAPE | Average percentage error |
| within ±1 / ±10% | Share of snapshots that were essentially right |

Compute these separately for quiet and crowded moments. A system that is perfect when empty and reads 40% low when packed is not safe to trust at the F threshold. If bias is strongly negative at high density, lower your alert thresholds to compensate, or use a bigger model (`yolov8m.pt`, higher `imgsz`).

Please share your results in an issue. Real numbers from real cameras are the most valuable thing this project can collect.
