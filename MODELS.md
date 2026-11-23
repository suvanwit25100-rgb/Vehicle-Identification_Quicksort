# Final model card

**Every model in the submitted system is pretrained and used as published. We did not train or fine-tune any model for it.**
The work is in how the models' uncertainty is carried through: per-character confidences, multi-frame fusion, and a
refusal gate. (`training/` contains an unused from-scratch experiment; it is not part of the system.)

Frozen on 2026-11-24 for submission. Versions: ultralytics 8.4.216, rapidocr-onnxruntime 1.4.4, onnxruntime 1.32.0,
transformers 5.24.0, torch 2.15.0, Python 3.11.

## The models

| Job | Model | Source | Licence | Size | In the repo? |
|---|---|---|---|---|---|
| Find and follow vehicles | YOLOv8n (COCO) with ByteTrack | Ultralytics | AGPL-3.0 | 6,549,796 B | yes, `backend/models/yolov8n.pt` |
| Find the plate | YOLO11 "s" plate detector | `morsetechlab/yolov11-license-plate-detection` on Hugging Face | AGPL-3.0 (stated on its page) | 19,173,715 B | yes, `backend/models/plate_s.pt` |
| Read the characters | PP-OCRv4 recogniser | bundled in the `rapidocr-onnxruntime` package | Apache-2.0 | 10,857,958 B | no, comes with the pip package |
| Body type (optional) | CLIP ViT-B/32 | `openai/clip-vit-base-patch32` on Hugging Face | **no licence is stated on its Hugging Face page** | 605,247,071 B | no, downloaded by `python backend/scripts/download_models.py` |
| Colour | none (pixel and hue analysis) | our code | n/a | n/a | n/a |

SHA-256 of the files we ran:

```
f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36  yolov8n.pt
95e50c25ab7066dd0ca5aec18fa80349676db08697780d1149576461174d2381  plate_s.pt
48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b  ch_PP-OCRv4_rec_infer.onnx
a63082132ba4f97a80bea76823f544493bffa8082296d62d71581a4feff1576f  clip-vit-b32/pytorch_model.bin
```

`backend/app/brains.py` is the in-code manifest. The monitor page and `/api/brains` show which of these are installed.
The CLIP file is checked by its exact size, so a truncated download is never treated as ready.

## How each one is used

- **YOLOv8n + ByteTrack.** Keeps four COCO classes (car, motorcycle, bus, truck) at confidence 0.3 with ByteTrack's default
  settings. A looser tracker setting cut fragmentation (29 to 23 tracks) but linked different vehicles and lost a plate, so it
  was reverted.
- **YOLO11 plate detector.** Run on each vehicle crop at confidence 0.25. Plates under about 80 px wide are flagged as too
  small instead of being read.
- **PP-OCRv4.** Only the recognition model is used. Its CTC output is limited to A-Z and 0-9, and each character's
  confidence is the raw probability the model gave it. That per-character confidence is what multi-frame fusion votes on.
- **CLIP.** Zero-shot: the vehicle crop is compared with text prompts such as "a photo of a hatchback", and the result is
  blended with the detector's class. If the file is absent the system falls back to the detector's class alone.
- **Colour.** Hue and saturation analysis of the vehicle crop, kept as a distribution, not a single label.

## What they can and cannot do (measured)

- Real Indian street clip: of 5 vehicles with a readable plate, 3 were read exactly (`UP14CA0914`, `DL8CAY4767`,
  `DL1LAJ2850`) and 2 partly (`DL9CA??014`, `DL1L??2711`). 29 vehicle tracks in all; most had no readable plate.
- A US dashcam clip: nothing readable, and the system correctly returned all unknown and no match.
- Only two real clips were ever tested, and there is no labelled evaluation set, so there is no measured accuracy figure for
  the whole pipeline.
- Body type from CLIP was close to a coin flip on real footage (a white hatchback came back as "tempo"), so it carries a low
  weight. Colour is imprecise.
- The plate grammar assumes 10 characters. A real 9-character plate (`DL1LR2711`, one series letter) appeared in our footage
  and was only partly read.
- Confidence scores are uncalibrated estimates. Agency thresholds were chosen by simulation, not on labelled footage.

## Alternatives we tested and did not adopt

Two other pretrained plate readers were run on the same plates, one crop at a time, on 2026-11-24.

| Test | Current reader | fast-plate-ocr | Awiros ANPR-OCR |
|---|---|---|---|
| 10 real crops (4 plates), exact | 70% | 70% | 80% |
| 300 synthetic, medium | 89% | 65% | 85% |
| 300 synthetic, hard | 69% | 30% | 70% |

None was clearly better alone, so none replaced the current reader. The real set is too small to prove anything, and the
synthetic plates use fonts unlike real ones. Awiros's own 98% figure was measured on its data and was not reproduced on ours.
Awiros and fast-plate-ocr also report near-100% confidence when wrong, which would weaken confidence-weighted fusion. When
PP-OCR and Awiros agreed, they were right about 99% of the time on synthetic plates, so a second-reader cross-check is a
promising next step. It is not built.

Not tested: pretrained body-type classifiers from Hugging Face (`yigechundong/car-body-classifier`,
`dima806/vehicle_10_types_image_detection`), which could replace the weak CLIP step.

## Licence note

The two YOLO models (and Ultralytics' code) are AGPL-3.0. That is fine for a hackathon submission. Deploying this as a
network service would need AGPL compliance or a commercial licence from Ultralytics; check before any deployment. CLIP's weights
are not committed here, and its Hugging Face page lists no licence, so check that too before redistributing them.

## Reproduce

```bash
cd backend && python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/download_models.py     # CLIP only, optional
python -m pytest
cd .. && python -m uvicorn app.main:app --app-dir backend --port 8000
```
