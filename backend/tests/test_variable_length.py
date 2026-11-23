"""Feature 2: a plate with one series letter has nine characters; the empty slot is 'absent', not 'unreadable'."""
from app.config import get_department
from app.crosscheck import cross_check
from app.fusion import fuse_frames
from app.matcher import match_registry
from app.schemas import ABSENT, to_slots
from app.vision.plate_text import align_to_slots

from .helpers import make_frame, row

NINE = "DL1LR2711"
POLICE = get_department("police")


def test_to_slots_inserts_marker_only_for_the_nine_character_format():
    assert to_slots("DL1LR2711") == "DL1LR-2711"
    assert to_slots("dl 1l r2711") == "DL1LR-2711"
    assert to_slots("MH12AB3456") == "MH12AB3456"      # ten characters: untouched
    assert to_slots("ABCDE") == "ABCDE"                # not a plate format: untouched


def test_alignment_places_single_series_letter_with_marker():
    slots = align_to_slots([(c, 0.9) for c in NINE])
    assert "".join(s.char if s else "?" for s in slots) == "DL1LR-2711"
    assert slots[5].conf < slots[4].conf               # inferred, so slightly less certain than the letter that implies it


def test_fusion_keeps_marker_and_counts_only_real_characters():
    frames = [make_frame(i, to_slots(NINE)) for i in range(3)]
    fused = fuse_frames(frames)
    assert fused.pattern == "DL1LR-2711"
    assert fused.display == "DL1LR2711"
    assert fused.known_count == 9


def test_marker_outside_second_series_slot_is_ignored():
    frames = [make_frame(i, "MH12AB3456", overrides={0: (ABSENT, 0.9)}) for i in range(3)]
    assert fuse_frames(frames).slots[0].char == "M" or fuse_frames(frames).slots[0].char is None


def test_nine_character_registry_plate_is_matched_and_shown_plainly():
    reg = [row("R1", NINE), row("R2", "MH12AB3456")]
    fused = fuse_frames([make_frame(i, to_slots(NINE)) for i in range(3)])
    res = match_registry(fused, {"white": 0.9}, {"suv": 0.9}, reg, POLICE)
    assert res.status == "match" and res.candidates[0].plate == NINE
    assert res.candidates[0].slots == "DL1LR-2711"


def test_extra_letter_against_a_nine_character_row_is_a_listed_mismatch():
    reg = [row("R1", NINE)]
    exact = match_registry(fuse_frames([make_frame(i, to_slots(NINE)) for i in range(3)]), {"white": 0.9}, {"suv": 0.9}, reg, POLICE)
    fused = fuse_frames([make_frame(i, "DL1LRA2711") for i in range(3)])
    res = match_registry(fused, {"white": 0.9}, {"suv": 0.9}, reg, POLICE)
    assert res.candidates[0].confidence < exact.candidates[0].confidence
    assert any("no letter" in r for r in res.candidates[0].reasons)


def test_crosscheck_does_not_count_the_marker_as_an_agreeing_character():
    fused = fuse_frames([make_frame(i, to_slots(NINE)) for i in range(3)])
    ok = cross_check(fused, NINE, "second")
    assert ok.verdict == "agrees" and ok.agree == 9 and ok.clash == 0
    assert cross_check(fused, "DL1LR2111", "second").verdict == "disagrees"
