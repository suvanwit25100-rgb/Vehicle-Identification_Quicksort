import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import complaints as cm
from app import main
from app.fusion import fuse_frames
from app.registry import load_registry

from .helpers import make_frame
from .test_jobs_report import sample_result
from .test_pipeline import needs_weights
from .vision_helpers import render_plate

KEY = {"X-Officer-Key": main.OFFICER_KEY}


def png_bytes(w=200, h=120):
    ok, buf = cv2.imencode(".png", np.full((h, w, 3), 90, np.uint8))
    return buf.tobytes()


def fake_reader(plate="CG04KA2819", unread=(4, 5), colour="white"):
    def read(img, vehicle_detector, plate_detector, cfg):
        return {"fused": fuse_frames([make_frame(0, plate, unread=unread)]),
                "crop": np.full((40, 120, 3), 200, np.uint8), "colour": {colour: 0.9},
                "vehicle_found": True, "plate_found": True, "plate_width_px": 120}
    return read


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "_still_models", lambda: (None, None))
    monkeypatch.setattr(cm, "read_photo", fake_reader())
    main.limiter.reset()
    return TestClient(main.app)


def preview(client, data=None):
    return client.post("/api/complaints/preview", files={"photo": ("car.png", data or png_bytes(), "image/png")})


def submit(client, draft_id, **over):
    body = {"draft_id": draft_id, "category": "traffic_violation", "description": "Jumped the red light.",
            "location_text": "Ring Road near ITO, Delhi", "consent": True, **over}
    return client.post("/api/complaints", json=body)


def test_every_category_routes_to_a_known_department(client):
    cats = client.get("/api/complaints/categories").json()
    assert {c["department"] for c in cats} <= {"police", "morth_nhai", "bsf", "ssb", "customs"}
    assert {"police", "morth_nhai", "bsf", "ssb", "customs"} <= {c["department"] for c in cats}


def test_preview_reads_the_plate_and_marks_unknown_slots(client):
    r = preview(client)
    assert r.status_code == 200
    j = r.json()
    assert j["pattern"] == "CG04??2819" and j["known_count"] == 8 and "marked ?" in j["note"]
    assert j["plate_crop_url"] and client.get(j["plate_crop_url"]).status_code == 200


def test_preview_rejects_files_that_are_not_images(client):
    r = preview(client, b"this is not an image")
    assert r.status_code == 415


def test_preview_rejects_oversize_photos(client):
    assert preview(client, b"\0" * (cm.MAX_PHOTO_BYTES + 1)).status_code == 413


def test_full_flow_and_citizen_never_sees_registry_or_officer_data(client):
    draft = preview(client).json()["draft_id"]
    r = submit(client, draft, contact="9999900000")
    assert r.status_code == 201
    cid = r.json()["complaint_id"]
    pub = client.get(f"/api/complaints/{cid}/status").json()
    assert set(pub) == {"complaint_id", "status", "created_at", "department", "category"}
    assert pub["status"] == "new" and pub["department"] == "Ministry of Road Transport and Highways / NHAI"
    assert "9999900000" not in r.text
    for path in (f"/api/desk/complaints/{cid}", f"/api/desk/complaints/{cid}/photo"):
        assert client.get(path).status_code == 401


def test_a_draft_can_only_be_submitted_once(client):
    draft = preview(client).json()["draft_id"]
    assert submit(client, draft).status_code == 201
    assert submit(client, draft).status_code == 404


@pytest.mark.parametrize("over,code", [
    ({"consent": False}, 422), ({"category": "nonsense"}, 422), ({"plate_confirmed": "!!"}, 422),
    ({"description": "no"}, 422), ({"lat": 123.0}, 422), ({"draft_id": "000000000000"}, 404),
])
def test_validation(client, over, code):
    draft = preview(client).json()["draft_id"]
    assert submit(client, over.get("draft_id", draft), **{k: v for k, v in over.items() if k != "draft_id"}).status_code == code


def test_there_is_no_built_in_officer_key():
    import os
    import subprocess
    import sys
    from pathlib import Path

    # a fresh interpreter with the variable unset must generate a random key, and two runs must differ
    code = "import os; os.environ.pop('NETRA_OFFICER_KEY', None); from app import main; print(main.OFFICER_KEY)"
    env = {k: v for k, v in os.environ.items() if k != "NETRA_OFFICER_KEY"}
    keys = [subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=Path(main.__file__).parents[1], env=env).stdout.strip()
            for _ in range(2)]
    assert all(len(k) >= 12 for k in keys) and keys[0] != keys[1]


def test_officer_key_is_required_and_checked(client):
    assert client.get("/api/desk/complaints").status_code == 401
    assert client.get("/api/desk/complaints", headers={"X-Officer-Key": "wrong"}).status_code == 401
    assert client.get("/api/desk/complaints", headers=KEY).status_code == 200


def test_a_typed_plate_with_the_wrong_colour_is_refused_under_the_police_threshold(client):
    # police routes "suspicious_vehicle" and has a 0.66 threshold; a white car vs a maroon registry row scores 0.62
    row = load_registry()[0]
    assert row.colour != "white"
    cid = submit(client, preview(client).json()["draft_id"], category="suspicious_vehicle",
                 plate_confirmed=row.plate).json()["complaint_id"]
    m = client.get(f"/api/desk/complaints/{cid}", headers=KEY).json()["match"]
    assert m["status"] == "no_confident_match" and m["candidates"] == []


def test_officer_sees_registry_match_for_a_typed_plate_and_can_triage(client, monkeypatch):
    row = load_registry()[0]
    plate = row.plate
    monkeypatch.setattr(cm, "read_photo", fake_reader(colour=row.colour))
    draft = preview(client).json()["draft_id"]
    cid = submit(client, draft, category="suspicious_vehicle", plate_confirmed=plate[:2] + " " + plate[2:]).json()["complaint_id"]
    lst = client.get("/api/desk/complaints", headers=KEY).json()
    assert [c["id"] for c in lst] == [cid] and lst[0]["department"] == "police" and lst[0]["plate_confirmed"] == plate
    d = client.get(f"/api/desk/complaints/{cid}", headers=KEY).json()
    assert d["match"]["candidates"][0]["plate"] == plate and "typed by the citizen" in d["match_basis"]
    assert client.get(f"/api/desk/complaints/{cid}/photo", headers=KEY).status_code == 200
    up = client.patch(f"/api/desk/complaints/{cid}", headers=KEY, json={"status": "verified", "note": "Checked on CCTV."})
    assert up.status_code == 200
    assert client.get(f"/api/complaints/{cid}/status").json()["status"] == "verified"
    assert client.get(f"/api/desk/complaints/{cid}", headers=KEY).json()["officer_note"] == "Checked on CCTV."
    assert client.patch(f"/api/desk/complaints/{cid}", headers=KEY, json={"status": "bogus"}).status_code == 422
    assert client.get("/api/desk/complaints?status=closed", headers=KEY).json() == []


def test_unreadable_photo_still_files_and_officer_match_uses_only_what_was_read(client, monkeypatch):
    monkeypatch.setattr(cm, "read_photo", fake_reader(unread=tuple(range(10))))
    draft = preview(client).json()["draft_id"]
    cid = submit(client, draft).json()["complaint_id"]
    d = client.get(f"/api/desk/complaints/{cid}", headers=KEY).json()
    assert d["match"]["status"] == "insufficient_evidence" and d["match"]["pattern"] == "?" * 10


def test_submit_rate_limit(client):
    codes = [submit(client, preview(client).json()["draft_id"]).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]


def test_monitor_counts_saved_jobs_and_complaints(client):
    main.save_job(sample_result())
    submit(client, preview(client).json()["draft_id"])
    m = client.get("/api/monitor").json()
    assert m["jobs"]["total"] == 1 and m["jobs"]["tracks"] == 1 and m["jobs"]["tracks_readable"] == 1
    assert m["jobs"]["outcomes"]["match"] == 1 and m["jobs"]["by_department"] == {"police": 1}
    assert m["jobs"]["recent"][0]["best_plate"] == "CG04??2819"
    assert m["complaints"]["total"] == 1 and m["complaints"]["by_department"] == {"morth_nhai": 1}
    assert {b["id"] for b in m["brains"]} >= {"vehicle_detector", "plate_detector", "plate_ocr"}


def test_monitor_with_nothing_saved_is_empty_not_an_error(client):
    m = client.get("/api/monitor").json()
    assert m["jobs"]["total"] == 0 and m["complaints"]["total"] == 0 and m["calibration"] is None


def test_clean_plate():
    assert cm.clean_plate("dl 8c-ay 4767") == "DL8CAY4767"
    assert cm.clean_plate("") is None and cm.clean_plate("!!") == "" and cm.clean_plate("ABC") == ""


@needs_weights
def test_real_models_read_a_plate_in_a_photo(tmp_path, monkeypatch):
    from app.vision.detectors import PlateDetector, VehicleDet

    class Stub:
        def detect(self, frame):
            return [VehicleDet(-1, "car", 0.9, (20, 40, 500, 290))]

    target = load_registry()[0].plate
    frame = np.full((300, 520, 3), 120, np.uint8)
    cv2.rectangle(frame, (20, 40), (500, 290), (18, 18, 18), -1)
    frame[200:245, 165:355] = cv2.resize(render_plate(target, 380), (190, 45))
    out = cm.read_photo(frame, Stub(), PlateDetector(), main.get_department("police"))
    assert out["plate_found"] and out["fused"].pattern.replace("?", "") in target and out["fused"].known_count >= 6
    assert out["colour"] is not None
