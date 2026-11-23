# Netra: read this first

You are joining mid-project with no earlier conversation. **Read `HANDOFF.md` (the full state of the project) and
`training/README.md` before doing anything.** Do not ask the user to re-explain the project; ask only for what is
listed under "What you need from the user".

## What this is
Hackathon problem AIML-01 Option A: vehicle identification from CCTV footage. It recovers a plate across many frames,
marks unreadable characters as unknown, extracts colour and body type, matches a registry (ranked top 5 with reasons),
or says "no confident match". FastAPI backend, YOLO + PP-OCR + CLIP, static site. 95 tests.

## Deadline
Final evaluation: **evening of 2026-11-24**. Keep a working demo at every step; never leave the app broken.

## This machine's job: the training track
An NVIDIA RTX 4050 (6 GB) is available here. The evaluator asked for the plate recogniser to be trained on a
plate-only dataset with augmentation (angles, Gaussian noise) for better accuracy.

1. Set up per HANDOFF.md section 5; check `torch.cuda.is_available()` is `True`; run `python -m pytest` in `backend/`.
2. In `training/`, run `python plategen.py --preview samples.png` and look at it.
3. With a real labelled crop dataset: `python train.py --epochs 40 --real-dir real --workers 6`
   (use `--workers 0` if Windows complains), then
   `python evaluate.py --real-dir real --split val --onnx checkpoints/plate_crnn.onnx --json eval_real.json`.
4. Commit and push `training/checkpoints/plate_crnn.onnx`, `train_log.jsonl` and `eval_real.json`.
   (`.gitignore` already allows exactly those.)
5. Wiring the model into `backend/app/vision/ocr.py` is described in HANDOFF.md section 7. Do it only if it beats
   PP-OCR on real held-out crops.

## What you need from the user
A **real labelled plate-crop dataset**: crops plus the text of each plate, laid out as `training/real/labels.csv`
(`filename,text`) and images. Detection-only datasets (boxes) are no use for the recogniser. Check licences.

## Rules that must not be broken
- **Never invent characters.** Unreadable positions stay `?`; refuse ("no confident match") when evidence is thin.
- **Report honestly.** No accuracy claim that was not measured. A synthetic-only score is not a real result; quote
  real-crop numbers. Say what was not verified.
- Training samples stay borderline legible (see `training/plategen.py`): never train on text a human could not read.
- Keep the repository **private**; do not commit video clips, job crops or the CLIP weights (see `.gitignore`).
- Ask before anything outward-facing (pushing to a new place, downloading large files). Pushing to this repo's
  `main` with the user's go-ahead is fine; never force-push.

## Style
Short, direct answers. One request at a time. State results plainly, including failures.
