import cv2
import numpy as np
import pytest

from app.registry import load_registry
from app.vision.detectors import MODELS_DIR, PlateDetector, VehicleDet, VehicleTracker
from app.vision.pipeline import analyze_video

from .vision_helpers import render_plate

needs_weights = pytest.mark.skipif(
    not (MODELS_DIR / "plate_s.pt").exists() or not (MODELS_DIR / "yolov8n.pt").exists(),
    reason="detector weights not downloaded",
)


class StubTracker:
    def reset(self):
        pass

    def update(self, frame):
        return [VehicleDet(1, "car", 0.9, (20, 40, 500, 290))]


def synthetic_clip(path, plate_text, n=120):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (520, 300))
    rng = np.random.default_rng(0)
    plate_img = cv2.resize(render_plate(plate_text, 380), (190, 45))
    for i in range(n):
        f = np.full((300, 520, 3), 120, np.uint8)
        cv2.rectangle(f, (20, 40), (500, 290), (18, 18, 18), -1)
        p = plate_img.copy()
        if i % 4 == 1:
            p = cv2.GaussianBlur(p, (0, 0), 2.5)
        if i % 5 == 2:
            p[:, 120:150] = 128
        if i % 7 == 3:
            p = np.clip(p.astype(int) + rng.normal(0, 25, p.shape), 0, 255).astype(np.uint8)
        f[200:245, 165:355] = p
        w.write(f)
    w.release()


@needs_weights
def test_pipeline_recovers_plate_from_degraded_synthetic_clip(tmp_path):
    target = load_registry()[0]
    clip = tmp_path / "clip.mp4"
    synthetic_clip(clip, target.plate)
    res = analyze_video(clip, "police", StubTracker(), PlateDetector(), out_dir=tmp_path / "jobs")
    track = res.tracks[0]
    assert track.match.pattern == target.plate
    assert track.match.status == "match"
    assert track.match.candidates[0].plate == target.plate
    assert len(res.source_sha256) == 64
    assert (tmp_path / "jobs" / res.job_id / track.plate_crops[0]).exists()


@needs_weights
def test_clip_without_plate_reports_insufficient_evidence(tmp_path):
    clip = tmp_path / "blank.mp4"
    w = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 30, (520, 300))
    for _ in range(60):
        w.write(np.full((300, 520, 3), 120, np.uint8))
    w.release()
    res = analyze_video(clip, "police", StubTracker(), PlateDetector())
    assert res.tracks[0].match.status == "insufficient_evidence"
    assert res.tracks[0].frames_with_plate == 0
    assert res.tracks[0].plate_note == "No plate was located in any frame."
    assert res.tracks[0].match.message.startswith("No plate was located in any frame.")


class FragmentingTracker:
    """Same car, but the tracker hands out a new id every few frames."""
    def __init__(self):
        self.n = 0

    def reset(self):
        self.n = 0

    def update(self, frame):
        self.n += 1
        return [VehicleDet(1 + self.n // 4, "car", 0.9, (20, 40, 500, 290))]


@needs_weights
def test_fragments_with_the_same_plate_are_merged_into_one_track(tmp_path):
    target = load_registry()[0]
    clip = tmp_path / "clip.mp4"
    synthetic_clip(clip, target.plate)
    res = analyze_video(clip, "police", FragmentingTracker(), PlateDetector())
    assert len(res.tracks) == 1
    t = res.tracks[0]
    assert t.merged_from and t.match.pattern == target.plate
    assert t.frames_seen == res.frames_sampled


@needs_weights
def test_unreadable_fragments_are_not_merged(tmp_path):
    clip = tmp_path / "blank.mp4"
    w = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 30, (520, 300))
    for _ in range(60):
        w.write(np.full((300, 520, 3), 120, np.uint8))
    w.release()
    res = analyze_video(clip, "police", FragmentingTracker(), PlateDetector())
    assert len(res.tracks) > 1 and all(not t.merged_from for t in res.tracks)


def test_plate_note_reasons():
    from app.vision.pipeline import MIN_PLATE_PX, plate_note

    assert plate_note(5, 150, known_chars=4) is None
    assert plate_note(0, None, 0) == "No plate was located in any frame."
    small = plate_note(8, 31, 0)
    assert "too small" in small and "31 px" in small and str(MIN_PLATE_PX) in small
    assert "could not be read reliably" in plate_note(8, 140, 0)


def test_tracks_with_readable_plates_come_first(tmp_path):
    target = load_registry()[0]
    clip = tmp_path / "clip.mp4"
    synthetic_clip(clip, target.plate)
    res = analyze_video(clip, "police", StubTracker(), PlateDetector())
    assert res.tracks[0].plate_note is None
    assert res.tracks[0].max_plate_width_px and res.tracks[0].max_plate_width_px > 100


@needs_weights
def test_real_vehicle_tracker_runs_and_resets(tmp_path):
    tracker = VehicleTracker()
    frame = np.full((300, 520, 3), 120, np.uint8)
    assert tracker.update(frame) == []
    tracker.reset()
    assert tracker.update(frame) == []
