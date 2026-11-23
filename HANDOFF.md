# Netra: full project handoff

*(The project was called PlateTrace until 2026-11-23. Netra means "the eye" in Hindi.)*

Written 2026-11-23. **Submission: morning of 2026-11-25. The model stack is final: see `MODELS.md`.** The mid evaluation went smoothly.
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
   better accuracy. **Decision on 2026-11-24: the user chose pretrained models for everything, so our own training
   is parked** (the kit stays in `training/`). Section 7 holds what was measured instead.
2. **Cleaner UI/UX.** The site only restates the problem statement. Build sections for the features we built, a
   section to **monitor** them, and a **complaint-logging** section where any user in the country can submit a
   camera photo of a car.

That was the complete feedback. With training parked, the main remaining work is the site rebuild (section 8), then
optional accuracy ideas (section 7a). See sections 7 to 9.

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
| Frontend | static multi-page site served by FastAPI: landing `/`, features `/features/`, console `/console/`, monitor `/monitor/`, citizen reports `/report-issue/`, officer desk `/desk/`. Dark navy and red palette from the hero image (`img/hero.webp`); fonts Unbounded (display), Manrope (body), JetBrains Mono (plates), loaded from Google Fonts; no project name is shown on the landing page by request |

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
                  plate_text, attributes, clip_brain, video, stitch), static/ (7 pages: ui.css/ui.js shared, per-page js), export.py (case file), crosscheck.py, complaints.py, monitor.py
  scripts/        make_registry.py, calibrate.py, download_models.py
  tests/          122 tests (fusion, matcher, API, stitching, pipeline, calibration, reports, brains, complaints, monitor, pages)
  models/         yolov8n.pt, plate_s.pt (committed); clip-vit-b32/ (download, see below)
  data/           registry.csv, calibration_report.json
training/         plate recogniser training kit (section 7); see training/README.md
.claude/launch.json   preview config
```

API: `/api/health`, `/api/departments`, `/api/match`, `/api/analyze`, `/api/brains`, `/api/registry/sample`,
`GET /api/jobs` (every stored analysis; `?plate=` finds a whole or partial plate across videos, ? matches any character), `/api/jobs/{id}`, `/api/jobs/{id}/report`, `/api/jobs/{id}/crops/{name}` (plate, vehicle and evidence images), `/api/jobs/{id}/download` (the whole case as a ZIP; `?include_video=false` leaves the video out), `/api/monitor`, and the citizen/officer set: `/api/complaints/categories`, `POST /api/complaints/preview` (photo to plate read, files nothing), `POST /api/complaints`, `/api/complaints/{id}/status` (public, no registry data), and `/api/desk/complaints[/{id}[/photo|/plate]]` (officer only, header `X-Officer-Key`). There is no built-in key: set `NETRA_OFFICER_KEY` before starting the server, or a random key is generated per run and printed once in the server log as "Officer key for this run".

## 5. Run it

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
# On an NVIDIA GPU install the CUDA build of torch from pytorch.org first
pip install -r requirements.txt
python scripts/download_models.py          # CLIP, ~577 MB, optional (body type falls back to the COCO prior)
python -m pytest                           # 122 tests; those needing weights skip if they are missing
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

## 7. Plate OCR accuracy (evaluator item 1)

### 7a. Pretrained plate readers compared (2026-11-24, measured)

The user decided on pretrained models only. Two ready-made plate readers were downloaded into an isolated test
environment (not part of the app) and compared with the current reader on the same plates:

- **Awiros ANPR-OCR** (`Awiros/anpr-ocr` on Hugging Face, Apache-2.0): PP-OCRv5 architecture fine-tuned by its
  authors on Indian plates; needs PaddlePaddle plus a clone of PaddleOCR (~232 MB) and 149 MB of weights. Per-character
  confidence was extracted from its CTC probability table.
- **fast-plate-ocr** (`cct-s-v2-global-model`, MIT): 5 MB ONNX, trained on plates from many countries, 10 slots with a
  probability per slot.
- **PP-OCRv4 (current)**: our decoder, restricted to A-Z0-9.

Test sets: **10 real crops** from the Indian clip (4 plates; truth read by eye from the crops; a hand-occluded plate and a
34 px fragment were left out) and **2 x 300 synthetic plates** from `training/plategen.py` (strength 0.5 and 0.8). None of
the readers trained on that generator. Exact match per plate, single crop (no multi-frame fusion):

| Set | PP-OCRv4 (current) | fast-plate-ocr | Awiros ANPR-OCR |
|---|---|---|---|
| real, 10 crops | 70% exact, 81% char | 70% exact, 96% char | **80% exact, 94% char** |
| synthetic, mid | **89%** | 65% | 85% |
| synthetic, hard | 69% | 30% | **70%** |

**Honest reading of this:**

- **No reader clearly beats the current PP-OCR.** Awiros is ahead by one crop on the 10 real ones (too small to mean
  anything) and level on the hard synthetic set; fast-plate-ocr is clearly worse here. Awiros's own claim of 98.4% was
  measured on its own data and was **not** reproduced on ours.
- The synthetic sets use fonts and spacing unlike real Indian plates, so they probably understate models trained on real
  plates. Treat them as a stress test, not as real accuracy.
- **Confidence behaviour differs.** Awiros and fast-plate-ocr report near-1.0 confidence even when wrong (mean confidence
  of wrong answers 0.91 and 0.99 on the real crops), while PP-OCR with our decoder is more informative (0.90 right vs
  0.52 wrong). The multi-frame fusion weights votes by confidence, so saturated confidences would help it less.
- **Agreement between two readers is a strong signal.** PP-OCR and Awiros agree on the whole plate for 78% (mid) and
  57% (hard) of synthetic plates, and **when they agree they are right 99.6% and 98.8% of the time**. When they disagree,
  one of them is right 85% and 61% of the time. On the 10 real crops: agree on 7, all 7 right. This suggests using a
  second reader as a cross-check (agree: trust; disagree: mark for verification), not as a replacement. **This is now built (see
  7a-2)**, using fast-plate-ocr rather than Awiros, because Awiros needs PaddlePaddle in the backend.
- A 9-character plate (`DL1LR2711`, one series letter) appeared in the real clip. Both new readers read it; our
  10-slot grammar (`LLDALLDDDD`) cannot represent it and produced `DL1L??2711`. Real plates can have 1 to 3 series letters.
- Not measured: speed of each reader on CPU, and body-type or colour models. Candidates found by search only (not
  downloaded or tested): `yigechundong/car-body-classifier` (EfficientNetV2-S, 8 body types; its card says outputs need
  temperature calibration and it is for prototypes) and `dima806/vehicle_10_types_image_detection` (ViT, Apache-2.0)
  for body type, which could replace the weak CLIP step. No documented pretrained colour model was found.

### 7a-2. Second-reader cross-check (built 2026-11-24)

`app/vision/second.py` runs fast-plate-ocr's `cct-s-v2-global-model` (MIT, 5 MB ONNX, files in `backend/models/fast-plate-ocr/`) on each
vehicle's sharpest plate crops, takes the most common reading, fits it to the same ten slots (`align_to_slots`), and `app/crosscheck.py`
compares it with the fused plate: **agrees** (no clash, at least 4 known characters confirmed), **disagrees** (any clash), or
**inconclusive**. It never changes the plate and never fills in a `?`. If the package or files are missing the feature switches off and
nothing else changes. Evidence for choosing it: fast-plate-ocr agreed with PP-OCR on 7 of 10 real crops (6 of those right) and was right
about 98% of the time when they agreed on 300 synthetic plates (small real sample; synthetic plates use unrealistic fonts). On the real
Indian clip it agreed on all five readable vehicles. Awiros agreed more often and was right on all 7 real agreements, but needs PaddlePaddle.
Each frame read also keeps its `raw` whole-plate string; the console shows the most common ones, which reveals that the 9-character plate
`DL1LR2711` was read whole by the first reader and only the ten-slot fitting dropped its `R`. The 9-character grammar is deliberately unchanged
(a test locks it in): a one-letter series does not fit the ten-slot model cleanly, and placing it could create false mismatches.

### 7b. Parked: our own training kit

The from-scratch training kit below was built before the decision. It works (see the learning test), but it is **not
the plan**; do not spend time on it unless the user asks. Details kept for reference.

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

**If training is ever resumed, what is needed, in order:**

1. **A real labelled plate-crop dataset** (crops plus the text of each plate). Detection-only datasets (boxes
   only) are no use for the recogniser. The three Roboflow links looked at earlier were detection datasets, so a
   conversion or a different source is needed. Check licences.
2. Run `training/README.md` steps 2 to 5 on the 4050; compare against PP-OCR on real crops with `evaluate.py`.
3. **If, and only if, it wins on real crops**, wire it into the backend: in `app/vision/ocr.py`, load
   `training/checkpoints/plate_crnn.onnx` (copy it to `backend/models/`), preprocess with the same
   `to_model_input`, run it, take `probs[0]` of shape `(48,37)`, decode with `ctc_greedy`, and return
   `[(char, conf)]` exactly as `read_plate_chars` does today. Keep PP-OCR as a fallback (env switch). Re-run the
   122 tests and the real clip.
4. Optional track B: fine-tune the plate detector with Ultralytics (command in the training README), measure recall
   before and after.
5. Build a small labelled real-clip evaluation (10 to 20 clips with the true plates written down) so the full pipeline has
   real numbers. The scoring harness for the full pipeline was started earlier and not kept; `evaluate.py` only
   covers the OCR step.

## 8. Site rebuild (evaluator item 2): built on 2026-11-24

The whole front end was redesigned around the supplied hero image and type reference, and the evaluator's missing pieces
were added. Everything below runs against the real backend.

- **Landing `/`**: cinematic hero (small credit block, giant "01", car and beam), how it works (6 steps), **eight feature
  cards reading live data** (real frame reads, refusal gauge, agency thresholds, calibration curve, latest real report,
  report and job counts), the working engine demo, five agency cards, an honest status board, entry tiles.
- **Console `/console/`**: drag-and-drop upload, agency info, recent analyses, model readiness, results with plate crops,
  ranked candidates, per-frame characters, unreadable vehicles collapsed. `?job=<id>` opens a saved job.
- **Monitor `/monitor/`**: totals, outcome split, characters-recovered histogram, analyses by agency, citizen-report counts,
  model readiness, calibration curves per agency with the chosen thresholds, recent analyses. All read from disk
  (`app/monitor.py`); refreshes every 20 s. An empty chart means nothing has happened; there is no sample data.
- **Features `/features/`**: every capability in six groups (reading the plate, deciding, agencies, citizens and officers,
  trust and proof, under the hood). Each has what it does, how it works, an honest status chip (built / partial /
  planned) and a live visual read from the running backend (real frame reads, a live engine run, calibration curve,
  agency table, model readiness). The measured plate-reader comparison and a "not built yet" list are on it.
- **Motion system (`ui.css` + `ui.js`, used by every page):** page-to-page curtain wipe (leaves from the left, uncovers to
  the right, no flash because the arriving page starts covered), staggered scroll reveals with left/right/scale variants
  (CSS animations, so a card's own hover transition cannot cancel them), bars that grow and charts that wipe in when their
  panel appears, plate characters that pop in one by one, number count-ups, a scroll progress bar, a cursor spotlight on
  cards, a button shine, a staged hero entrance with parallax on scroll, and step/row/detail transitions in the report flow
  and officer desk. Content added later by fetches is animated by a MutationObserver. The monitor's 20-second refresh does
  not replay animations (`data-live` plus `data-settled`). `prefers-reduced-motion` turns all of it off.
- **Citizen reports `/report-issue/`**: photo (camera or file) -> plate read with unknowns shown as `?` -> citizen may type
  the plate -> category (routes to an agency), description, place (optional "use my location"), time, optional contact,
  explicit consent -> report ID plus a status checker. EXIF time/GPS are only suggested. The photo is re-encoded (EXIF dropped).
- **Officer desk `/desk/`**: sign in with the officer key; list with filters; detail with photo, system read, citizen-typed
  plate, registry match with reasons (basis stated), details, and triage (status plus note).
- **Rules enforced in code and tests (`tests/test_complaints.py`):** citizens never receive registry data, owner data or
  officer notes; every `/api/desk` route needs the key; a draft can be submitted once; consent is required; per-client
  rate limits (20 previews and 5 reports per hour, in memory); photos limited to 10 MB; a typed plate that does not fit the
  registry is refused, not forced.
- **Everything stored per video (`backend/data/jobs/<id>/`):** the original video (`source.<ext>`, moved there after analysis), `result.json`
  (the complete analysis incl. video properties, processing time, body-type method and second reader), the sharpest plate crops, the best crop
  of every vehicle (`track<N>_vehicle.jpg`) and an evidence frame per plate read (`track<N>_evidence.jpg`: the frame it was read from, vehicle
  outlined white, plate red). About 40 MB for a 15 s 1080p clip. Nothing deletes stored videos yet.
- **Full case file `GET /api/jobs/{id}/download`:** one ZIP with `report.html` (self-contained, also prints to PDF), `result.json`,
  `manifest.json`, `data/tracks.csv`, `data/frame_reads.csv`, `data/candidates.csv` (UTF-8 with BOM for Excel), `media/plates|vehicles|evidence/`
  and `source/` (the original video). The manifest records each file's SHA-256, the models and their licences, software versions, the agency
  settings used, and the caveats; tests check every hash against the bytes. Older jobs without a stored video or new fields still export.
- **Archive `/archive/`:** lists every stored analysis (file, time, agency, vehicles, plates, resolution, size) with Open, Report and ZIP, and
  searches by whole or partial plate across all videos (an 8 or 9 character query is fitted to the ten slots first).
- **Storage:** SQLite `backend/data/netra.db` and photos in `backend/data/complaints/` (both gitignored).

Not built, by design or time: real officer accounts and citizen OTP sign-in (single shared key for the demo), face blurring,
retention and deletion rules, complaint de-duplication, and fusing several citizens' reads of one vehicle (the cross-camera
bonus). Photos from different reports of the same plate are not linked yet. Citizen photos are one frame, so expect more `?`.

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

> Read HANDOFF.md in this repo (CLAUDE.md summarises it). Set up the environment (section 5) and run the tests.
> We are using pretrained models only; our own training is parked (section 7). Ask me which open task from CLAUDE.md
> you should take so we do not edit the same files. Do not claim an improvement before it is measured on real crops.
> Final evaluation is the evening of 2026-11-24, so keep a working demo at every step.
