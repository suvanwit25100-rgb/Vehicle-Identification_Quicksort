"""Second plate reader: fast-plate-ocr's cct-s-v2-global model (MIT), used unchanged and only as a cross-check."""

from __future__ import annotations

from pathlib import Path

import cv2

from .detectors import MODELS_DIR

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

    def read(self, plate_bgr) -> str:
        rgb = cv2.cvtColor(plate_bgr, cv2.COLOR_BGR2RGB)
        out = self.rec.run(rgb)
        return (out[0].plate if out else "") or ""
