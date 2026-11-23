"""Score plate readers on a labelled set: the shipped PP-OCR reader vs your trained ONNX model.

    python evaluate.py --real-dir real --split val --onnx checkpoints/plate_crnn.onnx
    python evaluate.py --synthetic 2000 --strength 0.8 --onnx checkpoints/plate_crnn.onnx

IMPORTANT: a synthetic test set is made by the same generator the model trained on, so it flatters
the trained model against PP-OCR. Quote REAL-crop numbers (from --real-dir) as the headline result.
Real crops in the test split must never be used for training (the train/val split is by filename hash).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

import plategen
from data import RealPlates
from model import ctc_greedy

BACKEND = Path(__file__).resolve().parent.parent / "backend"
BUCKETS = [("<64 px", 0, 64), ("64-95 px", 64, 96), ("96-159 px", 96, 160), (">=160 px", 160, 10**6)]


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def load_onnx(path: str):
    import onnxruntime as ort

    sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])

    def read(img):
        probs = sess.run(None, {"image": plategen.to_model_input(img)[None]})[0][0]
        return ctc_greedy(probs)

    return read


def load_ppocr():
    sys.path.insert(0, str(BACKEND))
    from app.vision.ocr import read_plate_chars

    return read_plate_chars


def samples(args):
    if args.real_dir:
        ds = RealPlates(args.real_dir, args.split, augment=False)
        for name, text in ds.rows:
            yield text, cv2.imread(str(Path(args.real_dir) / name), cv2.IMREAD_COLOR)
    else:
        for i in range(args.synthetic):
            yield plategen.make_sample(random.Random(args.seed + i), args.strength)


def score(read, data) -> dict:
    n = exact = chars = errors = confident_wrong = 0
    by_bucket = {b[0]: [0, 0] for b in BUCKETS}
    for truth, img in data:
        out = read(img)
        pred = "".join(c for c, _ in out)
        ok = pred == truth
        n += 1
        exact += ok
        chars += len(truth)
        errors += edit_distance(pred, truth)
        if not ok and out and float(np.mean([p for _, p in out])) >= 0.8:
            confident_wrong += 1
        width = img.shape[1]
        for label, lo, hi in BUCKETS:
            if lo <= width < hi:
                by_bucket[label][0] += ok
                by_bucket[label][1] += 1
    return {"n": n, "exact": exact / n, "char_accuracy": 1 - errors / chars, "confident_wrong": confident_wrong / n,
            "by_width": {k: (v[0] / v[1] if v[1] else None, v[1]) for k, v in by_bucket.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real-dir")
    ap.add_argument("--split", default="val", choices=["val", "train", "all"])
    ap.add_argument("--synthetic", type=int, default=2000)
    ap.add_argument("--strength", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=777000, help="fixed so every run scores the same plates")
    ap.add_argument("--onnx", help="trained model to score")
    ap.add_argument("--no-ppocr", action="store_true")
    ap.add_argument("--font-dir")
    ap.add_argument("--json")
    args = ap.parse_args()
    plategen.set_font_dir(args.font_dir)

    readers = {}
    if not args.no_ppocr:
        try:
            readers["PP-OCRv4 (current)"] = load_ppocr()
        except Exception as e:  # noqa: BLE001
            print(f"[skip] PP-OCR baseline unavailable: {e}")
    if args.onnx:
        readers["trained CRNN"] = load_onnx(args.onnx)
    if not readers:
        sys.exit("nothing to evaluate: pass --onnx and/or install the backend's rapidocr")

    kind = f"REAL crops ({args.real_dir}, split={args.split})" if args.real_dir else \
        f"SYNTHETIC ({args.synthetic} plates, strength {args.strength}) - biased towards the trained model"
    print("test set:", kind)
    results = {}
    for name, read in readers.items():
        results[name] = score(read, samples(args))
    print(f"\n{'reader':22s}{'plates':>8s}{'exact':>9s}{'char acc':>10s}{'confident-wrong':>17s}")
    for name, r in results.items():
        print(f"{name:22s}{r['n']:8d}{r['exact']:9.1%}{r['char_accuracy']:10.1%}{r['confident_wrong']:17.1%}")
    print("\nexact-match by plate width (apparent resolution):")
    print(f"{'':22s}" + "".join(f"{b[0]:>14s}" for b in BUCKETS))
    for name, r in results.items():
        cells = "".join(f"{(f'{v[0]:.0%} (n={v[1]})' if v[0] is not None else '-'):>14s}" for v in r["by_width"].values())
        print(f"{name:22s}{cells}")
    if args.json:
        Path(args.json).write_text(json.dumps({"test_set": kind, "results": results}, indent=2))
        print("\nwrote", args.json)


if __name__ == "__main__":
    main()
