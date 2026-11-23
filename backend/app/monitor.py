"""Aggregates what the system has actually done (saved jobs, complaints, models, calibration) for the monitor page.
Everything here is read from disk; nothing is invented or sampled."""

from __future__ import annotations

import json
import os
import platform
import shutil
import statistics
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .schemas import AnalysisResult

_cache: dict[tuple[str, float], AnalysisResult] = {}
WIDTH_BINS = [("under 40 px", 0, 40), ("40 to 79 px", 40, 80), ("80 to 119 px", 80, 120), ("120 px and up", 120, 10**6)]
CONF_EDGES = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]
STARTED = time.time()


class Metrics:
    """Counts of what this server process has actually served since it started. In memory, so a restart resets it."""

    SKIP = ("/api/monitor", "/api/health")

    def __init__(self):
        self.lock = threading.Lock()
        self.counts: Counter = Counter()

    @staticmethod
    def group(path: str) -> str:
        for prefix, name in (("/api/analyze", "analyses"), ("/api/match", "plate matches"), ("/api/complaints", "citizen reports"),
                             ("/api/desk", "officer desk"), ("/api/jobs", "stored results")):
            if path.startswith(prefix):
                return name
        return "other"

    def record(self, path: str, status: int) -> None:
        if not path.startswith("/api/") or path.startswith(self.SKIP):
            return
        with self.lock:
            self.counts["total"] += 1
            self.counts[self.group(path)] += 1
            if status >= 500:
                self.counts["server_errors"] += 1
            elif status >= 400:
                self.counts["client_errors"] += 1

    def snapshot(self) -> dict:
        with self.lock:
            c = dict(self.counts)
        return {"started_at": datetime.fromtimestamp(STARTED, timezone.utc).isoformat(timespec="seconds"),
                "uptime_s": int(time.time() - STARTED), "total": c.pop("total", 0),
                "server_errors": c.pop("server_errors", 0), "client_errors": c.pop("client_errors", 0), "by_group": c}


metrics = Metrics()


def host_stats(data_dir: Path) -> dict:
    """Measurements of the machine and process, each included only if the platform can report it."""
    out: dict = {"cpus": os.cpu_count(), "python": platform.python_version(), "system": platform.system()}
    try:
        out["load_1m"], out["load_5m"], out["load_15m"] = (round(x, 2) for x in os.getloadavg())
    except (AttributeError, OSError):
        pass
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        out["peak_memory_mb"] = round(peak / (1048576 if sys.platform == "darwin" else 1024))
    except ImportError:
        pass
    try:
        du = shutil.disk_usage(data_dir if data_dir.exists() else data_dir.parent)
        out.update(disk_total_gb=round(du.total / 1e9), disk_free_gb=round(du.free / 1e9))
    except OSError:
        pass
    for name in ("jobs", "complaints"):
        d = data_dir / name
        out[f"{name}_bytes"] = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) if d.exists() else 0
    return out


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
    footage = 0.0
    proc_times: list[float] = []
    rt_factors: list[float] = []
    width_bins = {label: {"vehicles": 0, "any": 0, "most": 0} for label, _, _ in WIDTH_BINS}
    conf_hist = [0] * (len(CONF_EDGES) - 1)
    per_day: dict[str, dict[str, int]] = {}
    with_video = 0
    for mtime, r in results:
        by_dept[r.department] = by_dept.get(r.department, 0) + 1
        frames += r.frames_sampled
        if r.video and r.video.duration_s:
            footage += r.video.duration_s
        if r.processing_seconds is not None:
            proc_times.append(r.processing_seconds)
            if r.video and r.video.duration_s:
                rt_factors.append(r.processing_seconds / r.video.duration_s)
        day = (r.created_at or datetime.fromtimestamp(mtime, timezone.utc).isoformat())[:10]
        d = per_day.setdefault(day, {"analyses": 0, "vehicles": 0})
        d["analyses"] += 1
        d["vehicles"] += len(r.tracks)
        best, best_k, n_read = "", 0, 0
        for t in r.tracks:
            tracks += 1
            k = t.match.fused.known_count
            if t.max_plate_width_px:
                for label, lo, hi in WIDTH_BINS:
                    if lo <= t.max_plate_width_px < hi:
                        width_bins[label]["vehicles"] += 1
                        width_bins[label]["any"] += k >= 1
                        width_bins[label]["most"] += k >= 8
            for sl in t.match.fused.slots:
                if sl.char:
                    for i in range(len(CONF_EDGES) - 1):
                        if CONF_EDGES[i] <= sl.confidence < CONF_EDGES[i + 1]:
                            conf_hist[i] += 1
            known_hist[k] += 1
            outcomes[t.match.status] += 1
            if k and t.second_reader:
                cross[t.second_reader.verdict] += 1
            if k:
                readable += 1
                n_read += 1
                if k > best_k:
                    best, best_k = t.match.fused.display, k
        recent.append({"job_id": r.job_id, "when": datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds"),
                       "department": r.department, "tracks": len(r.tracks), "readable": n_read, "best_plate": best or None,
                       "filename": r.source_filename})
    stored_videos = sum(1 for _, r in results if any((jobs_dir / r.job_id).glob("source.*")))
    return {"total": len(results), "distinct_videos": len({r.source_sha256 for _, r in results}), "frames_sampled": frames, "tracks": tracks, "tracks_readable": readable,
            "outcomes": outcomes, "cross_check": cross, "by_department": by_dept, "known_chars_hist": known_hist, "recent": recent[:8],
            "footage_seconds": round(footage, 1), "stored_videos": stored_videos,
            "processing": {"count": len(proc_times), "median_s": round(statistics.median(proc_times), 1) if proc_times else None,
                           "max_s": round(max(proc_times), 1) if proc_times else None,
                           "realtime_factor": round(statistics.median(rt_factors), 2) if rt_factors else None},
            "plate_width": [{"bin": label, **width_bins[label]} for label, _, _ in WIDTH_BINS],
            "confidence_hist": [{"from": CONF_EDGES[i], "to": min(1.0, CONF_EDGES[i + 1]), "count": conf_hist[i]} for i in range(len(conf_hist))],
            "per_day": [{"date": k, **v} for k, v in sorted(per_day.items())][-14:]}


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
            "plates": [p.replace("-", "") for p in patterns[:8]], "matched_plates": [p.replace("-", "") for p in hits], "size_bytes": _size(d), "has_video": any(d.glob("source.*")),
            "video": r.video.model_dump() if r.video else None, "second_reader": r.second_reader_used,
            "processing_seconds": r.processing_seconds,
        })
        if len(out) >= limit:
            break
    return out
