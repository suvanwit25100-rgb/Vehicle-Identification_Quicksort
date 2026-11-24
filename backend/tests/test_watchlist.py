"""Feature 3: repeat sightings across stored videos, and an officer-only watch-list."""
import pytest

from app import main
from app.config import get_department
from app.fusion import fuse_frames
from app.matcher import match_registry
from app.schemas import AnalysisResult, TrackAnalysis, VideoInfo
from app.watchlist import WatchStore, clean_entry, compare, hit_level

from .helpers import make_frame
from .test_case_export import client  # noqa: F401  (fixture)

KEY = {"X-Officer-Key": main.OFFICER_KEY}


def job(job_id, filename, plates, duration=10.0, when="2026-11-24T10:00:00+00:00"):
    """A stored analysis whose vehicles read `plates` (ten-slot strings; ? = unreadable)."""
    tracks = []
    for n, plate in enumerate(plates, 1):
        unread = tuple(i for i, c in enumerate(plate) if c == "?")
        frames = [make_frame(i, plate.replace("?", "A"), unread=unread) for i in range(3)]
        fused = fuse_frames(frames)
        match = match_registry(fused, {"white": 0.9}, {"suv": 0.9}, [], get_department("police"))
        tracks.append(TrackAnalysis(track_id=n, vehicle_label="car", frames_seen=3, frames_with_plate=3, colour=None, body_type=None,
                                    frame_reads=frames, plate_crops=[], match=match))
    r = AnalysisResult(job_id=job_id, department="police", source_sha256="0" * 64, frames_sampled=3, tracks=tracks)
    r.source_filename, r.created_at = filename, when
    r.video = VideoInfo(width=1920, height=1080, fps=30.0, duration_s=duration, frames_total=300)
    main.save_job(r)
    return r


# ---------------------------------------------------------------- matching rules
def test_compare_ignores_unknowns_and_the_absent_marker():
    assert compare("DL1LR-2711", "DL1LR-2711") == (9, 0)
    assert compare("DL1L??2711", "DL1LR-2711") == (8, 0)
    assert compare("DL1LR-2711", "DL1LA-2711") == (8, 1)


def test_entry_needs_enough_known_characters():
    assert clean_entry("up14ca0914") == "UP14CA0914"
    assert clean_entry("DL1LR2711") == "DL1LR-2711"          # nine characters are placed in ten slots
    assert clean_entry("DL8C??4767") == "DL8C??4767"
    for bad in ("DL?", "?????????", "DL1;DROP", ""):
        with pytest.raises(ValueError):
            clean_entry(bad)


def test_a_partial_read_can_only_be_a_possible_hit_and_a_clash_is_never_a_hit():
    assert hit_level("UP14CA0914", "UP14CA0914") == "exact"
    assert hit_level("UP14CA0914", "UP14CA??14") == "possible"
    assert hit_level("UP14CA0914", "UP14CA0915") is None
    assert hit_level("UP14CA0914", "UP1?????14") is None      # too little read to say anything


# ---------------------------------------------------------------- repeat sightings
def test_same_plate_in_two_different_videos_is_a_repeat(client, tmp_path):
    job("aaaaaaaaaaa1", "monday.mp4", ["UP14CA0914", "DL8CAY4767"], duration=10.0)
    job("aaaaaaaaaaa2", "tuesday.mp4", ["UP14CA0914"], duration=22.0, when="2026-11-25T08:00:00+00:00")
    groups = client.get("/api/sightings").json()
    assert [g["plate"] for g in groups] == ["UP14CA0914"]
    g = groups[0]
    assert g["footage_count"] == 2 and g["sighting_count"] == 2 and g["complete"]
    assert g["first_seen"] < g["last_seen"] and {s["filename"] for s in g["sightings"]} == {"monday.mp4", "tuesday.mp4"}


def test_analysing_the_same_video_twice_is_not_a_repeat(client):
    job("bbbbbbbbbbb1", "clip.mp4", ["UP14CA0914"])
    job("bbbbbbbbbbb2", "clip.mp4", ["UP14CA0914"])
    assert client.get("/api/sightings").json() == []
    assert len(client.get("/api/sightings?min_videos=1").json()) == 1       # still one vehicle, two readings of the same footage


def test_a_partly_read_plate_joins_a_group_only_when_nothing_clashes(client):
    job("ccccccccccc1", "a.mp4", ["DL1LAJ2850"], duration=5.0)
    job("ccccccccccc2", "b.mp4", ["DL1L??2850"], duration=6.0)      # same plate, two characters unreadable
    job("ccccccccccc3", "c.mp4", ["DL1LAJ2860"], duration=7.0)      # one digit different: a different vehicle
    g = client.get("/api/sightings").json()
    assert len(g) == 1 and g[0]["footage_count"] == 2 and {s["filename"] for s in g[0]["sightings"]} == {"a.mp4", "b.mp4"}


def test_search_by_plate_narrows_the_groups(client):
    job("ddddddddddd1", "a.mp4", ["UP14CA0914", "MH12AB3456"], duration=5.0)
    job("ddddddddddd2", "b.mp4", ["UP14CA0914", "MH12AB3456"], duration=6.0)
    assert len(client.get("/api/sightings").json()) == 2
    assert [g["plate"] for g in client.get("/api/sightings?plate=MH1").json()] == []      # too few characters to search
    assert [g["plate"] for g in client.get("/api/sightings?plate=MH12AB34").json()] == ["MH12AB3456"]


def test_unreadable_vehicles_are_not_listed_as_sightings(client):
    job("eeeeeeeeeee1", "a.mp4", ["UP1???????"], duration=5.0)
    job("eeeeeeeeeee2", "b.mp4", ["UP1???????"], duration=6.0)
    assert client.get("/api/sightings").json() == []


# ---------------------------------------------------------------- the watch-list
def test_watchlist_is_closed_without_the_officer_key(client):
    for call in (lambda: client.get("/api/desk/watchlist"), lambda: client.post("/api/desk/watchlist", json={"plate": "UP14CA0914", "reason": "x"}),
                 lambda: client.delete("/api/desk/watchlist/abc")):
        assert call().status_code == 401
    assert client.get("/api/desk/watchlist", headers={"X-Officer-Key": "nope"}).status_code == 401


def test_add_list_alert_and_remove(client):
    job("fffffffffff1", "a.mp4", ["UP14CA0914", "MH12AB3456"], duration=5.0)
    job("fffffffffff2", "b.mp4", ["UP14CA??14"], duration=6.0)
    added = client.post("/api/desk/watchlist", json={"plate": "up14ca0914", "reason": "Reported stolen, FIR pending"}, headers=KEY)
    assert added.status_code == 200 and added.json()["plate"] == "UP14CA0914"
    body = client.get("/api/desk/watchlist", headers=KEY).json()
    assert len(body["entries"]) == 1 and "verify" in body["note"]
    hits = body["alerts"]
    assert [(h["level"], h["filename"]) for h in hits] == [("exact", "a.mp4"), ("possible", "b.mp4")]      # exact first, and MH12AB3456 is not flagged
    assert hits[0]["reason"] == "Reported stolen, FIR pending"
    wid = added.json()["id"]
    assert client.delete(f"/api/desk/watchlist/{wid}", headers=KEY).status_code == 200
    assert client.get("/api/desk/watchlist", headers=KEY).json() == {"entries": [], "alerts": [], "note": body["note"]}
    assert client.delete(f"/api/desk/watchlist/{wid}", headers=KEY).status_code == 404


def test_bad_entries_are_refused(client):
    ok = {"plate": "UP14CA0914", "reason": "x"}
    assert client.post("/api/desk/watchlist", json={**ok, "plate": "UP1"}, headers=KEY).status_code == 422
    assert client.post("/api/desk/watchlist", json={**ok, "reason": "  "}, headers=KEY).status_code == 422
    assert client.post("/api/desk/watchlist", json={**ok, "reason": "x" * 201}, headers=KEY).status_code == 422
    assert client.post("/api/desk/watchlist", json=ok, headers=KEY).status_code == 200
    assert client.post("/api/desk/watchlist", json=ok, headers=KEY).status_code == 422       # already listed


def test_the_watchlist_never_leaks_into_public_responses(client):
    job("ggggggggggg1", "a.mp4", ["UP14CA0914"], duration=5.0)
    client.post("/api/desk/watchlist", json={"plate": "UP14CA0914", "reason": "SECRETREASON"}, headers=KEY)
    for path in ("/api/jobs", "/api/jobs/ggggggggggg1", "/api/sightings?min_videos=1", "/api/monitor", "/api/jobs/ggggggggggg1/report"):
        assert "SECRETREASON" not in client.get(path).text, path


def test_removed_entries_stay_on_file_but_stop_matching(tmp_path):
    s = WatchStore(tmp_path)
    e = s.add("UP14CA0914", "reason")
    assert s.remove(e["id"]) and s.entries() == []
    assert s.get(e["id"])["plate"] == "UP14CA0914"                 # kept for the record
    s.add("UP14CA0914", "listed again")                              # and can be listed again
