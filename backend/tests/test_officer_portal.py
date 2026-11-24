"""The officer backend: accounts, sessions, audit trail, case management, dashboard."""
import pytest

from app import main

from .test_case_export import client, stored_case  # noqa: F401  (fixtures)

KEY = {"X-Officer-Key": main.OFFICER_KEY}
PW = "Strong-Pass-123"


@pytest.fixture(autouse=True)
def _reset():
    main.limiter.reset()
    yield
    main.limiter.reset()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def key_login(client):
    return client.post("/api/officer/login", json={"key": main.OFFICER_KEY}).json()["token"]


def make_officer(client, username="asha", role="officer", name="Asha Rao"):
    r = client.post("/api/officer/team", json={"username": username, "name": name, "role": role, "password": PW}, headers=KEY)
    assert r.status_code == 200, r.text
    return client.post("/api/officer/login", json={"username": username, "password": PW}).json()["token"]


def a_report(client, tmp_path):
    r = stored_case(tmp_path)
    return client.post(f"/api/jobs/{r.job_id}/tracks/1/flag", json={"category": "dangerous_driving", "description": "Overtook on a blind bend", "location_text": "NH30"}).json()["complaint_id"]


# ---------------------------------------------------------------- sign-in
def test_key_login_gives_an_admin_session_and_the_old_header_still_works(client):
    tok = key_login(client)
    me = client.get("/api/officer/me", headers=bearer(tok)).json()
    assert me["role"] == "admin" and me["username"] == "key"
    assert client.get("/api/officer/me", headers=KEY).json()["role"] == "admin"
    assert client.get("/api/officer/me").status_code == 401
    assert client.get("/api/officer/me", headers=bearer("not-a-token")).status_code == 401
    assert client.post("/api/officer/login", json={"key": "wrong"}).status_code == 401
    assert client.post("/api/officer/login", json={}).status_code == 422


def test_accounts_passwords_and_logout(client):
    tok = make_officer(client)
    assert client.get("/api/officer/me", headers=bearer(tok)).json()["username"] == "asha"
    assert client.post("/api/officer/login", json={"username": "asha", "password": "wrong"}).status_code == 401
    assert client.post("/api/officer/login", json={"username": "nobody", "password": PW}).status_code == 401
    assert client.post("/api/officer/logout", headers=bearer(tok)).status_code == 200
    assert client.get("/api/officer/me", headers=bearer(tok)).status_code == 401


def test_weak_or_duplicate_accounts_are_refused(client):
    ok = {"username": "ravi", "name": "Ravi K", "role": "officer", "password": PW}
    for bad in ({"password": "short"}, {"password": "alllowercase123"}, {"password": "NoDigitsHereAtAll"}, {"username": "X"}, {"role": "root"}, {"name": ""}):
        assert client.post("/api/officer/team", json={**ok, **bad}, headers=KEY).status_code == 422, bad
    assert client.post("/api/officer/team", json=ok, headers=KEY).status_code == 200
    assert client.post("/api/officer/team", json=ok, headers=KEY).status_code == 422          # username taken


def test_passwords_are_stored_hashed(client, tmp_path):
    import sqlite3

    make_officer(client)
    row = sqlite3.connect(tmp_path / "netra.db").execute("SELECT pw_hash, pw_salt FROM officers").fetchone()
    assert PW not in "".join(row) and len(row[0]) == 64


def test_only_admins_manage_the_team_and_read_the_audit_log(client):
    tok = make_officer(client)
    for call in (lambda: client.get("/api/officer/team/all", headers=bearer(tok)), lambda: client.get("/api/officer/audit", headers=bearer(tok)),
                 lambda: client.post("/api/officer/team", json={"username": "zed", "name": "Zed", "role": "officer", "password": PW}, headers=bearer(tok))):
        assert call().status_code == 403
    assert [o["username"] for o in client.get("/api/officer/team", headers=bearer(tok)).json()] == ["asha"]       # names only, for assigning
    assert "pw_hash" not in client.get("/api/officer/team/all", headers=KEY).text


def test_switching_an_account_off_signs_it_out_and_blocks_login(client):
    tok = make_officer(client)
    oid = client.get("/api/officer/team/all", headers=KEY).json()[0]["id"]
    assert client.patch(f"/api/officer/team/{oid}", json={"active": False}, headers=KEY).status_code == 200
    assert client.get("/api/officer/me", headers=bearer(tok)).status_code == 401
    assert client.post("/api/officer/login", json={"username": "asha", "password": PW}).status_code == 401
    client.patch(f"/api/officer/team/{oid}", json={"active": True, "password": "Another-Pass-456"}, headers=KEY)
    assert client.post("/api/officer/login", json={"username": "asha", "password": "Another-Pass-456"}).status_code == 200


def test_the_last_admin_and_your_own_account_are_protected(client):
    make_officer(client, "boss", "admin", "The Boss")
    boss = client.get("/api/officer/team/all", headers=KEY).json()[0]
    tok = client.post("/api/officer/login", json={"username": "boss", "password": PW}).json()["token"]
    assert client.patch(f"/api/officer/team/{boss['id']}", json={"active": False}, headers=bearer(tok)).status_code == 409      # not yourself
    assert client.patch(f"/api/officer/team/{boss['id']}", json={"role": "officer"}, headers=KEY).status_code == 409           # the last admin
    assert client.patch("/api/officer/team/nosuchid", json={"active": False}, headers=KEY).status_code == 404


def test_changing_your_own_password(client):
    tok = make_officer(client)
    h = bearer(tok)
    assert client.post("/api/officer/password", json={"current": "bad", "new": "New-Password-789"}, headers=h).status_code == 401
    assert client.post("/api/officer/password", json={"current": PW, "new": "weak"}, headers=h).status_code == 422
    assert client.post("/api/officer/password", json={"current": PW, "new": "New-Password-789"}, headers=h).status_code == 200
    assert client.post("/api/officer/login", json={"username": "asha", "password": "New-Password-789"}).status_code == 200
    assert client.post("/api/officer/password", json={"current": "x", "new": "New-Password-789"}, headers=KEY).status_code == 409   # the key has no password


def test_sign_in_attempts_are_limited(client):
    codes = [client.post("/api/officer/login", json={"username": "asha", "password": "nope"}).status_code for _ in range(15)]
    assert codes[0] == 401 and codes[-1] == 429


# ---------------------------------------------------------------- case management
def test_assign_note_status_and_timeline(client, tmp_path):
    tok = make_officer(client)
    cid = a_report(client, tmp_path)
    h = bearer(tok)
    assert client.post(f"/api/desk/complaints/{cid}/assign", json={"to": "asha"}, headers=h).status_code == 200
    assert client.post(f"/api/desk/complaints/{cid}/assign", json={"to": "ghost"}, headers=h).status_code == 422
    assert client.post(f"/api/desk/complaints/{cid}/notes", json={"text": "Called the toll booth, footage requested"}, headers=h).status_code == 200
    assert client.patch(f"/api/desk/complaints/{cid}", json={"status": "under_review"}, headers=h).status_code == 200
    mine = client.get("/api/desk/complaints?assigned=me", headers=h).json()
    assert [r["id"] for r in mine] == [cid] and mine[0]["assigned_to"] == "asha"
    assert client.get("/api/desk/complaints?assigned=unassigned", headers=h).json() == []
    tl = client.get(f"/api/desk/complaints/{cid}/timeline", headers=h).json()
    assert [(e["kind"], e["actor"]) for e in tl] == [("filed", "system"), ("assign", "asha"), ("note", "asha"), ("status", "asha")]
    assert tl[3]["text"] == "new -> under_review"
    assert client.post(f"/api/desk/complaints/{cid}/notes", json={"text": ""}, headers=h).status_code == 422
    assert client.post("/api/desk/complaints/000000000000/assign", json={"to": None}, headers=h).status_code == 404


def test_search_filters_the_queue(client, tmp_path):
    cid = a_report(client, tmp_path)
    assert [r["id"] for r in client.get("/api/desk/complaints?q=2819", headers=KEY).json()] == [cid]
    assert client.get("/api/desk/complaints?q=zzzz", headers=KEY).json() == []
    assert client.get("/api/desk/complaints?q=nh30", headers=KEY).json()[0]["id"] == cid


def test_csv_export_and_audit_trail(client, tmp_path):
    tok = make_officer(client)
    cid = a_report(client, tmp_path)
    client.patch(f"/api/desk/complaints/{cid}", json={"status": "verified"}, headers=bearer(tok))
    client.post("/api/desk/watchlist", json={"plate": "UP14CA0914", "reason": "test"}, headers=bearer(tok))
    csv_text = client.get("/api/desk/complaints.csv", headers=bearer(tok)).text
    assert csv_text.splitlines()[0].startswith("id,filed,source") and cid in csv_text and "console" in csv_text
    log = client.get("/api/officer/audit", headers=KEY).json()
    actions = [(a["actor"], a["action"]) for a in log]
    for want in [("key", "team.create"), ("console", "report.flag"), ("asha", "login"), ("asha", "report.status"), ("asha", "watchlist.add"), ("asha", "report.export")]:
        assert want in actions, want
    assert [a["action"] for a in client.get("/api/officer/audit?actor=asha", headers=KEY).json()][-1] == "login"
    assert all(a["actor"] == "asha" for a in client.get("/api/officer/audit?actor=asha", headers=KEY).json())


def test_failed_logins_are_in_the_audit_trail_without_the_password(client):
    client.post("/api/officer/login", json={"username": "asha", "password": "guess-1234"})
    client.post("/api/officer/login", json={"key": "wrongkey"})
    text = client.get("/api/officer/audit", headers=KEY).text
    assert "login.failed" in text and "guess-1234" not in text and "wrongkey" not in text


# ---------------------------------------------------------------- dashboard
def test_dashboard_numbers_match_what_is_stored(client, tmp_path):
    tok = make_officer(client)
    cid = a_report(client, tmp_path)
    d = client.get("/api/officer/dashboard", headers=bearer(tok)).json()
    assert d["reports"]["total"] == 1 and d["reports"]["by_status"] == {"new": 1} and d["reports"]["unassigned_open"] == 1
    assert d["reports"]["mine_open"] == 0 and d["reports"]["from_console"] == 1 and d["reports"]["aging_new_over_48h"] == 0
    assert sum(x["count"] for x in d["reports"]["per_day"]) == 1 and len(d["reports"]["per_day"]) == 7
    assert d["analyses"]["stored"] == 1 and d["watchlist"]["entries"] == 0 and d["repeat_plates"] == 0
    assert d["recent_activity"] == []                                   # the activity feed is for admins
    client.post(f"/api/desk/complaints/{cid}/assign", json={"to": "asha"}, headers=bearer(tok))
    d2 = client.get("/api/officer/dashboard", headers=bearer(tok)).json()
    assert d2["reports"]["mine_open"] == 1 and d2["reports"]["unassigned_open"] == 0
    assert client.get("/api/officer/dashboard", headers=KEY).json()["recent_activity"]
    assert client.get("/api/officer/dashboard").status_code == 401


def test_every_desk_route_accepts_a_session_and_refuses_strangers(client, tmp_path):
    cid = a_report(client, tmp_path)
    tok = make_officer(client)
    for path in ("/api/desk/complaints", f"/api/desk/complaints/{cid}", f"/api/desk/complaints/{cid}/timeline", f"/api/desk/complaints/{cid}/photo",
                 "/api/desk/watchlist", "/api/desk/complaints.csv", "/api/officer/dashboard"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=bearer(tok)).status_code == 200, path


# ---------------------------------------------------------------- per-agency permissions and sessions
def officer_for(client, username, agencies):
    r = client.post("/api/officer/team", json={"username": username, "name": username.title() + " Test", "role": "officer", "password": PW, "agencies": agencies}, headers=KEY)
    assert r.status_code == 200, r.text
    return client.post("/api/officer/login", json={"username": username, "password": PW}).json()["token"]


def test_an_officer_sees_only_their_agencies(client, tmp_path):
    cid = a_report(client, tmp_path)                 # a police report
    police, bsf = officer_for(client, "pol", ["police"]), officer_for(client, "bor", ["bsf"])
    assert [r["id"] for r in client.get("/api/desk/complaints", headers=bearer(police)).json()] == [cid]
    assert client.get("/api/desk/complaints", headers=bearer(bsf)).json() == []
    assert client.get("/api/desk/complaints?department=police", headers=bearer(bsf)).json() == []
    for path in (f"/api/desk/complaints/{cid}", f"/api/desk/complaints/{cid}/timeline", f"/api/desk/complaints/{cid}/photo"):
        assert client.get(path, headers=bearer(police)).status_code == 200, path
        assert client.get(path, headers=bearer(bsf)).status_code == 404, path          # outside their agencies: reported as missing
    assert client.post(f"/api/desk/complaints/{cid}/notes", json={"text": "x"}, headers=bearer(bsf)).status_code == 404
    assert client.patch(f"/api/desk/complaints/{cid}", json={"status": "closed"}, headers=bearer(bsf)).status_code == 404
    assert client.post(f"/api/desk/complaints/{cid}/assign", json={"to": None}, headers=bearer(bsf)).status_code == 404
    assert cid not in client.get("/api/desk/complaints.csv", headers=bearer(bsf)).text and cid in client.get("/api/desk/complaints.csv", headers=bearer(police)).text
    assert client.get("/api/officer/dashboard", headers=bearer(bsf)).json()["reports"]["total"] == 0
    assert client.get("/api/officer/dashboard", headers=bearer(police)).json()["reports"]["total"] == 1
    assert client.get("/api/desk/complaints", headers=KEY).json()[0]["id"] == cid         # the key and admins see everything


def test_agencies_are_validated_and_editable(client):
    bad = client.post("/api/officer/team", json={"username": "zed", "name": "Zed Z", "role": "officer", "password": PW, "agencies": ["mars"]}, headers=KEY)
    assert bad.status_code == 422
    officer_for(client, "lee", ["police"])
    oid = next(o["id"] for o in client.get("/api/officer/team/all", headers=KEY).json() if o["username"] == "lee")
    assert client.patch(f"/api/officer/team/{oid}", json={"agencies": ["bsf", "customs"]}, headers=KEY).json()["agencies"] == ["bsf", "customs"]
    assert client.patch(f"/api/officer/team/{oid}", json={"agencies": ["nope"]}, headers=KEY).status_code == 422
    assert client.patch(f"/api/officer/team/{oid}", json={"agencies": []}, headers=KEY).json()["agencies"] == []


def test_admins_can_list_and_end_sessions(client):
    tok = officer_for(client, "ann", [])
    admin = key_login(client)
    rows = client.get("/api/officer/sessions", headers=bearer(admin)).json()
    assert {r["username"] for r in rows} == {"ann", "key"} and [r["current"] for r in rows if r["username"] == "key"] == [True]
    assert "token" not in str(rows) and all(len(r["id"]) == 12 for r in rows)
    ann = next(r for r in rows if r["username"] == "ann")
    assert client.get("/api/officer/sessions", headers=bearer(tok)).status_code == 403
    assert client.delete(f"/api/officer/sessions/{ann['id']}", headers=bearer(admin)).status_code == 200
    assert client.get("/api/officer/me", headers=bearer(tok)).status_code == 401           # that sign-in is gone
    assert client.delete(f"/api/officer/sessions/{ann['id']}", headers=bearer(admin)).status_code == 404
    assert client.delete("/api/officer/sessions/not-an-id", headers=bearer(admin)).status_code == 404
