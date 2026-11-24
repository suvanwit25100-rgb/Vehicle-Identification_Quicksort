"""Feature 4: the case report as a PDF."""
import io
import zipfile

import pytest

pytest.importorskip("reportlab")
from pypdf import PdfReader  # noqa: E402

from app import main  # noqa: E402

from .test_case_export import client, stored_case  # noqa: F401,E402


def text_of(data: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def test_pdf_has_the_facts_of_the_report(client, tmp_path):
    result = stored_case(tmp_path)
    r = client.get(f"/api/jobs/{result.job_id}/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    text = text_of(r.content)
    for needle in ["ExLex analysis report", result.job_id, "Recovered plate", "never guessed", "Second reader", "Ranked candidates", "CG04KA2819", "Models and settings", "not identifications"]:
        assert needle in text, needle
    assert len(PdfReader(io.BytesIO(r.content)).pages) >= 1


def test_pdf_is_in_the_case_file_and_its_hash_is_in_the_manifest(client, tmp_path):
    import hashlib
    import json

    result = stored_case(tmp_path)
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/jobs/{result.job_id}/download").content))
    root = f"case-{result.job_id}/"
    assert root + "report.pdf" in z.namelist()
    manifest = json.loads(z.read(root + "manifest.json"))
    entry = next(f for f in manifest["files"] if f["path"] == "report.pdf")
    assert entry["sha256"] == hashlib.sha256(z.read(root + "report.pdf")).hexdigest()


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/000000000000/report.pdf").status_code == 404


def test_odd_text_does_not_break_the_pdf(client, tmp_path):
    result = stored_case(tmp_path)
    result.source_filename = "clip <b>&</b> नेत्रा.mp4"       # markup characters and non-Latin text
    main.save_job(result)
    r = client.get(f"/api/jobs/{result.job_id}/report.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_without_reportlab_the_endpoint_says_so_and_the_case_file_still_builds(client, tmp_path, monkeypatch):
    from app import pdf_report

    monkeypatch.setattr(pdf_report, "available", lambda: False)
    result = stored_case(tmp_path)
    assert client.get(f"/api/jobs/{result.job_id}/report.pdf").status_code == 501
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/jobs/{result.job_id}/download").content))
    assert not any(n.endswith("report.pdf") for n in z.namelist()) and any(n.endswith("report.html") for n in z.namelist())


def test_pdf_shows_a_confidence_for_each_character_in_each_frame(client, tmp_path):
    result = stored_case(tmp_path)
    r = client.get(f"/api/jobs/{result.job_id}/report.pdf")
    text = text_of(r.content)
    assert "Characters read per frame, with confidence" in text
    track = next(t for t in result.tracks if t.frame_reads)
    first = next(c for c in track.frame_reads[0].chars if c)
    assert f"{first.conf:.2f}" in text
    assert "Score parts:" in text


def test_compare_scores_a_typed_plate_against_the_recovered_one(client, tmp_path):
    result = stored_case(tmp_path)
    track = next(t for t in result.tracks if t.match)
    plate = "".join((s.char if s.char and s.char != "-" else "0") for s in track.match.fused.slots)
    url = f"/api/jobs/{result.job_id}/tracks/{track.track_id}/compare"
    full = client.post(url, json={"plate": plate}).json()
    assert full["score"] == 1.0 and not full["clash"]
    off = client.post(url, json={"plate": plate[:3] + ("1" if plate[3] != "1" else "2") + plate[4:]}).json()
    assert 0 < off["score"] < 1 and off["clash"] == [3]
    wild = client.post(url, json={"plate": plate[:3] + "?" + plate[4:]}).json()
    assert wild["score"] == 1.0 and 3 in wild["not_compared"]
    assert client.post(url, json={"plate": "AB"}).status_code == 422
    assert client.post(url, json={"plate": "bad plate!!"}).status_code == 422
    assert client.post(f"/api/jobs/{result.job_id}/tracks/9999/compare", json={"plate": plate}).status_code == 404
