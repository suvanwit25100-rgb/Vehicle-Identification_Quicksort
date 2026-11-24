import shutil

import pytest
from fastapi.testclient import TestClient

from app import main
from app.fusion import fuse_frames
from app.matcher import match_registry
from app.config import get_department
from app.report import render_report
from app.schemas import AnalysisResult, TrackAnalysis

from .helpers import make_frame, row


def sample_result(job_id="abcdef012345", crops=()):
    plate = "CG04KA2819"
    frames = [make_frame(i, plate, unread=(4, 5)) for i in range(3)]
    fused = fuse_frames(frames)
    registry = [row("R1", plate, "white", "suv", flags=["stolen"]), row("R2", "MH12AB3456")]
    match = match_registry(fused, {"white": 0.9}, {"suv": 0.9}, registry, get_department("police"))
    track = TrackAnalysis(
        track_id=1, vehicle_label="car", frames_seen=3, frames_with_plate=3,
        colour={"white": 0.9}, body_type={"suv": 0.9}, frame_reads=frames,
        plate_crops=list(crops), match=match,
    )
    return AnalysisResult(job_id=job_id, department="police", source_sha256="0" * 64,
                          frames_sampled=3, tracks=[track])


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    return TestClient(main.app)


def test_report_contains_required_sections():
    html = render_report(sample_result())
    for needle in ["Recovered plate", "Characters read per frame", "Ranked candidates",
                   "CG04KA2819", "unreadable and are marked unknown", "stolen", "0" * 64]:
        assert needle in html


def test_report_escapes_untrusted_text():
    r = sample_result()
    r.tracks[0].vehicle_label = "<script>alert(1)</script>"
    html = render_report(r)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_report_for_no_confident_match_says_so():
    r = sample_result()
    r.tracks[0].match.status = "no_confident_match"
    r.tracks[0].match.message = "No confident match: best score 0.31 is below the threshold."
    r.tracks[0].match.candidates = []
    html = render_report(r)
    assert "No confident match" in html
    assert "Ranked candidates" not in html


def test_report_collapses_tracks_without_a_readable_plate():
    r = sample_result()
    blank = fuse_frames([make_frame(0, "CG04KA2819", unread=tuple(range(10)))])
    unread = r.tracks[0].model_copy(update={
        "track_id": 9, "vehicle_label": "motorcycle", "frame_reads": [], "frames_with_plate": 0,
        "plate_note": "Plate located but too small: the largest was 31 px wide.",
        "match": match_registry(blank, None, None, [], get_department("police")),
    })
    r.tracks.append(unread)
    html = render_report(r)
    assert "Vehicles without a readable plate (1)" in html
    assert "too small: the largest was 31 px wide" in html
    assert "Vehicle track 1 (car)" in html
    assert "Vehicle track 9" not in html


def test_report_when_no_plate_could_be_read_anywhere():
    r = sample_result()
    blank = fuse_frames([make_frame(0, "CG04KA2819", unread=tuple(range(10)))])
    r.tracks[0] = r.tracks[0].model_copy(update={"match": match_registry(blank, None, None, [], get_department("police"))})
    html = render_report(r)
    assert "No plate could be read for any vehicle" in html


def test_job_round_trip_and_report_endpoint(client):
    result = sample_result()
    main.save_job(result)
    got = client.get(f"/api/jobs/{result.job_id}")
    assert got.status_code == 200 and got.json()["job_id"] == result.job_id
    rep = client.get(f"/api/jobs/{result.job_id}/report")
    assert rep.status_code == 200 and "ExLex analysis report" in rep.text


def test_crop_endpoint_serves_only_expected_names(client, tmp_path):
    result = sample_result(crops=["track1_plate0.jpg"])
    main.save_job(result)
    (tmp_path / "jobs" / result.job_id / "track1_plate0.jpg").write_bytes(b"\xff\xd8jpegdata")
    ok = client.get(f"/api/jobs/{result.job_id}/crops/track1_plate0.jpg")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/jobs/{result.job_id}/crops/result.json").status_code == 404


@pytest.mark.parametrize("bad", ["..", "ABCDEF012345", "abcdef01234", "abcdef0123456", "../etc"])
def test_malformed_job_ids_are_rejected(client, bad):
    assert client.get(f"/api/jobs/{bad}").status_code == 404


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/000000000000").status_code == 404


def test_analyze_rejects_wrong_extension_and_unknown_department(client):
    r = client.post("/api/analyze", files={"file": ("x.txt", b"hi")}, data={"department": "police"})
    assert r.status_code == 415
    r = client.post("/api/analyze", files={"file": ("x.mp4", b"hi")}, data={"department": "nope"})
    assert r.status_code == 404


PAGES = ["/", "/features/", "/console/", "/monitor/", "/archive/", "/report-issue/", "/desk/", "/officer/", "/developers/"]


@pytest.mark.parametrize("page", PAGES)
def test_every_page_loads_and_every_local_file_it_references_exists(client, page):
    import re

    r = client.get(page)
    assert r.status_code == 200 and "ui.css" in r.text and "ui.js" in r.text
    refs = set(re.findall(r'(?:src|href)="(/[^"#?]*)"', r.text)) - {page}
    assert refs, "page references no local files"
    for path in refs:
        assert client.get(path).status_code == 200, f"{page} references missing {path}"


def test_landing_shows_the_project_name_and_not_the_old_ones(client):
    text = client.get("/").text + client.get("/landing.js").text
    assert "ExLex" in client.get("/").text and "AIML-01" in text
    assert "Netra" not in text and "PlateTrace" not in text


def test_landing_data_files_are_served(client):
    for path in ("/data/demo_clear.json", "/img/hero.webp", "/img/hero-sm.webp", "/img/bg2.webp", "/img/bg2-sm.webp"):
        assert client.get(path).status_code == 200, path


def test_registry_sample_is_an_unflagged_synthetic_row(client):
    row = client.get("/api/registry/sample").json()
    assert len(row["plate"]) == 10 and row["flags"] == []
