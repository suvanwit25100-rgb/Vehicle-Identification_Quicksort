import json
import logging
import os
import re
import secrets
import shutil
import uuid
from functools import lru_cache
from pathlib import Path

import cv2
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import complaints as cm
from .brains import brain_status
from .config import get_department, load_departments
from .fusion import fuse_frames
from .matcher import match_registry
from .monitor import calibration_summary, job_summary, list_jobs
from .registry import load_registry
from .export import build_case_zip
from .report import render_report
from .schemas import AnalysisResult, Evidence, FusedPlate, MatchResult

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_EXT = {".mp4", ".avi", ".mov", ".mkv"}
JOB_ID_RE = re.compile(r"[0-9a-f]{12}")
CROP_RE = re.compile(r"track\d+_(?:plate\d+|vehicle|evidence)\.jpg")

app = FastAPI(title="Netra API")


@lru_cache
def _models():
    from .vision.detectors import PlateDetector, VehicleTracker

    clip = None
    if next(b for b in brain_status() if b["id"] == "clip")["ready"]:
        from .vision.clip_brain import ClipBrain

        clip = ClipBrain()
    return VehicleTracker(), PlateDetector(), clip


@lru_cache
def _second_reader():
    """The independent second reader, or None if its package or model files are missing (everything else still works)."""
    from .vision.second import SecondReader, available

    return SecondReader() if available() else None


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
    result = analyze_video(dest, department, tracker, plate_detector, out_dir=DATA_DIR / "jobs", body_classifier=clip,
                           source_name=file.filename, second_reader=_second_reader())
    save_job(result)
    # keep the original video with the rest of the case, so one folder holds everything about this analysis
    shutil.move(str(dest), str(DATA_DIR / "jobs" / result.job_id / f"source{ext}"))
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


@app.get("/api/jobs")
def jobs(plate: str | None = None, limit: int = 200):
    """Every stored analysis, newest first. `plate` may be partial: ? matches any character."""
    return list_jobs(DATA_DIR, plate=plate, limit=max(1, min(limit, 500)))


@app.get("/api/jobs/{job_id}/download")
def job_download(job_id: str, include_video: bool = True):
    """The whole case as one .zip: report, data tables, images, the original video and a manifest with hashes."""
    d = _job_dir(job_id)
    result = AnalysisResult.model_validate_json((d / "result.json").read_text())
    path = build_case_zip(result, d, include_video=include_video)
    return FileResponse(path, media_type="application/zip", filename=f"case-{job_id}.zip", background=BackgroundTask(os.unlink, path))


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


@app.get("/api/monitor")
def monitor():
    """Everything the monitor page shows, read from saved jobs, complaints, model files and the calibration report."""
    return {
        "generated_at": cm.now_iso(),
        "registry_rows": len(load_registry()),
        "brains": brain_status(),
        "jobs": job_summary(DATA_DIR),
        "complaints": _store().counts(),
        "calibration": calibration_summary(DATA_DIR),
    }


# ---------------------------------------------------------------- citizen complaints
# The officer key gates every /api/desk route. There is no built-in default: set NETRA_OFFICER_KEY, or a random key
# is generated for this run and printed once in the server log at start-up.
OFFICER_KEY = os.environ.get("NETRA_OFFICER_KEY") or secrets.token_urlsafe(9)
if not os.environ.get("NETRA_OFFICER_KEY"):
    logging.getLogger("uvicorn.error").warning("NETRA_OFFICER_KEY is not set. Officer key for this run: %s", OFFICER_KEY)
limiter = cm.RateLimiter()


def _store() -> cm.ComplaintStore:
    return cm.ComplaintStore(DATA_DIR)


def _client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@lru_cache
def _still_models():
    from .vision.detectors import VehicleDetector

    return VehicleDetector(), _models()[1]


def _jpeg(img) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return buf.tobytes()


class ComplaintIn(BaseModel):
    draft_id: str
    category: str
    description: str = Field(min_length=5, max_length=1000)
    location_text: str = Field(min_length=3, max_length=200)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    observed_at: str | None = Field(None, max_length=40)
    plate_confirmed: str | None = Field(None, max_length=20)
    contact: str | None = Field(None, max_length=120)
    consent: bool


class DeskUpdate(BaseModel):
    status: str
    note: str | None = Field(None, max_length=1000)


@app.get("/api/complaints/categories")
def complaint_categories():
    return [{"id": k, "label": label, "department": dept, "department_name": get_department(dept).name}
            for k, (label, dept) in cm.CATEGORIES.items()]


@app.post("/api/complaints/preview")
def complaint_preview(request: Request, photo: UploadFile = File(...)):
    """Read the plate in one photo. Nothing is filed yet; the citizen reviews the read first."""
    if not limiter.allow(_client_id(request), "preview", 20):
        raise HTTPException(status_code=429, detail="Too many photos from this device. Please try again later.")
    data = photo.file.read(cm.MAX_PHOTO_BYTES + 1)
    if len(data) > cm.MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo is larger than 10 MB.")
    img = cm.decode_photo(data)
    if img is None:
        raise HTTPException(status_code=415, detail="That file is not a readable image (use JPEG, PNG or WebP).")
    vehicle_detector, plate_detector = _still_models()
    r = cm.read_photo(img, vehicle_detector, plate_detector, get_department("police"))
    fused: FusedPlate = r["fused"]
    meta = {"pattern": fused.pattern, "fused": fused.model_dump(), "colour": r["colour"],
            "vehicle_found": r["vehicle_found"], "plate_found": r["plate_found"],
            "sha256": cm.sha256_bytes(data), "plate_width_px": r["plate_width_px"]}
    draft_id = _store().create_draft(_jpeg(img), _jpeg(r["crop"]) if r["crop"] is not None else None, meta)
    if not r["plate_found"]:
        note = "No number plate could be located in this photo. You can still file the report and type the plate yourself."
    elif fused.known_count == 10:
        note = "All 10 characters were read. Please check them against the photo before you continue."
    else:
        note = (f"{fused.known_count} of 10 characters were readable. The rest are marked ? and were not guessed. "
                "Please check the plate against the photo and correct it if you can see it.")
    return {"draft_id": draft_id, "pattern": fused.pattern, "known_count": fused.known_count,
            "slots": [{"index": s.index, "char": s.char, "confidence": s.confidence} for s in fused.slots],
            "vehicle_found": r["vehicle_found"], "plate_found": r["plate_found"], "plate_width_px": r["plate_width_px"],
            "note": note, "exif": cm.exif_hints(data),
            "plate_crop_url": f"/api/complaints/drafts/{draft_id}/plate" if r["crop"] is not None else None}


@app.get("/api/complaints/drafts/{draft_id}/plate")
def draft_plate(draft_id: str):
    p = _store().draft_file(draft_id, plate=True)
    if p is None:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(p, media_type="image/jpeg")


@app.post("/api/complaints", status_code=201)
def submit_complaint(body: ComplaintIn, request: Request):
    if not body.consent:
        raise HTTPException(status_code=422, detail="Consent is required to file a report.")
    if body.category not in cm.CATEGORIES:
        raise HTTPException(status_code=422, detail=f"unknown category '{body.category}'")
    plate = cm.clean_plate(body.plate_confirmed)
    if plate == "":
        raise HTTPException(status_code=422, detail="The plate must be 4 to 10 letters or digits.")
    if not limiter.allow(_client_id(request), "submit", 5):
        raise HTTPException(status_code=429, detail="Too many reports from this device. Please try again later.")
    fields = body.model_dump()
    fields["plate_confirmed"] = plate
    try:
        cid = _store().submit(body.draft_id, fields)
    except KeyError:
        raise HTTPException(status_code=404, detail="That photo was not found or was already submitted. Upload it again.")
    dept = get_department(cm.CATEGORIES[body.category][1])
    return {"complaint_id": cid, "status": "new", "department": dept.name,
            "message": "Your report was received. It is a lead for an officer to review, not a verdict on anyone."}


@app.get("/api/complaints/{cid}/status")
def complaint_status(cid: str):
    """What a citizen may see about their own report: its state, never registry data or officer notes."""
    row = _store().get(cid)
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")
    return {"complaint_id": row["id"], "status": row["status"], "created_at": row["created_at"],
            "department": get_department(row["department"]).name, "category": cm.CATEGORIES[row["category"]][0]}


# ---------------------------------------------------------------- officer desk
def require_officer(x_officer_key: str | None = Header(None)):
    if not x_officer_key or not secrets.compare_digest(x_officer_key.encode(), OFFICER_KEY.encode()):
        raise HTTPException(status_code=401, detail="A valid officer key is required.")


def _summary(row) -> dict:
    return {"id": row["id"], "created_at": row["created_at"], "category": row["category"],
            "category_label": cm.CATEGORIES[row["category"]][0], "department": row["department"],
            "department_name": get_department(row["department"]).name, "plate_read": row["plate_read"],
            "plate_confirmed": row["plate_confirmed"], "status": row["status"], "location_text": row["location_text"],
            "observed_at": row["observed_at"], "plate_found": bool(row["plate_found"]), "vehicle_found": bool(row["vehicle_found"])}


@app.get("/api/desk/complaints", dependencies=[Depends(require_officer)])
def desk_list(status: str | None = None, department: str | None = None):
    if status and status not in cm.STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {cm.STATUSES}")
    return [_summary(r) for r in _store().list(status, department)]


@app.get("/api/desk/complaints/{cid}", dependencies=[Depends(require_officer)])
def desk_detail(cid: str):
    row = _store().get(cid)
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")
    cfg = get_department(row["department"])
    read = FusedPlate.model_validate(json.loads(row["fused_json"]))
    typed = row["plate_confirmed"]
    fused = cm.fused_from_typed(typed, cfg) if typed else read
    match = match_registry(fused, json.loads(row["colour_json"] or "null"), None, load_registry(), cfg)
    return {**_summary(row), "description": row["description"], "lat": row["lat"], "lon": row["lon"],
            "contact": row["contact"], "image_sha256": row["image_sha256"], "officer_note": row["officer_note"],
            "updated_at": row["updated_at"], "read_slots": [s.model_dump() for s in read.slots],
            "match_basis": "plate typed by the citizen (unverified)" if typed else "system read of one photo (unverified)",
            "match": match.model_dump(), "statuses": cm.STATUSES}


@app.patch("/api/desk/complaints/{cid}", dependencies=[Depends(require_officer)])
def desk_update(cid: str, body: DeskUpdate):
    if body.status not in cm.STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {cm.STATUSES}")
    if not _store().update(cid, body.status, body.note):
        raise HTTPException(status_code=404, detail="report not found")
    return {"complaint_id": cid, "status": body.status}


@app.get("/api/desk/complaints/{cid}/photo", dependencies=[Depends(require_officer)])
@app.get("/api/desk/complaints/{cid}/plate", dependencies=[Depends(require_officer)])
def desk_image(cid: str, request: Request):
    store = _store()
    if store.get(cid) is None:
        raise HTTPException(status_code=404, detail="report not found")
    p = store.dir / (f"{cid}_plate.jpg" if request.url.path.endswith("/plate") else f"{cid}.jpg")
    if not p.exists():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(p, media_type="image/jpeg")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
