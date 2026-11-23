"""Plate OCR with true per-character confidence.

Runs the PP-OCRv4 recogniser bundled with rapidocr-onnxruntime directly,
restricted to A-Z0-9, and decodes CTC greedily. A character's confidence is
the raw probability mass the model put on it (not renormalised after masking),
so mass spent on out-of-alphabet classes lowers confidence instead of hiding.
"""

from functools import lru_cache

import numpy as np

ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


@lru_cache
def _engine():
    from rapidocr_onnxruntime import RapidOCR

    rec = RapidOCR().text_rec
    chars = rec.postprocess_op.character
    allowed_ids = np.array([i for i, c in enumerate(chars) if c in ALLOWED])
    return rec, chars, allowed_ids


def read_plate_chars(plate_bgr: np.ndarray) -> list[tuple[str, float]]:
    rec, chars, allowed_ids = _engine()
    h, w = plate_bgr.shape[:2]
    imgC, imgH, imgW = rec.rec_image_shape
    max_wh = max(imgW / imgH, w / h)
    batch = rec.resize_norm_img(plate_bgr, max_wh)[np.newaxis].astype(np.float32)
    probs = rec.session(batch)[0][0]  # (T, C), already softmax

    masked = np.zeros_like(probs)
    masked[:, allowed_ids] = probs[:, allowed_ids]
    best_allowed = masked.argmax(axis=1)
    best_allowed_p = masked.max(axis=1)
    blank_p = probs[:, 0]

    out: list[tuple[str, float]] = []
    prev = None
    run_best = 0.0
    for t in range(probs.shape[0]):
        is_char = best_allowed_p[t] > blank_p[t] and best_allowed_p[t] >= probs[t].max() * 0.5
        idx = int(best_allowed[t]) if is_char else None
        if idx is not None and idx == prev:
            run_best = max(run_best, float(best_allowed_p[t]))
            continue
        if prev is not None:
            out.append((chars[prev], run_best))
        prev = idx
        run_best = float(best_allowed_p[t]) if idx is not None else 0.0
    if prev is not None:
        out.append((chars[prev], run_best))
    return out
