# Netra: read this first

You are joining mid-project with no earlier conversation. **Read `HANDOFF.md` (the full state of the project) before
doing anything.** Do not ask the user to re-explain the project; ask which task below they want you to take, so two
machines never edit the same files.

## What this is
Hackathon problem AIML-01 Option A: vehicle identification from CCTV footage. It recovers a plate across many frames,
marks unreadable characters as unknown, extracts colour and body type, matches a registry (ranked top 5 with reasons),
or says "no confident match". FastAPI backend, YOLO + PP-OCR + CLIP, multi-page static site. The monitor page shows measured data only (no simulated or hard-coded figures). 168 tests.

## Deadline
Submission: **morning of 2026-11-25**. The model stack is final (see `MODELS.md`): pretrained only, no further model changes. Keep a working demo at every step; never leave the app broken.

## Decision (2026-11-24): pretrained models only, no training
The user decided not to train our own models. The from-scratch kit in `training/` is parked. The evaluator's accuracy
point was answered by comparing ready-made plate readers (HANDOFF.md section 7a): none clearly beats the current
PP-OCR alone, but two readers agreeing was right about 98% of the time on synthetic plates, so a lightweight second reader
(fast-plate-ocr, MIT, 5 MB) now cross-checks every plate (HANDOFF.md 7a-2). Everything analysed is stored, and downloadable as a ZIP case file.

## Open work (ask the user which one you take)
0. **Models: final** (MODELS.md; one second reader was added late, 2026-11-24). Do not swap or add models before submission.
1. **Site rebuild: done** (HANDOFF.md section 8): landing, features, console, monitor, citizen reports, officer desk, with a shared motion system. Remaining polish
   ideas: seed a few realistic demo reports, PDF export of the report, complaint de-duplication.
2. **Second-reader cross-check: done** with fast-plate-ocr. A stronger one (Awiros ANPR-OCR) needs PaddlePaddle in the backend; only if the user wants it.
3. **Pretrained body-type model** to replace the weak CLIP step (candidates in HANDOFF.md section 7a); test on real
   crops before swapping.
4. Set up per HANDOFF.md section 5 first: `python -m pytest` in `backend/` should pass.

## Rules that must not be broken
- **Never invent characters.** Unreadable positions stay `?`; refuse ("no confident match") when evidence is thin.
- **Report honestly.** No accuracy claim that was not measured. A synthetic-only score is not a real result; quote
  real-crop numbers. Say what was not verified.
- If training is ever resumed: keep samples borderline legible (see `training/plategen.py`); never train on text a
  human could not read.
- Keep the repository **private**; do not commit video clips, job crops or the CLIP weights (see `.gitignore`).
- Ask before anything outward-facing (pushing to a new place, downloading large files). Pushing to this repo's
  `main` with the user's go-ahead is fine; never force-push.

## Style
Short, direct answers. One request at a time. State results plainly, including failures.
