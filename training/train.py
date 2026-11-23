"""Train the plate recogniser and export it to ONNX.

    python train.py --epochs 40                       # synthetic only
    python train.py --epochs 40 --real-dir real       # mix in real labelled crops (recommended)

Model selection uses the REAL validation split when --real-dir is given, otherwise a fixed
synthetic validation set. A synthetic score only tells you the model learned the generator;
it says little about CCTV footage, so prefer real data for the final numbers.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
from torch import nn
from torch.utils.data import DataLoader

import plategen
from data import Mixed, RealPlates, SyntheticPlates, collate
from model import PlateCRNN, ProbExport, ctc_greedy

OUT = Path(__file__).parent / "checkpoints"


def pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


@torch.no_grad()
def validate(model: PlateCRNN, loader: DataLoader, device) -> dict:
    model.eval()
    exact = chars = right = n = 0
    for images, _, _, texts in loader:
        probs = torch.softmax(model(images.to(device)).float(), dim=-1).cpu().numpy()
        for p, truth in zip(probs, texts):
            pred = "".join(c for c, _ in ctc_greedy(p))
            exact += pred == truth
            right += sum(a == b for a, b in zip(pred, truth))
            chars += len(truth)
            n += 1
    return {"exact": exact / n, "char_acc": right / chars, "n": n}


def export_onnx(model: PlateCRNN, path: Path) -> None:
    wrapper = ProbExport(model.cpu()).eval()
    dummy = torch.zeros(1, 1, plategen.IMG_H, plategen.IMG_W)
    torch.onnx.export(wrapper, dummy, str(path), input_names=["image"], output_names=["probs"],
                      dynamic_axes={"image": {0: "batch"}, "probs": {0: "batch"}}, opset_version=17, dynamo=False)
    wrapper.eval()  # torch.onnx.export restores training mode afterwards, which would skew the comparison
    x = torch.randn(3, 1, plategen.IMG_H, plategen.IMG_W)
    with torch.no_grad():
        ref = wrapper(x).numpy()
    got = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"]).run(None, {"image": x.numpy()})[0]
    diff = float(np.abs(ref - got).max())
    assert diff < 1e-3, f"ONNX output differs from PyTorch by {diff}"
    print(f"exported {path} (max difference from PyTorch: {diff:.2e})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--epoch-size", type=int, default=40000, help="samples per epoch")
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--real-dir", help="folder with labels.csv + real plate crops")
    ap.add_argument("--p-real", type=float, default=0.5, help="share of each batch drawn from real crops")
    ap.add_argument("--font-dir", help="folder of extra .ttf fonts (a DIN-like font helps realism)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--resume")
    a = ap.parse_args()

    plategen.set_font_dir(a.font_dir)
    print("fonts available to the generator:", len(plategen.find_fonts()) or "none, using built-in fallback")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    device = pick_device()
    print("device:", device)

    real_train = RealPlates(a.real_dir, "train") if a.real_dir else None
    real_val = RealPlates(a.real_dir, "val", augment=False) if a.real_dir else None
    if real_train:
        print(f"real crops: {len(real_train)} train / {len(real_val)} validation")
    train_ds = Mixed(SyntheticPlates(a.epoch_size), real_train, a.p_real)
    train_dl = DataLoader(train_ds, a.batch_size, shuffle=True, num_workers=a.workers, collate_fn=collate,
                          persistent_workers=a.workers > 0, drop_last=True)
    val_sets = {"synthetic": DataLoader(SyntheticPlates(2000, fixed=True, strength=0.7), 256, collate_fn=collate)}
    if real_val:
        val_sets["real"] = DataLoader(real_val, 256, collate_fn=collate)
    select_on = "real" if real_val else "synthetic"

    model = PlateCRNN().to(device)
    if a.resume:
        model.load_state_dict(torch.load(a.resume, map_location=device))
    print(f"parameters: {sum(p.numel() for p in model.parameters()):,}")
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, a.lr, total_steps=a.epochs * len(train_dl), pct_start=0.15)
    ctc = nn.CTCLoss(blank=0, zero_infinity=True)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")

    best, log = -1.0, open(out / "train_log.jsonl", "a")
    for epoch in range(1, a.epochs + 1):
        model.train()
        t0, total = time.time(), 0.0
        for images, targets, lengths, _ in train_dl:
            images = images.to(device)
            with torch.autocast(device.type, enabled=device.type == "cuda"):
                logits = model(images)
            log_probs = logits.float().log_softmax(-1).transpose(0, 1)  # (T, N, C)
            in_len = torch.full((images.size(0),), log_probs.size(0), dtype=torch.long)
            loss = ctc(log_probs.cpu(), targets, in_len, lengths)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss.to(device)).backward()
            scaler.unscale_(opt)
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            total += float(loss)
        scores = {k: validate(model, dl, device) for k, dl in val_sets.items()}
        rec = {"epoch": epoch, "loss": total / len(train_dl), "seconds": round(time.time() - t0, 1), **scores}
        print(json.dumps(rec))
        log.write(json.dumps(rec) + "\n")
        log.flush()
        torch.save(model.state_dict(), out / "last.pt")
        if scores[select_on]["exact"] > best:
            best = scores[select_on]["exact"]
            torch.save(model.state_dict(), out / "best.pt")
            print(f"  new best on {select_on}: exact {best:.3f}")

    model.load_state_dict(torch.load(out / "best.pt", map_location=device))
    export_onnx(model, out / "plate_crnn.onnx")


if __name__ == "__main__":
    main()
