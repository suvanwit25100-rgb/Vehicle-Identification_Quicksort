"""The citizen's plain-language view of their report."""
import pytest

from app import main

from .test_case_export import client  # noqa: F401  (fixture)
from .test_officer_portal import KEY, a_report, bearer, make_officer  # noqa: F401


@pytest.fixture(autouse=True)
def _reset():
    main.limiter.reset()
    yield
    main.limiter.reset()


def test_progress_tells_the_story_in_plain_words(client, tmp_path):
    cid = a_report(client, tmp_path)
    tok = make_officer(client)
    client.post(f"/api/desk/complaints/{cid}/assign", json={"to": "asha"}, headers=bearer(tok))
    client.patch(f"/api/desk/complaints/{cid}", json={"status": "under_review"}, headers=bearer(tok))
    p = client.get(f"/api/complaints/{cid}/progress").json()
    assert p["status"] == "under_review" and p["label"] == "Being looked at" and "reviewing" in p["meaning"]
    assert [e["text"] for e in p["timeline"]] == ["You filed this report.", "An officer took your report.", "Status changed to “Being looked at”."]
    assert [s["label"] for s in p["steps"]] == ["Received", "Being looked at", "Checked", "Passed on", "Finished"] and p["rejected"] is False
    assert p["department"] == "Police" and "lead for an officer" in p["note"]


def test_a_rejected_report_is_explained_kindly_and_has_no_progress_bar_flag(client, tmp_path):
    cid = a_report(client, tmp_path)
    client.patch(f"/api/desk/complaints/{cid}", json={"status": "rejected"}, headers=KEY)
    p = client.get(f"/api/complaints/{cid}/progress").json()
    assert p["rejected"] is True and "not a judgement about you" in p["meaning"]


def test_nothing_private_is_ever_in_the_public_view(client, tmp_path):
    cid = a_report(client, tmp_path)
    tok = make_officer(client)
    client.post(f"/api/desk/complaints/{cid}/notes", json={"text": "SECRETNOTE suspect is known to us"}, headers=bearer(tok))
    client.post(f"/api/desk/complaints/{cid}/assign", json={"to": "asha"}, headers=bearer(tok))
    text = client.get(f"/api/complaints/{cid}/progress").text
    for private in ("SECRETNOTE", "asha", "Asha", "CG04", "plate", "registry_", "officer_note", "image_sha256", "location"):
        assert private not in text, private


def test_unknown_and_malformed_ids_and_lookup_limits(client):
    assert client.get("/api/complaints/000000000000/progress").status_code == 404
    assert client.get("/api/complaints/not-an-id/progress").status_code == 404
    codes = [client.get("/api/complaints/000000000000/progress").status_code for _ in range(62)]
    assert codes[0] == 404 and codes[-1] == 429


def test_the_page_and_the_tracking_link_exist(client):
    page = client.get("/status/")
    assert page.status_code == 200 and "status.js" in page.text and "noindex" in page.text
    assert "/status/" in client.get("/report-issue/").text
