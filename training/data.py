"""Datasets: unlimited synthetic plates, plus real labelled plate crops when you have them.

Real data layout (any image sizes, any number of sub-folders is NOT supported, keep it flat):

    real/
      labels.csv        header: filename,text      e.g.  img_0001.jpg,DL8CAY4767
      img_0001.jpg
      ...

Only A-Z and 0-9 are kept from the text; rows with an empty label are skipped.
"""

from __future__ import annotations

import csv
import hashlib
import random
import re
from pathlib import Path

import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

import plategen
from model import encode


def _clean(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _item(img_bgr: np.ndarray, text: str):
    return torch.from_numpy(plategen.to_model_input(img_bgr)), torch.tensor(encode(text), dtype=torch.long), text


class SyntheticPlates(Dataset):
    """fixed=True gives a reproducible set (for validation); otherwise every access is a fresh sample."""

    def __init__(self, size: int, fixed: bool = False, strength: float | None = None, seed: int = 12345):
        self.size, self.fixed, self.strength, self.seed = size, fixed, strength, seed

    def __len__(self) -> int:
        return self.size

    def __getitem__(self, i: int):
        rng = random.Random(self.seed + i) if self.fixed else random.Random()
        text, img = plategen.make_sample(rng, self.strength)
        return _item(img, text)


class RealPlates(Dataset):
    """Labelled real crops. split='val' takes a stable ~10% by filename hash (the model never trains on it)."""

    def __init__(self, root: str, split: str = "train", augment: bool = True, val_fraction: float = 0.1):
        self.root, self.augment = Path(root), augment
        rows = []
        with open(self.root / "labels.csv", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                text = _clean(r["text"])
                if text and (self.root / r["filename"]).exists():
                    h = int(hashlib.md5(r["filename"].encode()).hexdigest(), 16) % 1000
                    is_val = h < val_fraction * 1000
                    if split == "all" or (split == "val") == is_val:
                        rows.append((r["filename"], text))
        if not rows:
            raise ValueError(f"no usable rows for split '{split}' in {root}/labels.csv")
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i: int):
        name, text = self.rows[i]
        img = cv2.imread(str(self.root / name), cv2.IMREAD_COLOR)
        if self.augment:
            img = plategen.degrade(img, random.Random(), strength=random.uniform(0.05, 0.5))
        return _item(img, text)


class Mixed(Dataset):
    """Each access draws from the real set with probability p_real, otherwise a fresh synthetic plate."""

    def __init__(self, synthetic: SyntheticPlates, real: RealPlates | None, p_real: float):
        self.synthetic, self.real, self.p_real = synthetic, real, p_real

    def __len__(self) -> int:
        return len(self.synthetic)

    def __getitem__(self, i: int):
        if self.real is not None and random.random() < self.p_real:
            return self.real[random.randrange(len(self.real))]
        return self.synthetic[i]


def collate(batch):
    images, targets, texts = zip(*batch)
    return (torch.stack(images), torch.cat(targets),
            torch.tensor([len(t) for t in targets], dtype=torch.long), list(texts))
