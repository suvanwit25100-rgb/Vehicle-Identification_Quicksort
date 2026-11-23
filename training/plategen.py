"""Synthetic Indian number-plate generator with realistic CCTV degradations.

Every sample comes with a perfect label, so it can be produced without limit.
`random_plate` follows the project's 10-slot grammar (LLDALLDDDD): two state
letters, a digit, a digit-or-letter (Delhi-style RTO codes such as 1L / 8C),
two series letters and four digits.

Run `python plategen.py --preview samples.png` to look at a grid of samples.
"""

from __future__ import annotations

import math
import os
import random
import string
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ALPHABET = string.ascii_uppercase + string.digits  # 36 symbols
IMG_H, IMG_W = 48, 192  # model input size

STATES = [("DL", 14), ("UP", 8), ("MH", 6), ("KA", 5), ("TN", 5), ("HR", 5), ("RJ", 4), ("GJ", 4),
          ("MP", 3), ("CG", 3), ("PB", 3), ("BR", 3), ("WB", 3), ("AP", 2), ("TS", 2), ("KL", 2),
          ("OD", 2), ("JH", 2), ("UK", 2), ("HP", 1), ("AS", 1), ("JK", 1), ("CH", 1), ("GA", 1)]
LETTERS_NO_IO = "".join(c for c in string.ascii_uppercase if c not in "IO")

# (background, text colour, weight): private, commercial, rental, electric
SCHEMES = [((250, 250, 250), (15, 15, 15), 55), ((245, 200, 40), (15, 15, 15), 25),
           ((15, 15, 15), (240, 200, 40), 8), ((30, 140, 70), (250, 250, 250), 6),
           ((235, 235, 225), (20, 20, 40), 6)]

_FONT_NAMES = ["arialbd.ttf", "calibrib.ttf", "verdanab.ttf", "tahomabd.ttf", "segoeuib.ttf", "consolab.ttf",
               "trebucbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf",
               "Verdana Bold.ttf", "Tahoma Bold.ttf", "DIN Alternate Bold.ttf", "Impact.ttf", "arial.ttf"]
_extra_font_dir: str | None = None


def set_font_dir(path: str | None) -> None:
    """Add a folder of .ttf/.otf files (e.g. a DIN-style or HSRP-like font) to the pool."""
    global _extra_font_dir
    _extra_font_dir = path
    find_fonts.cache_clear()


@lru_cache
def find_fonts() -> tuple[str, ...]:
    dirs = ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
            str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"),
            "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation"]
    found = [str(Path(d) / n) for d in dirs for n in _FONT_NAMES if (Path(d) / n).exists()]
    if _extra_font_dir:
        found += [str(p) for p in Path(_extra_font_dir).glob("*") if p.suffix.lower() in (".ttf", ".otf")]
    return tuple(dict.fromkeys(found))


@lru_cache(maxsize=512)
def _font(path: str | None, size: int):
    if path is None:
        return ImageFont.load_default(size)
    return ImageFont.truetype(path, size)


def random_plate(rng: random.Random) -> str:
    states, weights = zip(*STATES)
    state = rng.choices(states, weights)[0]
    d2 = rng.choice(string.digits) if rng.random() < 0.85 else rng.choice(LETTERS_NO_IO)
    series = "".join(rng.choice(LETTERS_NO_IO if rng.random() < 0.9 else string.ascii_uppercase) for _ in range(2))
    return state + rng.choice(string.digits) + d2 + series + "".join(rng.choice(string.digits) for _ in range(4))


def _jitter(colour, rng, amount=16):
    return tuple(int(min(255, max(0, c + rng.randint(-amount, amount)))) for c in colour)


def render_plate(text: str, rng: random.Random) -> np.ndarray:
    """A clean, high-resolution plate image (BGR)."""
    fonts = find_fonts()
    path = rng.choice(fonts) if fonts else None
    width = rng.randint(300, 520)
    height = max(64, int(width / rng.uniform(3.4, 5.0)))
    bg, fg, _ = rng.choices(SCHEMES, [s[2] for s in SCHEMES])[0]
    bg, fg = _jitter(bg, rng), _jitter(fg, rng, 10)
    img = Image.new("RGB", (width, height), bg)
    d = ImageDraw.Draw(img)
    border = max(2, int(height * rng.uniform(0.03, 0.07)))
    d.rounded_rectangle([0, 0, width - 1, height - 1], radius=int(height * rng.uniform(0, 0.12)),
                        outline=fg, width=border)
    x0 = border + int(0.03 * width)
    if rng.random() < 0.3:  # blue "IND" strip
        strip = int(width * 0.08)
        d.rectangle([border, border, border + strip, height - border], fill=(20, 45, 150))
        d.text((border + strip // 2, height // 2), "IND", font=_font(path, max(6, strip // 3)),
               fill=(255, 255, 255), anchor="mm")
        x0 = border + strip + int(0.02 * width)

    shown = text if rng.random() < 0.4 else f"{text[:2]} {text[2:4]} {text[4:6]} {text[6:]}"
    tracking = rng.uniform(0.0, 0.14)
    word_gap = rng.uniform(0.8, 1.6)
    avail = width - x0 - border - int(0.03 * width)
    size = max(10, int(height * rng.uniform(0.5, 0.72) / 0.72))

    def layout(sz):
        f = _font(path, sz)
        advances = [f.getlength(c) * (word_gap if c == " " else 1) + sz * tracking for c in shown]
        return f, advances, sum(advances) - sz * tracking

    font, advances, total = layout(size)
    if total > avail:
        font, advances, total = layout(max(8, int(size * avail / total * 0.98)))
    cap = -font.getbbox("H", anchor="ls")[1]
    x = x0 + max(0, (avail - total) / 2) + rng.uniform(-0.02, 0.02) * width
    baseline = height / 2 + cap / 2 + rng.uniform(-0.03, 0.03) * height
    for ch, adv in zip(shown, advances):
        if ch != " ":
            d.text((x, baseline), ch, font=font, fill=fg, anchor="ls")
        x += adv
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def _motion_kernel(length: int, angle: float) -> np.ndarray:
    k = np.zeros((length, length), np.float32)
    k[length // 2, :] = 1.0
    rot = cv2.getRotationMatrix2D((length / 2 - 0.5, length / 2 - 0.5), angle, 1.0)
    k = cv2.warpAffine(k, rot, (length, length))
    return k / max(k.sum(), 1e-6)


def degrade(img: np.ndarray, rng: random.Random, strength: float = 0.7) -> np.ndarray:
    """Make a clean plate look like a CCTV crop. strength in [0, 1] scales every effect."""
    s = float(strength)
    nrng = np.random.default_rng(rng.getrandbits(32))
    h, w = img.shape[:2]

    # context around the plate, as a detector box would include (car body, bumper)
    ph, pw = int(h * rng.uniform(0.04, 0.04 + 0.2 * s)), int(w * rng.uniform(0.03, 0.03 + 0.1 * s))
    grey = rng.randint(25, 200)
    img = cv2.copyMakeBorder(img, ph, ph, pw, pw, cv2.BORDER_CONSTANT,
                             value=(grey + rng.randint(-20, 20), grey + rng.randint(-20, 20), grey + rng.randint(-20, 20)))
    h, w = img.shape[:2]

    # lighting
    f = img.astype(np.float32)
    f = (f - 128) * (1 + rng.uniform(-0.3, 0.3) * s) + rng.uniform(-35, 35) * s
    f = 255 * np.clip(f / 255, 0, 1) ** math.exp(rng.uniform(-0.5, 0.5) * s)
    f *= np.array([1 + rng.uniform(-0.12, 0.12) * s for _ in range(3)], np.float32)
    if rng.random() < 0.35 * s + 0.05:  # shadow / uneven light
        ang = rng.uniform(0, math.pi)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        ramp = (xx * math.cos(ang) + yy * math.sin(ang))
        ramp = (ramp - ramp.min()) / max(ramp.max() - ramp.min(), 1e-6)
        f *= (1 - rng.uniform(0.15, 0.4) * ramp)[..., None]
    img = np.clip(f, 0, 255).astype(np.uint8)

    # viewing angle: perspective + small rotation
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dy = rng.uniform(-0.2, 0.2) * s * h
    dx = rng.uniform(-0.05, 0.05) * s * w
    dst = src + np.float32([[dx, dy], [-dx, -dy], [-dx, dy], [dx, -dy]])
    dst += np.float32([[rng.uniform(-1, 1) * 0.02 * s * w, rng.uniform(-1, 1) * 0.04 * s * h] for _ in range(4)])
    th = math.radians(rng.uniform(-10, 10) * s)
    c, sn = math.cos(th), math.sin(th)
    ctr = np.float32([w / 2, h / 2])
    dst = (dst - ctr) @ np.float32([[c, -sn], [sn, c]]).T + ctr
    img = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (w, h), borderMode=cv2.BORDER_REPLICATE)

    # low resolution (far vehicle)
    # The floor keeps the hardest samples borderline legible: training on text a human
    # cannot see would teach the model to guess, and its confidences would be meaningless.
    lo = max(52, int(w * (1 - 0.88 * s)))
    target_w = int(math.exp(rng.uniform(math.log(lo), math.log(w))))
    if target_w < w:
        img = cv2.resize(img, (target_w, max(4, int(h * target_w / w))), interpolation=cv2.INTER_AREA)
    cur_w = img.shape[1]

    # blur (scaled to the current size so small plates are not destroyed)
    if rng.random() < 0.65 * s + 0.1:
        img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.3, 0.3 + 1.2 * s) * min(1.0, cur_w / 160))
    if rng.random() < 0.25 * s:  # vehicles move across the frame, so blur is mostly horizontal
        k = rng.randint(3, max(4, min(9, int(0.06 * cur_w))))
        img = cv2.filter2D(img, -1, _motion_kernel(k | 1, rng.uniform(-20, 20)))

    # sensor noise
    if rng.random() < 0.75:
        noise = nrng.normal(0, rng.uniform(0, 22) * s, img.shape[:2])[..., None]
        noise = noise + nrng.normal(0, 4 * s, img.shape)
        img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    if rng.random() < 0.2 * s:  # dirt / speckle
        mask = nrng.random(img.shape[:2]) < 0.01 * s
        img[mask] = nrng.integers(0, 255, (int(mask.sum()), 1), dtype=np.uint8)

    # JPEG artefacts
    if rng.random() < 0.6:
        ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, rng.randint(18, 90)])
        if ok:
            img = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    return img


def make_sample(rng: random.Random, strength: float | None = None) -> tuple[str, np.ndarray]:
    text = random_plate(rng)
    s = rng.uniform(0.2, 1.0) if strength is None else strength
    return text, degrade(render_plate(text, rng), rng, s)


def to_model_input(img_bgr: np.ndarray) -> np.ndarray:
    """BGR crop of any size -> float32 (1, 48, 192) in [-1, 1]. The backend must use this exact preprocessing."""
    grey = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    grey = cv2.resize(grey, (IMG_W, IMG_H), interpolation=cv2.INTER_LINEAR)
    return ((grey.astype(np.float32) / 255.0 - 0.5) / 0.5)[None]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", default="samples.png")
    ap.add_argument("--font-dir")
    ap.add_argument("--strength", type=float)
    a = ap.parse_args()
    set_font_dir(a.font_dir)
    print("fonts found:", len(find_fonts()) or "none (using the built-in fallback font)")
    rng = random.Random(7)
    tiles = []
    for _ in range(24):
        text, im = make_sample(rng, a.strength)
        tile = cv2.resize(im, (384, 96))
        cv2.putText(tile, text, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)
        tiles.append(tile)
    rows = [np.hstack(tiles[i:i + 3]) for i in range(0, 24, 3)]
    cv2.imwrite(a.preview, np.vstack(rows))
    print("wrote", a.preview)
