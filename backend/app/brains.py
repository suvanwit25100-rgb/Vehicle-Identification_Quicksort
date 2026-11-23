"""Manifest of every pretrained model the system uses, and whether it is installed."""

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from .vision.detectors import MODELS_DIR

CLIP_DIR = MODELS_DIR / "clip-vit-b32"
CLIP_WEIGHTS_BYTES = 605_247_071


@dataclass(frozen=True)
class Brain:
    id: str
    role: str
    source: str
    license: str
    path: Path | None
    required: bool


BRAINS = [
    Brain("vehicle_detector", "Vehicle detection and tracking", "Ultralytics YOLOv8n, COCO-pretrained",
          "AGPL-3.0", MODELS_DIR / "yolov8n.pt", True),
    Brain("plate_detector", "Plate localisation", "morsetechlab/yolov11-license-plate-detection (s variant)",
          "AGPL-3.0", MODELS_DIR / "plate_s.pt", True),
    Brain("plate_ocr", "Plate characters with per-character confidence",
          "PP-OCRv4 recogniser bundled in rapidocr-onnxruntime", "Apache-2.0", None, True),
    Brain("clip", "Zero-shot body type; appearance embedding for cross-camera matching",
          "openai/clip-vit-base-patch32", "check model card", CLIP_DIR, False),
]


def brain_status() -> list[dict]:
    out = []
    for b in BRAINS:
        if b.id == "clip":
            weights = CLIP_DIR / "pytorch_model.bin"
            ready = weights.exists() and weights.stat().st_size == CLIP_WEIGHTS_BYTES
        else:
            ready = Path(b.path).exists() if b.path else find_spec("rapidocr_onnxruntime") is not None
        out.append({"id": b.id, "role": b.role, "source": b.source, "license": b.license,
                    "required": b.required, "ready": ready})
    return out
