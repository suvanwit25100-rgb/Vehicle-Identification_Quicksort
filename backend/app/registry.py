"""Where the registry comes from.

Order of use: an authorised feed (EXLEX_REGISTRY_URL, optional EXLEX_REGISTRY_KEY), then a CSV file
(EXLEX_REGISTRY), then the small test registry built from the sample clip. ExLex ships with no government
data and does not scrape third-party sites. An agency that is authorised to use its own register points the
feed or the file at it; the matcher, the reasons and the refusal gate do not change.

CSV columns: reg_id, plate, colour, body_type, make, model, flags (flags separated by ;).
A feed may return that CSV, or JSON: a list of objects with the same keys.
"""
import csv
import io
import json
import os
import urllib.request
from functools import lru_cache
from pathlib import Path

from .schemas import RegistryRow

DATA = Path(__file__).resolve().parent.parent / "data"
SYNTHETIC_REGISTRY = DATA / "registry.csv"             # 300 random rows; tests and calibration only
TEST_REGISTRY = DATA / "registry_clip_test.csv"        # plates read from the sample clip; demo only
DEMO_REGISTRY = DATA / "registry_demo.csv"             # synthetic rows + the clip plates; demo only
DEFAULT_REGISTRY = next((p for p in (DEMO_REGISTRY, TEST_REGISTRY) if p.exists()), SYNTHETIC_REGISTRY)
FEED_TIMEOUT_S = 15
MAX_FEED_BYTES = 20_000_000


def _rows(records) -> list[RegistryRow]:
    out = []
    for r in records:
        flags = r.get("flags") or ""
        if isinstance(flags, str):
            flags = [f for f in flags.split(";") if f]
        out.append(RegistryRow(reg_id=str(r["reg_id"]), plate=str(r["plate"]).upper().replace(" ", ""), colour=str(r.get("colour", "")),
                               body_type=str(r.get("body_type", "")), make=str(r.get("make", "-")), model=str(r.get("model", "-")), flags=list(flags)))
    return out


def _from_feed(url: str, key: str | None) -> list[RegistryRow]:
    if not url.startswith("https://"):
        raise ValueError("the registry feed must be an https address")
    req = urllib.request.Request(url, headers={"Accept": "application/json, text/csv", **({"Authorization": f"Bearer {key}"} if key else {})})
    with urllib.request.urlopen(req, timeout=FEED_TIMEOUT_S) as resp:        # noqa: S310 - https only, checked above
        raw = resp.read(MAX_FEED_BYTES + 1)
        if len(raw) > MAX_FEED_BYTES:
            raise ValueError("the registry feed is larger than 20 MB")
        text = raw.decode("utf-8-sig")
    if text.lstrip().startswith(("[", "{")):
        data = json.loads(text)
        return _rows(data["rows"] if isinstance(data, dict) else data)
    return _rows(csv.DictReader(io.StringIO(text)))


def _from_file(p: Path) -> list[RegistryRow]:
    with p.open(newline="", encoding="utf-8-sig") as fh:
        return _rows(csv.DictReader(fh))


_source = "not loaded"


def registry_source() -> str:
    """One plain sentence on where the rows came from, for screens and /api/health."""
    load_registry()
    return _source


@lru_cache
def load_registry(path: str | None = None) -> list[RegistryRow]:
    global _source
    if path:
        _source = f"file {Path(path).name}"
        return _from_file(Path(path))
    url = os.environ.get("EXLEX_REGISTRY_URL")
    if url:
        try:
            rows = _from_feed(url, os.environ.get("EXLEX_REGISTRY_KEY"))
            _source = "authorised feed"
            return rows
        except Exception as exc:  # noqa: BLE001 - a broken feed must not take the app down; say so and fall back
            _source = f"authorised feed failed ({type(exc).__name__}); using the local file"
    env = os.environ.get("EXLEX_REGISTRY")
    p = Path(env) if env else DEFAULT_REGISTRY
    if not url:
        same = lambda a, b: a.resolve() == b.resolve()
        _source = ("synthetic demo registry (not real data)" if same(p, SYNTHETIC_REGISTRY) else
                   "demo registry: random synthetic rows plus plates from the sample clip (not real data)" if same(p, DEMO_REGISTRY) else
                   "test registry built from the sample clip (not government data)" if same(p, TEST_REGISTRY) else "registry file you supplied")
    return _from_file(p)
