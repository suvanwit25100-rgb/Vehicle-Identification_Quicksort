"""Aggregates what the system has actually done (saved jobs, complaints, models, calibration) for the monitor page.
Everything here is read from disk; nothing is invented or sampled."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .schemas import AnalysisResult

_cache: dict[tuple[str, float], AnalysisResult] = {}


def _load(path: Path) -> AnalysisResult | None:
    key = (str(path), path.stat().st_mtime)
    if key not in _cache:
        try:
            _cache[key] = AnalysisResult.model_validate_json(path.read_text())
        except Exception:  # noqa: BLE001 - skip unreadable or older-format jobs
            return None
    return _cache[key]


def job_summary(data_dir: Path) -> dict:
    jobs_dir = data_dir / "jobs"
    results = []
    if jobs_dir.exists():
        for f in jobs_dir.glob("*/result.json"):
            r = _load(f)
            if r is not None:
                results.append((f.stat().st_mtime, r))
    results.sort(key=lambda x: -x[0])

    outcomes = {"match": 0, "ambiguous": 0, "no_confident_match": 0, "insufficient_evidence": 0}
    cross = {"agrees": 0, "disagrees": 0, "inconclusive": 0}
    by_dept: dict[str, int] = {}
    known_hist = [0] * 11
    tracks = readable = frames = 0
    recent = []
    for mtime, r in results:
        by_dept[r.department] = by_dept.get(r.department, 0) + 1
        frames += r.frames_sampled
        best, n_read = "", 0
        for t in r.tracks:
            tracks += 1
            k = t.match.fused.known_count
            known_hist[k] += 1
            outcomes[t.match.status] += 1
            if k and t.second_reader:
                cross[t.second_reader.verdict] += 1
            if k:
                readable += 1
                n_read += 1
                if k > sum(c != "?" for c in best):
                    best = t.match.pattern
        recent.append({"job_id": r.job_id, "when": datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds"),
                       "department": r.department, "tracks": len(r.tracks), "readable": n_read, "best_plate": best or None,
                       "filename": r.source_filename})
    return {"total": len(results), "frames_sampled": frames, "tracks": tracks, "tracks_readable": readable,
            "outcomes": outcomes, "cross_check": cross, "by_department": by_dept, "known_chars_hist": known_hist, "recent": recent[:8]}


def calibration_summary(data_dir: Path) -> dict | None:
    p = data_dir / "calibration_report.json"
    return json.loads(p.read_text()) if p.exists() else None


def plate_matches(query: str, pattern: str) -> bool:
    """Does a (possibly partial) plate fit a stored pattern? ? on either side matches anything; known characters must agree."""
    q = "".join(c for c in query.upper() if c.isalnum() or c == "?")
    if "?" not in q and len(q) in (8, 9):
        # a whole plate of 8 or 9 characters (e.g. one series letter) is fitted to the ten slots, exactly as readers are
        from .vision.plate_text import align_to_slots

        slots = align_to_slots([(c, 1.0) for c in q])
        fitted = "".join(sl.char if sl else "?" for sl in slots)
        if sum(c != "?" for c in fitted) >= 6:
            q = fitted
    known = sum(c != "?" for c in q)
    if not known or len(q) > len(pattern):
        return False
    compared = 0
    for a, b in zip(q, pattern):
        if a != "?" and b != "?":
            if a != b:
                return False
            compared += 1
    return compared >= min(4, known)


def _size(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())


def list_jobs(data_dir: Path, plate: str | None = None, limit: int = 200) -> list[dict]:
    """Every stored analysis, newest first, optionally only those containing a plate that fits `plate`."""
    jobs_dir = data_dir / "jobs"
    out = []
    if not jobs_dir.exists():
        return out
    for f in sorted(jobs_dir.glob("*/result.json"), key=lambda x: -x.stat().st_mtime):
        r = _load(f)
        if r is None:
            continue
        patterns = [t.match.pattern for t in r.tracks if t.match.fused.known_count]
        hits = [p for p in patterns if plate_matches(plate, p)] if plate else []
        if plate and not hits:
            continue
        d = f.parent
        out.append({
            "job_id": r.job_id, "when": r.created_at or datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
            "filename": r.source_filename, "department": r.department, "vehicles": len(r.tracks), "readable": len(patterns),
            "plates": patterns[:8], "matched_plates": hits, "size_bytes": _size(d), "has_video": any(d.glob("source.*")),
            "video": r.video.model_dump() if r.video else None, "second_reader": r.second_reader_used,
            "processing_seconds": r.processing_seconds,
        })
        if len(out) >= limit:
            break
    return out
