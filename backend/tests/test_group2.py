"""Duplicate-report grouping, plate-quality advice, hot-list import."""
import sqlite3

import pytest

from app import main
from app.advisor import advise_job, advise_track
from app.config import get_department
from app.dedupe import related_map

from .test_case_export import client, stored_case  # noqa: F401  (fixtures)
from .test_officer_portal import KEY, a_report, bearer, make_officer  # noqa: F401
from .test_watchlist import job

BODY = {"category": "dangerous_driving", "description": "Overtook on a blind bend", "location_text": "NH30"}


@pytest.fixture(autouse=True)
def _reset():
    main.limiter.reset()
    yield
    main.limiter.reset()


# ---------------------------------------------------------------- duplicates
class Row(dict):
    pass


def row(id_, plate_read, when, typed=None):
    return Row(id=id_, plate_read=plate_read, plate_confirmed=typed, created_at=when)


def test_same_plate_in_the_same_day_is_related_and_a_clash_or_a_long_gap_is_not():
    rows = [row("a", "UP14CA0914", "2026-11-24T08:00:00+00:00"), row("b", "UP14CA0914", "2026-11-24T20:00:00+00:00"),
            row("c", "UP14CA0915", "2026-11-24T09:00:00+00:00"),          # one digit different: another vehicle
            row("d", "UP14CA0914", "2026-11-26T08:00:00+00:00"),          # two days later
            row("e", "UP1???09??", "2026-11-24T09:00:00+00:00")]          # only 5 characters read: too little to say
    assert related_map(rows) == {"a": ["b"], "b": ["a"]}


def test_a_typed_plate_is_used_and_a_partial_read_joins_a_whole_one():
    rows = [row("a", "??????????", "2026-11-24T08:00:00+00:00", typed="up14 ca 0914"), row("b", "UP14C?????", "2026-11-24T09:00:00+00:00"),
            row("c", "UP14CA??14", "2026-11-24T10:00:00+00:00")]
    rel = related_map(rows)
    assert rel["a"] == ["c"] and rel["c"] == ["a"] and "b" not in rel          # b has only 5 characters read


def test_the_desk_shows_related_counts_and_lists_the_others(client, tmp_path):
    r = stored_case(tmp_path)
    ids = [client.post(f"/api/jobs/{r.job_id}/tracks/1/flag", json=BODY).json()["complaint_id"]]
    r2 = stored_case(tmp_path, job_id="abcdef012346")
    ids.append(client.post(f"/api/jobs/{r2.job_id}/tracks/1/flag", json=BODY).json()["complaint_id"])
    listed = {x["id"]: x["related"] for x in client.get("/api/desk/complaints", headers=KEY).json()}
    assert listed == {ids[0]: 1, ids[1]: 1}
    assert [x["id"] for x in client.get(f"/api/desk/complaints/{ids[0]}/related", headers=KEY).json()] == [ids[1]]
    assert client.get("/api/desk/complaints/000000000000/related", headers=KEY).status_code == 404
    assert client.get(f"/api/desk/complaints/{ids[0]}/related").status_code == 401


# ---------------------------------------------------------------- advisor
def test_advice_restates_what_was_measured(client, tmp_path):
    r = stored_case(tmp_path)
    t = r.tracks[0]
    t.match.fused = type(t.match.fused).model_validate({"slots": [{"index": i, "char": None, "confidence": 0.0} for i in range(10)]})
    t.frames_with_plate, t.max_plate_width_px = 2, 42
    tips = advise_track(t)
    assert any("42 px" in x and "80 px" in x for x in tips) and any("only 2 frames" in x for x in tips)
    t.frames_with_plate = 0
    assert advise_track(t)[0].startswith("The plate was never located")
    job_advice = advise_job(r)
    assert job_advice["summary"][0] == "1 of 1 vehicles had no readable plate."


def test_a_fully_read_plate_gets_no_advice_and_the_endpoint_works(client, tmp_path):
    r = stored_case(tmp_path)
    assert advise_track(job("fffffffffff1", "a.mp4", ["UP14CA0914"]).tracks[0]) == []
    body = client.get(f"/api/jobs/{r.job_id}/advice").json()
    assert set(body) == {"tracks", "summary"} and "1" in body["tracks"]            # the sample plate has two unread positions
    assert client.get("/api/jobs/000000000000/advice").status_code == 404


# ---------------------------------------------------------------- import
def test_import_adds_good_rows_and_explains_the_rest(client):
    csv_text = "plate,reason\nUP14CA0914,Stolen FIR 12\nDL8C??4767,Seen at border\nAB,too short\nUP14CA0914,duplicate\nMH12AB3456,\n"
    r = client.post("/api/desk/watchlist/import", json={"csv": csv_text, "default_reason": "Bulk list, Nov 2026"}, headers=KEY)
    assert r.status_code == 200
    out = r.json()
    assert out["added"] == 3 and [(s["row"], s["plate"]) for s in out["skipped"]] == [(3, "AB"), (4, "UP14CA0914")]
    entries = client.get("/api/desk/watchlist", headers=KEY).json()["entries"]
    assert {e["plate"]: e["reason"] for e in entries}["MH12AB3456"] == "Bulk list, Nov 2026"
    assert client.post("/api/desk/watchlist/import", json={"csv": "x\n" * 501}, headers=KEY).status_code == 422
    assert client.post("/api/desk/watchlist/import", json={"csv": "UP14CA0914,x"}).status_code == 401
    assert ("key", "watchlist.import") in [(a["actor"], a["action"]) for a in client.get("/api/officer/audit", headers=KEY).json()]
