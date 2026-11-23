import cv2
import numpy as np
import pytest

from app.vision.attributes import average_distributions, body_distribution, colour_distribution
from app.vision.ocr import read_plate_chars
from app.vision.plate_text import align_to_slots
from app.vision.video import laplacian_var, sample_frames

from .vision_helpers import render_plate, solid


def chars(s, conf=0.9):
    return [(c, conf) for c in s]


class TestAlign:
    def test_ten_chars_map_directly(self):
        slots = align_to_slots(chars("CG04KA2819"))
        assert "".join(s.char for s in slots) == "CG04KA2819"

    def test_nine_char_single_letter_series_marks_second_series_slot_absent(self):
        slots = align_to_slots(chars("CG04A1234"))
        assert [s.char if s else None for s in slots] == ["C", "G", "0", "4", "A", "-", "1", "2", "3", "4"]

    def test_unplaceable_read_yields_all_unknown(self):
        assert all(s is None for s in align_to_slots(chars("CGKA2819")))

    def test_dropped_number_digits_keep_only_certain_prefix(self):
        slots = align_to_slots(chars("CG04KA28"))
        assert [s.char if s else None for s in slots] == ["C", "G", "0", "4", "K", "A", None, None, None, None]

    def test_short_number_is_not_placed(self):
        slots = align_to_slots(chars("CG04KA281"))
        assert [s.char if s else None for s in slots][6:] == [None] * 4
        assert slots[4].char == "K" and slots[5].char == "A"

    def test_extra_leading_character_is_shifted_out(self):
        # Real clip: "HDL9CANGOY" was a Delhi plate read with a stray leading H
        slots = align_to_slots([("H", .6), ("D", .77), ("L", .99), ("9", .88), ("C", .98), ("A", .97),
                                ("N", .44), ("G", .37), ("O", .32), ("Y", .31)])
        assert [s.char if s else None for s in slots][:6] == ["D", "L", "9", "C", "A", "N"]

    def test_eleven_chars_with_extra_leading_character(self):
        slots = align_to_slots(chars("HDL9CAM9014"))
        assert "".join(s.char for s in slots) == "DL9CAM9014"

    def test_trailing_extra_character_is_dropped(self):
        assert "".join(s.char for s in align_to_slots(chars("DL9CAM9014X"))) == "DL9CAM9014"

    def test_clean_ten_character_read_is_never_shifted(self):
        for plate in ("CG04KA2819", "DL1LAJ2850", "UP14CA0914", "MH12AB3456"):
            assert "".join(s.char for s in align_to_slots(chars(plate))) == plate

    def test_shifted_frame_no_longer_poisons_the_vote(self):
        from app.fusion import fuse_frames
        from app.schemas import FrameRead

        clean = [("D", .96), ("L", 1.0), ("9", .94), ("C", .99), ("A", .98), ("M", .55), ("9", .37), ("0", .48), ("1", .93), ("4", .95)]
        shifted = [("H", .6), ("D", .77), ("L", .99), ("9", .88), ("C", .98), ("A", .97), ("N", .44), ("G", .37), ("O", .32), ("Y", .31)]
        frames = [FrameRead(frame_id=i, sharpness=100, plate_area=1000, chars=align_to_slots(c))
                  for i, c in enumerate([clean, shifted])]
        assert fuse_frames(frames).pattern[:5] == "DL9CA"

    def test_delhi_letter_rto_aligns_when_digits_are_dropped(self):
        slots = align_to_slots(chars("DL1LAJ28"))
        assert [s.char if s else None for s in slots] == ["D", "L", "1", "L", "A", "J", None, None, None, None]

    def test_punctuation_and_case_are_normalised(self):
        slots = align_to_slots([(c, 0.9) for c in "cg-04 ka 2819" if c.isalnum()])
        assert "".join(s.char for s in slots) == "CG04KA2819"


class TestColour:
    @pytest.mark.parametrize("bgr,expected", [
        ((250, 250, 250), "white"), ((15, 15, 15), "black"), ((40, 40, 200), "red"),
        ((200, 60, 40), "blue"), ((40, 200, 200), "yellow"), ((60, 180, 60), "green"),
    ])
    def test_solid_body_colour(self, bgr, expected):
        img = solid(bgr)
        dist = colour_distribution(img, (0, 0, 200, 200))
        assert max(dist, key=dist.get) == expected
        assert abs(sum(dist.values()) - 1.0) < 0.01

    def test_probabilities_are_smoothed_not_certain(self):
        dist = colour_distribution(solid((250, 250, 250)), (0, 0, 200, 200))
        assert max(dist.values()) < 1.0 and min(dist.values()) > 0.0

    def test_empty_roi_returns_empty(self):
        assert colour_distribution(solid((0, 0, 0)), (10, 10, 10, 10)) == {}


def test_body_distribution_sums_to_one_and_unknown_label_is_empty():
    for label in ("car", "motorcycle", "bus", "truck"):
        assert abs(sum(body_distribution(label).values()) - 1.0) < 1e-6
    assert body_distribution("boat") == {}


def test_average_distributions_weights():
    avg = average_distributions([{"a": 1.0}, {"b": 1.0}], [3.0, 1.0])
    assert avg == {"a": 0.75, "b": 0.25}
    assert average_distributions([{}, {}]) == {}


class TestOCR:
    PLATES = ["CG04KA2819", "MH12AB3456", "DL08ZX9021", "BR26RH4022", "KA51MN6789", "WB19CD5081"]

    @pytest.mark.parametrize("plate", PLATES)
    def test_reads_clean_plate_with_high_confidence(self, plate):
        img = cv2.GaussianBlur(render_plate(plate), (0, 0), 2)
        out = read_plate_chars(img)
        assert "".join(c for c, _ in out) == plate
        assert sum(p for _, p in out) / len(out) > 0.9

    def test_small_blurred_plate_still_readable(self):
        img = cv2.resize(cv2.GaussianBlur(render_plate("MH12AB3456"), (0, 0), 3), (120, 28))
        assert "".join(c for c, _ in read_plate_chars(img)) == "MH12AB3456"

    def test_blank_image_reads_nothing(self):
        assert read_plate_chars(np.full((60, 200, 3), 255, np.uint8)) == []


class TestVideo:
    def test_sampling_rate_and_frame_ids(self, tmp_path):
        path = tmp_path / "clip.mp4"
        w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (64, 48))
        for i in range(90):
            w.write(np.full((48, 64, 3), i * 2, np.uint8))
        w.release()
        frames = sample_frames(path, target_fps=6)
        assert len(frames) == 18
        assert [f.frame_id for f in frames[:3]] == [0, 5, 10]

    def test_unreadable_file_raises(self, tmp_path):
        bad = tmp_path / "x.mp4"
        bad.write_bytes(b"not a video")
        with pytest.raises(ValueError):
            sample_frames(bad)

    def test_blur_lowers_laplacian_variance(self):
        sharp = render_plate("CG04KA2819")
        assert laplacian_var(cv2.GaussianBlur(sharp, (0, 0), 4)) < laplacian_var(sharp)
