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
- **Monitor `/monitor/` (real data only, by decision on 2026-11-24):** every number is measured. Panels: totals (analyses, of how many
  *distinct* videos, vehicles, plates read, footage analysed, bytes stored, citizen reports), outcome per vehicle with the
  second-reader verdicts, characters recovered, analyses by agency, **plate width against how much was read** (the system's own evidence
  for the 80 px rule), confidence of recovered characters, analyses per day, processing speed (median and real-time factor), the server
  (uptime, requests by kind, 4xx and 5xx counts, load, peak memory, disk) and citizen reports, plus model files and recent analyses. Every
  panel states what it was drawn from; an empty panel means nothing has happened. Removed because they were not measured: the
  calibration curves (a simulation, now served separately at `/api/calibration` with `simulated: true` and used only on the landing and
  Features pages, labelled as a design target), the registry-row count (synthetic data) and two hard-coded sentences that asserted
  conclusions. Server counters live in memory and restart with the server (`Metrics` in `app/monitor.py`; `/api/monitor` and `/api/health` are not
  counted so polling cannot inflate them). Host figures are included only if the platform can report them (load average and
  `resource` do not exist on Windows). The stored analyses include development re-runs of the same test clips; that is why the page shows distinct
  videos, and why plate-size figures lean on one clip.
- **Features `/features/`**: every capability in six groups (reading the plate, deciding, agencies, citizens and officers,
  trust and proof, under the hood). Each has what it does, how it works, an honest status chip (built / partial /
  planned) and a live visual read from the running backend (real frame reads, a live engine run, calibration curve,
  agency table, model readiness). The measured plate-reader comparison and a "not built yet" list are on it.
- **Second background and lighting (`ui.css` environment block, built by `ui.js initEnv`):** the red light-streak image (`img/bg2.webp`,
  736x1308) fills the whole viewport (`cover`) behind every page except the landing hero, which keeps the main image. Its geometry was measured
  and `ui.js` uses it on every scroll and resize: the two bright streaks sit at 46.2% and 53.7% of the image width and its brightest row (the
  flare) is 72% down. At the top of a page the view is positioned (66%) so the streaks rise into the flare; as you scroll the view climbs the
  image (to 36%), so the page gets calmer further down. Light pulses start at the flare row and travel up the streak columns, recomputed from the
  rendered size, so they stay on the streaks at any screen shape (checked at 1440x900, 2200x900 and a 375x812 phone; a portrait screen shows the
  whole image fitted to its height). The panel and scrim colours moved from navy to the image's own warm black (`#060204`) and secondary glows use
  its orange-red flare colour (`--ember`, `#e0583a`); the image has no blue, so the blue light orb was removed. Also: drifting light orbs, film
  grain, a top scrim for legible headings, and a soft light that follows the cursor. Empty states are filled with the same image. Scroll effects: the
  hero fades and lifts as you leave it, a marquee strip that speeds up while you scroll, a "how it works" rail that fills and lights each step,
  section dividers that draw themselves, cards that tilt and have a cursor spotlight, primary buttons that lean towards the cursor, feature visuals
  that float with depth, and headings that rise word by word (full text kept in `aria-label`). All of it is off under `prefers-reduced-motion`.
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

## 8b. Features built after the model freeze (2026-11-24), one at a time, each tested before the next

The user chose: handle motorcycles WITHOUT training, then variable-length plates, watch-list with repeat sightings, PDF export, and agency tools.
All use the existing pretrained models; nothing was trained.

### Feature 1: motorcycles and two-row plates (`app/vision/rows.py`)
- **Why:** the registry, the COCO motorcycle class and the `two_wheeler` body type already existed, so the real gap was reading the plate. Most Indian
  two-wheelers have a two-row plate (DL14S over Z8550), and a reader built for one line returns fragments. In our real clip all 10 motorcycles were unreadable;
  the crops showed several clear two-row plates (e.g. track 95), read as `2658` or `ALSS`.
- **How:** `find_split` locates the gap between rows from the text-density profile; `read_plate` reads each row as a line and joins them. A crop that is not
  clearly one line (width/height under 3.0) is read BOTH ways and the reading that fits the plate format better by at least one confident character wins, so a
  one-row plate with a loose crop is never damaged. The second reader does the same. `FrameRead.rows` and `TrackAnalysis.plate_layout` record it; the console
  shows a "two-row plate" chip and the CSVs and report carry it. Layout is judged by the frames that produced a reading (`plate_layout` in `pipeline.py`).
- **Measured (generated plates, `training/plategen.py` now has `two_row=True`; 300 per setting):** two-row plates, old reader 0.0% exact, new 82.3% (easier) and
  65.7% (harder), fixing 247 and 197 plates and breaking none. One-row plates identical before and after (94.3%, 86.7%). Real clip: track 95 now reads
  `DL14SZ8550` exactly (second reader agrees 10/10); other motorcycle plates are mostly too small or blurry, and track 30 is read partly with the second reader
  disagreeing, so it is flagged for manual verification. Only one clear real two-row plate could be checked; generated plates use unrealistic fonts.
- **Not done:** a 80 px minimum is still applied to all plates (no real motorcycle data to calibrate a separate one); no helmet or rider logic.

### Feature 2: variable-length plates (nine-character plates with one series letter)
- **Why:** real plates like `DL1LR2711` have a single series letter (9 characters). The engine models 10 slots, so the second series slot was left unreadable and the match was partial.
- **How:** the second series slot can now hold an explicit **absent marker `-`** (`schemas.ABSENT`, slot 5), different from `?` (unreadable). `to_slots()` converts a 9-character plate to ten slots;
  `align_to_slots` places a single series letter with certainty (marker confidence x0.9); fusion lets the marker vote only in slot 5; the matcher compares in slots (a nine-character
  registry row meets a nine-character read, reasons say "no letter"); the cross-check does not count the marker as a confirmed character; `FusedPlate.display` / `known_count` hide it, so people see `DL1LR2711` and "9 of 9".
  The registry gained 24 nine-character rows (REG0301-REG0324, separate RNG; the first 300 rows are byte-identical). Calibration simulates ten-character plates only.
- **Measured:** real clip track 90 was `DL1L??2711` and is now `DL1LR-2711` (second reader agrees); the other tracks are unchanged. 186 tests pass (7 new in `test_variable_length.py`).
- **Not handled:** three series letters, numbers shorter than four digits, and Bharat-series plates (`22BH1234AA`).

### Feature 3: repeat sightings and an officer watch-list (`app/watchlist.py`)
- **Repeat sightings** (`GET /api/sightings`, public like the archive; panel on the archive page): readable plates (7+ characters) from all stored analyses are grouped when no character clashes and 7+ agree
  (`?` and the absent marker never count). A repeat needs **two or more distinct videos**, identified by the SHA-256 of the video file, so analysing one clip several times is not a repeat. On our real data (one clip analysed many times) the list is correctly empty.
- **Watch-list** (officer key only: `GET/POST /api/desk/watchlist`, `DELETE /api/desk/watchlist/{id}`; panel on the officer desk): an entry is a plate with unknown characters allowed (at least 4 known) and a reason. Hits are found in all stored videos:
  "exact" if every character the entry names was read and agrees, "possible" if the read agrees but some of it is unreadable; any clash, or fewer than 6 agreeing characters, is never a hit. Removing an entry is a soft delete (kept for the record). The watch-list and its reasons never appear in public responses (tested).
- **Not done:** hits are shown on the desk on request, not pushed as notifications; citizen-report plates are not checked against the list; one shared officer key.
- 199 tests pass (13 new in `test_watchlist.py`).

### Feature 4: PDF export (`app/pdf_report.py`, reportlab)
- `GET /api/jobs/{id}/report.pdf` and `report.pdf` inside the case-file ZIP (hash in the manifest). Same content as the HTML report: recovered plate with per-slot confidence, second-reader verdict, vehicle crop, plate crops,
  evidence frame, ranked candidates with reasons, per-frame reads (first 12 frames), unreadable vehicles, models and settings, honesty notes. Images are downscaled to about 150 dpi (real 11-page report: 2.3 MB).
- If `reportlab` is missing the endpoint answers 501 with the install hint and the ZIP simply omits the PDF; everything else still works. `reportlab` and `pypdf` (tests) are in `requirements.txt`.
- Checked by extracting the text of the generated PDF (tests) and of a real job; not looked at page by page as images (no PDF rasteriser here). Core Latin-1 font: non-Latin characters in a file name print as `?`.
- 204 tests pass (5 new in `test_pdf_report.py`).

### Feature 5: agency tools (`app/agency_tools.py`)
- `GET /api/jobs/{id}/actions` returns suggested next steps per vehicle, **only for a confirmed "match"** (ambiguous gets "verify manually", refusals get nothing). Driven by the registry flags (demo data, synthetic):
  police: stolen = verify against live records first; expired insurance/PUC = document lead with a draft challan. MoRTH/NHAI: document violations get a draft challan, stolen is referred to police. BSF/SSB/Customs: stolen is referred to police, documents only noted.
- `GET /api/desk/jobs/{id}/tracks/{tid}/challan.pdf` (officer key) returns a **DRAFT e-challan** (police and MoRTH/NHAI, document violations only; 409 elsewhere): watermarked DRAFT, evidence frame and plate crop, video hash, how sure the plate is,
  blank place/officer fields, no fine amount. Not an official document and nothing is sent anywhere. The console shows the steps and a button; it uses the key stored by the officer-desk sign-in.
- **Not built:** FASTag class check, permit/route check, convoy detection, challans for citizen reports, real registry data. Fine amounts and legal sections were deliberately left out rather than guessed.
- 212 tests pass in total (8 new in `test_agency_tools.py`). The site's features, landing and roadmap lists were updated to match what is built.

### Flag a vehicle from the console (post-freeze, requested after Feature 5)
- Each readable vehicle in the console has "Flag this vehicle": category, what was seen, where. `POST /api/jobs/{id}/tracks/{tid}/flag` files a report straight into the complaints store
  (`ComplaintStore.flag_track`): the video's evidence frame is the photo, the first plate crop is the plate image, and the fused plate is the read. The report is routed by category like any citizen report.
- The complaints table gained `source` ('citizen' or 'console'), `job_id`, `track_id` (existing databases are upgraded in place; old reports keep working, tested). The officer desk marks console reports and links back to the analysis.
  `GET /api/jobs/{id}/flags` tells the console which vehicles are already flagged; a second flag of the same vehicle is refused (409). Rate limited to 30 per hour per connection.
- **Gap:** the console has no sign-in, so anyone who can reach it can flag (a flag is only a lead in the officer queue). Add the officer key here if that is a concern. Real UI check was done on a scratch copy of one job so no real report was created.
- 218 tests pass (6 new in `test_flag_vehicle.py`).

### Officer portal and officer backend (post-freeze, 2026-11-24)
- **Portal:** `/officer/` (the old `/desk/` redirects there). Sections: Dashboard (open, unassigned, mine, over 48 h, watch-list hits, repeat plates, 7-day chart, status and agency breakdown), Reports (filters, search, detail with
  evidence and registry match, assign / take it, status, notes, full file history, CSV export), Analyses, Watch-list, Repeat sightings, and for admins Audit trail and Team. Front end: `static/officer/`.
- **Access:** sign in with username and password, or with the **master key** (administrator). The key is `EXLEX_OFFICER_KEY` (or old `NETRA_OFFICER_KEY`), else generated once and kept in `backend/data/officer_key.txt` (gitignored, mode 600). It is never in the source.
  The admin creates one account per officer (`/api/officer/team`); passwords are scrypt-hashed (10+ characters, mixed case, a digit); sessions are random 12-hour tokens, only their hash is stored; sign-in is rate limited; disabling an account or resetting its password signs it out;
  the last active admin and your own account are protected. The old `X-Officer-Key` header still works on every `/api/desk/*` route, so nothing built earlier broke.
- **Audit trail:** every sign-in (and failure, without the secret), status change, assignment, note, watch-list change, challan draft, export, account change and console flag is logged with who did it (`audit` table, read by admins at `/api/officer/audit`).
- **Data:** the complaints table gained `assigned_to` and a `case_events` table (history of status, assignment and notes); existing databases are upgraded in place.
- **Not built:** two-factor sign-in, password reset by email, live push alerts, per-agency permissions (all officers see all agencies), session list/revoke screen.
- 234 tests pass (16 new in `test_officer_portal.py`); the portal was driven in a real browser against a scratch copy of the data (sign-in as officer and admin, take a report, add a note, team and audit pages).

### Ten more features (post-freeze, 2026-11-24, built from the Features-tab suggestions)
Not built, on purpose: live camera streams, helmet/rider checks, FASTag/permit checks and a stronger second reader (new models or real data sources; the model stack is frozen), and two-factor sign-in.
1. **Per-agency permissions** (`agencies` on officer accounts; `_case()` / `allowed()` in `main.py`): an officer limited to some agencies sees only those reports in lists, detail, photos, notes, CSV, dashboard, outbox and map; others read as "not found". The key and admins see all.
2. **Sessions list and revoke** (admin): `GET/DELETE /api/officer/sessions`; ids are a 12-character hash prefix, never a credential. Changing an officer's role, agencies, password or active flag signs them out.
3. **Related reports** (`dedupe.py`): same plate (no clash, 7+ characters agree), filed within 24 h. `related` count in the list, `/api/desk/complaints/{id}/related`.
4. **Plate-quality advisor** (`advisor.py`, `/api/jobs/{id}/advice`): restates measured width, frames and characters; shown in the console.
5. **Watch-list CSV import** (`POST /api/desk/watchlist/import`, up to 500 rows, per-row reasons for failures).
6. **Retention** (admin): preview then apply (`/api/officer/retention/*`), refused unless `confirm` and the previewed count still match; only closed/rejected reports or analyses older than N days; audited. `DELETE /api/officer/analyses/{id}?confirm=true`.
7. **Citizen messages, demo** (`outbox` table): queued when a report is filed or its status changes, if a contact was given; masked destination, no plate or owner data in the text. Nothing is sent.
8. **Demo data** (`demo_data.py`): ten labelled reports (`source='demo'`) built from stored analyses; `ComplaintStore.counts()` excludes them so the monitor stays measured-only. Admin buttons on the dashboard.
9. **Map** (`/api/desk/map`, Leaflet 1.9.4 from cdnjs + OpenStreetMap tiles, popups built from DOM nodes so place text cannot inject HTML). Needs internet; the table below always works.
10. **API page** (`/developers/`): built live from `/openapi.json`.
- 256 tests pass. Browser-checked on scratch data: map, demo panel, reports list with demo/related chips, API page, team/sessions.

### Two-factor, password reset, live alerts (post-freeze, 2026-11-24)
- **Why the master key said "Method Not Allowed":** the preview server on port 8000 had been started before the portal existed (it still reported 300 registry rows), so it had no `/api/officer/login` route and the static-file mount answered POST with 405. Fix: restart the server (preview `exlex`). After any code change the server must be restarted (it does not auto-reload).
- **Two-factor** (`totp.py`, RFC 6238, Google Authenticator compatible; tested against the RFC reference values): `POST /api/officer/2fa/setup` (QR via `segno` plus a typed key), `/enable` (confirms a code, returns 8 one-time recovery codes), `/disable` (password plus code). With it on, `/api/officer/login` returns `needs_2fa` and a 5-minute challenge instead of a session; `/api/officer/login/2fa` takes the app code or a recovery code (5 tries per challenge, an already-used time step is refused, so no replay). Admins reset a lost phone with `reset_2fa` on the team PATCH. The master key has no second step (break-glass).
  "Google auth" was read as Google Authenticator codes. Sign in with a Google account (OAuth) is NOT built: it needs a Google Cloud OAuth client that the owner creates.
- **Password reset by email:** officers have an `email`; `POST /api/officer/password/forgot` always answers the same; the link is single use for 30 minutes and signs the officer out everywhere. Mail is sent only if `EXLEX_SMTP_HOST` and `EXLEX_SMTP_FROM` are set (optional `_PORT`, `_USER`, `_PASSWORD`); otherwise it is only queued in the admin "Mail queue" with the state "queued (SMTP not configured: nothing was sent)". Set `EXLEX_PUBLIC_URL` so the link uses the right address. Real SMTP sending was tested with a fake server, not with a live mail account.
- **Live alerts:** `alerts` table; raised for new citizen reports, console flags and watch-list hits in a new analysis; `GET /api/officer/alerts?since=` (agency-filtered). The portal polls every 15 s, shows pop-ups and an unread count, optional desktop notifications. Not a push to a closed browser.
- Per-agency permissions and the session list/revoke screen were already built earlier (the "not built" list pasted by the user was out of date).
- 273 tests pass (17 new in `test_security_features.py`). Browser-checked on scratch data: enrol (QR, 8 codes), sign-in with and without the code, wrong code, forgot and reset flow, alert pop-up and unread count.

### Going online (2026-11-24)
- Asked to deploy; the user chose a public link from the Mac, then asked about Vercel and chose "Vercel front end + backend elsewhere". **Nothing is deployed.** Cloudflare quick tunnels were tried and are blocked on the network in use (connection reset three times); `cloudflared` was installed with Homebrew and is still on the Mac.
- Prepared: `Dockerfile` + `deploy/start.sh` (CPU PyTorch, no CLIP), `render.yaml` (standard plan, 10 GB disk, secrets left blank), `vercel.json` (static output `backend/app/static`, `/api` rewrites), `deploy/set_backend.py` (fills in the backend address), `DEPLOY.md` (steps).
- Code changes for hosting: `EXLEX_DATA_DIR` (data, key and database on a persistent disk), `EXLEX_CORS_ORIGINS` (off unless set; no credentials), `static/config.js` (`uploadBase` so large uploads go straight to the API), real visitor address behind a proxy for rate limits, 300 MB upload cap and analysis limit (30/hour/visitor), security headers, `robots.txt` disallowing indexing.
- **Not verified:** the Docker image was never built (no Docker here); Vercel rewrites were not exercised against a live backend. The local dry run of the start command (proxy headers, per-visitor limits) did pass. 280 tests pass.

### Seven more features (post-freeze, 2026-11-24; the user picked these from a list)
1. **Cross-camera trail:** optional `camera`, `place`, `lat`/`lon`, `recorded_at` on `/api/analyze` (validated; stored on the result), `GET /api/trail?plate=` (in recording order, else analysis order, labelled), map and table on the archive page. Same footage analysed twice is one sighting.
2. **Batch upload:** the console takes several clips and runs them one after another through the same endpoint (status per clip, stop button). Front end only.
3. **Registry search** (`registry_search.py`, `/api/desk/registry/search`, officers only, audited): partial plate with `?`, colour, body type, make; needs 3 known characters or another filter.
4. **Citizen status page** (`/status/`, `GET /api/complaints/{id}/progress`): plain-language progress and timeline; tested to carry no notes, officer names, registry data or plates; 60 lookups/hour/visitor.
5. **Night-light boost: measured and NOT shipped.** Code written, tested, then removed. Generated plates darkened and noised (300 per level): very dark 51.7% exact reads without it, 53.0% with it at selection margin 1.0 (0 readings made worse) or 54.3% at margin 0.5 (1 made worse); dim and bright within 0.6 points. That is inside the noise for 300 plates. On the real clip, 4 of 20 unique crops of the five known vehicles were dark and the boost changed none. No evidence it helps, so it is not in the product. (The evaluation script was a scratch file, not kept.)
6. **Hindi and English** (`static/i18n.js`): swaps text that matches a dictionary entry (also text added later), covering the menu, landing hero, report-a-problem pages, track page, categories, agency names, statuses. Untranslated text stays English. `tests/test_i18n.py` fails if a translated phrase no longer exists in the pages or server text. Dates stay in English format. **The Hindi has not been reviewed by a native speaker.**
7. **Installable app** (`manifest.webmanifest`, `sw.js`, `pwa.js`, `offline.html`, icons in `static/img`): the service worker caches only the citizen page shell, never `/api`, `/officer`, `/desk`, writes or other sites. Offline notice on the pages; a report still needs a connection. The in-app browser pane refuses to register service workers, so registration was not seen live there; the worker's logic is tested in Node with a fake cache and network (`tests/sw_harness.js`). Install on a real phone is unverified.
- 311 tests pass.

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

## Name (2026-11-24)
The project is now called **ExLex** (earlier names: Netra, PlateTrace). It is shown on the landing hero, the nav bar, page titles, reports, PDFs and the API title. Left as they were on purpose so nothing breaks: the database file `data/netra.db` (existing reports live in it), and the old environment variable names `NETRA_OFFICER_KEY` / `NETRA_DEVICE`, which still work next to the new `EXLEX_OFFICER_KEY` / `EXLEX_DEVICE`.

### 8c. Body-type tuning and per-frame PDF confidence (2026-11-24)
- **Measured on real crops.** 87 vehicle crops from the sample clip (about 15 distinct vehicles seen many times), labelled by eye by the
  assistant, not by an independent annotator. Several vehicle types accept more than one answer (a van may be car or tempo; a cargo
  three-wheeler may be auto, tempo or truck). Top-1 body type: **75/87 before, 78/87 after** new CLIP prompts. Small sample, one clip, one scene.
- **Still wrong (zero-shot limit):** a white hatchback (Santro) is read as SUV or tempo; one e-rickshaw whose detector box says
  "motorcycle" is read as two-wheeler; a grey van partly hidden by a motorcycle. Changes that fixed one broke another (tuned prior, softer
  prior: 75/87), so they were not kept.
- **Matcher fix instead of a model change:** car and SUV (and truck and tempo) are look-alikes, so the matcher gives half credit when the
  registry says one and the camera the other, and says so in the reasons (`NEAR_BODY` in `vision/attributes.py`). Tests added.
- **PDF:** the per-frame table now shows each character with its own confidence (red below 0.50), up to 30 frames, and each candidate lists
  its score parts (plate, colour, body, mismatch penalty). It still shows three plate crops and one evidence frame, not every frame image.
- Existing stored jobs keep their old body-type values; only new analyses use the new prompts.
