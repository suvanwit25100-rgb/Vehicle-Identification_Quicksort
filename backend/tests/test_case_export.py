import csv
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import main
from app.crosscheck import cross_check, pick_reading
from app.fusion import fuse_frames
from app.monitor import plate_matches
from app.registry import load_registry
from app.schemas import SecondReading, VideoInfo

from .helpers import make_frame
from .test_jobs_report import sample_result
from .test_pipeline import StubTracker, needs_weights, synthetic_clip


def fused(plate, unread=()):
    return fuse_frames([make_frame(0, plate, unread=unread)])


# ---------------------------------------------------------------- cross-check logic
def test_a_second_reader_that_matches_every_known_character_agrees():
    r = cross_check(fused("CG04KA2819"), "CG04KA2819", "x")
    assert (r.verdict, r.agree, r.clash) == ("agrees", 10, 0)


def test_one_clashing_character_means_disagreement():
    r = cross_check(fused("CG04KA2819"), "CG04KA2810", "x")
    assert r.verdict == "disagrees" and r.clash == 1


def test_unknown_positions_are_not_compared_and_never_filled_in():
    r = cross_check(fused("CG04KA2819", unread=(4, 5)), "CG04KA2819", "x")
    assert r.verdict == "agrees" and r.agree == 8 and r.clash == 0


def test_a_nine_character_read_is_aligned_like_the_first_reader_before_comparing():
    # the first reader fused DL1L??2711; the second read the whole plate DL1LR2711
    r = cross_check(fused("DL1LAJ2711", unread=(4, 5)), "DL1LR2711", "x")
    assert r.verdict == "agrees" and r.clash == 0 and r.agree == 8


def test_nothing_to_compare_is_inconclusive():
    assert cross_check(fused("CG04KA2819"), "", "x").verdict == "inconclusive"
    assert cross_check(fused("CG04KA2819", unread=tuple(range(10))), "CG04KA2819", "x").verdict == "inconclusive"


def test_pick_reading_prefers_the_most_common_then_the_sharpest():
    assert pick_reading(["AB12CD3456", "AB12CD3456", "AB12CD3450"]) == "AB12CD3456"
    assert pick_reading(["AB12CD3456", "ZZ99ZZ9999"]) == "AB12CD3456"
    assert pick_reading(["", ""]) == ""


@pytest.mark.parametrize("query,pattern,expected", [
    ("CG04KA", "CG04KA2819", True), ("cg04 ka", "CG04KA2819", True), ("CG04??2819", "CG04KA2819", True),
    ("CG04KA2819", "CG04??2819", True), ("CG04KB", "CG04KA2819", False), ("ZZ", "CG04KA2819", False),
    ("", "CG04KA2819", False), ("??????", "CG04KA2819", False), ("CG04KA28190", "CG04KA2819", False),
    ("DL1LR2711", "DL1L??2711", True),    # a real 9-character plate finds its stored, partly read version
    ("DL1LR2712", "DL1L??2711", False),
])
def test_plate_matches(query, pattern, expected):
    assert plate_matches(query, pattern) is expected


# ---------------------------------------------------------------- the case file
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    return TestClient(main.app)


def stored_case(tmp_path, job_id="abcdef012345", rich=True, video=b"fakevideobytes" * 100):
    result = sample_result(job_id=job_id, crops=["track1_plate0.jpg"])
    d = tmp_path / "jobs" / job_id
    if rich:
        t = result.tracks[0]
        t.vehicle_crop, t.evidence_frame = "track1_vehicle.jpg", "track1_evidence.jpg"
        t.max_plate_width_px = 100
        t.second_reader = SecondReading(reader="test reader", reading="CG04KA2819", verdict="agrees", agree=8, clash=0)
        t.frame_reads[0].raw = "CG04KA2819"
        result.source_filename, result.created_at = "street clip.mp4", "2026-11-24T10:00:00+00:00"
        result.video, result.processing_seconds = VideoInfo(width=1920, height=1080, fps=30.0, duration_s=12.5, frames_total=375), 18.2
        result.body_model, result.second_reader_used = "detector class only (CLIP not installed)", "test reader"
    main.save_job(result)
    for name in ("track1_plate0.jpg", "track1_vehicle.jpg", "track1_evidence.jpg"):
        (d / name).write_bytes(b"\xff\xd8" + name.encode())
    if video:
        (d / "source.mp4").write_bytes(video)
    return result


def open_zip(response):
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(response.content))


def test_the_case_file_holds_everything_and_every_hash_in_the_manifest_is_true(client, tmp_path):
    result = stored_case(tmp_path)
    z = open_zip(client.get(f"/api/jobs/{result.job_id}/download"))
    root = f"case-{result.job_id}/"
    names = {n[len(root):] for n in z.namelist()}
    assert {"README.txt", "manifest.json", "report.html", "result.json", "data/tracks.csv", "data/frame_reads.csv", "data/candidates.csv",
            "media/plates/track1_plate0.jpg", "media/vehicles/track1_vehicle.jpg", "media/evidence/track1_evidence.jpg",
            "source/source.mp4"} <= names
    manifest = json.loads(z.read(root + "manifest.json"))
    assert manifest["case_id"] == result.job_id and manifest["source"]["included_in_this_file"] is True
    assert manifest["source"]["original_filename"] == "street clip.mp4" and manifest["analysis"]["vehicles_with_a_readable_plate"] == 1
    assert manifest["department_settings"]["match_threshold"] > 0 and {m["id"] for m in manifest["models"]} >= {"plate_detector", "second_reader"}
    assert len(manifest["files"]) >= 9
    for entry in manifest["files"]:
        data = z.read(root + entry["path"])
        assert len(data) == entry["bytes"] and hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]


def test_the_data_tables_say_what_the_report_says(client, tmp_path):
    result = stored_case(tmp_path)
    z = open_zip(client.get(f"/api/jobs/{result.job_id}/download"))
    root = f"case-{result.job_id}/"
    read = lambda n: list(csv.DictReader(io.StringIO(z.read(root + n).decode("utf-8-sig"))))
    tracks = read("data/tracks.csv")
    assert len(tracks) == 1 and tracks[0]["plate_pattern"] == "CG04??2819" and tracks[0]["known_characters"] == "8"
    assert tracks[0]["status"] == "match" and tracks[0]["second_reader_verdict"] == "agrees" and tracks[0]["top_candidate_plate"] == "CG04KA2819"
    assert "plate_layout" in tracks[0] and "rows" in read("data/frame_reads.csv")[0]
    frames = read("data/frame_reads.csv")
    assert len(frames) == 3 and frames[0]["whole_read"] == "CG04KA2819" and frames[0]["p1_char"] == "C" and frames[0]["p1_conf"] == "0.900"
    # positions 5 and 6 were unreadable in these frames: their cells stay blank rather than holding a guess
    assert frames[0]["p5_char"] == "" and frames[0]["p5_conf"] == "" and frames[0]["p6_char"] == "" and frames[0]["p7_char"] == "2"
    cands = read("data/candidates.csv")
    assert cands[0]["plate"] == "CG04KA2819" and cands[0]["flags"] == "stolen" and cands[0]["reasons"]
    html = z.read(root + "report.html").decode()
    for needle in ["Second reader", "Frame the plate was read from", "Whole read", "Models and settings", "street clip.mp4", "1920x1080"]:
        assert needle in html


def test_the_video_can_be_left_out_and_the_manifest_says_so(client, tmp_path):
    result = stored_case(tmp_path)
    z = open_zip(client.get(f"/api/jobs/{result.job_id}/download?include_video=false"))
    root = f"case-{result.job_id}/"
    assert not any("/source/" in n for n in z.namelist())
    m = json.loads(z.read(root + "manifest.json"))["source"]
    assert m["included_in_this_file"] is False and m["stored_on_server"] is True
    assert "not in this archive" in z.read(root + "README.txt").decode()


def test_a_job_saved_by_an_earlier_version_still_downloads(client, tmp_path):
    result = stored_case(tmp_path, rich=False, video=b"")
    z = open_zip(client.get(f"/api/jobs/{result.job_id}/download"))
    root = f"case-{result.job_id}/"
    m = json.loads(z.read(root + "manifest.json"))
    assert m["source"]["stored_on_server"] is False and m["created_at"] is None
    assert "data/tracks.csv" in {n[len(root):] for n in z.namelist()}


def test_temporary_zip_files_are_cleaned_up(client, tmp_path):
    result = stored_case(tmp_path)
    before = set(Path(tempfile.gettempdir()).glob("*.zip"))
    client.get(f"/api/jobs/{result.job_id}/download")
    assert set(Path(tempfile.gettempdir()).glob("*.zip")) == before


def test_download_of_an_unknown_or_malformed_job_is_404(client):
    assert client.get("/api/jobs/000000000000/download").status_code == 404
    assert client.get("/api/jobs/..%2F..%2Fetc/download").status_code == 404


def test_vehicle_and_evidence_images_are_served_and_nothing_else(client, tmp_path):
    result = stored_case(tmp_path)
    for name in ("track1_vehicle.jpg", "track1_evidence.jpg", "track1_plate0.jpg"):
        assert client.get(f"/api/jobs/{result.job_id}/crops/{name}").status_code == 200
    for bad in ("result.json", "source.mp4", "track1_vehicle.png"):
        assert client.get(f"/api/jobs/{result.job_id}/crops/{bad}").status_code == 404


# ---------------------------------------------------------------- archive and search
def test_the_archive_lists_every_job_and_finds_plates_across_videos(client, tmp_path):
    stored_case(tmp_path, "aaaaaaaaaaaa")
    other = sample_result(job_id="bbbbbbbbbbbb")
    other.tracks[0].match = other.tracks[0].match.model_copy(update={"pattern": "MH12AB3456"})
    main.save_job(other)
    allj = client.get("/api/jobs").json()
    assert {j["job_id"] for j in allj} == {"aaaaaaaaaaaa", "bbbbbbbbbbbb"}
    rich = next(j for j in allj if j["job_id"] == "aaaaaaaaaaaa")
    assert rich["filename"] == "street clip.mp4" and rich["has_video"] and rich["size_bytes"] > 1000 and rich["readable"] == 1
    hits = client.get("/api/jobs?plate=CG04KA").json()
    assert [j["job_id"] for j in hits] == ["aaaaaaaaaaaa"] and hits[0]["matched_plates"] == ["CG04??2819"]
    assert client.get("/api/jobs?plate=CG04KA2819").json()[0]["job_id"] == "aaaaaaaaaaaa"   # ? in the stored plate matches
    assert client.get("/api/jobs?plate=ZZ99").json() == []
    assert len(client.get("/api/jobs?limit=1").json()) == 1


def test_the_archive_is_empty_not_an_error_when_nothing_is_stored(client):
    assert client.get("/api/jobs").json() == []


def test_the_monitor_counts_second_reader_verdicts_and_shows_filenames(client, tmp_path):
    stored_case(tmp_path)
    m = client.get("/api/monitor").json()["jobs"]
    assert m["cross_check"] == {"agrees": 1, "disagrees": 0, "inconclusive": 0} and m["recent"][0]["filename"] == "street clip.mp4"


# ---------------------------------------------------------------- the whole upload path
@needs_weights
def test_uploading_a_video_stores_everything_and_the_download_matches_it(client, tmp_path, monkeypatch):
    from app.vision.detectors import PlateDetector

    target = load_registry()[0].plate

    class StubSecond:
        name = "stub second reader"

        def read(self, img):
            return target

    monkeypatch.setattr(main, "_models", lambda: (StubTracker(), PlateDetector(), None))
    monkeypatch.setattr(main, "_second_reader", lambda: StubSecond())
    clip = tmp_path / "in.mp4"
    synthetic_clip(clip, target)
    video_bytes = clip.read_bytes()

    r = client.post("/api/analyze", files={"file": ("lane camera 3.mp4", video_bytes, "video/mp4")}, data={"department": "police"})
    assert r.status_code == 200
    res = r.json()
    t = res["tracks"][0]
    assert res["source_filename"] == "lane camera 3.mp4" and res["video"]["width"] == 520 and res["processing_seconds"] > 0
    assert res["body_model"].startswith("detector class only") and res["second_reader_used"] == "stub second reader"
    assert t["second_reader"]["verdict"] == "agrees" and t["match"]["pattern"] == target
    assert t["frame_reads"][0]["raw"]
    job = tmp_path / "jobs" / res["job_id"]
    assert (job / "source.mp4").read_bytes() == video_bytes            # the original is kept with the case
    assert not list((tmp_path / "uploads").glob("*"))                   # and is not left behind in the upload folder
    assert (job / t["vehicle_crop"]).exists() and (job / t["evidence_frame"]).exists()
    assert cv2.imread(str(job / t["evidence_frame"])) is not None

    z = open_zip(client.get(f"/api/jobs/{res['job_id']}/download"))
    root = f"case-{res['job_id']}/"
    assert z.read(root + "source/source.mp4") == video_bytes
    manifest = json.loads(z.read(root + "manifest.json"))
    assert manifest["source"]["sha256"] == res["source_sha256"] == hashlib.sha256(video_bytes).hexdigest()


# ---------------------------------------------------------------- the real second reader
def test_the_second_reader_is_listed_in_the_manifest():
    status = {b["id"]: b for b in main.brain_status()}
    assert "second_reader" in status and status["second_reader"]["license"] == "MIT" and status["second_reader"]["required"] is False


@pytest.mark.skipif(not __import__("app.vision.second", fromlist=["available"]).available(), reason="second reader not installed")
def test_the_real_second_reader_reads_a_clean_plate():
    from app.vision.second import SecondReader

    from .vision_helpers import render_plate

    target = load_registry()[0].plate
    reading = SecondReader().read(render_plate(target, 380))
    assert isinstance(reading, str) and len(reading) >= 6
    assert cross_check(fused(target), reading, "real").verdict != "disagrees"
