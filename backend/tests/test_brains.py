import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.brains import brain_status
from app.main import app
from app.vision.attributes import BODY_PROMPTS, COCO_TO_BODY, fuse_body


def test_brain_status_lists_every_brain_and_required_ones_are_ready():
    status = {b["id"]: b for b in brain_status()}
    assert set(status) == {"vehicle_detector", "plate_detector", "plate_ocr", "second_reader", "clip"}
    assert all(b["ready"] for b in status.values() if b["required"])


def test_api_brains_matches_manifest():
    assert TestClient(app).get("/api/brains").json() == brain_status()


def test_prompts_cover_every_body_class_used_by_the_matcher():
    labels = {c for table in COCO_TO_BODY.values() for c in table}
    assert labels <= set(BODY_PROMPTS)


class TestFuseBody:
    def test_clip_can_override_coco_label(self):
        clip = {"auto_rickshaw": 0.80, "car": 0.10, "suv": 0.05, "truck": 0.05}
        fused = fuse_body("car", clip)
        assert max(fused, key=fused.get) == "auto_rickshaw"

    def test_coco_prior_breaks_a_near_tie(self):
        clip = {"car": 0.34, "bus": 0.33, "suv": 0.33}
        fused = fuse_body("bus", clip)
        assert max(fused, key=fused.get) == "bus"

    def test_result_is_a_distribution(self):
        fused = fuse_body("truck", {"truck": 0.5, "tempo": 0.3, "bus": 0.2})
        assert abs(sum(fused.values()) - 1.0) < 0.01

    def test_unknown_coco_label_passes_clip_through(self):
        clip = {"car": 0.6, "suv": 0.4}
        assert fuse_body("boat", clip) == clip


@pytest.mark.skipif(
    not next(b for b in brain_status() if b["id"] == "clip")["ready"], reason="CLIP weights not downloaded"
)
def test_clip_separates_clearly_different_vehicle_images():
    from app.vision.clip_brain import ClipBrain

    brain = ClipBrain()
    blank = np.full((224, 224, 3), 128, np.uint8)
    out = brain.classify([blank], BODY_PROMPTS)[0]
    assert set(out) == set(BODY_PROMPTS)
    assert abs(sum(out.values()) - 1.0) < 0.01
    assert brain.embed(blank).shape == (512,)
