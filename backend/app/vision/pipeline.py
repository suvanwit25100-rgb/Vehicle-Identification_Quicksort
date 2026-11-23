import hashlib
import time
import uuid
from datetime import datetime, timezone
from collections import Counter, defaultdict
from pathlib import Path

import cv2

from app.config import get_department
from app.crosscheck import cross_check, pick_reading
from app.fusion import fuse_frames
from app.matcher import match_registry
from app.registry import load_registry
from app.schemas import AnalysisResult, FrameRead, TrackAnalysis, VideoInfo

from .attributes import BODY_PROMPTS, average_distributions, body_distribution, colour_distribution, fuse_body
from .rows import read_plate
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


def plate_layout(reads: list[FrameRead]) -> str | None:
    """"two-row" or "one-row", judged by the frames that actually produced a reading. Tiny frames fall back to one-row and would
    otherwise outvote the one good frame."""
    good = [r.rows for r in reads if r.rows and sum(c is not None for c in r.chars) >= 5]
    votes = good or [r.rows for r in reads if r.rows]
    if not votes:
        return None
    return "two-row" if sum(v == 2 for v in votes) * 2 > len(votes) else "one-row"


def _video_info(path: Path) -> VideoInfo | None:
    cap = cv2.VideoCapture(str(path))
    try:
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None
    finally:
        cap.release()
    if not (w and h):
        return None
    dur = n / fps if (n and fps) else None
    return VideoInfo(width=w, height=h, fps=round(fps, 2), duration_s=round(dur, 2) if dur else None, frames_total=n)


def _fit(img, max_w: int):
    h, w = img.shape[:2]
    return img if w <= max_w else cv2.resize(img, (max_w, max(1, int(h * max_w / w))), interpolation=cv2.INTER_AREA)


def _annotate(img, vehicle_box, plate_box, track_id: int, pattern: str):
    """The frame the plate was read from, with the vehicle (white) and the plate (red) outlined."""
    out = img.copy()
    t = max(2, out.shape[1] // 640)
    cv2.rectangle(out, vehicle_box[:2], vehicle_box[2:], (255, 255, 255), t)
    cv2.rectangle(out, plate_box[:2], plate_box[2:], (63, 42, 255), t + 1)
    label = f"#{track_id}  {pattern}"
    scale = max(0.7, out.shape[1] / 1600)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    x, y = vehicle_box[0], max(th + 10, vehicle_box[1] - 8)
    cv2.rectangle(out, (x, y - th - 8), (x + tw + 10, y + 6), (18, 12, 6), -1)
    cv2.putText(out, label, (x + 5, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 2, cv2.LINE_AA)
    return _fit(out, 1280)


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
    source_name: str | None = None,
    second_reader=None,
) -> AnalysisResult:
    t0 = time.perf_counter()
    path = Path(path)
    info = _video_info(path)
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
    best_vehicle: dict[int, tuple] = {}   # tid -> (area, frame, vehicle box)
    evidence: dict[int, tuple] = {}       # tid -> (score, frame, vehicle box, plate box): where the plate read best

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
            v_area = (x2 - x1) * (y2 - y1)
            if tid not in best_vehicle or v_area > best_vehicle[tid][0]:
                best_vehicle[tid] = (v_area, fr.image, (x1, y1, x2, y2))
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
            chars_raw, n_rows = read_plate(plate)
            chars = align_to_slots(chars_raw)
            sharp = laplacian_var(plate)
            area = float((px2 - px1) * (py2 - py1))
            reads[tid].append(FrameRead(frame_id=fr.frame_id, sharpness=sharp, plate_area=area, chars=chars,
                                        raw="".join(c for c, _ in chars_raw), rows=n_rows))
            crops[tid].append((sharp * area, plate))
            if tid not in evidence or sharp * area > evidence[tid][0]:
                evidence[tid] = (sharp * area, fr.image, (x1, y1, x2, y2), (x1 + max(0, px1), y1 + max(0, py1), x1 + px2, y1 + py2))

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
            if tid in best_vehicle and (primary not in best_vehicle or best_vehicle[tid][0] > best_vehicle[primary][0]):
                best_vehicle[primary] = best_vehicle[tid]
            if tid in evidence and (primary not in evidence or evidence[tid][0] > evidence[primary][0]):
                evidence[primary] = evidence[tid]
            best_vehicle.pop(tid, None)
            evidence.pop(tid, None)
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

        second = None
        if second_reader is not None and crops[tid]:
            top = [img for _, img in sorted(crops[tid], key=lambda c: -c[0])[:KEEP_CROPS]]
            second = cross_check(fused, pick_reading([second_reader.read(img) for img in top]), second_reader.name)

        saved = []
        if job_dir is not None and crops[tid]:
            job_dir.mkdir(parents=True, exist_ok=True)
            for k, (_, img) in enumerate(sorted(crops[tid], key=lambda c: -c[0])[:KEEP_CROPS]):
                name = f"track{tid}_plate{k}.jpg"
                cv2.imwrite(str(job_dir / name), img)
                saved.append(name)
        vehicle_name = evidence_name = None
        if job_dir is not None:
            job_dir.mkdir(parents=True, exist_ok=True)
            if tid in best_vehicle:
                _, vimg, (vx1, vy1, vx2, vy2) = best_vehicle[tid]
                vehicle_name = f"track{tid}_vehicle.jpg"
                cv2.imwrite(str(job_dir / vehicle_name), _fit(vimg[vy1:vy2, vx1:vx2], 640))
            if tid in evidence:
                _, eimg, vbox, pbox = evidence[tid]
                evidence_name = f"track{tid}_evidence.jpg"
                cv2.imwrite(str(job_dir / evidence_name), _annotate(eimg, vbox, pbox, tid, fused.display))

        layout = plate_layout(reads[tid])

        tracks.append(TrackAnalysis(
            track_id=tid, vehicle_label=labels[tid].most_common(1)[0][0], frames_seen=seen[tid],
            frames_with_plate=len(reads[tid]), colour=colour, body_type=body,
            frame_reads=reads[tid], plate_crops=saved, max_plate_width_px=widths[tid] or None,
            plate_note=note, merged_from=sorted(merged_from.get(tid, [])), vehicle_crop=vehicle_name,
            evidence_frame=evidence_name, second_reader=second, plate_layout=layout, match=result,
        ))
    tracks.sort(key=lambda t: (-t.match.fused.known_count, -t.frames_with_plate, -t.frames_seen))

    return AnalysisResult(
        job_id=job_id, department=department, source_sha256=_sha256(path), frames_sampled=len(frames), tracks=tracks,
        source_filename=source_name, created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), video=info,
        processing_seconds=round(time.perf_counter() - t0, 1),
        body_model="CLIP zero-shot with the detector class" if body_classifier is not None else "detector class only (CLIP not installed)",
        second_reader_used=getattr(second_reader, "name", None))
