"""Officer registry search."""
import pytest

from app import main
from app.registry_search import clean_query, search

from .helpers import row
from .test_case_export import client  # noqa: F401  (fixture)
from .test_officer_portal import KEY, bearer, make_officer  # noqa: F401

ROWS = [row("R1", "UP14CA0914", "white", "suv", flags=["stolen"]), row("R2", "UP14CA0915", "white", "car"), row("R3", "DL8CAY4767", "red", "truck"),
        row("R4", "DL1LR2711", "silver", "car")]


def test_queries_are_cleaned_padded_and_must_say_enough():
    assert clean_query("up14 ca-0914") == "UP14CA0914"
    assert clean_query("UP14") == "UP14??????"                       # a prefix: the rest is left open
    assert clean_query("DL1LR2711") == "DL1LR-2711"                   # nine characters are placed in ten slots
    assert clean_query("") is None
    for bad in ("UP", "??1??????", "UP14CA0914X"):
        with pytest.raises(ValueError):
            clean_query(bad)


def test_partial_plate_colour_body_and_make_filter_with_reasons():
    r = search(ROWS, plate="UP14CA09??")
    assert [x["plate"] for x in r["results"]] == ["UP14CA0914", "UP14CA0915"] and "all 8 typed characters agree" in r["results"][0]["reasons"][0]
    assert [x["plate"] for x in search(ROWS, plate="UP14", colour="white", body_type="suv")["results"]] == ["UP14CA0914"]
    assert [x["plate"] for x in search(ROWS, colour="red")["results"]] == ["DL8CAY4767"]
    assert search(ROWS, plate="DL1LR2711")["results"][0]["plate"] == "DL1LR2711"
    assert search(ROWS, plate="UP14CA0914")["results"][0]["flags"] == ["stolen"]
    assert search(ROWS, make="test car")["total"] == 4 and search(ROWS, make="nothing")["total"] == 0
    assert search(ROWS, plate="UP14CA0916")["total"] == 0                    # a known character that differs never matches
    with pytest.raises(ValueError):
        search(ROWS)                                                          # no criteria: refuse instead of dumping the registry


def test_limit_and_total():
    many = [row(f"R{i}", f"UP14CA{i:04d}", "white", "car") for i in range(80)]
    r = search(many, plate="UP14CA????", limit=50)
    assert r["total"] == 80 and r["shown"] == 50 and len(r["results"]) == 50


def test_the_api_needs_sign_in_validates_and_audits(client):
    assert client.get("/api/desk/registry/search?plate=UP14").status_code == 401
    assert client.get("/api/desk/registry/facets").status_code == 401
    f = client.get("/api/desk/registry/facets", headers=KEY).json()
    assert f["rows"] >= 324 and "white" in f["colours"] and "synthetic" in f["note"]
    assert client.get("/api/desk/registry/search", headers=KEY).status_code == 422
    assert client.get("/api/desk/registry/search?plate=UP", headers=KEY).status_code == 422
    r = client.get("/api/desk/registry/search?colour=white&body_type=suv", headers=KEY).json()
    assert r["total"] > 0 and all(x["colour"] == "white" and x["body_type"] == "suv" for x in r["results"]) and "lead" in r["note"]
    tok = make_officer(client)
    assert client.get("/api/desk/registry/search?colour=red", headers=bearer(tok)).status_code == 200
    log = [(a["actor"], a["action"]) for a in client.get("/api/officer/audit", headers=KEY).json()]
    assert ("asha", "registry.search") in log


def test_a_nine_character_registry_plate_is_found():
    from app.registry import load_registry

    nine = next(r for r in load_registry() if len(r.plate) == 9)
    found = search(load_registry(), plate=nine.plate)
    assert nine.plate in [x["plate"] for x in found["results"]]
