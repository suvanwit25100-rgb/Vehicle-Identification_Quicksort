# Netra: full project handoff

*(The project was called PlateTrace until 2026-11-23. Netra means "the eye" in Hindi.)*

Written 2026-11-23. **Final evaluation: evening of 2026-11-24.** The mid evaluation went smoothly.
This file is the complete state of the project so a new machine (the RTX 4050 laptop) and a new Claude Code
session can pick it up without the earlier conversation. Start with section 10 for the first-session prompt.

---

## 1. The project

College hackathon, problem **AIML-01, Option A: Vehicle Identification and Traceability from CCTV Footage**.

**Must-haves:** multi-frame plate recovery (characters that cannot be read are marked unknown, never invented);
colour and body-type extraction; registry matching with a ranked top 5, a confidence and reasons; a
"no confident match" outcome; an investigator UI and a per-clip report (frames used, characters per frame with
confidence, reasoning).
**Bonus:** make/model recognition, cross-camera tracking.
**Deliverables:** working app, matching/ranking algorithm, per-clip analysis report.

**Departments locked in** (one engine, per-department config): Police, MoRTH/NHAI, BSF, SSB, Customs.

## 2. Evaluator feedback from the mid evaluation (this is the work for the final)

1. **Train on a plate-only dataset**, with augmentation for different angles (Gaussian noise and similar), for
   better accuracy. This reverses an earlier "no training" decision; training is now in scope.
2. **Cleaner UI/UX.** The site only restates the problem statement. Build sections for the features we built, a
   section to **monitor** them, and a **complaint-logging** section where any user in the country can submit a
   camera photo of a car.

That was the complete feedback. Suggested order: (a) get a real labelled plate set and a baseline, (b) train and
compare in parallel with (c) the site rebuild, (d) complaints last. See sections 7 to 9.

## 3. How it works (pipeline, stack, core logic)

```
video -> sample frames (6 fps) -> detect + track vehicles -> detect plate per vehicle per frame
      -> OCR into 10 slots with per-character confidence -> multi-frame fusion -> merge duplicate tracks
      -> colour + body type -> registry matching + refusal gate -> explanations -> console UI + HTML report
```

| Layer | Used |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2, pytest |
| Vehicles | YOLOv8n (COCO car/motorcycle/bus/truck) + ByteTrack, conf 0.3 (`app/vision/detectors.py`) |
| Plates | YOLO11 plate detector `models/plate_s.pt` (morsetechlab/yolov11-license-plate-detection, s variant, AGPL-3.0) |
| OCR | PP-OCRv4 recogniser from `rapidocr-onnxruntime`, CTC output restricted to A-Z0-9, per-character confidence (`app/vision/ocr.py`) |
| Body type | CLIP ViT-B/32 zero-shot, fused with the COCO class prior (`app/vision/attributes.py`, `clip_brain.py`) |
| Colour | pixel-distribution analysis on the vehicle crop |
| Registry | `data/registry.csv`, 300 synthetic rows incl. Delhi-style RTO codes and 12 near-duplicates (`scripts/make_registry.py`) |
| Frontend | static site served by FastAPI: landing `/`, console `/console/`; dark HUD theme from the supplied background image; fonts Oxanium / Rajdhani / JetBrains Mono |

**Core logic (the rules that must survive any change):**

- **The track is the unit of evidence.** Every decision uses many frames, never one.
- **Plate grammar:** 10 slots, kinds `LLDALLDDDD` (`SLOT_KINDS` in `app/fusion.py`). Slot 3 is "A" (letter or digit)
  because Delhi RTO codes look like `1L`, `8C`; it is never coerced. Other slots coerce letter<->digit
  confusions with a 0.8 confidence discount. `align_to_slots` in `plate_text.py` tolerates one extra or missing
  leading/trailing OCR character (`best_offset`).
- **Fusion** (`fuse_frames`): per-slot weighted vote, weight = character confidence x sharpness (Laplacian
  variance) x plate area. A character is accepted only if its score >= `slot_accept` (0.60) and it beats the
  runner-up by `slot_margin` (0.25); `unknown_prior` is 0.30. Otherwise the slot is `?`. **Unknown is a valid answer.**
- **Track stitching** (`app/vision/stitch.py`): merge two tracks only if their fused plates agree on >= 6
  characters and clash on none; a group grows only if every pair is compatible.
- **Matching** (`app/matcher.py`): `plate_fit = sum(conf of matched known slots) / 10`; combined with colour and
  body fits using per-department weights; weights renormalise if an attribute is absent; mismatch penalty;
  top 5 with reasons.
- **Refusal gate:** per-department threshold, `min_known_chars`, `max_known_mismatches`. Statuses: `match`,
  `ambiguous`, `no_confident_match`, `insufficient_evidence`.
- **Per-department config** (`app/departments.yaml`, loaded by `app/config.py`): thresholds police 0.66,
  morth_nhai 0.61, bsf 0.59, ssb 0.62, customs 0.62; min known chars 4/5/6/5/5; max known mismatches 1/1/0/1/1.
- **Calibration** (`app/calibration.py`, `scripts/calibrate.py`, output `data/calibration_report.json`): by
  simulation (easy/medium/hard sightings; in-registry positives; lookalike and random negatives); the threshold is
  chosen with the Wilson upper bound on the false-match rate. It rests on assumed noise, not on labelled data.
- **Report** (`app/report.py`): one self-contained HTML file (CSS inline, plate crops embedded as base64) with the
  input SHA-256, frames used, characters per frame with confidence, ranked candidates with reasons.

## 4. Repo map

```
backend/
  app/            main.py (API + static), fusion.py, matcher.py, config.py, departments.yaml, registry.py,
                  calibration.py, schemas.py, report.py, brains.py, vision/ (pipeline, detectors, ocr,
                  plate_text, attributes, clip_brain, video, stitch), static/ (landing + console)
  scripts/        make_registry.py, calibrate.py, download_models.py
  tests/          95 tests (fusion, matcher, API, stitching, pipeline, calibration, reports, brains)
  models/         yolov8n.pt, plate_s.pt (committed); clip-vit-b32/ (download, see below)
  data/           registry.csv, calibration_report.json
training/         plate recogniser training kit (section 7); see training/README.md
.claude/launch.json   preview config
```

API: `/api/health`, `/api/departments`, `/api/match`, `/api/analyze`, `/api/brains`, `/api/registry/sample`,
`/api/jobs/{id}`, `/api/jobs/{id}/report`, `/api/jobs/{id}/crops/{name}`.

## 5. Run it

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
# On an NVIDIA GPU install the CUDA build of torch from pytorch.org first
pip install -r requirements.txt
python scripts/download_models.py          # CLIP, ~577 MB, optional (body type falls back to the COCO prior)
python -m pytest                           # 95 tests; those needing weights skip if they are missing
cd .. && python -m uvicorn app.main:app --app-dir backend --port 8000
```

Open http://localhost:8000 (landing) and http://localhost:8000/console/. The device is CPU by default; set
`NETRA_DEVICE=cuda` to run the detectors on the GPU. `.claude/launch.json` uses the macOS venv path; on
Windows change it to `backend/.venv/Scripts/python.exe`.

## 6. Status and results so far

Real-footage test (Indian street clip, 1920x1080, hand-held): 29 tracks, 5 with a readable plate:
`UP14CA0914`, `DL8CAY4767`, `DL1LAJ2850` read exactly; `DL9CA??014` and `DL1L??2711` partial. A US dashcam clip:
nothing readable, all unknown, 0 matches (the refusal behaves correctly). **Only two real clips have ever been
tested, and there is no labelled evaluation set**, so there are no measured accuracy numbers for the full system.

Honest confidence per component: vehicle detection medium-high; tracking medium-low (fragmentation); plate
detector medium (plates under ~80 px are not read; `MIN_PLATE_PX = 80` produces a "too small" note); OCR medium on
large clear plates, low otherwise; fusion logic medium-high but tested on two clips; **CLIP body type low (about a
coin flip on real footage; a white hatchback came back as "tempo")**; colour low-medium; matcher and gate medium.
Confidence scores shown in the app are uncalibrated estimates, and the report footer says so.

Known weaknesses and dead ends (do not repeat these):

- **Track fragmentation.** Sampling rate is not the cause (more fps made it worse: 29 tracks at 6 fps, 76 at 30
  fps). `match_thresh=0.9` cut 29 to 23 tracks but linked different vehicles and **lost the plate `DL9CA??014`**, so it
  was reverted (see the comment on `TRACKER_CFG` in `detectors.py`). Buffer length and low-confidence threshold did
  nothing; BoT-SORT was mixed. Plate-based merging is in and tested but changed nothing on the Indian clip.
  Fragments are mostly unreadable vehicles and are collapsed in the UI.
- BSF, SSB and Customs refuse some correct reads because attribute weighting is weak (CLIP).
- Not built: PDF export (the report prints to PDF from the browser), department-specific features (watch-lists,
  FASTag, repeat crossing), make/model, cross-camera tracking.

## 7. Training track (evaluator item 1): state of the kit

`training/` is built and smoke-tested. See `training/README.md` for the exact commands.

- `plategen.py`: unlimited synthetic Indian plates (white/yellow/black/green schemes, several fonts, IND strip,
  Delhi-style RTO codes) with augmentation: perspective and rotation (viewing angle), Gaussian and speckle noise,
  blur and mostly-horizontal motion blur, low resolution, uneven light, JPEG artefacts. **Hardest samples are kept
  borderline legible on purpose**: my first version produced unreadable smears, and training on text a human cannot
  read teaches the model to guess, which breaks the "never invent" rule and ruins the confidences.
- `model.py`: plate-only CRNN + CTC, about 2.04M parameters. Input `(N,1,48,192)` float32 in [-1,1] via
  `plategen.to_model_input` (grey, resize, scale). Output `(N,48,37)` probabilities; index 0 is the CTC blank,
  1..36 are `A-Z0-9`. `ctc_greedy` returns `(char, confidence)` with confidence = peak probability within the run,
  matching how `ocr.py` does it for PP-OCR.
- `train.py`: AdamW + OneCycle, CUDA autocast, optional `--real-dir` mixing (`--p-real` 0.5), model selection on
  the real validation split if given, ONNX export with a PyTorch-vs-ONNX check (max difference measured 2e-7).
- `data.py`: `RealPlates` reads `labels.csv` (`filename,text`), cleans labels, holds out ~10% by filename hash.
- `evaluate.py`: scores PP-OCR and the trained ONNX on the same plates: exact match, character accuracy,
  "confidently wrong" rate, accuracy by plate width.

Verified: generator output viewed and tuned; train / validate / export run end to end; real-crop path tested on a
fake folder; evaluate.py runs; the model learns on synthetic data (below).

**Learning test (finished):** 12 epochs x 20,000 synthetic plates on the Mac (about 18 minutes, MPS). The loss sat
flat near 3 for four epochs, as CTC usually does, then broke out at epoch 5 and ended at **94.9% exact / 99.0%
character accuracy on its synthetic validation set (strength 0.7)**. On 500 fresh synthetic plates (strength 0.8):

| reader | exact | character acc | confidently wrong |
|---|---|---|---|
| PP-OCRv4 (current) | 68.8% | 91.7% | 20.0% |
| trained CRNN | 89.6% | 98.0% | 7.6% |

**Read this carefully:** that test set comes from the same generator the CRNN trained on, so it flatters the CRNN.
It proves the kit works and the model can learn plate reading; it does **not** prove the model beats PP-OCR on real CCTV
footage. Nothing has been run on real crops or on the GPU yet. **Do not claim an accuracy gain until `evaluate.py`
shows it on real held-out crops.** Expect the synthetic-to-real gap to cost accuracy; mixing real crops into training
(`--real-dir`) is the main defence. On the 4050 use the default 40 epochs x 40,000 samples.

Gotchas found while building it: the legacy ONNX exporter needs the `onnx` package and `dynamo=False`;
`AdaptiveAvgPool2d((1, None))` does not export (replaced by a mean over height); `torch.onnx.export` puts the model
back into training mode afterwards, so verify in eval mode; DataLoader workers use spawn (Windows, macOS), so
scripts must be real files with a `__main__` guard.

**What is needed next, in order:**

1. **A real labelled plate-crop dataset** (crops plus the text of each plate). Detection-only datasets (boxes
   only) are no use for the recogniser. The three Roboflow links looked at earlier were detection datasets, so a
   conversion or a different source is needed. Check licences.
2. Run `training/README.md` steps 2 to 5 on the 4050; compare against PP-OCR on real crops with `evaluate.py`.
3. **If, and only if, it wins on real crops**, wire it into the backend: in `app/vision/ocr.py`, load
   `training/checkpoints/plate_crnn.onnx` (copy it to `backend/models/`), preprocess with the same
   `to_model_input`, run it, take `probs[0]` of shape `(48,37)`, decode with `ctc_greedy`, and return
   `[(char, conf)]` exactly as `read_plate_chars` does today. Keep PP-OCR as a fallback (env switch). Re-run the
   95 tests and the real clip.
4. Optional track B: fine-tune the plate detector with Ultralytics (command in the training README), measure recall
   before and after.
5. Build a small labelled real-clip evaluation (10 to 20 clips with the true plates written down) so the full pipeline has
   real numbers. The scoring harness for the full pipeline was started earlier and not kept; `evaluate.py` only
   covers the OCR step.

## 8. Site rebuild (evaluator item 2): thinking so far, nothing built

- **Feature sections** showing real output, not prose: multi-frame fusion (per-frame votes collapsing into one
  plate), the refusal gate (a refused case with its reason), per-department config side by side, calibration curves
  from `calibration_report.json`, the audit report.
- **Monitoring section:** model readiness (`/api/brains`), jobs run, outcomes by status, confidence distributions,
  per-department activity. Jobs are only files on disk today; real monitoring needs a small database (SQLite is enough).
  Do not show invented numbers: read from stored job history.
- **Complaint logging:** a mobile-friendly page (`<input type="file" accept="image/*" capture="environment">`)
  where a citizen uploads a photo, the system reads the plate, the citizen confirms or edits it, adds location,
  time and category, and it lands in a department queue with an officer triage view.
  Design rules: a single photo has no multi-frame fusion, so more characters will be `?` and the plate must be
  editable and shown as "to be verified". **Citizens must never see owner details from the registry; only officers.**
  A complaint is a lead, not a verdict. Plan for false or malicious complaints (rate limits, officer verification),
  faces and personal data in photos (India's DPDP Act), consent and retention, and use EXIF time/GPS as supporting
  evidence with a hash of each image. "Any user in the country" needs authentication: simple role-based login is fine
  for the demo, and say that real OTP sign-in is the production answer.
  Nice tie-in: several complaints about the same vehicle act as extra frames, so fusing their plate reads is the
  cross-camera tracking bonus.

## 9. Ground rules, preferences and history

- **Never invent characters; refuse when evidence is thin; show the evidence.** This is the project's identity.
- Report outcomes faithfully. No accuracy numbers that were not measured. State limitations before a judge finds them.
- Prefer one-sentence honest summaries over hype. Confirm before anything outward-facing (pushing, downloading).
- The user (head of the AIML club) asked earlier to avoid writing a scoring harness without asking first, and to
  fix things one at a time (shifted reads, UI noise, calibration, track splitting were each separate requests).
- Real clips used so far are not in the repo (large, and they show real vehicles): `14851570_1920_1080_30fps.mp4`
  (Indian street) and `13588978_1280_720_30fps.mp4` (US dashcam), both on the original machine's Desktop.
  `backend/app/static/data/demo_clear.json` holds real frame reads from the Indian clip for the landing-page demo.
  **Keep this repository private.**
- Model licences: YOLOv8n and the plate detector are AGPL-3.0; PP-OCRv4 via rapidocr is Apache-2.0; CLIP's licence
  should be checked on its model card before any distribution.

## 10. First prompt for Claude Code on the new machine

> Read HANDOFF.md and training/README.md in this repo. Set up the environment (section 5), confirm
> `torch.cuda.is_available()` is True, run the tests, then look at the generated plate samples
> (`python plategen.py --preview samples.png` in training/). I will give you a real labelled plate dataset next.
> Work on the training track in section 7, in order, and report real-crop numbers from `training/evaluate.py`.
> Do not claim an improvement before it is measured on held-out real crops. Final evaluation is the evening of
> 2026-11-24, so keep a working demo at every step.
