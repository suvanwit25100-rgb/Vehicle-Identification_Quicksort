"""Fetch the CLIP weights (about 577 MB), which are too large to keep in git.

    python scripts/download_models.py

YOLOv8n and the plate detector (plate_s.pt) are committed in backend/models.
CLIP is optional: without it the system falls back to the COCO class prior for body type.
"""

from pathlib import Path

from huggingface_hub import snapshot_download

DEST = Path(__file__).resolve().parents[1] / "models" / "clip-vit-b32"
EXPECTED_BYTES = 605_247_071  # app/brains.py checks this exact size

if __name__ == "__main__":
    DEST.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        "openai/clip-vit-base-patch32", local_dir=str(DEST),
        allow_patterns=["config.json", "preprocessor_config.json", "tokenizer.json", "tokenizer_config.json",
                        "vocab.json", "merges.txt", "special_tokens_map.json", "pytorch_model.bin"],
    )
    size = (DEST / "pytorch_model.bin").stat().st_size
    if size != EXPECTED_BYTES:
        raise SystemExit(f"pytorch_model.bin is {size} bytes, expected {EXPECTED_BYTES}. Delete it and run again.")
    print("CLIP ready at", DEST)
