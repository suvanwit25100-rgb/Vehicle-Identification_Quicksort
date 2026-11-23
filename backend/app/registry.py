import csv
from functools import lru_cache
from pathlib import Path

from .schemas import RegistryRow

DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "data" / "registry.csv"


@lru_cache
def load_registry(path: str | None = None) -> list[RegistryRow]:
    p = Path(path) if path else DEFAULT_REGISTRY
    with p.open(newline="") as fh:
        return [
            RegistryRow(**{**r, "flags": [f for f in r["flags"].split(";") if f]})
            for r in csv.DictReader(fh)
        ]
