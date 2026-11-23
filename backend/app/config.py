from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

CONFIG_PATH = Path(__file__).parent / "departments.yaml"


class Weights(BaseModel):
    plate: float
    colour: float
    body: float
    mismatch_penalty: float


class DepartmentConfig(BaseModel):
    id: str
    name: str
    min_known_chars: int
    match_threshold: float
    ambiguity_margin: float
    max_known_mismatches: int
    slot_accept: float
    weights: Weights


@lru_cache
def load_departments() -> dict[str, DepartmentConfig]:
    raw = yaml.safe_load(CONFIG_PATH.read_text())["departments"]
    return {k: DepartmentConfig(id=k, **v) for k, v in raw.items()}


def get_department(dept_id: str) -> DepartmentConfig:
    depts = load_departments()
    if dept_id not in depts:
        raise KeyError(f"unknown department '{dept_id}'; expected one of {sorted(depts)}")
    return depts[dept_id]
