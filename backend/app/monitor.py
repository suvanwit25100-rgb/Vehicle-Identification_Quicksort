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
            if k:
                readable += 1
                n_read += 1
                if k > sum(c != "?" for c in best):
                    best = t.match.pattern
        recent.append({"job_id": r.job_id, "when": datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds"),
                       "department": r.department, "tracks": len(r.tracks), "readable": n_read, "best_plate": best or None})
    return {"total": len(results), "frames_sampled": frames, "tracks": tracks, "tracks_readable": readable,
            "outcomes": outcomes, "by_department": by_dept, "known_chars_hist": known_hist, "recent": recent[:8]}


def calibration_summary(data_dir: Path) -> dict | None:
    p = data_dir / "calibration_report.json"
    return json.loads(p.read_text()) if p.exists() else None
