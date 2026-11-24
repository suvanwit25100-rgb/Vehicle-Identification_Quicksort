"""RTO code check: the first characters of a plate against the public code list."""
from app import rto
from app.fusion import fuse_frames

from .helpers import make_frame


def fused(plate, unread=(), conf=0.8):
    return fuse_frames([make_frame(i, plate, conf=conf, unread=unread) for i in range(3)])


def test_the_table_loaded_with_many_states_and_codes():
    t = rto._table()["states"]
    assert len(t) >= 30 and sum(len(v["codes"]) for v in t.values()) > 1000
    assert "Kolkata" in t["WB"]["codes"]["06"]["place"] and "Raipur" in t["CG"]["codes"]["04"]["place"]
    assert "csv" in rto.source().lower() and "wikipedia" in rto.source().lower()


def test_a_real_code_matches_with_the_readers_confidence():
    r = rto.check(fused("CG04KA2819", conf=0.8))
    assert r["status"] == "match" and r["code"] == "CG-04" and r["state"] == "Chhattisgarh" and "Raipur" in r["region"] and 0.8 <= r["confidence"] <= 1 and r["chars_used"] == 4


def test_a_one_digit_district_uses_three_characters():
    r = rto.check(fused("DL8CAY4767"))
    assert r["status"] == "match" and r["code"] == "DL-08" and r["chars_used"] == 3


def test_an_unknown_code_is_flagged_not_forced():
    r = rto.check(fused("CG99KA2819"))
    assert r["status"] == "unknown_code" and r["confidence"] is None
    r = rto.check(fused("ZZ04KA2819"))
    assert r["status"] == "unknown_code" and "misread" in r["message"]


def test_unreadable_code_characters_are_not_guessed():
    assert rto.check(fused("CG04KA2819", unread=(0,)))["status"] == "unreadable"
    assert rto.check(fused("CG04KA2819", unread=(3,)))["status"] == "unreadable"


from .test_case_export import client, stored_case  # noqa: F401,E402


def test_the_job_endpoint_carries_the_rto_check(client, tmp_path):
    result = stored_case(tmp_path)
    data = client.get(f"/api/jobs/{result.job_id}").json()
    track = next(t for t in data["tracks"] if t["frame_reads"])
    assert track["rto"]["status"] in {"match", "unknown_code", "unreadable"}
    assert "rto" not in (tmp_path / "jobs" / result.job_id / "result.json").read_text() or '"rto":null' in (tmp_path / "jobs" / result.job_id / "result.json").read_text().replace(" ", "")
