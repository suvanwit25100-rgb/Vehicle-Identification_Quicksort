"""One analysed video as a single download: report, data tables, every image, the original video, and a manifest.

The manifest lists every file with its SHA-256, plus the models, software and agency settings used, so the file stands on its own
as a record of what was analysed and how.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import zipfile
from importlib import metadata
from pathlib import Path

from .brains import brain_status
from .config import get_department
from .report import render_report
from .schemas import PLATE_LEN, AnalysisResult

CAVEATS = [
    "Confidence scores are uncalibrated estimates, not probabilities.",
    "Candidates are leads for an investigator to verify, not identifications.",
    "Characters shown as ? could not be read reliably and were not guessed.",
    "A second reader that agrees is a strong sign, and one that disagrees is a reason to look; neither changes the fused plate.",
    "Agency thresholds were chosen by simulation, not on labelled footage.",
]

README = """CASE FILE {case}

This archive holds everything the system stored about one analysed video.

report.html            The printable report. Open it in a browser (it prints to PDF). It is self-contained.
result.json            The complete analysis as structured data.
manifest.json          Who/what/when, the models and settings used, and the SHA-256 of every file here.
data/tracks.csv        One row per vehicle: recovered plate, status, top candidate, colour, body type, second-reader verdict.
data/frame_reads.csv   One row per frame the plate was read in: the whole read and each of the 10 characters with its confidence.
data/candidates.csv    The ranked registry candidates for each vehicle, with the reasons.
media/plates/          The sharpest plate crops used.
media/vehicles/        The best crop of each vehicle.
media/evidence/        The frame each plate was read from, with the vehicle (white) and plate (red) outlined.
source/                The original video, if it was included.

The CSV files use UTF-8 with a byte-order mark so they open correctly in Excel.
Characters shown as ? could not be read reliably and were never guessed. {extra}
"""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _versions() -> dict[str, str]:
    out = {}
    for pkg in ("ultralytics", "rapidocr-onnxruntime", "onnxruntime", "fast-plate-ocr", "transformers", "torch", "opencv-python", "numpy"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            pass
    return out


def _csv(header: list[str], rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _top(dist: dict[str, float] | None) -> tuple[str, str]:
    if not dist:
        return "", ""
    k = max(dist, key=dist.get)
    return k, f"{dist[k]:.2f}"


def tracks_csv(result: AnalysisResult) -> bytes:
    header = ["track_id", "vehicle", "frames_seen", "frames_with_plate", "merged_from", "plate_pattern", "known_characters", "status",
              "message", "top_candidate_plate", "top_candidate_confidence", "colour", "colour_confidence", "body_type",
              "body_type_confidence", "largest_plate_px", "plate_note", "second_reader", "second_reader_reading",
              "second_reader_verdict", "second_reader_agree", "second_reader_clash", "plate_layout"]
    rows = []
    for t in result.tracks:
        m, top = t.match, (t.match.candidates[0] if t.match.candidates else None)
        c, cc = _top(t.colour)
        b, bc = _top(t.body_type)
        s = t.second_reader
        rows.append([t.track_id, t.vehicle_label, t.frames_seen, t.frames_with_plate, " ".join(map(str, t.merged_from)), m.pattern,
                     m.fused.known_count, m.status, m.message, top.plate if top else "", f"{top.confidence:.2f}" if top else "", c, cc, b, bc,
                     t.max_plate_width_px or "", t.plate_note or "", s.reader if s else "", s.reading if s else "",
                     s.verdict if s else "", s.agree if s else "", s.clash if s else "", t.plate_layout or ""])
    return _csv(header, rows)


def frame_reads_csv(result: AnalysisResult) -> bytes:
    header = ["track_id", "frame_id", "sharpness", "plate_area_px2", "whole_read", "rows"] + [f"p{i}_{k}" for i in range(1, PLATE_LEN + 1) for k in ("char", "conf")]
    rows = []
    for t in result.tracks:
        for fr in t.frame_reads:
            cells = []
            for c in fr.chars:
                cells += [c.char, f"{c.conf:.3f}"] if c else ["", ""]
            rows.append([t.track_id, fr.frame_id, f"{fr.sharpness:.1f}", f"{fr.plate_area:.0f}", fr.raw or "", fr.rows or ""] + cells)
    return _csv(header, rows)


def candidates_csv(result: AnalysisResult) -> bytes:
    header = ["track_id", "rank", "registry_id", "plate", "confidence", "make", "model", "colour", "body_type", "flags", "matched_slots",
              "mismatched_slots", "unknown_slots", "reasons"]
    rows = []
    for t in result.tracks:
        for i, c in enumerate(t.match.candidates, 1):
            rows.append([t.track_id, i, c.reg_id, c.plate, f"{c.confidence:.3f}", c.make, c.model, c.colour, c.body_type, " ".join(c.flags),
                         " ".join(str(x + 1) for x in c.matched_slots), " ".join(str(x + 1) for x in c.mismatched_slots),
                         " ".join(str(x + 1) for x in c.unknown_slots), " | ".join(c.reasons)])
    return _csv(header, rows)


def build_case_zip(result: AnalysisResult, job_dir: Path, include_video: bool = True) -> Path:
    """Write the case file to a temporary .zip and return its path. The caller deletes it after sending."""
    root = f"case-{result.job_id}"
    entries: list[dict] = []
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()

    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as z:
        def add_bytes(arc: str, data: bytes) -> None:
            z.writestr(f"{root}/{arc}", data)
            entries.append({"path": arc, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})

        def add_file(arc: str, path: Path, stored: bool = False) -> None:
            z.write(path, f"{root}/{arc}", compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
            entries.append({"path": arc, "bytes": path.stat().st_size, "sha256": _sha256_file(path)})

        for t in result.tracks:
            for name in t.plate_crops:
                if (job_dir / name).exists():
                    add_file(f"media/plates/{name}", job_dir / name, stored=True)
            if t.vehicle_crop and (job_dir / t.vehicle_crop).exists():
                add_file(f"media/vehicles/{t.vehicle_crop}", job_dir / t.vehicle_crop, stored=True)
            if t.evidence_frame and (job_dir / t.evidence_frame).exists():
                add_file(f"media/evidence/{t.evidence_frame}", job_dir / t.evidence_frame, stored=True)

        add_bytes("data/tracks.csv", tracks_csv(result))
        add_bytes("data/frame_reads.csv", frame_reads_csv(result))
        add_bytes("data/candidates.csv", candidates_csv(result))
        add_bytes("report.html", render_report(result, job_dir).encode("utf-8"))
        add_bytes("result.json", result.model_dump_json(indent=2).encode("utf-8"))

        source = next(iter(sorted(job_dir.glob("source.*"))), None)
        included = bool(include_video and source)
        if included:
            add_file(f"source/{source.name}", source, stored=True)

        try:
            dept = get_department(result.department).model_dump()
        except KeyError:
            dept = None
        readable = sum(1 for t in result.tracks if t.match.fused.known_count)
        manifest = {
            "case_id": result.job_id, "created_at": result.created_at, "department": result.department, "department_settings": dept,
            "source": {"original_filename": result.source_filename, "sha256": result.source_sha256,
                       "video": result.video.model_dump() if result.video else None, "included_in_this_file": included,
                       "stored_on_server": bool(source)},
            "analysis": {"frames_sampled": result.frames_sampled, "vehicles_tracked": len(result.tracks), "vehicles_with_a_readable_plate": readable,
                         "processing_seconds": result.processing_seconds, "body_type_method": result.body_model,
                         "second_reader": result.second_reader_used},
            "software": _versions(),
            "models": [{k: b[k] for k in ("id", "role", "source", "license", "required")} | {"installed_when_exported": b["ready"]} for b in brain_status()],
            "files": sorted(entries, key=lambda e: e["path"]),
            "notes": CAVEATS,
        }
        add_bytes("manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
        extra = "" if included else "The original video is not in this archive (it was left out, or was not stored)."
        z.writestr(f"{root}/README.txt", README.format(case=result.job_id, extra=extra))
    return Path(tmp.name)
