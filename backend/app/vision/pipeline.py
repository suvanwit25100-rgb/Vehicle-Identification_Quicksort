import hashlib
import uuid
from collections import Counter, defaultdict
from pathlib import Path

import cv2

from app.config import get_department
from app.fusion import fuse_frames
from app.matcher import match_registry
from app.registry import load_registry
from app.schemas import AnalysisResult, FrameRead, TrackAnalysis

from .attributes import BODY_PROMPTS, average_distributions, body_distribution, colour_distribution, fuse_body
from .ocr import read_plate_chars
from .plate_text import align_to_slots
from .stitch import group_tracks
from .video import laplacian_var, sample_frames

MIN_VEHICLE_PX = 40
PLATE_PAD = 0.06
KEEP_CROPS = 3
# On real clips, full 10-character reads appeared at plate widths of roughly 85 px and up.
MIN_PLATE_PX = 80


def plate_note(frames_with_plate: int, max_width: int | None, known_chars: int) -> str | None:
    """Why this vehicle has no readable plate; None when at least one character was recovered."""
    if known_chars:
        return None
    if frames_with_plate == 0:
        return "No plate was located in any frame."
    if max_width is not None and max_width < MIN_PLATE_PX:
        return (f"Plate located but too small: the largest was {max_width} px wide, and about "
                f"{MIN_PLATE_PX} px or more is needed to read it reliably.")
    return "Plate located but its characters could not be read reliably (blur, angle or occlusion)."


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def analyze_video(
    path: str | Path,
    department: str,
    tracker,
    plate_detector,
    out_dir: Path | None = None,
    target_fps: float = 6.0,
    max_frames: int = 240,
    body_classifier=None,
) -> AnalysisResult:
    path = Path(path)
    cfg = get_department(department)
    job_id = uuid.uuid4().hex[:12]
    job_dir = out_dir / job_id if out_dir is not None else None
    frames = sample_frames(path, target_fps=target_fps, max_frames=max_frames)
    tracker.reset()

    labels: dict[int, Counter] = defaultdict(Counter)
    seen: dict[int, int] = defaultdict(int)
    colours: dict[int, list] = defaultdict(list)
    bodies: dict[int, list] = defaultdict(list)
    det_conf: dict[int, list] = defaultdict(list)
    reads: dict[int, list[FrameRead]] = defaultdict(list)
    crops: dict[int, list[tuple[float, object]]] = defaultdict(list)
    vcrops: dict[int, list[tuple[int, str, object]]] = defaultdict(list)
    widths: dict[int, int] = defaultdict(int)

    for fr in frames:
        for det in tracker.update(fr.image):
            x1, y1, x2, y2 = det.bbox
            x1, y1 = max(0, x1), max(0, y1)
            if x2 - x1 < MIN_VEHICLE_PX or y2 - y1 < MIN_VEHICLE_PX:
                continue
            tid = det.track_id
            labels[tid][det.label] += 1
            seen[tid] += 1
            det_conf[tid].append(det.conf)
            colours[tid].append(colour_distribution(fr.image, (x1, y1, x2, y2)))
            bodies[tid].append(body_distribution(det.label))

            vehicle = fr.image[y1:y2, x1:x2]
            if body_classifier is not None:
                vcrops[tid].append(((x2 - x1) * (y2 - y1), det.label, vehicle.copy()))
                vcrops[tid] = sorted(vcrops[tid], key=lambda c: -c[0])[:3]
            hit = plate_detector.best(vehicle)
            if hit is None:
                continue
            (px1, py1, px2, py2), _ = hit
            widths[tid] = max(widths[tid], px2 - px1)
            pad = int(PLATE_PAD * (px2 - px1))
            plate = vehicle[max(0, py1):py2, max(0, px1 - pad):px2 + pad]
            if plate.shape[0] < 8 or plate.shape[1] < 16:
                continue
            chars = align_to_slots(read_plate_chars(plate))
            sharp = laplacian_var(plate)
            area = float((px2 - px1) * (py2 - py1))
            reads[tid].append(FrameRead(frame_id=fr.frame_id, sharpness=sharp, plate_area=area, chars=chars))
            crops[tid].append((sharp * area, plate))

    patterns = {tid: fuse_frames(reads[tid], slot_accept=cfg.slot_accept).pattern for tid in seen}
    merged_from: dict[int, list[int]] = {}
    for group in group_tracks(patterns):
        if len(group) == 1:
            continue
        primary = max(group, key=lambda t: (len(reads[t]), -t))
        for tid in group:
            if tid == primary:
                continue
            seen[primary] += seen.pop(tid)
            labels[primary] += labels.pop(tid)
            colours[primary] += colours.pop(tid)
            bodies[primary] += bodies.pop(tid)
            det_conf[primary] += det_conf.pop(tid)
            reads[primary] = sorted(reads[primary] + reads.pop(tid), key=lambda r: r.frame_id)
            crops[primary] += crops.pop(tid)
            vcrops[primary] = sorted(vcrops[primary] + vcrops.pop(tid, []), key=lambda c: -c[0])[:3]
            widths[primary] = max(widths[primary], widths.pop(tid, 0))
            merged_from.setdefault(primary, []).append(tid)

    tracks = []
    for tid in sorted(seen):
        colour = average_distributions(colours[tid], det_conf[tid]) or None
        if body_classifier is not None and vcrops[tid]:
            clip = body_classifier.classify([c[2] for c in vcrops[tid]], BODY_PROMPTS)
            body = average_distributions([fuse_body(c[1], p) for c, p in zip(vcrops[tid], clip)]) or None
        else:
            body = average_distributions(bodies[tid], det_conf[tid]) or None
        fused = fuse_frames(reads[tid], slot_accept=cfg.slot_accept)
        result = match_registry(fused, colour, body, load_registry(), cfg)
        note = plate_note(len(reads[tid]), widths[tid] or None, fused.known_count)
        if note and result.status == "insufficient_evidence":
            result = result.model_copy(update={"message": f"{note} No match attempted."})

        saved = []
        if job_dir is not None and crops[tid]:
            job_dir.mkdir(parents=True, exist_ok=True)
            for k, (_, img) in enumerate(sorted(crops[tid], key=lambda c: -c[0])[:KEEP_CROPS]):
                name = f"track{tid}_plate{k}.jpg"
                cv2.imwrite(str(job_dir / name), img)
                saved.append(name)

        tracks.append(TrackAnalysis(
            track_id=tid, vehicle_label=labels[tid].most_common(1)[0][0], frames_seen=seen[tid],
            frames_with_plate=len(reads[tid]), colour=colour, body_type=body,
            frame_reads=reads[tid], plate_crops=saved, max_plate_width_px=widths[tid] or None,
            plate_note=note, merged_from=sorted(merged_from.get(tid, [])), match=result,
        ))
    tracks.sort(key=lambda t: (-t.match.fused.known_count, -t.frames_with_plate, -t.frames_seen))

    return AnalysisResult(job_id=job_id, department=department, source_sha256=_sha256(path),
                          frames_sampled=len(frames), tracks=tracks)
