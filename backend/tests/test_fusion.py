from app.fusion import fuse_frames

from .helpers import make_frame

PLATE = "CG04KA2819"


def test_clean_frames_recover_full_plate():
    fused = fuse_frames([make_frame(i, PLATE) for i in range(3)])
    assert fused.pattern == PLATE
    assert fused.known_count == 10


def test_majority_beats_one_bad_frame():
    frames = [make_frame(i, PLATE) for i in range(3)]
    frames.append(make_frame(3, PLATE, overrides={9: ("1", 0.9)}))
    fused = fuse_frames(frames)
    assert fused.slots[9].char == "9"


def test_conflicting_reads_stay_unknown():
    frames = [
        make_frame(0, PLATE),
        make_frame(1, PLATE),
        make_frame(2, PLATE, overrides={9: ("1", 0.9)}),
        make_frame(3, PLATE, overrides={9: ("1", 0.9)}),
    ]
    fused = fuse_frames(frames)
    assert fused.slots[9].char is None
    assert fused.pattern == PLATE[:9] + "?"
    assert set(fused.slots[9].alternatives) == {"9", "1"}


def test_single_weak_read_is_not_accepted():
    fused = fuse_frames([make_frame(0, PLATE, conf=0.3)])
    assert fused.known_count == 0


def test_never_invents_unread_slots():
    frames = [make_frame(i, PLATE, unread=(4, 5)) for i in range(3)]
    fused = fuse_frames(frames)
    assert fused.pattern == "CG04??2819"
    assert fused.slots[4].confidence == 0.0


def test_letter_in_digit_slot_is_coerced_with_discount():
    frames = [make_frame(i, PLATE, overrides={2: ("O", 0.9)}) for i in range(3)]
    fused = fuse_frames(frames)
    assert fused.slots[2].char == "0"
    clean = fuse_frames([make_frame(i, PLATE) for i in range(3)])
    assert fused.slots[2].confidence < clean.slots[2].confidence


def test_delhi_rto_letter_is_kept_not_coerced_to_a_digit():
    # Real footage: DL1LAJ2850 was being rewritten to DL11AJ2850 (L -> 1)
    for plate in ("DL1LAJ2850", "DL8CAY4767"):
        fused = fuse_frames([make_frame(i, plate, conf=0.98) for i in range(2)])
        assert fused.pattern == plate


def test_first_rto_position_is_still_a_digit_slot():
    frames = [make_frame(i, "DL8CAY4767", overrides={2: ("B", 0.9)}) for i in range(3)]
    assert fuse_frames(frames).slots[2].char == "8"


def test_sharp_large_frame_outweighs_blurry_small_ones():
    good = make_frame(0, PLATE, sharpness=1.0, area=1.0)
    bad = [make_frame(i, PLATE, overrides={9: ("1", 0.9)}, sharpness=0.1, area=0.2) for i in (1, 2)]
    fused = fuse_frames([good, *bad], slot_margin=0.1, slot_accept=0.5)
    assert fused.slots[9].char == "9"
