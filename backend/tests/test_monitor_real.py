"""The monitor shows measured data only: no simulated figures, no hard-coded claims, and numbers that match what is stored."""

import json

import pytest

from app import main
from app.monitor import Metrics

from .test_case_export import client, stored_case  # noqa: F401  (fixtures)


def test_the_monitor_carries_only_measured_sections(client):
    m = client.get("/api/monitor").json()
    assert set(m) == {"generated_at", "server", "host", "brains", "jobs", "complaints"}
    assert "calibration" not in m and "registry_rows" not in m     # a simulation and a synthetic count do not belong here


def test_calibration_is_served_separately_and_labelled_as_a_simulation(client, tmp_path):
    empty = client.get("/api/calibration").json()
    assert empty["simulated"] is True and empty["agencies"] is None and "not a measured accuracy" in empty["note"]
    (tmp_path / "calibration_report.json").write_text(json.dumps({"police": {"target_fmr": 0.05}}))
    assert client.get("/api/calibration").json()["agencies"]["police"]["target_fmr"] == 0.05


def test_statistics_are_computed_from_what_is_stored(client, tmp_path):
    stored_case(tmp_path)            # 1 vehicle, 8 known characters, plate 100 px wide, 12.5 s video, 18.2 s to process
    j = client.get("/api/monitor").json()["jobs"]
    assert j["footage_seconds"] == 12.5 and j["stored_videos"] == 1 and j["distinct_videos"] == 1
    assert j["processing"] == {"count": 1, "median_s": 18.2, "max_s": 18.2, "realtime_factor": round(18.2 / 12.5, 2)}
    width = {b["bin"]: b for b in j["plate_width"]}
    assert width["80 to 119 px"] == {"bin": "80 to 119 px", "vehicles": 1, "any": 1, "most": 1}
    assert sum(b["vehicles"] for b in j["plate_width"]) == 1
    assert sum(b["count"] for b in j["confidence_hist"]) == 8          # one entry per recovered character, no more
    assert len(j["per_day"]) == 1 and j["per_day"][0]["analyses"] == 1 and j["per_day"][0]["vehicles"] == 1
    assert j["per_day"][0]["date"] == "2026-11-24"


def test_with_nothing_stored_every_statistic_is_empty_not_invented(client):
    j = client.get("/api/monitor").json()["jobs"]
    assert j["footage_seconds"] == 0 and j["stored_videos"] == 0 and j["distinct_videos"] == 0 and j["per_day"] == []
    assert j["processing"] == {"count": 0, "median_s": None, "max_s": None, "realtime_factor": None}
    assert all(b["vehicles"] == 0 for b in j["plate_width"]) and sum(b["count"] for b in j["confidence_hist"]) == 0


def test_the_request_counters_count_real_requests_and_not_the_monitor_itself(client):
    base = client.get("/api/monitor").json()["server"]
    client.get("/api/monitor")
    client.get("/api/health")
    assert client.get("/api/monitor").json()["server"]["total"] == base["total"]      # polling must not inflate the counts
    client.get("/api/departments")
    client.get("/api/jobs/000000000000")                                               # a 404
    s = client.get("/api/monitor").json()["server"]
    assert s["total"] == base["total"] + 2 and s["client_errors"] == base["client_errors"] + 1
    assert s["by_group"].get("stored results", 0) >= 1 and s["uptime_s"] >= 0 and s["started_at"]


@pytest.mark.parametrize("path,group", [("/api/analyze", "analyses"), ("/api/match", "plate matches"), ("/api/complaints/preview", "citizen reports"),
                                        ("/api/desk/complaints", "officer desk"), ("/api/jobs/abc/download", "stored results"), ("/api/brains", "other")])
def test_request_groups(path, group):
    assert Metrics.group(path) == group


def test_host_measurements_are_real_numbers(client, tmp_path):
    stored_case(tmp_path)
    h = client.get("/api/monitor").json()["host"]
    assert h["cpus"] >= 1 and h["disk_total_gb"] > 0 and h["disk_free_gb"] >= 0 and h["jobs_bytes"] > 1000 and h["complaints_bytes"] == 0
    assert "python" in h and "system" in h


def test_repeated_runs_of_one_video_are_counted_once_as_a_video(client, tmp_path):
    stored_case(tmp_path, "aaaaaaaaaaaa")
    stored_case(tmp_path, "bbbbbbbbbbbb")          # the same input hash again: a second analysis, not a second video
    j = client.get("/api/monitor").json()["jobs"]
    assert j["total"] == 2 and j["distinct_videos"] == 1
