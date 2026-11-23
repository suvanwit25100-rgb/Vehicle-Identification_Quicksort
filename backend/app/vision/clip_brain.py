"""Zero-shot classification and appearance embeddings with a local CLIP model.

Loads from disk only (local_files_only), so a missing model raises instead of
triggering a silent download.
"""

from pathlib import Path

import cv2
import numpy as np

from .detectors import DEVICE, MODELS_DIR

LOGIT_SCALE = 100.0


def _as_tensor(x):
    # transformers >= 5 returns an output object whose pooler_output is the projected embedding
    return x if hasattr(x, "shape") else x.pooler_output


class ClipBrain:
    def __init__(self, path: Path | None = None):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        p = Path(path or MODELS_DIR / "clip-vit-b32")
        self._torch = torch
        self.model = CLIPModel.from_pretrained(p, local_files_only=True).to(DEVICE).eval()
        self.processor = CLIPProcessor.from_pretrained(p, local_files_only=True)
        self._label_cache: dict[tuple, tuple[list[str], object]] = {}

    def _image_features(self, crops_bgr: list[np.ndarray]):
        from PIL import Image

        torch = self._torch
        imgs = [Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB)) for c in crops_bgr]
        inputs = self.processor(images=imgs, return_tensors="pt").to(DEVICE)
        with torch.no_grad():
            feats = _as_tensor(self.model.get_image_features(**inputs))
        return torch.nn.functional.normalize(feats, dim=-1)

    def _label_features(self, labels: dict[str, list[str]]):
        key = tuple((k, tuple(v)) for k, v in labels.items())
        if key in self._label_cache:
            return self._label_cache[key]
        torch = self._torch
        names, rows = [], []
        for name, prompts in labels.items():
            inputs = self.processor(text=prompts, return_tensors="pt", padding=True).to(DEVICE)
            with torch.no_grad():
                f = torch.nn.functional.normalize(_as_tensor(self.model.get_text_features(**inputs)), dim=-1)
            rows.append(torch.nn.functional.normalize(f.mean(dim=0), dim=-1))
            names.append(name)
        self._label_cache[key] = (names, torch.stack(rows))
        return self._label_cache[key]

    def classify(self, crops_bgr: list[np.ndarray], labels: dict[str, list[str]]) -> list[dict[str, float]]:
        if not crops_bgr:
            return []
        torch = self._torch
        names, text = self._label_features(labels)
        img = self._image_features(crops_bgr)
        probs = torch.softmax(LOGIT_SCALE * img @ text.T, dim=-1).cpu().numpy()
        return [{n: round(float(p), 4) for n, p in zip(names, row)} for row in probs]

    def embed(self, crop_bgr: np.ndarray) -> np.ndarray:
        return self._image_features([crop_bgr])[0].cpu().numpy()
