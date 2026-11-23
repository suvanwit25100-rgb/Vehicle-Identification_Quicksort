from fastapi.testclient import TestClient

from app.main import app
from app.registry import load_registry

from .helpers import make_frame

client = TestClient(app)


def test_departments_lists_all_five():
    ids = {d["id"] for d in client.get("/api/departments").json()}
    assert ids == {"police", "morth_nhai", "bsf", "ssb", "customs"}


def test_match_round_trip_against_generated_registry():
    target = load_registry()[0]
    frames = [make_frame(i, target.plate).model_dump() for i in range(3)]
    body = {"department": "police", "frames": frames,
            "colour": {target.colour: 0.9}, "body_type": {target.body_type: 0.9}}
    res = client.post("/api/match", json=body).json()
    assert res["status"] in ("match", "ambiguous")
    assert target.plate in [c["plate"] for c in res["candidates"]]


def test_unknown_department_is_404():
    r = client.post("/api/match", json={"department": "nope", "frames": []})
    assert r.status_code == 404
