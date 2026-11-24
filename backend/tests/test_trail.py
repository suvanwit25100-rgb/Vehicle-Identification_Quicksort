"""Cross-camera trail: optional camera fields on upload, and one plate's route in order."""
import pytest

from app import main

from .test_case_export import client  # noqa: F401  (fixture)
from .test_watchlist import job


@pytest.fixture(autouse=True)
def _reset():
    main.limiter.reset()
    yield
    main.limiter.reset()


def with_camera(jid, filename, plate, duration, camera, place, lat, lon, recorded, when="2026-11-24T10:00:00+00:00"):
    r = job(jid, filename, [plate], duration=duration, when=when)
    r.camera, r.camera_place, r.camera_lat, r.camera_lon, r.recorded_at = camera, place, lat, lon, recorded
    main.save_job(r)


def test_the_trail_orders_stops_by_recording_time_not_by_when_they_were_analysed(client):
    # analysed in the opposite order to how the car actually drove past
    with_camera("aaaaaaaaaaa1", "late.mp4", "UP14CA0914", 5.0, "Mowa bridge", "Mowa", 21.265, 81.664, "2026-11-24T18:30", when="2026-11-24T10:00:00+00:00")
    with_camera("aaaaaaaaaaa2", "early.mp4", "UP14CA0914", 6.0, "Telibandha gate", "Telibandha Chowk", 21.2399, 81.6523, "2026-11-24T08:15", when="2026-11-24T11:00:00+00:00")
    g = client.get("/api/trail?plate=UP14CA0914").json()
    assert len(g) == 1 and g[0]["plate"] == "UP14CA0914" and g[0]["ordered_by"] == "recording time"
    assert [s["camera"] for s in g[0]["stops"]] == ["Telibandha gate", "Mowa bridge"]
    assert g[0]["stops"][0]["lat"] == 21.2399 and g[0]["stops"][0]["recorded_at"] == "2026-11-24T08:15"


def test_a_single_video_is_a_trail_of_one_and_missing_times_fall_back_with_a_label(client):
    with_camera("bbbbbbbbbbb1", "a.mp4", "MH12AB3456", 5.0, None, None, None, None, None)
    g = client.get("/api/trail?plate=MH12AB3456").json()
    assert len(g[0]["stops"]) == 1 and "analysis time" in g[0]["ordered_by"] and g[0]["stops"][0]["camera"] is None


def test_a_partial_plate_finds_the_trail_and_a_stranger_does_not(client):
    with_camera("ccccccccccc1", "a.mp4", "DL8CAY4767", 5.0, "Gate", "Here", 21.2, 81.6, "2026-11-24T09:00")
    assert client.get("/api/trail?plate=DL8C??4767").json()[0]["plate"] == "DL8CAY4767"
    assert client.get("/api/trail?plate=KA01AB1234").json() == []
    assert client.get("/api/trail?plate=DL8").json() == []                                      # too few characters to follow


def test_camera_details_are_validated_and_trimmed():
    f = main._camera_fields
    assert f("  Gate   2 ", "Telibandha", "21.24", "81.65", "2026-11-24T08:15") == ("Gate 2", "Telibandha", 21.24, 81.65, "2026-11-24T08:15")
    assert f("", "", "", "", "") == (None, None, None, None, None)
    for bad in (("", "", "abc", "81", ""), ("", "", "95", "81", ""), ("", "", "21", "200", ""), ("", "", "21", "", ""), ("", "", "", "", "yesterday")):
        with pytest.raises(main.HTTPException) as e:
            f(*bad)
        assert e.value.status_code == 422, bad
    assert len(f("x" * 200, "y" * 300, "", "", "")[0]) == 80


def test_an_old_result_without_camera_fields_still_loads(client, tmp_path):
    r = job("ddddddddddd1", "old.mp4", ["UP14CA0914"])
    data = r.model_dump()
    for k in ("camera", "camera_place", "camera_lat", "camera_lon", "recorded_at"):
        data.pop(k)
    (tmp_path / "jobs" / "ddddddddddd1" / "result.json").write_text(main.AnalysisResult.model_validate(data).model_dump_json(exclude={"camera", "camera_place", "camera_lat", "camera_lon", "recorded_at"}))
    assert client.get("/api/jobs/ddddddddddd1").status_code == 200
    assert client.get("/api/trail?plate=UP14CA0914").json()[0]["stops"][0]["camera"] is None
