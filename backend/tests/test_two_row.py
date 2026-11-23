"""Two-row plates, the usual layout on Indian two-wheelers: found, read row by row, and never allowed to harm a one-row plate."""

import cv2
import numpy as np
import pytest

from app import complaints as cm
from app.config import get_department
from app.schemas import FusedPlate
from app.vision.ocr import read_plate_chars
from app.vision.pipeline import analyze_video
from app.vision.plate_text import align_to_slots
from app.vision.rows import find_split, read_plate, split_rows

from .test_pipeline import StubTracker
from .vision_helpers import render_plate, render_two_row_plate


def as_slots(chars):
    return "".join(s.char if s else "?" for s in align_to_slots(chars))


def test_the_gap_between_two_rows_is_found_near_the_middle():
    img = render_two_row_plate("DL14S", "Z8550")
    y = find_split(img)
    assert y is not None and 0.35 * img.shape[0] < y < 0.65 * img.shape[0]
    top, bottom = split_rows(img)
    assert top.shape[0] < 0.7 * img.shape[0] and bottom.shape[0] < 0.7 * img.shape[0]


def test_a_one_row_plate_is_never_split():
    assert split_rows(render_plate("MH12AB3456", 380)) is None


@pytest.mark.parametrize("top,bottom", [("DL14S", "Z8550"), ("MH12", "AB3456"), ("DL8C", "AY4767")])
def test_a_two_row_plate_is_read_as_the_whole_plate(top, bottom):
    img = render_two_row_plate(top, bottom)
    assert as_slots(read_plate_chars(img)) != top + bottom        # read as one line it fails, which is why this exists
    chars, rows = read_plate(img)
    assert rows == 2 and as_slots(chars) == top + bottom


def test_a_one_row_plate_reads_exactly_as_before():
    img = render_plate("MH12AB3456", 380)
    chars, rows = read_plate(img)
    assert rows == 1 and "".join(c for c, _ in chars) == "".join(c for c, _ in read_plate_chars(img)) == "MH12AB3456"


def test_a_one_row_plate_with_a_loose_crop_is_not_damaged():
    plate = render_plate("MH12AB3456", 380)
    h, w = plate.shape[:2]
    loose = cv2.copyMakeBorder(plate, int(w / 2.3 / 2 - h / 2), int(w / 2.3 / 2 - h / 2), 0, 0, cv2.BORDER_CONSTANT, value=(70, 70, 70))
    assert w / loose.shape[0] < 3.0                                # squarish enough that a split is attempted
    chars, _ = read_plate(loose)
    assert as_slots(chars) == "MH12AB3456"


def test_a_blank_crop_reads_as_nothing():
    chars, rows = read_plate(np.full((60, 120, 3), 255, np.uint8))
    assert chars == [] and rows == 1


# ---- through the pipeline and the citizen-photo path, with the plate detector stubbed so no weights are needed
class StubPlateDetector:
    def __init__(self, box):
        self.box = box

    def best(self, crop):
        return self.box, 0.9


def two_row_frame(top, bottom):
    f = np.full((300, 520, 3), 120, np.uint8)
    cv2.rectangle(f, (20, 40), (500, 290), (18, 18, 18), -1)
    plate = render_two_row_plate(top, bottom, 190)
    f[150:150 + plate.shape[0], 165:165 + plate.shape[1]] = plate
    return f, plate.shape


def test_the_pipeline_reads_a_two_row_plate_and_records_the_layout(tmp_path):
    f, (ph, pw, _) = two_row_frame("DL14S", "Z8550")
    clip = tmp_path / "moto.mp4"
    w = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 30, (520, 300))
    for _ in range(60):
        w.write(f)
    w.release()
    box = (145, 110, 145 + pw, 110 + ph)      # in vehicle-crop coordinates (the vehicle starts at 20, 40)
    res = analyze_video(clip, "police", StubTracker(), StubPlateDetector(box))
    t = res.tracks[0]
    assert t.plate_layout == "two-row" and t.match.pattern == "DL14SZ8550"
    assert all(r.rows == 2 for r in t.frame_reads) and t.frame_reads[0].raw == "DL14SZ8550"


def test_a_citizen_photo_of_a_two_row_plate_is_read_too():
    f, (ph, pw, _) = two_row_frame("MH12", "AB3456")

    class Vehicle:
        def detect(self, frame):
            from app.vision.detectors import VehicleDet

            return [VehicleDet(-1, "motorcycle", 0.9, (20, 40, 500, 290))]

    out = cm.read_photo(f, Vehicle(), StubPlateDetector((145, 110, 145 + pw, 110 + ph)), get_department("police"))
    assert isinstance(out["fused"], FusedPlate) and out["fused"].pattern == "MH12AB3456" and out["plate_found"]


def test_layout_is_judged_by_the_frames_that_produced_a_reading():
    from app.vision.pipeline import plate_layout

    from .helpers import make_frame

    good = make_frame(0, "DL14SZ8550")
    good.rows = 2
    junk = [make_frame(i, "DL14SZ8550", unread=tuple(range(9))) for i in range(1, 6)]   # tiny frames: almost nothing read
    for j in junk:
        j.rows = 1
    assert plate_layout([good, *junk]) == "two-row"          # one good frame outweighs five empty ones
    assert plate_layout(junk) == "one-row" and plate_layout([]) is None
    plain = make_frame(9, "MH12AB3456")
    plain.rows = 1
    assert plate_layout([plain, good]) in ("one-row", "two-row")
