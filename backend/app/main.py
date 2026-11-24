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
from fastapi.responses import FileResponse, HTMLResponse, Response
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import complaints as cm
from . import officers as of
from .brains import brain_status
from .config import get_department, load_departments
from .fusion import fuse_frames
from .matcher import match_registry
from .monitor import calibration_summary, host_stats, job_summary, list_jobs, metrics
from .registry import load_registry
from .export import build_case_zip
from .report import render_report
from .schemas import AnalysisResult, Evidence, FusedPlate, MatchResult

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_EXT = {".mp4", ".avi", ".mov", ".mkv"}
JOB_ID_RE = re.compile(r"[0-9a-f]{12}")
CROP_RE = re.compile(r"track\d+_(?:plate\d+|vehicle|evidence)\.jpg")

app = FastAPI(title="ExLex API")


@app.middleware("http")
async def count_requests(request: Request, call_next):
    response = await call_next(request)
    metrics.record(request.url.path, response.status_code)
    return response


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


@app.get("/api/sightings")
def sightings(plate: str | None = None, min_videos: int = 2):
    """Plates seen in more than one distinct video. The same video analysed twice is not a repeat."""
    from . import watchlist as wl

    return wl.repeat_groups(wl.all_sightings(DATA_DIR), min_footage=max(1, min(min_videos, 50)), plate=plate)


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


@app.get("/api/jobs/{job_id}/report.pdf")
def job_report_pdf(job_id: str):
    from . import pdf_report

    d = _job_dir(job_id)
    if not pdf_report.available():
        raise HTTPException(status_code=501, detail="PDF export needs the reportlab package (pip install reportlab). The HTML report still works.")
    result = AnalysisResult.model_validate_json((d / "result.json").read_text())
    return Response(pdf_report.render_pdf(result, d), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="report-{job_id}.pdf"'})


@app.get("/api/jobs/{job_id}/actions")
def job_actions(job_id: str):
    """What the agency is told to do with each confirmed match (only for a 'match'; derived from the registry flags)."""
    from . import agency_tools as at

    d = _job_dir(job_id)
    result = AnalysisResult.model_validate_json((d / "result.json").read_text())
    return {"department": result.department, "actions": at.actions_for(result),
            "note": "Suggestions follow the registry flags, and the demo registry is synthetic. They are leads for an officer, not decisions."}


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
    """Everything the monitor page shows. Every number is measured: saved analyses, citizen reports, model files, this server's own
    request counters, and the machine it runs on. Nothing simulated and nothing hard-coded."""
    return {
        "generated_at": cm.now_iso(),
        "server": metrics.snapshot(),
        "host": host_stats(DATA_DIR),
        "brains": brain_status(),
        "jobs": job_summary(DATA_DIR),
        "complaints": _store().counts(),
    }


@app.get("/api/calibration")
def calibration():
    """The threshold calibration. This is the output of a SIMULATION (assumed noise), not measured footage, and is labelled so."""
    return {"simulated": True, "agencies": calibration_summary(DATA_DIR),
            "note": "Produced by scripts/calibrate.py from simulated sightings. A design target, not a measured accuracy."}


# ---------------------------------------------------------------- citizen complaints
# The officer key gates every /api/desk route. There is no built-in default: set EXLEX_OFFICER_KEY (NETRA_OFFICER_KEY still works), or a random key
# is generated for this run and printed once in the server log at start-up.
OFFICER_KEY, _KEY_SOURCE = of.load_or_create_key(DATA_DIR, os.environ.get("EXLEX_OFFICER_KEY") or os.environ.get("NETRA_OFFICER_KEY"))
logging.getLogger("uvicorn.error").warning("Officer master key comes from: %s", _KEY_SOURCE)
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


class FlagIn(BaseModel):
    category: str
    description: str = Field(min_length=5, max_length=1000)
    location_text: str = Field(min_length=3, max_length=200)
    observed_at: str | None = Field(None, max_length=40)


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
    elif "?" not in fused.pattern:
        note = f"All {fused.known_count} characters were read. Please check them against the photo before you continue."
    else:
        note = (f"{fused.known_count} of 10 characters were readable. The rest are marked ? and were not guessed. "
                "Please check the plate against the photo and correct it if you can see it.")
    return {"draft_id": draft_id, "pattern": fused.pattern, "display": fused.display, "known_count": fused.known_count,
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
    _store().queue_message(cid, body.contact, f"ExLex: we received your report {cid}. Use this ID to check its status. It is a lead for an officer to review.")
    return {"complaint_id": cid, "status": "new", "department": dept.name,
            "message": "Your report was received. It is a lead for an officer to review, not a verdict on anyone."}


@app.get("/api/jobs/{job_id}/advice")
def job_advice(job_id: str):
    """Why plates could not be read (fully) in this analysis, and what would help. Restates what was measured; guesses nothing."""
    from .advisor import advise_job

    d = _job_dir(job_id)
    return advise_job(AnalysisResult.model_validate_json((d / "result.json").read_text()))


@app.get("/api/jobs/{job_id}/flags")
def job_flags(job_id: str):
    """Which vehicles of this analysis were already flagged, and the report each one became."""
    _job_dir(job_id)
    return {str(t): cid for t, cid in _store().flagged_for(job_id).items()}


@app.post("/api/jobs/{job_id}/tracks/{track_id}/flag")
def flag_vehicle(job_id: str, track_id: int, body: FlagIn, request: Request):
    """Flag an analysed vehicle: it becomes a report on the officer desk, with the evidence frame, the fused plate and a link back here.
    Nothing here accuses anyone; like every report it is a lead for an officer to check."""
    d = _job_dir(job_id)
    if body.category not in cm.CATEGORIES:
        raise HTTPException(status_code=422, detail="unknown category")
    if not limiter.allow(_client_id(request), "flag", 30):
        raise HTTPException(status_code=429, detail="Too many flags from this connection. Try again later.")
    result = AnalysisResult.model_validate_json((d / "result.json").read_text())
    track = next((t for t in result.tracks if t.track_id == track_id), None)
    if track is None:
        raise HTTPException(status_code=404, detail="no such vehicle in this analysis")
    store = _store()
    already = store.flagged_for(job_id).get(track_id)
    if already:
        raise HTTPException(status_code=409, detail=f"This vehicle was already flagged (report {already}).")
    photo_name = next((n for n in (track.evidence_frame, track.vehicle_crop) if n and (d / n).exists()), None)
    if photo_name is None:
        raise HTTPException(status_code=409, detail="This analysis kept no image of the vehicle, so it cannot be flagged.")
    crop = next(((d / n).read_bytes() for n in track.plate_crops if (d / n).exists()), None)
    cid = store.flag_track(job_id, track_id, body.model_dump(), (d / photo_name).read_bytes(), crop, track.match.fused.model_dump_json(),
                           track.match.pattern, track.colour, bool(crop))
    dept = get_department(cm.CATEGORIES[body.category][1])
    _officers().log({"username": "console", "role": "-"}, "report.flag", cid, f"{job_id}/{track_id}")
    return {"complaint_id": cid, "status": "new", "department": dept.name, "plate": track.match.fused.display}


@app.get("/api/complaints/{cid}/status")
def complaint_status(cid: str):
    """What a citizen may see about their own report: its state, never registry data or officer notes."""
    row = _store().get(cid)
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")
    return {"complaint_id": row["id"], "status": row["status"], "created_at": row["created_at"],
            "department": get_department(row["department"]).name, "category": cm.CATEGORIES[row["category"]][0]}


# ---------------------------------------------------------------- officer desk
def _officers() -> of.OfficerStore:
    return of.OfficerStore(DATA_DIR)


def require_officer(x_officer_key: str | None = Header(None), authorization: str | None = Header(None)) -> dict:
    """Who is calling: a signed-in officer (Bearer token) or the master key (an administrator). Anything else is refused."""
    if authorization and authorization.lower().startswith("bearer "):
        ident = _officers().identity(authorization[7:].strip())
        if ident:
            return ident
    elif x_officer_key and secrets.compare_digest(x_officer_key.encode(), OFFICER_KEY.encode()):
        return dict(of.KEY_IDENTITY)
    raise HTTPException(status_code=401, detail="Sign in as an officer to continue.")


def allowed(who: dict, department: str) -> bool:
    """An officer with agencies listed sees only those; no agencies listed means all (administrators and the master key)."""
    return not who.get("agencies") or department in who["agencies"]


def _case(who: dict, cid: str):
    """A report this officer may work on. One outside their agencies is reported as missing, so its existence is not revealed."""
    row = _store().get(cid)
    if row is None or not allowed(who, row["department"]):
        raise HTTPException(status_code=404, detail="report not found")
    return row


def require_admin(who: dict = Depends(require_officer)) -> dict:
    if who["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only an administrator can do that.")
    return who


def _summary(row) -> dict:
    return {"id": row["id"], "created_at": row["created_at"], "category": row["category"],
            "category_label": cm.CATEGORIES[row["category"]][0], "department": row["department"],
            "department_name": get_department(row["department"]).name, "plate_read": row["plate_read"].replace("-", ""),
            "plate_confirmed": row["plate_confirmed"], "status": row["status"], "location_text": row["location_text"],
            "observed_at": row["observed_at"], "plate_found": bool(row["plate_found"]), "vehicle_found": bool(row["vehicle_found"]),
            "source": row["source"], "job_id": row["job_id"], "track_id": row["track_id"], "assigned_to": row["assigned_to"]}


@app.get("/api/desk/complaints", dependencies=[Depends(require_officer)])
def desk_list(status: str | None = None, department: str | None = None, assigned: str | None = None, q: str | None = None,
              who: dict = Depends(require_officer)):
    if status and status not in cm.STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {cm.STATUSES}")
    if assigned == "me":
        assigned = who["username"]
    if department and not allowed(who, department):
        return []
    from .dedupe import related_map

    rows = _store().list(status, department, assigned=assigned, q_text=(q or "")[:60] or None, departments=who.get("agencies") or None)
    rel = related_map(_store().list(limit=5000, departments=who.get("agencies") or None))      # related across all visible reports, not just this filter
    return [{**_summary(r), "related": len(rel.get(r["id"], []))} for r in rows]


@app.get("/api/desk/complaints/{cid}")
def desk_detail(cid: str, who: dict = Depends(require_officer)):
    row = _case(who, cid)
    cfg = get_department(row["department"])
    read = FusedPlate.model_validate(json.loads(row["fused_json"]))
    typed = row["plate_confirmed"]
    fused = cm.fused_from_typed(typed, cfg) if typed else read
    match = match_registry(fused, json.loads(row["colour_json"] or "null"), None, load_registry(), cfg)
    return {**_summary(row), "description": row["description"], "lat": row["lat"], "lon": row["lon"],
            "contact": row["contact"], "image_sha256": row["image_sha256"], "officer_note": row["officer_note"],
            "updated_at": row["updated_at"], "read_slots": [s.model_dump() for s in read.slots],
            "match_basis": ("plate typed by the citizen (unverified)" if typed else
                            f"fused read of the video (analysis {row['job_id']}, vehicle {row['track_id']})" if row["source"] in ("console", "demo")
                            else "system read of one photo (unverified)"),
            "match": match.model_dump(), "statuses": cm.STATUSES}


@app.patch("/api/desk/complaints/{cid}", dependencies=[Depends(require_officer)])
def desk_update(cid: str, body: DeskUpdate, who: dict = Depends(require_officer)):
    if body.status not in cm.STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {cm.STATUSES}")
    store = _store()
    row = _case(who, cid)
    store.update(cid, body.status, body.note)
    if row["status"] != body.status:
        store.add_event(cid, who["username"], "status", f"{row['status']} -> {body.status}")
        store.queue_message(cid, row["contact"], f"ExLex: your report {cid} is now \"{body.status.replace('_', ' ')}\". Check the status any time with this ID.")
        _officers().log(who, "report.status", cid, f"{row['status']} -> {body.status}")
    if body.note and body.note.strip() != (row["officer_note"] or "").strip():
        store.add_event(cid, who["username"], "note", body.note.strip())
        _officers().log(who, "report.note", cid)
    return {"complaint_id": cid, "status": body.status}


class AssignIn(BaseModel):
    to: str | None = None


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@app.post("/api/desk/complaints/{cid}/assign")
def desk_assign(cid: str, body: AssignIn, who: dict = Depends(require_officer)):
    store = _store()
    _case(who, cid)
    to = (body.to or "").strip().lower() or None
    if to and to != "key" and not (_officers().by_username(to) or {}).get("active"):
        raise HTTPException(status_code=422, detail="No active officer with that username.")
    store.assign(cid, to)
    store.add_event(cid, who["username"], "assign", f"assigned to {to}" if to else "unassigned")
    _officers().log(who, "report.assign", cid, to or "unassigned")
    return {"complaint_id": cid, "assigned_to": to}


@app.post("/api/desk/complaints/{cid}/notes")
def desk_note(cid: str, body: NoteIn, who: dict = Depends(require_officer)):
    store = _store()
    _case(who, cid)
    store.add_event(cid, who["username"], "note", body.text.strip())
    _officers().log(who, "report.note", cid)
    return {"ok": True}


@app.get("/api/desk/complaints/{cid}/related")
def desk_related(cid: str, who: dict = Depends(require_officer)):
    """Other reports about the same vehicle filed within 24 hours of this one."""
    from .dedupe import related_map

    _case(who, cid)
    rows = _store().list(limit=5000, departments=who.get("agencies") or None)
    ids = set(related_map(rows).get(cid, []))
    return [_summary(r) for r in rows if r["id"] in ids]


@app.get("/api/desk/complaints/{cid}/messages")
def desk_messages(cid: str, who: dict = Depends(require_officer)):
    """Messages queued for the citizen who filed this report. Demo: queued and shown here, never sent."""
    _case(who, cid)
    return _store().messages(cid)


@app.get("/api/desk/outbox")
def desk_outbox(who: dict = Depends(require_officer)):
    return {"messages": _store().outbox(who.get("agencies") or None),
            "note": "Demo build: messages are queued and listed here, nothing is sent by email or SMS. A real deployment would connect a sender."}


@app.get("/api/desk/complaints/{cid}/timeline")
def desk_timeline(cid: str, who: dict = Depends(require_officer)):
    store = _store()
    row = _case(who, cid)
    filed = "flagged from the console" if row["source"] == "console" else "filed by a citizen"
    return [{"at": row["created_at"], "actor": "system", "kind": "filed", "text": filed}, *store.events(cid)]


@app.get("/api/desk/complaints.csv", dependencies=[Depends(require_officer)])
def desk_csv(who: dict = Depends(require_officer)):
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "filed", "source", "category", "agency", "status", "assigned_to", "plate_read", "plate_typed", "location", "observed_at", "analysis", "vehicle"])
    for r in _store().list(limit=5000, departments=who.get("agencies") or None):
        w.writerow([r["id"], r["created_at"], r["source"], r["category"], r["department"], r["status"], r["assigned_to"] or "", r["plate_read"].replace("-", ""),
                    r["plate_confirmed"] or "", r["location_text"], r["observed_at"] or "", r["job_id"] or "", r["track_id"] if r["track_id"] is not None else ""])
    _officers().log(who, "report.export", None, "csv")
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="reports.csv"'})


@app.get("/api/desk/complaints/{cid}/photo", dependencies=[Depends(require_officer)])
@app.get("/api/desk/complaints/{cid}/plate", dependencies=[Depends(require_officer)])
def desk_image(cid: str, request: Request, who: dict = Depends(require_officer)):
    store = _store()
    if not store.get(cid) or not allowed(who, store.get(cid)["department"]):
        raise HTTPException(status_code=404, detail="report not found")
    p = store.dir / (f"{cid}_plate.jpg" if request.url.path.endswith("/plate") else f"{cid}.jpg")
    if not p.exists():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(p, media_type="image/jpeg")




# ---------------------------------------------------------------- officer watch-list (never part of a public response)
class WatchIn(BaseModel):
    plate: str
    reason: str


def _watch():
    from . import watchlist as wl

    return wl.WatchStore(DATA_DIR)


@app.get("/api/desk/watchlist", dependencies=[Depends(require_officer)])
def desk_watchlist():
    from . import watchlist as wl

    entries = _watch().entries()
    hits = wl.alerts(DATA_DIR, entries)
    return {"entries": entries, "alerts": hits,
            "note": "A hit is a lead to verify against the video, not a conclusion. 'possible' means the read agrees but some characters were unreadable."}


@app.post("/api/desk/watchlist", dependencies=[Depends(require_officer)])
def desk_watch_add(body: WatchIn, who: dict = Depends(require_officer)):
    try:
        entry = _watch().add(body.plate, body.reason)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _officers().log(who, "watchlist.add", entry["id"], entry["plate"])
    return entry


class ImportIn(BaseModel):
    csv: str = Field(max_length=200_000)
    default_reason: str = Field("", max_length=200)


@app.post("/api/desk/watchlist/import")
def desk_watch_import(body: ImportIn, who: dict = Depends(require_officer)):
    """Add many plates at once from CSV text: plate,reason per line (a header line is fine). Each row follows the same rules as one added by hand."""
    import csv as _csv
    import io

    rows = [r for r in _csv.reader(io.StringIO(body.csv)) if r and any(c.strip() for c in r)]
    if rows and rows[0][0].strip().lower() in ("plate", "plates", "number"):
        rows = rows[1:]
    if len(rows) > 500:
        raise HTTPException(status_code=422, detail="At most 500 rows at a time.")
    added, skipped = 0, []
    for n, r in enumerate(rows, 1):
        plate, reason = r[0].strip(), (r[1].strip() if len(r) > 1 else "") or body.default_reason.strip()
        try:
            _watch().add(plate, reason)
            added += 1
        except ValueError as e:
            skipped.append({"row": n, "plate": plate[:20], "error": str(e)})
    _officers().log(who, "watchlist.import", None, f"{added} added, {len(skipped)} skipped")
    return {"added": added, "skipped": skipped}


@app.delete("/api/desk/watchlist/{wid}", dependencies=[Depends(require_officer)])
def desk_watch_remove(wid: str, who: dict = Depends(require_officer)):
    if not _watch().remove(wid):
        raise HTTPException(status_code=404, detail="No such entry.")
    _officers().log(who, "watchlist.remove", wid)
    return {"removed": wid}


@app.get("/api/desk/jobs/{job_id}/tracks/{track_id}/challan.pdf", dependencies=[Depends(require_officer)])
def desk_challan(job_id: str, track_id: int, who: dict = Depends(require_officer)):
    """A DRAFT e-challan for a document violation. Officer key required; never an official document."""
    from . import agency_tools as at, pdf_report

    d = _job_dir(job_id)
    result = AnalysisResult.model_validate_json((d / "result.json").read_text())
    track = next((t for t in result.tracks if t.track_id == track_id), None)
    if track is None:
        raise HTTPException(status_code=404, detail="no such vehicle in this analysis")
    if not at.challan_available(result.department, track.match):
        raise HTTPException(status_code=409, detail="No challan can be drafted: it needs a confirmed match with a recorded document violation, for the police or MoRTH/NHAI.")
    if not pdf_report.available():
        raise HTTPException(status_code=501, detail="PDF export needs the reportlab package (pip install reportlab).")
    _officers().log(who, "challan.draft", f"{job_id}/{track_id}", track.match.fused.display)
    return Response(at.render_challan(result, track, d), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="draft-challan-{job_id}-{track_id}.pdf"'})


# ---------------------------------------------------------------- officer accounts, sign-in, audit, dashboard
class LoginIn(BaseModel):
    username: str | None = Field(None, max_length=40)
    password: str | None = Field(None, max_length=200)
    key: str | None = Field(None, max_length=200)


def _bearer(authorization: str | None) -> str | None:
    return authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else None


@app.post("/api/officer/login")
def officer_login(body: LoginIn, request: Request):
    """Sign in with a username and password, or with the master key (administrator). Failed attempts are limited and logged."""
    client = _client_id(request)
    if not limiter.allow(client, "login", 12, 900):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Wait a few minutes.")
    store = _officers()
    if body.key:
        if not secrets.compare_digest(body.key.encode(), OFFICER_KEY.encode()):
            store.log({"username": "key", "role": "-"}, "login.failed", None, "master key")
            raise HTTPException(status_code=401, detail="That key was not accepted.")
        ident = dict(of.KEY_IDENTITY)
        token = store.open_session(ident)
    elif body.username and body.password:
        got = store.login(body.username, body.password)
        if got is None:
            store.log({"username": body.username.strip().lower()[:40], "role": "-"}, "login.failed")
            raise HTTPException(status_code=401, detail="Wrong username or password, or the account is switched off.")
        token, ident = got
    else:
        raise HTTPException(status_code=422, detail="Give a username and password, or the officer key.")
    store.log(ident, "login")
    return {"token": token, "officer": ident, "expires_in_hours": of.SESSION_HOURS}


@app.get("/api/officer/me")
def officer_me(who: dict = Depends(require_officer)):
    return who


@app.post("/api/officer/logout")
def officer_logout(authorization: str | None = Header(None), who: dict = Depends(require_officer)):
    tok = _bearer(authorization)
    if tok:
        _officers().logout(tok)
    _officers().log(who, "logout")
    return {"ok": True}


class PasswordIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


@app.post("/api/officer/password")
def officer_password(body: PasswordIn, who: dict = Depends(require_officer)):
    if who["id"] == "key":
        raise HTTPException(status_code=409, detail="The master key has no password. Change it by setting EXLEX_OFFICER_KEY or editing data/officer_key.txt.")
    store = _officers()
    got = store.login(who["username"], body.current)
    if got is None:
        raise HTTPException(status_code=401, detail="The current password is wrong.")
    try:
        store.update(who["id"], password=body.new)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    store.log(who, "account.password")
    return {"ok": True}


class NewOfficer(BaseModel):
    username: str = Field(max_length=40)
    name: str = Field(max_length=100)
    role: str = "officer"
    password: str = Field(max_length=200)
    agencies: list[str] = []


class OfficerPatch(BaseModel):
    role: str | None = None
    active: bool | None = None
    password: str | None = Field(None, max_length=200)
    agencies: list[str] | None = None


def _check_agencies(agencies: list[str] | None) -> None:
    bad = [a for a in (agencies or []) if a not in load_departments()]
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown agency: {', '.join(bad)}.")


@app.get("/api/officer/team", dependencies=[Depends(require_officer)])
def team_list():
    """Names and roles of the active team, so a report can be assigned. Admins see everything on /api/officer/team/all."""
    return [{"username": o["username"], "name": o["name"], "role": o["role"]} for o in _officers().team() if o["active"]]


@app.get("/api/officer/team/all", dependencies=[Depends(require_admin)])
def team_all():
    return _officers().team()


@app.post("/api/officer/team")
def team_create(body: NewOfficer, who: dict = Depends(require_admin)):
    _check_agencies(body.agencies)
    try:
        o = _officers().create(body.username, body.name, body.role, body.password, body.agencies)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _officers().log(who, "team.create", o["username"], o["role"])
    return o


@app.patch("/api/officer/team/{oid}")
def team_update(oid: str, body: OfficerPatch, who: dict = Depends(require_admin)):
    if oid == who["id"] and (body.active is False or (body.role and body.role != who["role"])):
        raise HTTPException(status_code=409, detail="You cannot switch off or demote your own account.")
    store = _officers()
    target = store.get(oid)
    if target is None:
        raise HTTPException(status_code=404, detail="No such officer.")
    if target["role"] == "admin" and (body.active is False or body.role == "officer") and store.admins_active() <= 1:
        raise HTTPException(status_code=409, detail="That is the last active administrator.")
    _check_agencies(body.agencies)
    try:
        o = store.update(oid, role=body.role, active=body.active, password=body.password, agencies=body.agencies)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    what = ", ".join(k for k, v in (("role", body.role), ("active", body.active), ("password reset", body.password), ("agencies", body.agencies)) if v is not None)
    store.log(who, "team.update", target["username"], what)
    return o


@app.get("/api/officer/sessions")
def sessions_list(authorization: str | None = Header(None), who: dict = Depends(require_admin)):
    return _officers().sessions(_bearer(authorization))


@app.delete("/api/officer/sessions/{sid}")
def session_revoke(sid: str, who: dict = Depends(require_admin)):
    if not _officers().revoke(sid):
        raise HTTPException(status_code=404, detail="No such session.")
    _officers().log(who, "session.revoke", sid)
    return {"revoked": sid}


class RetentionIn(BaseModel):
    what: str                      # "analyses" or "reports"
    days: int = Field(ge=1, le=3650)
    confirm: bool = False
    expect: int | None = None      # the number the preview showed; the delete is refused if it has changed


def _retention_targets(what: str, days: int) -> list[dict]:
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    if what == "reports":
        return [{"id": r["id"], "when": r["updated_at"], "label": f"{r['category']} · {r['status']}"} for r in _store().reports_older_than(days)]
    if what == "analyses":
        out = []
        for f in (DATA_DIR / "jobs").glob("*/result.json") if (DATA_DIR / "jobs").exists() else []:
            r = _load_result(f)
            when = r.created_at if r and r.created_at else datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
            try:
                old = datetime.fromisoformat(when) < cutoff
            except ValueError:
                old = False
            if old:
                out.append({"id": f.parent.name, "when": when, "label": (r.source_filename if r else None) or "(unnamed)"})
        return sorted(out, key=lambda x: x["when"])
    raise HTTPException(status_code=422, detail='what must be "analyses" or "reports"')


def _load_result(path):
    try:
        return AnalysisResult.model_validate_json(path.read_text())
    except Exception:  # noqa: BLE001
        return None


@app.post("/api/officer/retention/preview")
def retention_preview(body: RetentionIn, who: dict = Depends(require_admin)):
    """What a clean-up would delete. Reports are only ever closed or rejected ones; open reports are never touched. Nothing is deleted here."""
    t = _retention_targets(body.what, body.days)
    return {"what": body.what, "days": body.days, "count": len(t), "sample": t[:10],
            "note": "Deleting is permanent. Analyses lose their video, images and data; flagged reports keep their own evidence copy." if body.what == "analyses"
                    else "Deleting is permanent. Only closed and rejected reports are included."}


@app.post("/api/officer/retention/apply")
def retention_apply(body: RetentionIn, who: dict = Depends(require_admin)):
    import shutil as _sh

    if not body.confirm:
        raise HTTPException(status_code=422, detail="Set confirm to true to delete. This cannot be undone.")
    t = _retention_targets(body.what, body.days)
    if body.expect is None or body.expect != len(t):
        raise HTTPException(status_code=409, detail=f"The list changed: {len(t)} would be deleted now. Preview again and confirm.")
    for x in t:
        if body.what == "reports":
            _store().delete_report(x["id"])
        else:
            _sh.rmtree(DATA_DIR / "jobs" / x["id"], ignore_errors=True)
    _officers().log(who, f"retention.{body.what}", None, f"deleted {len(t)} older than {body.days} days")
    return {"deleted": len(t)}


@app.delete("/api/officer/analyses/{job_id}")
def delete_analysis(job_id: str, confirm: bool = False, who: dict = Depends(require_admin)):
    import shutil as _sh

    d = _job_dir(job_id)
    if not confirm:
        raise HTTPException(status_code=422, detail="Add ?confirm=true to delete this analysis. This cannot be undone.")
    _sh.rmtree(d, ignore_errors=True)
    _officers().log(who, "analysis.delete", job_id)
    return {"deleted": job_id}


@app.get("/api/officer/demo")
def demo_status(who: dict = Depends(require_admin)):
    return {"loaded": _store().demo_count()}


@app.post("/api/officer/demo/seed")
def demo_seed(who: dict = Depends(require_admin)):
    """Load about ten demo reports built from stored analyses. They are labelled demo and never counted by the monitor."""
    from . import demo_data

    try:
        n = demo_data.seed(DATA_DIR, _store())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    _officers().log(who, "demo.seed", None, f"{n} demo reports")
    return {"created": n}


@app.delete("/api/officer/demo")
def demo_remove(who: dict = Depends(require_admin)):
    n = _store().delete_demo()
    _officers().log(who, "demo.remove", None, f"{n} demo reports")
    return {"removed": n}


@app.get("/api/desk/map")
def desk_map(who: dict = Depends(require_officer)):
    """Reports that carry a location, as pins. Citizen photos with GPS and demo reports have one; console flags do not."""
    rows = [r for r in _store().list(limit=5000, departments=who.get("agencies") or None) if r["lat"] is not None and r["lon"] is not None]
    return [{"id": r["id"], "lat": r["lat"], "lon": r["lon"], "plate": r["plate_confirmed"] or r["plate_read"].replace("-", ""), "status": r["status"],
             "category": cm.CATEGORIES[r["category"]][0].split("(")[0].strip(), "department": r["department"], "when": r["created_at"], "place": r["location_text"],
             "source": r["source"]} for r in rows]


@app.get("/api/officer/audit", dependencies=[Depends(require_admin)])
def audit_log(limit: int = 200, actor: str | None = None, action: str | None = None):
    return _officers().audit(max(1, min(limit, 1000)), actor, action)


@app.get("/api/officer/dashboard")
def officer_dashboard(who: dict = Depends(require_officer)):
    from collections import Counter
    from datetime import datetime, timedelta, timezone

    from . import watchlist as wl

    store = _store()
    rows = store.list(limit=5000, departments=who.get("agencies") or None)
    now = datetime.now(timezone.utc)
    open_states = {"new", "under_review"}
    aging = 0
    per_day: Counter = Counter()
    for r in rows:
        try:
            t = datetime.fromisoformat(r["created_at"])
        except ValueError:
            continue
        if r["status"] == "new" and now - t > timedelta(hours=48):
            aging += 1
        if now - t <= timedelta(days=7):
            per_day[t.date().isoformat()] += 1
    days = [(now - timedelta(days=i)).date().isoformat() for i in range(6, -1, -1)]
    mine = sum(1 for r in rows if r["assigned_to"] == who["username"] and r["status"] in open_states)
    entries = _watch().entries()
    alerts = wl.alerts(DATA_DIR, entries) if entries else []
    jobs = job_summary(DATA_DIR)
    counts = {"total": len(rows), "by_status": dict(Counter(r["status"] for r in rows)), "by_department": dict(Counter(r["department"] for r in rows))}
    return {
        "reports": {"total": counts["total"], "by_status": counts["by_status"], "by_agency": counts["by_department"],
                    "unassigned_open": sum(1 for r in rows if r["assigned_to"] is None and r["status"] in open_states),
                    "mine_open": mine, "aging_new_over_48h": aging, "from_console": sum(1 for r in rows if r["source"] == "console"),
                    "per_day": [{"date": d, "count": per_day.get(d, 0)} for d in days]},
        "analyses": {"stored": jobs["total"], "distinct_videos": jobs["distinct_videos"], "vehicles": jobs["tracks"], "readable": jobs["tracks_readable"]},
        "watchlist": {"entries": len(entries), "hits_exact": sum(a["level"] == "exact" for a in alerts), "hits_possible": sum(a["level"] == "possible" for a in alerts)},
        "repeat_plates": len(wl.repeat_groups(wl.all_sightings(DATA_DIR))),
        "recent_activity": _officers().audit(8) if who["role"] == "admin" else [],
        "you": who,
    }


# the static site is mounted last, so it can never shadow an API route
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
