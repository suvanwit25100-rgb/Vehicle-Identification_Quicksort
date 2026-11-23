"""Two-row plates, the usual layout on Indian two-wheelers: DL 14S over Z 8550.

The reader is built for one line of text, so a two-row crop read as a whole comes back as fragments. This module finds the gap between
the rows, reads each row as its own line and joins the results. It is applied only when it helps: a plate that is not clearly a single
line is read both ways, and the reading that fits the plate format better wins, so a single-row plate with a loose crop is never damaged.
"""

from __future__ import annotations

import cv2
import numpy as np

from .ocr import read_plate_chars
from .plate_text import align_to_slots

SINGLE_LINE_RATIO = 3.0     # a crop at least this much wider than tall is one line of text
SQUARE_RATIO = 1.8          # narrower than this cannot be one line, so a weak gap is still taken as the split
MIN_ROW_PX = 10
GAP_DEPTH = 0.7             # the gap must carry at most this share of the text density of the rows around it
MARGIN = 1.0                # two-row must beat one-row by about one confident character to be chosen


def _text_mask(gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if bw.mean() > 127:          # text is the minority colour, whether it is dark on light or light on dark
        bw = 255 - bw
    return bw > 0


def find_split(plate_bgr: np.ndarray) -> int | None:
    """Row at which a two-row plate divides, or None if this is not (or not clearly) a two-row plate."""
    h, w = plate_bgr.shape[:2]
    ratio = w / max(h, 1)
    if ratio >= SINGLE_LINE_RATIO or h < 2 * MIN_ROW_PX:
        return None
    gray = cv2.cvtColor(plate_bgr, cv2.COLOR_BGR2GRAY) if plate_bgr.ndim == 3 else plate_bgr
    profile = _text_mask(gray)[:, int(0.08 * w):int(0.92 * w)].mean(axis=1)
    k = max(3, h // 10) | 1
    profile = np.convolve(profile, np.ones(k) / k, mode="same")
    lo, hi = int(0.32 * h), int(0.68 * h)
    valley = lo + int(np.argmin(profile[lo:hi]))
    edge = int(0.10 * h)                                   # ignore the plate border at the top and bottom
    top = profile[edge:valley].max() if valley - edge > 2 else 0.0
    bottom = profile[valley:h - edge].max() if h - edge - valley > 2 else 0.0
    peak = min(top, bottom)
    depth = profile[valley] / peak if peak > 0 else 1.0
    if depth <= GAP_DEPTH or ratio < SQUARE_RATIO:
        return valley
    return None


def split_rows(plate_bgr: np.ndarray) -> list[np.ndarray] | None:
    y = find_split(plate_bgr)
    if y is None:
        return None
    h = plate_bgr.shape[0]
    pad = max(1, int(0.04 * h))
    top, bottom = plate_bgr[:min(h, y + pad)], plate_bgr[max(0, y - pad):]
    return [top, bottom] if min(top.shape[0], bottom.shape[0]) >= MIN_ROW_PX else None


def placed_score(chars: list[tuple[str, float]]) -> float:
    """How well a read fits the plate format: the summed confidence of the characters that land in a slot."""
    return sum(s.conf for s in align_to_slots(chars) if s)


def read_plate(plate_bgr: np.ndarray) -> tuple[list[tuple[str, float]], int]:
    """(characters with confidence, number of rows the plate was read as)."""
    one = read_plate_chars(plate_bgr)
    parts = split_rows(plate_bgr)
    if parts is None:
        return one, 1
    two = [c for part in parts for c in read_plate_chars(part)]
    return (two, 2) if placed_score(two) >= placed_score(one) + MARGIN else (one, 1)
