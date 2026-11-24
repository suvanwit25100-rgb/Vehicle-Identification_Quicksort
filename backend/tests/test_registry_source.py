"""The registry can come from a feed, a file or the sample-clip test registry, and says which."""
import json

import pytest

from app import registry


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    registry.load_registry.cache_clear()
    yield
    registry.load_registry.cache_clear()


def test_a_supplied_csv_is_used_and_labelled(tmp_path, monkeypatch):
    f = tmp_path / "r.csv"
    f.write_text("reg_id,plate,colour,body_type,make,model,flags\nX1,cg04 ka 2819,white,suv,Tata,Safari,stolen\n")
    monkeypatch.delenv("EXLEX_REGISTRY_URL", raising=False)
    monkeypatch.setenv("EXLEX_REGISTRY", str(f))
    rows = registry.load_registry()
    assert rows[0].plate == "CG04KA2819" and rows[0].flags == ["stolen"]
    assert "you supplied" in registry.registry_source()


def test_a_feed_must_be_https(monkeypatch):
    monkeypatch.setenv("EXLEX_REGISTRY_URL", "http://example.invalid/r.json")
    monkeypatch.setenv("EXLEX_REGISTRY", str(registry.SYNTHETIC_REGISTRY))
    assert len(registry.load_registry()) > 0
    assert "feed failed" in registry.registry_source()          # fell back, and said so


def test_a_json_feed_is_read(monkeypatch):
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=-1): return json.dumps([{"reg_id": "A", "plate": "DL01AB1234", "colour": "red", "body_type": "car"}]).encode()
    seen = {}
    def fake(req, timeout):
        seen["auth"] = req.get_header("Authorization")
        return Resp()
    monkeypatch.setattr(registry.urllib.request, "urlopen", fake)
    monkeypatch.setenv("EXLEX_REGISTRY_URL", "https://registry.example.invalid/rows")
    monkeypatch.setenv("EXLEX_REGISTRY_KEY", "k123")
    rows = registry.load_registry()
    assert [r.plate for r in rows] == ["DL01AB1234"] and seen["auth"] == "Bearer k123"
    assert registry.registry_source() == "authorised feed"


def test_the_shipped_test_registry_is_labelled_and_has_no_made_up_vehicles():
    rows = registry._from_file(registry.TEST_REGISTRY)
    assert rows and all(r.make == "-" and r.model == "-" and r.reg_id.startswith("TEST") for r in rows)
