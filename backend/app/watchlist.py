"""Watch-list and repeat sightings.

Two separate ideas, both built on the plates already stored with every analysis:

* Repeat sightings answer "has this vehicle been seen in more than one video?" Readable plates from all stored analyses are grouped when
  they cannot be told apart (no character clashes, at least MIN_AGREE characters agree). Reading the same video twice is not a repeat:
  footage is identified by the hash of the video file (file name and duration when no hash is recorded), and only distinct footage counts.
* The watch-list is a short list of plates an officer wants flagged, with a reason. It is behind the officer key and is never part of a
  public response. A hit is a lead to verify, never a conclusion: a partial read can only ever be a "possible" hit.

Neither changes how a plate is read. Unknown characters stay unknown and are never used to make a hit.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .monitor import _load
from .schemas import ABSENT, PLATE_LEN, to_slots

MIN_KNOWN_TO_LIST = 7      # a plate needs this many read characters to be grouped as a sighting
MIN_AGREE = 7              # characters that must agree (and none clash) for two readings to be the same plate
MIN_ENTRY_KNOWN = 4        # a watch-list entry must say at least this much, or it would flag half the roads
MIN_HIT_AGREE = 6          # read characters that must agree with an entry before it can be a hit
MAX_ENTRIES = 500
MAX_REASON = 200

ENTRY_RE = re.compile(r"^[A-Z0-9?\-]{4,12}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    id TEXT PRIMARY KEY,
    plate TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    removed_at TEXT
)
"""


def compare(a: str, b: str) -> tuple[int, int]:
    """(agree, clash) between two ten-slot patterns. ? on either side is unknown and counts for neither; the absent marker is not a character."""
    agree = clash = 0
    for x, y in zip(a, b):
        if x == "?" or y == "?":
            continue
        if x == y:
            agree += x != ABSENT
        else:
            clash += 1
    return agree, clash


def clean_entry(text: str) -> str:
    """A watch-list plate in ten slots, or ValueError. ? stands for a character the officer does not know."""
    t = "".join(text.upper().split())
    if not ENTRY_RE.fullmatch(t):
        raise ValueError("Use letters, digits and ? only (4 to 12 characters).")
    slots = to_slots(t.replace("-", ""))
    if len(slots) > PLATE_LEN:
        raise ValueError("A plate has at most 10 characters.")
    known = sum(c not in "?-" for c in slots)
    if known < MIN_ENTRY_KNOWN:
        raise ValueError(f"Give at least {MIN_ENTRY_KNOWN} known characters; a shorter entry would match too many vehicles.")
    return slots.ljust(PLATE_LEN, "?")


def shown(slots: str) -> str:
    return slots.replace(ABSENT, "")


class WatchStore:
    def __init__(self, root: Path):
        self.path = root / "netra.db"
        root.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.execute(SCHEMA)

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add(self, plate: str, reason: str) -> dict:
        slots = clean_entry(plate)
        reason = " ".join(reason.split())
        if not reason:
            raise ValueError("Say why this plate is on the list.")
        if len(reason) > MAX_REASON:
            raise ValueError(f"Keep the reason under {MAX_REASON} characters.")
        with self.db() as c:
            if c.execute("SELECT COUNT(*) FROM watchlist WHERE removed_at IS NULL").fetchone()[0] >= MAX_ENTRIES:
                raise ValueError("The watch-list is full.")
            if c.execute("SELECT 1 FROM watchlist WHERE plate=? AND removed_at IS NULL", (slots,)).fetchone():
                raise ValueError("That plate is already on the list.")
            wid = uuid.uuid4().hex[:10]
            c.execute("INSERT INTO watchlist (id, plate, reason, created_at) VALUES (?,?,?,?)",
                      (wid, slots, reason, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        return self.get(wid)

    def get(self, wid: str) -> dict | None:
        with self.db() as c:
            r = c.execute("SELECT * FROM watchlist WHERE id=?", (wid,)).fetchone()
        return self._row(r) if r else None

    def entries(self) -> list[dict]:
        with self.db() as c:
            rows = c.execute("SELECT * FROM watchlist WHERE removed_at IS NULL ORDER BY created_at DESC").fetchall()
        return [self._row(r) for r in rows]

    def remove(self, wid: str) -> bool:
        """Soft delete: the row stays for the record, it just stops matching."""
        with self.db() as c:
            n = c.execute("UPDATE watchlist SET removed_at=? WHERE id=? AND removed_at IS NULL",
                          (datetime.now(timezone.utc).isoformat(timespec="seconds"), wid)).rowcount
        return bool(n)

    @staticmethod
    def _row(r) -> dict:
        return {"id": r["id"], "plate": shown(r["plate"]), "slots": r["plate"], "reason": r["reason"], "created_at": r["created_at"]}


def hit_level(entry_slots: str, pattern: str) -> str | None:
    """"exact" when every character the entry names was read and agrees, "possible" when the read agrees but some of it is unknown, else None."""
    agree, clash = compare(entry_slots, pattern)
    wanted = sum(c not in "?-" for c in entry_slots)
    if clash or agree < min(MIN_HIT_AGREE, wanted):
        return None
    return "exact" if agree >= wanted else "possible"


def _footage_key(r) -> tuple:
    if r.source_sha256 and set(r.source_sha256) != {"0"}:
        return (r.source_sha256,)               # the video's own content hash: the same file is the same footage whatever it was called
    v = r.video
    return (r.source_filename or r.job_id, v.duration_s if v else None, f"{v.width}x{v.height}" if v else None)


def all_sightings(data_dir: Path) -> list[dict]:
    """Every readable plate in every stored analysis, newest analysis first."""
    out = []
    jobs = data_dir / "jobs"
    if not jobs.exists():
        return out
    for f in sorted(jobs.glob("*/result.json"), key=lambda x: -x.stat().st_mtime):
        r = _load(f)
        if r is None:
            continue
        footage = "|".join(map(str, _footage_key(r)))
        for t in r.tracks:
            if t.match.fused.known_count >= MIN_KNOWN_TO_LIST:
                out.append({"job_id": r.job_id, "track_id": t.track_id, "when": r.created_at or datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
                            "filename": r.source_filename, "footage": footage, "slots": t.match.pattern, "known": t.match.fused.known_count,
                            "vehicle": t.vehicle_label, "department": r.department})
    return out


def repeat_groups(sightings: list[dict], min_footage: int = 2, plate: str | None = None) -> list[dict]:
    """Group sightings that cannot be told apart; keep the groups seen in at least `min_footage` distinct videos."""
    groups: list[dict] = []
    for s in sorted(sightings, key=lambda x: -x["known"]):
        for g in groups:
            agree, clash = compare(g["slots"], s["slots"])
            if not clash and agree >= MIN_AGREE:
                g["sightings"].append(s)
                break
        else:
            groups.append({"slots": s["slots"], "sightings": [s]})
    out = []
    for g in groups:
        footage = {s["footage"] for s in g["sightings"]}
        if len(footage) < min_footage:
            continue
        ss = sorted(g["sightings"], key=lambda x: x["when"])
        if plate:
            try:
                q = clean_entry(plate)
            except ValueError:
                return []
            if hit_level(q, g["slots"]) is None:
                continue
        out.append({
            "plate": shown(g["slots"]), "slots": g["slots"], "complete": "?" not in g["slots"],
            "footage_count": len(footage), "sighting_count": len(ss), "first_seen": ss[0]["when"], "last_seen": ss[-1]["when"],
            "sightings": [{k: s[k] for k in ("job_id", "track_id", "when", "filename", "slots", "vehicle", "department")} | {"plate": shown(s["slots"])} for s in ss],
        })
    return sorted(out, key=lambda g: (-g["footage_count"], g["plate"]))


def alerts(data_dir: Path, entries: list[dict]) -> list[dict]:
    """Every stored vehicle that fits a watch-list entry, strongest first."""
    out = []
    jobs = data_dir / "jobs"
    for f in sorted(jobs.glob("*/result.json"), key=lambda x: -x.stat().st_mtime) if jobs.exists() else []:
        r = _load(f)
        if r is None:
            continue
        for t in r.tracks:
            pattern = t.match.pattern
            if not t.match.fused.known_count:
                continue
            for e in entries:
                level = hit_level(e["slots"], pattern)
                if level:
                    out.append({"entry_id": e["id"], "watch_plate": e["plate"], "reason": e["reason"], "level": level, "job_id": r.job_id, "track_id": t.track_id,
                                "read": shown(pattern), "when": r.created_at, "filename": r.source_filename, "department": r.department})
    out.sort(key=lambda a: a["when"] or "", reverse=True)                 # newest first, then exact hits ahead of possible ones
    out.sort(key=lambda a: a["level"] != "exact")
    return out
