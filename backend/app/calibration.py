"""Simulation-based calibration of department thresholds.

Generates noisy plate sightings (clean to hard), runs them through the real
fusion and matcher, and measures how often each confidence threshold returns a
wrong or out-of-registry vehicle. The noise model is an assumption, loosely
based on errors seen in real clips; it sets *relative* operating points and
must be re-checked against real footage.
"""

import math
import random
from dataclasses import dataclass

from .config import DepartmentConfig
from .fusion import SLOT_KINDS, fuse_frames
from .matcher import SIMILAR_COLOURS, match_registry
from .schemas import PLATE_LEN, CharRead, FrameRead, RegistryRow
from .vision.attributes import BODY_PROMPTS, COLOURS

LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"
DIGITS = "0123456789"
STATE_CODES = ["CG", "MH", "DL", "UP", "KA", "WB", "BR", "RJ", "MP", "OD", "HR", "GJ", "TN"]
CONFUSABLE = {"O": "0", "0": "O", "I": "1", "1": "I", "B": "8", "8": "B", "S": "5",
              "5": "S", "Z": "2", "2": "Z", "G": "6", "6": "G", "D": "0", "L": "1"}

LEVELS = {
    "easy":   dict(p=0.4, frames=(8, 20), read=0.95, err=0.03, ok=(0.97, 0.03), bad=(0.60, 0.15)),
    "medium": dict(p=0.4, frames=(4, 12), read=0.80, err=0.10, ok=(0.90, 0.06), bad=(0.55, 0.15)),
    "hard":   dict(p=0.2, frames=(2, 6),  read=0.50, err=0.25, ok=(0.80, 0.10), bad=(0.50, 0.15)),
}
BODY_CLASSES = list(BODY_PROMPTS)
NO_ATTR_CHANCE = 0.0


def _clamp(x: float) -> float:
    return max(0.05, min(1.0, x))


def _substitute(ch: str, kind: str, rng: random.Random) -> str:
    if ch in CONFUSABLE and rng.random() < 0.6:
        return CONFUSABLE[ch]
    pool = LETTERS if ch.isalpha() else DIGITS
    return rng.choice([c for c in pool if c != ch])


def simulate_frames(plate: str, rng: random.Random, level: str) -> list[FrameRead]:
    cfg = LEVELS[level]
    frames = []
    for f in range(rng.randint(*cfg["frames"])):
        q = rng.uniform(0.3, 1.0)
        chars: list[CharRead | None] = []
        for i in range(PLATE_LEN):
            if rng.random() > cfg["read"]:
                chars.append(None)
                continue
            if rng.random() < cfg["err"]:
                chars.append(CharRead(char=_substitute(plate[i], SLOT_KINDS[i], rng),
                                      conf=_clamp(rng.gauss(*cfg["bad"]))))
            else:
                chars.append(CharRead(char=plate[i], conf=_clamp(rng.gauss(*cfg["ok"]))))
        frames.append(FrameRead(frame_id=f, sharpness=q * rng.uniform(70, 130),
                                plate_area=q * rng.uniform(700, 1300), chars=chars))
    return frames


def _spread(top: str, labels: list[str], p_top: float) -> dict[str, float]:
    rest = (1 - p_top) / (len(labels) - 1)
    return {lab: round(p_top if lab == top else rest, 4) for lab in labels}


def simulate_attributes(colour: str, body: str, rng: random.Random):
    r = rng.random()
    if r < 0.55:
        c = colour
    elif r < 0.80:
        mates = [next(iter(p - {colour})) for p in SIMILAR_COLOURS if colour in p]
        c = rng.choice(mates) if mates else rng.choice(COLOURS)
    else:
        c = rng.choice(COLOURS)
    b = body if rng.random() < 0.5 else rng.choice(BODY_CLASSES)
    return (_spread(c, COLOURS, rng.uniform(0.4, 0.8)),
            _spread(b, BODY_CLASSES, rng.uniform(0.35, 0.6)))


def _random_plate(rng: random.Random) -> str:
    return (rng.choice(STATE_CODES) + f"{rng.randint(1, 90):02d}"
            + "".join(rng.choice(LETTERS) for _ in range(2)) + str(rng.randint(1000, 9999)))


def _lookalike(plate: str, rng: random.Random) -> str:
    chars = list(plate)
    for pos in rng.sample(range(4, PLATE_LEN), rng.choice([1, 2])):
        pool = LETTERS if chars[pos].isalpha() else DIGITS
        chars[pos] = rng.choice([c for c in pool if c != chars[pos]])
    return "".join(chars)


@dataclass
class Sample:
    kind: str  # pos | neg_lookalike | neg_random
    level: str
    truth: str
    frames: list[FrameRead]
    colour: dict[str, float]
    body: dict[str, float]


def make_samples(registry: list[RegistryRow], n_pos: int, n_neg: int, seed: int = 7) -> list[Sample]:
    rng = random.Random(seed)
    known = {r.plate for r in registry}
    levels, weights = list(LEVELS), [LEVELS[k]["p"] for k in LEVELS]
    out = []
    for _ in range(n_pos):
        row = rng.choice(registry)
        lv = rng.choices(levels, weights)[0]
        col, body = simulate_attributes(row.colour, row.body_type, rng)
        out.append(Sample("pos", lv, row.plate, simulate_frames(row.plate, rng, lv), col, body))
    for _ in range(n_neg):
        lv = rng.choices(levels, weights)[0]
        base = rng.choice(registry)
        if rng.random() < 0.3:
            plate = _lookalike(base.plate, rng)
            kind, attr_src = "neg_lookalike", base
        else:
            plate = _random_plate(rng)
            kind, attr_src = "neg_random", rng.choice(registry)
        if plate in known:
            continue
        col, body = simulate_attributes(attr_src.colour, attr_src.body_type, rng)
        out.append(Sample(kind, lv, plate, simulate_frames(plate, rng, lv), col, body))
    return out


def run_matcher(samples: list[Sample], registry: list[RegistryRow], cfg: DepartmentConfig) -> list[dict]:
    """Run the real fusion + matcher with the threshold disabled; record the outcome for offline sweeps."""
    open_cfg = cfg.model_copy(update={"match_threshold": 0.0})
    records = []
    for s in samples:
        fused = fuse_frames(s.frames, slot_accept=cfg.slot_accept)
        res = match_registry(fused, s.colour, s.body, registry, open_cfg)
        top = res.candidates[0] if res.candidates else None
        records.append({"kind": s.kind, "level": s.level, "truth": s.truth, "status": res.status,
                        "top_plate": top.plate if top else None, "top_score": top.confidence if top else 0.0})
    return records


def wilson_upper(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 1.0
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return min(1.0, (centre + margin) / (1 + z * z / n))


def _returned(r: dict, theta: float) -> bool:
    return r["status"] in ("match", "ambiguous") and r["top_score"] >= theta


def metrics_at(records: list[dict], theta: float) -> dict:
    pos = [r for r in records if r["kind"] == "pos"]
    neg = [r for r in records if r["kind"] != "pos"]
    fm = sum(_returned(r, theta) for r in neg)
    look = [r for r in neg if r["kind"] == "neg_lookalike"]
    return {
        "theta": round(theta, 2),
        "recall_top1": round(sum(_returned(r, theta) and r["top_plate"] == r["truth"] for r in pos) / len(pos), 3),
        "pos_wrong_return": round(sum(_returned(r, theta) and r["top_plate"] != r["truth"] for r in pos) / len(pos), 3),
        "false_match_rate": round(fm / len(neg), 4),
        "false_match_upper95": round(wilson_upper(fm, len(neg)), 4),
        "lookalike_false_match": round(sum(_returned(r, theta) for r in look) / len(look), 3) if look else None,
    }


def choose_threshold(records: list[dict], fmr_target: float) -> dict:
    """Lowest threshold whose 95% upper bound on the false-match rate meets the target."""
    for step in range(25, 100):
        m = metrics_at(records, step / 100)
        if m["false_match_upper95"] <= fmr_target:
            return m
    return metrics_at(records, 0.99)
