"""Flagging an analysed vehicle from the console files a report on the officer desk."""
import sqlite3

from app import main

from .test_case_export import client, stored_case  # noqa: F401  (fixtures)

KEY = {"X-Officer-Key": main.OFFICER_KEY}
BODY = {"category": "dangerous_driving", "description": "Overtook on a blind bend", "location_text": "NH30 near Raipur toll"}


def flag(client, job_id, track=1, **over):
    return client.post(f"/api/jobs/{job_id}/tracks/{track}/flag", json={**BODY, **over})


def test_flagging_creates_a_desk_report_with_the_evidence_and_a_link_back(client, tmp_path):
    r = stored_case(tmp_path)
    resp = flag(client, r.job_id)
    assert resp.status_code == 200
    out = resp.json()
    assert out["status"] == "new" and out["department"] == "Police" and out["plate"] == "CG04??2819"
    d = client.get(f"/api/desk/complaints/{out['complaint_id']}", headers=KEY).json()
    assert d["source"] == "console" and d["job_id"] == r.job_id and d["track_id"] == 1
    assert d["description"] == BODY["description"] and d["location_text"] == BODY["location_text"]
    assert "fused read of the video" in d["match_basis"] and d["plate_found"] and d["match"]["pattern"] == "CG04??2819"
    assert client.get(f"/api/desk/complaints/{out['complaint_id']}/photo", headers=KEY).status_code == 200      # the evidence frame
    assert client.get(f"/api/desk/complaints/{out['complaint_id']}/plate", headers=KEY).status_code == 200
    listed = client.get("/api/desk/complaints", headers=KEY).json()
    assert [(x["id"], x["source"]) for x in listed] == [(out["complaint_id"], "console")]


def test_the_same_vehicle_cannot_be_flagged_twice_and_the_console_can_see_it(client, tmp_path):
    r = stored_case(tmp_path)
    cid = flag(client, r.job_id).json()["complaint_id"]
    again = flag(client, r.job_id)
    assert again.status_code == 409 and cid in again.json()["detail"]
    assert client.get(f"/api/jobs/{r.job_id}/flags").json() == {"1": cid}
    assert len(client.get("/api/desk/complaints", headers=KEY).json()) == 1


def test_bad_flags_are_refused(client, tmp_path):
    r = stored_case(tmp_path)
    assert flag(client, r.job_id, category="nonsense").status_code == 422
    assert flag(client, r.job_id, description="no").status_code == 422
    assert flag(client, r.job_id, location_text="").status_code == 422
    assert flag(client, r.job_id, track=99).status_code == 404
    assert flag(client, "000000000000").status_code == 404
    assert client.get("/api/desk/complaints", headers=KEY).json() == []


def test_a_vehicle_with_no_stored_image_cannot_be_flagged(client, tmp_path):
    r = stored_case(tmp_path)
    for f in (tmp_path / "jobs" / r.job_id).glob("track1_*.jpg"):
        f.unlink()
    assert flag(client, r.job_id).status_code == 409


def test_flagging_is_rate_limited(client, tmp_path):
    r = stored_case(tmp_path)
    main.limiter.reset()
    codes = {flag(client, r.job_id, track=i).status_code for i in range(2, 40)}      # unknown tracks are 404, but every try counts
    assert 429 in codes
    main.limiter.reset()


def test_citizen_reports_are_unchanged_and_an_old_database_is_upgraded(tmp_path):
    from app import complaints as cm

    db = tmp_path / "netra.db"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE complaints (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, category TEXT NOT NULL, department TEXT NOT NULL,
      description TEXT NOT NULL, location_text TEXT NOT NULL, lat REAL, lon REAL, observed_at TEXT, plate_read TEXT NOT NULL, fused_json TEXT NOT NULL,
      plate_confirmed TEXT, contact TEXT, colour_json TEXT, vehicle_found INTEGER NOT NULL, plate_found INTEGER NOT NULL, image_sha256 TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'new', officer_note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)""")
    con.execute("INSERT INTO complaints VALUES ('abcdef012345','2026-11-23T10:00:00+00:00','hit_and_run','police','old report','somewhere',NULL,NULL,NULL,'UP14CA0914','{}',NULL,NULL,NULL,1,1,'x','new','','2026-11-23T10:00:00+00:00')")
    con.commit()
    con.close()
    store = cm.ComplaintStore(tmp_path)
    row = store.get("abcdef012345")
    assert row["source"] == "citizen" and row["job_id"] is None and row["description"] == "old report"
