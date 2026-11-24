"""Feature 5: per-agency suggestions and a DRAFT e-challan, only ever for a confirmed match."""
import io

import pytest

from app import main
from app.agency_tools import challan_available, suggest
from app.config import get_department
from app.fusion import fuse_frames
from app.matcher import match_registry

from .helpers import make_frame, row
from .test_case_export import client  # noqa: F401  (fixture)
from .test_jobs_report import sample_result

KEY = {"X-Officer-Key": main.OFFICER_KEY}
PLATE = "CG04KA2819"


def matched(flags, dept="police", plate=PLATE, read=PLATE, n=3):
    fused = fuse_frames([make_frame(i, read) for i in range(n)])
    return match_registry(fused, {"white": 0.9}, {"suv": 0.9}, [row("R1", plate, "white", "suv", flags=flags)], get_department(dept))


def kinds(dept, flags):
    return [a["kind"] for a in suggest(dept, matched(flags, dept))]


def test_police_are_told_to_verify_a_stolen_flag_and_can_draft_a_document_challan():
    assert kinds("police", ["stolen"]) == ["alert"]
    assert kinds("police", ["insurance_expired"]) == ["document"]
    assert [a["challan"] for a in suggest("police", matched(["insurance_expired", "puc_expired"]))] == [True]


def test_other_agencies_refer_stolen_to_police_and_only_note_documents():
    assert kinds("bsf", ["stolen"]) == ["refer"]
    assert kinds("customs", ["puc_expired"]) == ["note"]
    assert not challan_available("customs", matched(["puc_expired"], "customs"))
    assert kinds("morth_nhai", ["puc_expired"]) == ["document"] and kinds("morth_nhai", ["stolen"]) == ["refer"]


def test_a_clean_record_says_so():
    assert kinds("police", []) == ["clear"]


def test_nothing_is_suggested_without_a_confirmed_match():
    assert suggest("police", matched(["stolen"], read="MH12AB3456")) == []              # no confident match
    ambiguous = match_registry(fuse_frames([make_frame(i, PLATE, unread=(8, 9)) for i in range(3)]), {"white": 0.9}, {"suv": 0.9},
                               [row("R1", "CG04KA2810", flags=["stolen"]), row("R2", "CG04KA2819", flags=["stolen"])], get_department("police"))
    assert ambiguous.status == "ambiguous"
    assert [a["kind"] for a in suggest("police", ambiguous)] == ["verify"]          # no stolen alert on an unconfirmed plate


def test_job_actions_endpoint(client, tmp_path):
    from .test_case_export import stored_case

    result = stored_case(tmp_path)          # its top candidate is flagged "stolen"
    body = client.get(f"/api/jobs/{result.job_id}/actions").json()
    assert body["department"] == "police" and "synthetic" in body["note"]
    assert body["actions"]["1"][0]["kind"] in ("alert", "verify")


def doc_violation_job(tmp_path, dept="police"):
    from .test_case_export import stored_case

    r = stored_case(tmp_path)
    r.department = dept
    r.tracks[0].match = matched(["insurance_expired"], dept)
    main.save_job(r)
    return r


def test_challan_needs_the_officer_key(client, tmp_path):
    r = doc_violation_job(tmp_path)
    assert client.get(f"/api/desk/jobs/{r.job_id}/tracks/1/challan.pdf").status_code == 401


def test_draft_challan_is_a_labelled_draft(client, tmp_path):
    pytest.importorskip("reportlab")
    from pypdf import PdfReader

    r = doc_violation_job(tmp_path)
    resp = client.get(f"/api/desk/jobs/{r.job_id}/tracks/1/challan.pdf", headers=KEY)
    assert resp.status_code == 200 and resp.content.startswith(b"%PDF")
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(resp.content)).pages)
    for needle in ["DRAFT e-challan", "Not an official e-challan", "synthetic", PLATE, "insurance", "To be set by the issuing officer", f"DRAFT-{r.job_id}-1"]:
        assert needle in text, needle


def test_challan_is_refused_where_it_does_not_apply(client, tmp_path):
    r = doc_violation_job(tmp_path, dept="bsf")
    assert client.get(f"/api/desk/jobs/{r.job_id}/tracks/1/challan.pdf", headers=KEY).status_code == 409      # not that agency's remit
    r2 = doc_violation_job(tmp_path)
    assert client.get(f"/api/desk/jobs/{r2.job_id}/tracks/99/challan.pdf", headers=KEY).status_code == 404
    assert client.get("/api/jobs/000000000000/actions").status_code == 404
