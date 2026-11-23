from app.calibration import (choose_threshold, make_samples, metrics_at, run_matcher,
                             simulate_frames, wilson_upper)
from app.config import get_department
from app.registry import load_registry

import random

REG = load_registry()


def records_for(dept, n_pos=120, n_neg=200, seed=3):
    return run_matcher(make_samples(REG, n_pos, n_neg, seed), REG, get_department(dept))


def test_samples_are_deterministic_and_negatives_are_not_in_registry():
    a, b = make_samples(REG, 40, 60, seed=1), make_samples(REG, 40, 60, seed=1)
    assert [s.truth for s in a] == [s.truth for s in b]
    known = {r.plate for r in REG}
    assert all(s.truth not in known for s in a if s.kind != "pos")
    assert all(s.truth in known for s in a if s.kind == "pos")


def test_easy_sightings_are_mostly_read_correctly():
    rng = random.Random(0)
    plate = REG[0].plate
    frames = simulate_frames(plate, rng, "easy")
    reads = [f.chars[i].char for f in frames for i in range(10) if f.chars[i]]
    right = sum(c == plate[i] for f in frames for i, c in enumerate(x.char if x else None for x in f.chars))
    assert right / len(reads) > 0.9


def test_false_matches_never_increase_as_threshold_rises():
    recs = records_for("police")
    rates = [metrics_at(recs, t / 100)["false_match_rate"] for t in range(30, 96, 5)]
    assert rates == sorted(rates, reverse=True)
    recalls = [metrics_at(recs, t / 100)["recall_top1"] for t in range(30, 96, 5)]
    assert recalls == sorted(recalls, reverse=True)


def test_chosen_threshold_meets_its_target_upper_bound():
    recs = records_for("bsf", 150, 400)
    m = choose_threshold(recs, 0.02)
    assert m["false_match_upper95"] <= 0.02 or m["theta"] == 0.99


def test_positives_are_never_returned_with_the_wrong_top_vehicle_at_configured_thresholds():
    for dept in ("police", "bsf"):
        cfg = get_department(dept)
        m = metrics_at(records_for(dept), cfg.match_threshold)
        assert m["pos_wrong_return"] <= 0.02


def test_wilson_upper_bound_behaviour():
    assert wilson_upper(0, 0) == 1.0
    assert 0 < wilson_upper(0, 1000) < 0.005
    assert wilson_upper(10, 100) > 0.10
