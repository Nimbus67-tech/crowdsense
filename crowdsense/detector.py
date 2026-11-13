"""Person detection + multi-object tracking via Ultralytics YOLO and ByteTrack.

Only the 'person' class is used, and only box geometry leaves this module. No faces are extracted,
no embeddings are computed, no identity is ever stored.
"""
from __future__ import annotations

from typing import List, Optional

from .types import Track


class PersonTracker:
    def __init__(self, model: str, conf: float, imgsz: int, tracker: str = "bytetrack.yaml", device: Optional[str] = None):
        try:
            from ultralytics import YOLO
        except ImportError as e:  # pragma: no cover
            raise SystemExit(
                "The vision extras are not installed. Run:  pip install 'crowdsense[vision]'"
            ) from e
        self.model = YOLO(model)
        self.conf, self.imgsz, self.tracker, self.device = conf, imgsz, tracker, device

    def track(self, frame) -> List[Track]:
        res = self.model.track(
            frame,
            persist=True,
            classes=[0],  # COCO class 0 = person
            conf=self.conf,
            imgsz=self.imgsz,
            tracker=self.tracker,
            device=self.device,
            verbose=False,
        )[0]
        boxes = res.boxes
        if boxes is None or boxes.id is None:
            return []
        xyxy = boxes.xyxy.cpu().numpy()
        ids = boxes.id.int().cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        return [Track(int(i), tuple(map(float, b)), float(c)) for i, b, c in zip(ids, xyxy, confs)]
