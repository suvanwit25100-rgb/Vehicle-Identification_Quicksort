"""Demo reports and the map endpoint."""
import pytest

from app import main

from .test_case_export import client, stored_case  # noqa: F401  (fixtures)
from .test_officer_portal import KEY, a_report, bearer, make_officer  # noqa: F401


@pytest.fixture(autouse=True)
def _reset():
    main.limiter.reset()
    yield
    main.limiter.reset()


def test_demo_needs_a_stored_analysis_and_admin_rights(client, tmp_path):
    assert client.post("/api/officer/demo/seed", headers=KEY).status_code == 409           # nothing to build them from
    tok = make_officer(client)
    for call in (lambda: client.post("/api/officer/demo/seed", headers=bearer(tok)), lambda: client.delete("/api/officer/demo", headers=bearer(tok)),
                 lambda: client.get("/api/officer/demo", headers=bearer(tok))):
        assert call().status_code == 403
    assert client.post("/api/officer/demo/seed").status_code == 401


def test_demo_reports_are_labelled_real_data_is_untouched_and_the_monitor_ignores_them(client, tmp_path):
    real = a_report(client, tmp_path)
    before = client.get("/api/monitor").json()["complaints"]
    made = client.post("/api/officer/demo/seed", headers=KEY).json()["created"]
    assert made == 10 and client.get("/api/officer/demo", headers=KEY).json() == {"loaded": 10}
    rows = client.get("/api/desk/complaints", headers=KEY).json()
    demo = [r for r in rows if r["source"] == "demo"]
    assert len(demo) == 10 and len(rows) == 11
    d = client.get(f"/api/desk/complaints/{demo[0]['id']}", headers=KEY).json()
    assert d["description"].startswith("[demo]") and "fused read" in d["match_basis"]
    assert client.get(f"/api/desk/complaints/{demo[0]['id']}/photo", headers=KEY).status_code == 200
    assert client.get("/api/monitor").json()["complaints"] == before                          # measured data only: demo is not counted
    assert client.post("/api/officer/demo/seed", headers=KEY).status_code == 409              # not loaded twice
    removed = client.delete("/api/officer/demo", headers=KEY).json()["removed"]
    assert removed == 10
    assert [r["id"] for r in client.get("/api/desk/complaints", headers=KEY).json()] == [real]      # the real report is untouched
    actions = [a["action"] for a in client.get("/api/officer/audit", headers=KEY).json()]
    assert "demo.seed" in actions and "demo.remove" in actions


def test_demo_reports_show_related_grouping_and_the_map(client, tmp_path):
    stored_case(tmp_path)
    client.post("/api/officer/demo/seed", headers=KEY)
    rows = client.get("/api/desk/complaints", headers=KEY).json()
    assert any(r["related"] for r in rows)                                                      # one plate, several reports: grouped
    pins = client.get("/api/desk/map", headers=KEY).json()
    assert len(pins) == 10 and all(20 < p["lat"] < 22 and 81 < p["lon"] < 83 and p["source"] == "demo" for p in pins)
    assert {"id", "plate", "status", "category", "department", "when", "place"} <= set(pins[0])
    assert client.get("/api/desk/map").status_code == 401


def test_the_map_only_has_reports_with_a_location_and_respects_agencies(client, tmp_path):
    a_report(client, tmp_path)                                                                   # a console flag has no coordinates
    assert client.get("/api/desk/map", headers=KEY).json() == []
    client.post("/api/officer/demo/seed", headers=KEY)
    client.post("/api/officer/team", json={"username": "bor", "name": "Bor Der", "role": "officer", "password": "Strong-Pass-123", "agencies": ["bsf"]}, headers=KEY)
    tok = client.post("/api/officer/login", json={"username": "bor", "password": "Strong-Pass-123"}).json()["token"]
    assert all(p["department"] == "bsf" for p in client.get("/api/desk/map", headers=bearer(tok)).json())


# ---------------------------------------------------------------- going online: client address, upload cap, headers
def test_the_visitor_address_comes_from_the_proxy_only_when_the_connection_is_local():
    from types import SimpleNamespace

    def req(host, headers):
        return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers)

    assert main._client_id(req("127.0.0.1", {"cf-connecting-ip": "203.0.113.9"})) == "203.0.113.9"
    assert main._client_id(req("127.0.0.1", {"x-forwarded-for": "198.51.100.4, 10.0.0.1"})) == "198.51.100.4"
    assert main._client_id(req("127.0.0.1", {})) == "127.0.0.1"
    assert main._client_id(req("203.0.113.50", {"cf-connecting-ip": "1.2.3.4"})) == "203.0.113.50"      # a remote caller cannot forge it


def test_security_headers_are_sent_and_robots_asks_not_to_be_indexed(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY" and r.headers["referrer-policy"] == "no-referrer"
    assert "Disallow: /" in client.get("/robots.txt").text


def test_an_oversized_or_over_limit_upload_is_refused_before_any_analysis(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_MB", 0)
    r = client.post("/api/analyze", files={"file": ("clip.mp4", b"x" * 2048, "video/mp4")}, data={"department": "police"})
    assert r.status_code == 413 and "MB" in r.json()["detail"]
    monkeypatch.setattr(main, "MAX_UPLOAD_MB", 300)
    main.limiter.reset()
    codes = {client.post("/api/analyze", files={"file": ("clip.txt", b"x", "text/plain")}, data={"department": "police"}).status_code for _ in range(32)}
    assert 429 in codes and 415 in codes
    main.limiter.reset()
