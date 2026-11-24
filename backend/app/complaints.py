"""Citizen complaint intake: one photo in, a plate read out, stored for an officer to triage.

Rules this module enforces:
- A complaint is a lead, not a verdict. Nothing here accuses anyone.
- Citizens never see registry data. Only the officer endpoints (see main.py) return matches.
- A single photo has no multi-frame fusion, so the read is shown as "to be verified" and the citizen may correct it.
- The stored photo is re-encoded, which drops EXIF; time and GPS from EXIF are offered as editable suggestions only.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .config import DepartmentConfig
from .fusion import fuse_frames
from .schemas import FrameRead, FusedPlate
from .vision.attributes import colour_distribution
from .vision.rows import read_plate
from .vision.plate_text import align_to_slots
from .vision.video import laplacian_var

# category id -> (label shown to citizens, department that triages it)
CATEGORIES: dict[str, tuple[str, str]] = {
    "traffic_violation": ("Traffic violation (signal, wrong side, helmet, seat belt)", "morth_nhai"),
    "dangerous_driving": ("Reckless or dangerous driving", "police"),
    "hit_and_run": ("Hit-and-run or accident", "police"),
    "suspicious_vehicle": ("Suspicious or abandoned vehicle", "police"),
    "fake_plate": ("Number plate looks fake, missing or tampered with", "morth_nhai"),
    "border_west_east": ("Suspicious vehicle near the western or eastern border", "bsf"),
    "border_nepal_bhutan": ("Suspicious vehicle near the Nepal or Bhutan border", "ssb"),
    "contraband": ("Suspected smuggling or contraband movement", "customs"),
}
STATUSES = ["new", "under_review", "verified", "forwarded", "closed", "rejected"]
ID_RE = re.compile(r"[0-9a-f]{12}")
PLATE_RE = re.compile(r"[A-Z0-9]{4,10}")
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_SIDE = 2400
PLATE_PAD = 0.06
TYPED_CONF = 0.9  # a citizen-typed character is unverified, but a human read it from the photo

SCHEMA = """CREATE TABLE IF NOT EXISTS complaints (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, category TEXT NOT NULL, department TEXT NOT NULL,
  description TEXT NOT NULL, location_text TEXT NOT NULL, lat REAL, lon REAL, observed_at TEXT,
  plate_read TEXT NOT NULL, fused_json TEXT NOT NULL, plate_confirmed TEXT, contact TEXT, colour_json TEXT,
  vehicle_found INTEGER NOT NULL, plate_found INTEGER NOT NULL, image_sha256 TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new', officer_note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def decode_photo(data: bytes) -> np.ndarray | None:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        s = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def exif_hints(data: bytes) -> dict:
    """Time and GPS the camera recorded, if any. Offered to the citizen as editable suggestions."""
    out: dict = {"observed_at": None, "lat": None, "lon": None}
    try:
        exif = Image.open(BytesIO(data)).getexif()
        raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        if raw:
            out["observed_at"] = datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S").isoformat(timespec="minutes")
        gps = exif.get_ifd(0x8825)
        if gps.get(2) and gps.get(4):
            def dec(v, ref):
                d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
                return -d if ref in ("S", "W") else d
            out["lat"], out["lon"] = round(dec(gps[2], gps.get(1, "N")), 6), round(dec(gps[4], gps.get(3, "E")), 6)
    except Exception:  # noqa: BLE001 - a missing or odd EXIF block is normal
        pass
    return out


def read_photo(img: np.ndarray, vehicle_detector, plate_detector, cfg: DepartmentConfig) -> dict:
    """Find the vehicle and plate in a still photo and read the plate. Never invents characters."""
    h, w = img.shape[:2]
    vehicles = [v for v in vehicle_detector.detect(img)
                if v.bbox[2] - v.bbox[0] >= 40 and v.bbox[3] - v.bbox[1] >= 40]
    region = None
    colour = None
    hit, source = None, img
    if vehicles:
        x1, y1, x2, y2 = max(vehicles, key=lambda v: (v.bbox[2] - v.bbox[0]) * (v.bbox[3] - v.bbox[1])).bbox
        region = (max(0, x1), max(0, y1), min(w, x2), min(h, y2))
        colour = colour_distribution(img, region)
        source = img[region[1]:region[3], region[0]:region[2]]
        hit = plate_detector.best(source)
    if hit is None:  # no vehicle box, or no plate inside it: try the whole photo
        source = img
        hit = plate_detector.best(img)

    reads: list[FrameRead] = []
    crop = None
    width = None
    if hit is not None:
        (px1, py1, px2, py2), _ = hit
        width = px2 - px1
        pad = int(PLATE_PAD * width)
        crop = source[max(0, py1):py2, max(0, px1 - pad):px2 + pad]
        if crop.shape[0] >= 8 and crop.shape[1] >= 16:
            reads.append(FrameRead(frame_id=0, sharpness=laplacian_var(crop), plate_area=float((px2 - px1) * (py2 - py1)),
                                   chars=align_to_slots(read_plate(crop)[0])))
        else:
            crop = None
    fused = fuse_frames(reads, slot_accept=cfg.slot_accept)
    return {"fused": fused, "crop": crop, "colour": colour, "vehicle_found": bool(vehicles),
            "plate_found": crop is not None, "plate_width_px": width}


def fused_from_typed(plate: str, cfg: DepartmentConfig) -> FusedPlate:
    """A plate typed by the citizen, run through the same 10-slot alignment as an OCR read."""
    read = FrameRead(frame_id=0, sharpness=1.0, plate_area=1.0,
                     chars=align_to_slots([(c, TYPED_CONF) for c in plate]))
    return fuse_frames([read], slot_accept=cfg.slot_accept)


def clean_plate(text: str | None) -> str | None:
    if not text:
        return None
    t = re.sub(r"[\s\-]", "", text.upper())
    return t if PLATE_RE.fullmatch(t) else ""


class RateLimiter:
    """Per-client sliding window kept in memory. Good enough for a demo; production would use a shared store."""

    def __init__(self):
        self.hits: dict[tuple[str, str], deque] = defaultdict(deque)

    def allow(self, client: str, kind: str, limit: int, window_s: int = 3600) -> bool:
        q = self.hits[(client, kind)]
        now = time.time()
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self.hits.clear()


class ComplaintStore:
    def __init__(self, root: Path):
        self.dir = root / "complaints"
        (self.dir / "drafts").mkdir(parents=True, exist_ok=True)
        self.db_path = root / "netra.db"
        with self.db() as c:
            c.execute(SCHEMA)
            have = {r[1] for r in c.execute("PRAGMA table_info(complaints)")}
            c.execute("""CREATE TABLE IF NOT EXISTS case_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, complaint_id TEXT NOT NULL, at TEXT NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL)""")
            for col, ddl in (("source", "TEXT NOT NULL DEFAULT 'citizen'"), ("job_id", "TEXT"), ("track_id", "INTEGER"), ("assigned_to", "TEXT")):
                if col not in have:                      # older databases: add the columns, keep every existing report
                    c.execute(f"ALTER TABLE complaints ADD COLUMN {col} {ddl}")

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # drafts: a photo that has been read but not yet submitted
    def create_draft(self, photo_jpeg: bytes, crop_jpeg: bytes | None, meta: dict) -> str:
        draft_id = uuid.uuid4().hex[:12]
        (self.dir / "drafts" / f"{draft_id}.jpg").write_bytes(photo_jpeg)
        if crop_jpeg:
            (self.dir / "drafts" / f"{draft_id}_plate.jpg").write_bytes(crop_jpeg)
        (self.dir / "drafts" / f"{draft_id}.json").write_text(json.dumps(meta))
        return draft_id

    def draft_meta(self, draft_id: str) -> dict | None:
        p = self.dir / "drafts" / f"{draft_id}.json"
        return json.loads(p.read_text()) if ID_RE.fullmatch(draft_id) and p.exists() else None

    def draft_file(self, draft_id: str, plate: bool = False) -> Path | None:
        p = self.dir / "drafts" / f"{draft_id}{'_plate' if plate else ''}.jpg"
        return p if ID_RE.fullmatch(draft_id) and p.exists() else None

    def submit(self, draft_id: str, f: dict) -> str:
        meta = self.draft_meta(draft_id)
        if meta is None:
            raise KeyError("draft not found or already submitted")
        cid = draft_id
        for suffix in ("", "_plate"):
            src = self.dir / "drafts" / f"{draft_id}{suffix}.jpg"
            if src.exists():
                src.replace(self.dir / f"{cid}{suffix}.jpg")
        (self.dir / "drafts" / f"{draft_id}.json").unlink()
        ts = now_iso()
        with self.db() as c:
            c.execute(
                """INSERT INTO complaints (id, created_at, category, department, description, location_text, lat, lon,
                   observed_at, plate_read, fused_json, plate_confirmed, contact, colour_json, vehicle_found,
                   plate_found, image_sha256, status, officer_note, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new','',?)""",
                (cid, ts, f["category"], CATEGORIES[f["category"]][1], f["description"], f["location_text"],
                 f.get("lat"), f.get("lon"), f.get("observed_at"), meta["pattern"], json.dumps(meta["fused"]),
                 f.get("plate_confirmed") or None, f.get("contact") or None, json.dumps(meta.get("colour")),
                 int(meta["vehicle_found"]), int(meta["plate_found"]), meta["sha256"], ts))
        return cid

    def flag_track(self, job_id: str, track_id: int, f: dict, photo: bytes, crop: bytes | None, fused_json: str, pattern: str,
                   colour: dict | None, plate_found: bool) -> str:
        """File a report straight from an analysed vehicle. The video's evidence frame is the photo; the fused plate is the read."""
        cid = uuid.uuid4().hex[:12]
        (self.dir / f"{cid}.jpg").write_bytes(photo)
        if crop:
            (self.dir / f"{cid}_plate.jpg").write_bytes(crop)
        ts = now_iso()
        with self.db() as c:
            c.execute(
                """INSERT INTO complaints (id, created_at, category, department, description, location_text, lat, lon,
                   observed_at, plate_read, fused_json, plate_confirmed, contact, colour_json, vehicle_found,
                   plate_found, image_sha256, status, officer_note, updated_at, source, job_id, track_id)
                   VALUES (?,?,?,?,?,?,NULL,NULL,?,?,?,NULL,NULL,?,1,?,?,'new','',?,'console',?,?)""",
                (cid, ts, f["category"], CATEGORIES[f["category"]][1], f["description"], f["location_text"], f.get("observed_at"),
                 pattern, fused_json, json.dumps(colour), int(plate_found), sha256_bytes(photo), ts, job_id, track_id))
        return cid

    def flagged_for(self, job_id: str) -> dict[int, str]:
        """track id -> report id, for every vehicle of this analysis that has already been flagged."""
        with self.db() as c:
            rows = c.execute("SELECT track_id, id FROM complaints WHERE source='console' AND job_id=? ORDER BY created_at", (job_id,)).fetchall()
        return {r["track_id"]: r["id"] for r in rows}

    def get(self, cid: str) -> sqlite3.Row | None:
        if not ID_RE.fullmatch(cid):
            return None
        with self.db() as c:
            return c.execute("SELECT * FROM complaints WHERE id=?", (cid,)).fetchone()

    def add_event(self, cid: str, actor: str, kind: str, text: str) -> None:
        with self.db() as c:
            c.execute("INSERT INTO case_events (complaint_id, at, actor, kind, text) VALUES (?,?,?,?,?)", (cid, now_iso(), actor, kind, text[:1000]))

    def events(self, cid: str) -> list[dict]:
        with self.db() as c:
            return [dict(r) for r in c.execute("SELECT at, actor, kind, text FROM case_events WHERE complaint_id=? ORDER BY id", (cid,))]

    def assign(self, cid: str, username: str | None) -> bool:
        with self.db() as c:
            return c.execute("UPDATE complaints SET assigned_to=?, updated_at=? WHERE id=?", (username, now_iso(), cid)).rowcount > 0

    def list(self, status: str | None = None, department: str | None = None, limit: int = 200,
             assigned: str | None = None, q_text: str | None = None, departments: list[str] | None = None) -> list[sqlite3.Row]:
        q, args = "SELECT * FROM complaints WHERE 1=1", []
        if departments:
            q += f" AND department IN ({','.join('?' * len(departments))})"
            args += list(departments)
        if status:
            q += " AND status=?"
            args.append(status)
        if department:
            q += " AND department=?"
            args.append(department)
        if assigned == "unassigned":
            q += " AND assigned_to IS NULL"
        elif assigned:
            q += " AND assigned_to=?"
            args.append(assigned)
        if q_text:
            like = f"%{q_text.strip().upper().replace('%', '')}%"
            q += " AND (UPPER(plate_read) LIKE ? OR UPPER(COALESCE(plate_confirmed,'')) LIKE ? OR UPPER(id) LIKE ? OR UPPER(location_text) LIKE ? OR UPPER(description) LIKE ?)"
            args += [like] * 5
        with self.db() as c:
            return c.execute(q + " ORDER BY created_at DESC LIMIT ?", (*args, limit)).fetchall()

    def update(self, cid: str, status: str, note: str | None) -> bool:
        with self.db() as c:
            cur = c.execute("UPDATE complaints SET status=?, officer_note=COALESCE(?, officer_note), updated_at=? WHERE id=?",
                            (status, note, now_iso(), cid))
            return cur.rowcount > 0

    def counts(self) -> dict:
        with self.db() as c:
            def group(col):
                return {r[0]: r[1] for r in c.execute(f"SELECT {col}, COUNT(*) FROM complaints GROUP BY {col}")}
            return {"total": c.execute("SELECT COUNT(*) FROM complaints").fetchone()[0],
                    "by_status": group("status"), "by_category": group("category"), "by_department": group("department")}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
