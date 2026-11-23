import os
from dataclasses import dataclass
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
DEVICE = os.environ.get("PLATETRACE_DEVICE", "cpu")
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
# Default association settings: a looser match threshold cut tracks 29 -> 23 on one clip but linked different vehicles and lost a plate.
TRACKER_CFG = "bytetrack.yaml"


@dataclass
class VehicleDet:
    track_id: int
    label: str
    conf: float
    bbox: tuple[int, int, int, int]


class VehicleTracker:
    def __init__(self, weights: Path | None = None, conf: float = 0.3):
        from ultralytics import YOLO

        self.model = YOLO(str(weights or MODELS_DIR / "yolov8n.pt"))
        self.conf = conf

    def reset(self) -> None:
        self.model.predictor = None

    def update(self, frame) -> list[VehicleDet]:
        r = self.model.track(
            frame, persist=True, tracker=str(TRACKER_CFG), classes=list(VEHICLE_CLASSES),
            conf=self.conf, device=DEVICE, verbose=False,
        )[0]
        if r.boxes is None or r.boxes.id is None:
            return []
        out = []
        for box, tid, cls, conf in zip(r.boxes.xyxy.tolist(), r.boxes.id.tolist(),
                                       r.boxes.cls.tolist(), r.boxes.conf.tolist()):
            x1, y1, x2, y2 = (int(v) for v in box)
            out.append(VehicleDet(int(tid), VEHICLE_CLASSES[int(cls)], float(conf), (x1, y1, x2, y2)))
        return out


class PlateDetector:
    def __init__(self, weights: Path | None = None, conf: float = 0.25):
        from ultralytics import YOLO

        self.model = YOLO(str(weights or MODELS_DIR / "plate_s.pt"))
        self.conf = conf

    def best(self, crop) -> tuple[tuple[int, int, int, int], float] | None:
        r = self.model.predict(crop, conf=self.conf, device=DEVICE, verbose=False)[0]
        if r.boxes is None or len(r.boxes) == 0:
            return None
        i = int(r.boxes.conf.argmax())
        x1, y1, x2, y2 = (int(v) for v in r.boxes.xyxy[i].tolist())
        return (x1, y1, x2, y2), float(r.boxes.conf[i])
