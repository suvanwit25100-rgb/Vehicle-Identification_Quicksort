from app.config import get_department
from app.fusion import fuse_frames
from app.matcher import match_registry

from .helpers import make_frame, row

TARGET = "CG04KA2819"
REGISTRY = [
    row("R1", TARGET, "white", "suv"),
    row("R2", "MH12AB3456", "black", "car"),
    row("R3", "DL08ZX9021", "red", "two_wheeler"),
    row("R4", "CG04KA2810", "blue", "truck"),
]
POLICE = get_department("police")
BSF = get_department("bsf")


def fused_for(plate, n=3, unread=(), **kw):
    return fuse_frames([make_frame(i, plate, unread=unread, **kw) for i in range(n)])


def test_exact_read_ranks_true_vehicle_first():
    res = match_registry(fused_for(TARGET), {"white": 0.9}, {"suv": 0.9}, REGISTRY, POLICE)
    assert res.status == "match"
    assert res.candidates[0].plate == TARGET
    assert res.candidates[0].confidence >= 0.8
    assert any("Colour" in r for r in res.candidates[0].reasons)


def test_partial_plate_lists_unknown_slots_in_reasons():
    res = match_registry(fused_for(TARGET, unread=(4, 5)), {"white": 0.9}, {"suv": 0.9}, REGISTRY, POLICE)
    assert res.status == "match"
    top = res.candidates[0]
    assert top.plate == TARGET
    assert top.unknown_slots == [4, 5]
    assert any("unknown, not guessed" in r for r in top.reasons)


def test_too_few_characters_is_insufficient_evidence():
    fused = fused_for(TARGET, unread=tuple(range(3, 10)))
    res = match_registry(fused, {"white": 0.9}, {"suv": 0.9}, REGISTRY, POLICE)
    assert res.status == "insufficient_evidence"
    assert res.candidates == []


def test_plate_absent_from_registry_gives_no_confident_match():
    res = match_registry(fused_for("KA01ZZ7777"), {"white": 0.9}, {"suv": 0.9}, REGISTRY, POLICE)
    assert res.status == "no_confident_match"
    assert res.candidates == []


def test_one_digit_apart_rows_are_flagged_ambiguous_when_digit_unread():
    res = match_registry(
        fused_for(TARGET, unread=(9,)), {"white": 0.9}, None,
        [row("R1", "CG04KA2819", "white"), row("R4", "CG04KA2810", "white")], POLICE,
    )
    assert res.status == "ambiguous"
    assert len(res.candidates) == 2


def test_single_mismatch_penalised_but_listed_for_police_rejected_for_bsf():
    near = [row("N1", "CG04KA2810", "white", "suv")]
    fused = fused_for(TARGET)
    police = match_registry(fused, {"white": 0.9}, {"suv": 0.9}, near, POLICE)
    bsf = match_registry(fused, {"white": 0.9}, {"suv": 0.9}, near, BSF)
    assert bsf.status == "no_confident_match"
    assert bsf.candidates == []
    assert police.status == "match"
    assert police.candidates[0].mismatched_slots == [9]
    assert police.candidates[0].confidence < match_registry(
        fused, {"white": 0.9}, {"suv": 0.9}, [row("N1", TARGET, "white", "suv")], POLICE
    ).candidates[0].confidence


def test_bsf_demands_more_readable_characters_than_police():
    fused = fused_for(TARGET, unread=(0, 1, 2, 3, 4))
    res_police = match_registry(fused, {"white": 0.9}, {"suv": 0.9}, REGISTRY, POLICE)
    res_bsf = match_registry(fused, {"white": 0.9}, {"suv": 0.9}, REGISTRY, BSF)
    assert res_bsf.status == "insufficient_evidence"
    assert res_police.status != "insufficient_evidence"


def test_missing_attributes_do_not_crash_or_deflate_score():
    res = match_registry(fused_for(TARGET), None, None, REGISTRY, POLICE)
    assert res.status == "match"
    assert res.candidates[0].confidence >= 0.8


def test_car_and_suv_earn_half_credit_but_unrelated_types_earn_none():
    from app.config import get_department
    from app.matcher import match_registry
    from app.schemas import FusedPlate
    from .helpers import make_frame
    from app.fusion import fuse_frames

    fused = fuse_frames([make_frame(i, TARGET) for i in range(3)])
    cfg = get_department("police")
    seen = {"suv": 0.8, "car": 0.1, "two_wheeler": 0.1}
    c = lambda body: match_registry(fused, {"white": 0.9}, seen, [row("R", TARGET, "white", body)], cfg).candidates[0]
    suv, car, bike = c("suv"), c("car"), c("two_wheeler")
    assert car.components["body_fit"] == 0.4          # 0.8 for the neighbouring type, halved
    assert suv.components["body_fit"] == 0.8
    assert bike.components["body_fit"] == 0.1         # no look-alike credit for a bike
    assert any("half credit" in r for r in car.reasons) and not any("half credit" in r for r in suv.reasons)
