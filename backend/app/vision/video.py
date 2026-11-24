from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class SampledFrame:
    frame_id: int
    t: float
    image: np.ndarray


def laplacian_var(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXT


def sample_frames(path: str | Path, target_fps: float = 6.0, max_frames: int = 240) -> list[SampledFrame]:
    if is_image(path):                       # a still image is one frame: there is nothing to fuse across
        img = cv2.imread(str(path))
        if img is None:
            raise ValueError(f"cannot open image: {path}")
        return [SampledFrame(frame_id=0, t=0.0, image=img)]
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"cannot open video: {path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, round(src_fps / target_fps))
    frames, idx = [], 0
    try:
        while len(frames) < max_frames:
            ok, img = cap.read()
            if not ok:
                break
            if idx % step == 0:
                frames.append(SampledFrame(frame_id=idx, t=idx / src_fps, image=img))
            idx += 1
    finally:
        cap.release()
    return frames
