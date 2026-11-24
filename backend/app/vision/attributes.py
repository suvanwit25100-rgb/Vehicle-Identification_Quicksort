"""Vehicle colour and body-type estimates as probability distributions."""

import cv2
import numpy as np

COLOURS = ["white", "black", "silver", "grey", "red", "blue", "yellow", "green", "brown", "orange", "maroon"]
SMOOTHING = 0.10

# Stand-in until a trained body-type head exists: COCO only has car / motorcycle /
# bus / truck, so each class spreads its mass over the finer labels it may hide.
COCO_TO_BODY = {
    "car": {"car": 0.50, "suv": 0.38, "auto_rickshaw": 0.07, "tempo": 0.05},
    "motorcycle": {"two_wheeler": 0.90, "auto_rickshaw": 0.10},
    "bus": {"bus": 0.90, "truck": 0.10},
    "truck": {"truck": 0.55, "tempo": 0.30, "tractor": 0.05, "bus": 0.05, "auto_rickshaw": 0.05},
}


# Prompts were tuned on 87 real vehicle crops from the sample clip (hand-labelled, HANDOFF.md 8c):
# 75 -> 78 correct. Two or more prompts per class are averaged, so one odd phrase cannot decide alone.
BODY_PROMPTS = {
    "car": ["a photo of a hatchback car", "a photo of a sedan car", "a photo of a small compact car", "a photo of a car seen from behind"],
    "suv": ["a photo of an SUV", "a photo of a large SUV with a tall boxy body"],
    "two_wheeler": ["a photo of a motorcycle with a rider", "a photo of a scooter with a rider"],
    "auto_rickshaw": ["a photo of an auto rickshaw", "a photo of a three-wheeled tuk-tuk",
                      "a photo of an electric e-rickshaw with passenger seats",
                      "a photo of the back of a yellow and green CNG auto rickshaw"],
    "truck": ["a photo of a large cargo truck", "a photo of a lorry"],
    "tempo": ["a photo of a pickup truck with an open cargo bed", "a photo of a white delivery van with no side windows"],
    "bus": ["a photo of a bus"],
    "tractor": ["a photo of a farm tractor"],
}
# Types that look alike from a CCTV angle. The matcher gives partial credit when the registry says
# one and the camera says the other, because telling a hatchback from a small SUV is a coin flip.
NEAR_BODY = {"car": {"suv": 0.5}, "suv": {"car": 0.5}, "truck": {"tempo": 0.5}, "tempo": {"truck": 0.5}}
PRIOR_FLOOR = 0.05


def fuse_body(coco_label: str, clip_probs: dict[str, float]) -> dict[str, float]:
    """CLIP decides the fine class; the COCO label acts as a soft prior, never a veto."""
    compat = COCO_TO_BODY.get(coco_label)
    if not compat:
        return dict(clip_probs)
    weighted = {c: p * max(PRIOR_FLOOR, compat.get(c, 0.0)) for c, p in clip_probs.items()}
    total = sum(weighted.values())
    return {c: round(w / total, 4) for c, w in weighted.items()} if total > 0 else dict(clip_probs)


def _classify_pixels(hsv: np.ndarray) -> np.ndarray:
    h = hsv[:, 0].astype(int)
    s = hsv[:, 1].astype(int)
    v = hsv[:, 2].astype(int)
    out = np.full(len(h), -1, dtype=int)
    idx = {c: i for i, c in enumerate(COLOURS)}

    black = v < 55
    low_s = (s < 45) & ~black
    out[black] = idx["black"]
    out[low_s & (v >= 200)] = idx["white"]
    out[low_s & (v >= 135) & (v < 200)] = idx["silver"]
    out[low_s & (v < 135)] = idx["grey"]

    chroma = ~black & ~low_s
    red = chroma & ((h < 8) | (h > 172))
    out[red & (v >= 110)] = idx["red"]
    out[red & (v < 110)] = idx["maroon"]
    orange_hue = chroma & (h >= 8) & (h < 20)
    out[orange_hue & (v >= 130)] = idx["orange"]
    out[orange_hue & (v < 130)] = idx["brown"]
    out[chroma & (h >= 20) & (h < 36)] = idx["yellow"]
    out[chroma & (h >= 36) & (h < 90)] = idx["green"]
    out[chroma & (h >= 90) & (h <= 132)] = idx["blue"]
    return out


def colour_distribution(image: np.ndarray, bbox: tuple[int, int, int, int]) -> dict[str, float]:
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    # Body panels sit in the lower-middle of the box; windows and road sit outside it.
    rx1, rx2 = x1 + int(0.15 * w), x2 - int(0.15 * w)
    ry1, ry2 = y1 + int(0.40 * h), y1 + int(0.85 * h)
    roi = image[max(0, ry1):max(1, ry2), max(0, rx1):max(1, rx2)]
    if roi.size == 0:
        return {}
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    labels = _classify_pixels(hsv)
    labels = labels[labels >= 0]
    if len(labels) == 0:
        return {}
    counts = np.bincount(labels, minlength=len(COLOURS)).astype(float)
    p = counts / counts.sum()
    p = (1 - SMOOTHING) * p + SMOOTHING / len(COLOURS)
    return {c: round(float(x), 4) for c, x in zip(COLOURS, p)}


def body_distribution(coco_label: str) -> dict[str, float]:
    return dict(COCO_TO_BODY.get(coco_label, {}))


def average_distributions(dists: list[dict[str, float]], weights: list[float] | None = None) -> dict[str, float]:
    dists_w = [(d, w) for d, w in zip(dists, weights or [1.0] * len(dists)) if d]
    if not dists_w:
        return {}
    total_w = sum(w for _, w in dists_w)
    keys = {k for d, _ in dists_w for k in d}
    return {k: round(sum(d.get(k, 0.0) * w for d, w in dists_w) / total_w, 4) for k in keys}
