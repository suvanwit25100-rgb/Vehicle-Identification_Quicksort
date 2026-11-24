"""Retention and deletion, and the (demo) notification outbox."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import main
from app.complaints import ComplaintStore

from .test_case_export import client, stored_case  # noqa: F401  (fixtures)
from .test_officer_portal import KEY, a_report, bearer, make_officer  # noqa: F401


@pytest.fixture(autouse=True)
def _reset():
    main.limiter.reset()
    yield
    main.limiter.reset()


def age(tmp_path, table, col, ident, days):
    when = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    con = sqlite3.connect(tmp_path / "netra.db")
    con.execute(f"UPDATE {table} SET {col}=? WHERE id=?", (when, ident))
    con.commit()
    con.close()


# ---------------------------------------------------------------- outbox
def test_contact_channels_are_recognised_and_masked():
    f = ComplaintStore.contact_channel
    assert f("asha.rao@example.com") == ("email", "a***@example.com")
    assert f("+91 98765 43210") == ("sms", "•••••3210")
    assert f("call me") is None and f("") is None and f(None) is None and f("12345") is None


def test_status_changes_queue_a_demo_message_for_the_citizen(client, tmp_path):
    cid = a_report(client, tmp_path)
    assert client.get(f"/api/desk/complaints/{cid}/messages", headers=KEY).json() == []          # a console flag has no contact
    store = ComplaintStore(tmp_path)
    con = sqlite3.connect(tmp_path / "netra.db")
    con.execute("UPDATE complaints SET contact='asha@example.com' WHERE id=?", (cid,))
    con.commit()
    con.close()
    assert client.patch(f"/api/desk/complaints/{cid}", json={"status": "under_review"}, headers=KEY).status_code == 200
    msgs = client.get(f"/api/desk/complaints/{cid}/messages", headers=KEY).json()
    assert len(msgs) == 1 and msgs[0]["channel"] == "email" and msgs[0]["destination"] == "a***@example.com"
    assert "under review" in msgs[0]["message"] and cid in msgs[0]["message"] and "demo: not sent" in msgs[0]["state"]
    assert "CG04" not in msgs[0]["message"]                                                       # never the plate or any owner data
    out = client.get("/api/desk/outbox", headers=KEY).json()
    assert len(out["messages"]) == 1 and "nothing is sent" in out["note"]
    assert client.get("/api/desk/outbox").status_code == 401


def test_an_unchanged_status_queues_nothing(client, tmp_path):
    cid = a_report(client, tmp_path)
    client.patch(f"/api/desk/complaints/{cid}", json={"status": "new"}, headers=KEY)
    assert client.get("/api/desk/outbox", headers=KEY).json()["messages"] == []


def test_messages_follow_agency_permissions(client, tmp_path):
    cid = a_report(client, tmp_path)
    ComplaintStore(tmp_path).queue_message(cid, "asha@example.com", "hello")
    client.post("/api/officer/team", json={"username": "bor", "name": "Bor Der", "role": "officer", "password": "Strong-Pass-123", "agencies": ["bsf"]}, headers=KEY)
    tok = client.post("/api/officer/login", json={"username": "bor", "password": "Strong-Pass-123"}).json()["token"]
    assert client.get("/api/desk/outbox", headers=bearer(tok)).json()["messages"] == []
    assert client.get(f"/api/desk/complaints/{cid}/messages", headers=bearer(tok)).status_code == 404


# ---------------------------------------------------------------- retention
def test_retention_is_admin_only_and_needs_confirmation_and_a_matching_count(client, tmp_path):
    tok = make_officer(client)
    body = {"what": "reports", "days": 30}
    for path in ("/api/officer/retention/preview", "/api/officer/retention/apply"):
        assert client.post(path, json=body, headers=bearer(tok)).status_code == 403
    assert client.post("/api/officer/retention/preview", json={"what": "nonsense", "days": 30}, headers=KEY).status_code == 422
    assert client.post("/api/officer/retention/preview", json={"what": "reports", "days": 0}, headers=KEY).status_code == 422
    assert client.post("/api/officer/retention/apply", json={**body, "expect": 0}, headers=KEY).status_code == 422          # no confirm
    assert client.post("/api/officer/retention/apply", json={**body, "confirm": True}, headers=KEY).status_code == 409      # no expected count
    assert client.post("/api/officer/retention/apply", json={**body, "confirm": True, "expect": 5}, headers=KEY).status_code == 409


def test_only_old_closed_reports_are_deleted_with_their_files(client, tmp_path):
    old_closed, old_open, new_closed = a_report(client, tmp_path), None, None
    r2 = stored_case(tmp_path, job_id="abcdef012346")
    old_open = client.post(f"/api/jobs/{r2.job_id}/tracks/1/flag", json={"category": "dangerous_driving", "description": "Another one here", "location_text": "NH30"}).json()["complaint_id"]
    r3 = stored_case(tmp_path, job_id="abcdef012347")
    new_closed = client.post(f"/api/jobs/{r3.job_id}/tracks/1/flag", json={"category": "dangerous_driving", "description": "A third one here", "location_text": "NH30"}).json()["complaint_id"]
    client.patch(f"/api/desk/complaints/{old_closed}", json={"status": "closed"}, headers=KEY)
    client.patch(f"/api/desk/complaints/{new_closed}", json={"status": "rejected"}, headers=KEY)
    age(tmp_path, "complaints", "updated_at", old_closed, 100)
    age(tmp_path, "complaints", "updated_at", old_open, 100)          # old but still open: must survive
    prev = client.post("/api/officer/retention/preview", json={"what": "reports", "days": 30}, headers=KEY).json()
    assert prev["count"] == 1 and prev["sample"][0]["id"] == old_closed
    assert (tmp_path / "complaints" / f"{old_closed}.jpg").exists()
    done = client.post("/api/officer/retention/apply", json={"what": "reports", "days": 30, "confirm": True, "expect": 1}, headers=KEY)
    assert done.json() == {"deleted": 1}
    ids = {r["id"] for r in client.get("/api/desk/complaints", headers=KEY).json()}
    assert ids == {old_open, new_closed}
    assert not (tmp_path / "complaints" / f"{old_closed}.jpg").exists() and (tmp_path / "complaints" / f"{old_open}.jpg").exists()
    assert ("key", "retention.reports") in [(a["actor"], a["action"]) for a in client.get("/api/officer/audit", headers=KEY).json()]


def test_old_analyses_are_deleted_and_flagged_reports_keep_their_evidence(client, tmp_path):
    old = stored_case(tmp_path, job_id="abcdef012345")
    new = stored_case(tmp_path, job_id="abcdef012346")
    cid = client.post(f"/api/jobs/{old.job_id}/tracks/1/flag", json={"category": "dangerous_driving", "description": "Overtook here", "location_text": "NH30"}).json()["complaint_id"]
    for jid, days in ((old.job_id, 100), (new.job_id, 1)):
        p = tmp_path / "jobs" / jid / "result.json"
        r = main.AnalysisResult.model_validate_json(p.read_text())
        r.created_at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        p.write_text(r.model_dump_json())
    prev = client.post("/api/officer/retention/preview", json={"what": "analyses", "days": 30}, headers=KEY).json()
    assert [x["id"] for x in prev["sample"]] == [old.job_id] and "keep their own evidence" in prev["note"]
    assert client.post("/api/officer/retention/apply", json={"what": "analyses", "days": 30, "confirm": True, "expect": 1}, headers=KEY).json() == {"deleted": 1}
    assert client.get(f"/api/jobs/{old.job_id}").status_code == 404 and client.get(f"/api/jobs/{new.job_id}").status_code == 200
    assert client.get(f"/api/desk/complaints/{cid}/photo", headers=KEY).status_code == 200            # the report's own copy of the evidence survives


def test_one_analysis_can_be_deleted_by_an_admin_with_confirmation(client, tmp_path):
    r = stored_case(tmp_path)
    tok = make_officer(client)
    assert client.delete(f"/api/officer/analyses/{r.job_id}?confirm=true", headers=bearer(tok)).status_code == 403
    assert client.delete(f"/api/officer/analyses/{r.job_id}", headers=KEY).status_code == 422
    assert client.get(f"/api/jobs/{r.job_id}").status_code == 200
    assert client.delete(f"/api/officer/analyses/{r.job_id}?confirm=true", headers=KEY).json() == {"deleted": r.job_id}
    assert client.get(f"/api/jobs/{r.job_id}").status_code == 404
    assert client.delete(f"/api/officer/analyses/{r.job_id}?confirm=true", headers=KEY).status_code == 404
