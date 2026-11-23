"""Second plate reader: fast-plate-ocr's cct-s-v2-global model (MIT), used unchanged and only as a cross-check."""

from __future__ import annotations

from pathlib import Path

import cv2

from .detectors import MODELS_DIR
from .plate_text import align_to_slots
from .rows import MARGIN, split_rows

MODEL_DIR = MODELS_DIR / "fast-plate-ocr"
ONNX = MODEL_DIR / "cct_s_v2_global.onnx"
CONFIG = MODEL_DIR / "cct_s_v2_global_plate_config.yaml"
NAME = "fast-plate-ocr cct-s-v2-global"


def available() -> bool:
    try:
        import fast_plate_ocr  # noqa: F401
    except ImportError:
        return False
    return ONNX.exists() and CONFIG.exists()


class SecondReader:
    name = NAME

    def __init__(self, onnx: Path = ONNX, config: Path = CONFIG):
        from fast_plate_ocr import LicensePlateRecognizer

        self.rec = LicensePlateRecognizer(onnx_model_path=str(onnx), plate_config_path=str(config),
                                          providers=["CPUExecutionProvider"])

    def _read(self, img) -> str:
        out = self.rec.run(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        return (out[0].plate if out else "") or ""

    def read(self, plate_bgr) -> str:
        """The plate as text. A two-row plate is read row by row when that fits the plate format clearly better, as for the first reader."""
        one = self._read(plate_bgr)
        parts = split_rows(plate_bgr)
        if parts is None:
            return one
        two = "".join(self._read(p) for p in parts)
        placed = lambda t: sum(1 for s in align_to_slots([(c, 1.0) for c in t]) if s)
        return two if placed(two) >= placed(one) + MARGIN else one
