"""Plate-only CRNN + CTC recogniser (about 2M parameters).

Input  (N, 1, 48, 192) float32 in [-1, 1]   (see plategen.to_model_input)
Output (N, 48, 37) per-step probabilities; index 0 is the CTC blank and
index i (1..36) is ALPHABET[i - 1]. The ONNX export bakes in the softmax, so the
backend can read per-character confidence exactly as it does with PP-OCR.
"""

from __future__ import annotations

import numpy as np
import torch
from torch import nn

from plategen import ALPHABET

N_CLASSES = len(ALPHABET) + 1


def _conv(i: int, o: int) -> nn.Sequential:
    return nn.Sequential(nn.Conv2d(i, o, 3, padding=1, bias=False), nn.BatchNorm2d(o), nn.ReLU(inplace=True))


class PlateCRNN(nn.Module):
    def __init__(self, hidden: int = 128):
        super().__init__()
        self.cnn = nn.Sequential(
            _conv(1, 32), nn.MaxPool2d(2, 2),                       # 24 x 96
            _conv(32, 64), nn.MaxPool2d(2, 2),                      # 12 x 48
            _conv(64, 128), _conv(128, 128), nn.MaxPool2d((2, 1)),  # 6 x 48
            _conv(128, 192), _conv(192, 192), nn.MaxPool2d((2, 1)), # 3 x 48
            _conv(192, 256),                                        # 3 x 48, height averaged in forward()
        )
        self.rnn = nn.LSTM(256, hidden, num_layers=2, bidirectional=True, batch_first=True, dropout=0.1)
        self.fc = nn.Linear(2 * hidden, N_CLASSES)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # logits (N, T, C)
        f = self.cnn(x).mean(dim=2).transpose(1, 2)  # (N, T, 256)
        out, _ = self.rnn(f)
        return self.fc(out)


class ProbExport(nn.Module):
    """Wrapper used for ONNX export: logits -> probabilities."""

    def __init__(self, model: PlateCRNN):
        super().__init__()
        self.model = model

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.softmax(self.model(x), dim=-1)


def encode(text: str) -> list[int]:
    return [ALPHABET.index(c) + 1 for c in text]


def ctc_greedy(probs: np.ndarray) -> list[tuple[str, float]]:
    """probs (T, C) -> [(char, confidence)]. Confidence is the peak probability within the character's run."""
    idx, peak = probs.argmax(axis=1), probs.max(axis=1)
    out: list[tuple[str, float]] = []
    prev, best = 0, 0.0
    for t in range(len(idx)):
        i = int(idx[t])
        if i == prev:
            if i:
                best = max(best, float(peak[t]))
            continue
        if prev:
            out.append((ALPHABET[prev - 1], best))
        prev, best = i, (float(peak[t]) if i else 0.0)
    if prev:
        out.append((ALPHABET[prev - 1], best))
    return out
