import re
import shutil
import uuid
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .brains import brain_status
from .config import get_department, load_departments
from .fusion import fuse_frames
from .matcher import match_registry
from .registry import load_registry
from .report import render_report
from .schemas import AnalysisResult, Evidence, MatchResult

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_EXT = {".mp4", ".avi", ".mov", ".mkv"}
JOB_ID_RE = re.compile(r"[0-9a-f]{12}")
CROP_RE = re.compile(r"track\d+_plate\d+\.jpg")

app = FastAPI(title="Netra API")


@lru_cache
def _models():
    from .vision.detectors import PlateDetector, VehicleTracker

    clip = None
    if next(b for b in brain_status() if b["id"] == "clip")["ready"]:
        from .vision.clip_brain import ClipBrain

        clip = ClipBrain()
    return VehicleTracker(), PlateDetector(), clip


@app.get("/api/registry/sample")
def registry_sample():
    row = next((r for r in load_registry() if not r.flags), load_registry()[0])
    return row


@app.get("/api/brains")
def brains():
    return brain_status()


@app.post("/api/analyze", response_model=AnalysisResult)
def analyze(file: UploadFile = File(...), department: str = Form("police")):
    from .vision.pipeline import analyze_video

    try:
        get_department(department)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=415, detail=f"unsupported file type '{ext}'; use one of {sorted(ALLOWED_EXT)}")

    upload_dir = DATA_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{uuid.uuid4().hex}{ext}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)

    tracker, plate_detector, clip = _models()
    result = analyze_video(dest, department, tracker, plate_detector, out_dir=DATA_DIR / "jobs", body_classifier=clip)
    save_job(result)
    return result


def save_job(result: AnalysisResult) -> None:
    job_dir = DATA_DIR / "jobs" / result.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "result.json").write_text(result.model_dump_json())


def _job_dir(job_id: str) -> Path:
    if not JOB_ID_RE.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    d = DATA_DIR / "jobs" / job_id
    if not (d / "result.json").exists():
        raise HTTPException(status_code=404, detail="job not found")
    return d


@app.get("/api/jobs/{job_id}", response_model=AnalysisResult)
def get_job(job_id: str):
    return AnalysisResult.model_validate_json((_job_dir(job_id) / "result.json").read_text())


@app.get("/api/jobs/{job_id}/report", response_class=HTMLResponse)
def job_report(job_id: str):
    d = _job_dir(job_id)
    result = AnalysisResult.model_validate_json((d / "result.json").read_text())
    return render_report(result, d)


@app.get("/api/jobs/{job_id}/crops/{name}")
def job_crop(job_id: str, name: str):
    d = _job_dir(job_id)
    if not CROP_RE.fullmatch(name) or not (d / name).exists():
        raise HTTPException(status_code=404, detail="crop not found")
    return FileResponse(d / name, media_type="image/jpeg")


@app.get("/api/health")
def health():
    return {"status": "ok", "registry_rows": len(load_registry())}


@app.get("/api/departments")
def departments():
    return [
        {"id": d.id, "name": d.name, "match_threshold": d.match_threshold,
         "min_known_chars": d.min_known_chars}
        for d in load_departments().values()
    ]


@app.post("/api/match", response_model=MatchResult)
def match(evidence: Evidence):
    try:
        cfg = get_department(evidence.department)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    fused = fuse_frames(evidence.frames, slot_accept=cfg.slot_accept)
    return match_registry(fused, evidence.colour, evidence.body_type, load_registry(), cfg)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
