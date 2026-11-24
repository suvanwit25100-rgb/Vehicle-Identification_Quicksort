"""RTO code check: the first characters of a plate (state letters, district number) against the public list of RTO codes.

Data: data/rto_codes.json, built by scripts/make_rto_codes.py from Wikipedia's "List of Regional Transport Office districts in India"
(CC BY-SA 4.0, volunteer-edited, can be out of date). It is a region lookup. It holds no vehicle or owner data, and a match here says the plate
starts with a real code for a place; it does not say the vehicle is registered or whose it is.

Confidence = average confidence of the characters used for the code (state letters plus district digits), straight from the reader.
"""
import json
from functools import lru_cache
from pathlib import Path

from .schemas import AnalysisResult

TABLE = Path(__file__).resolve().parent.parent / "data" / "rto_codes.json"


@lru_cache
def _table() -> dict:
    return json.loads(TABLE.read_text(encoding="utf-8"))


def source() -> str:
    return _table()["source"]


def check(fused) -> dict:
    slots = fused.slots
    s = lambda i: slots[i] if slots[i].char and slots[i].char != "-" else None
    state_slots = [s(0), s(1)]
    d1, d2 = s(2), slots[3]
    if not all(state_slots):
        return {"status": "unreadable", "message": "The state letters were not both readable, so the RTO code cannot be checked."}
    state = state_slots[0].char + state_slots[1].char
    used = state_slots[:]
    if d1 is None or not d1.char.isdigit():
        return {"status": "unreadable", "state_code": state, "message": f"The district number after {state} was not readable, so the RTO code cannot be checked."}
    used.append(d1)
    if d2.char is None:
        return {"status": "unreadable", "state_code": state, "message": f"The second district character after {state}{d1.char} was not readable (it could be a digit or the series letter), so the RTO code cannot be checked."}
    district = d1.char
    if d2.char.isdigit():
        district += d2.char
        used.append(d2)
    conf = round(sum(x.confidence for x in used) / len(used), 4)
    entry = _table()["states"].get(state)
    code = f"{state}-{district.zfill(2)}"
    if entry is None:
        return {"status": "unknown_code", "code": code, "confidence": None, "chars_used": len(used),
                "message": f"{state} is not a state or territory code in the list, so one of those letters may be misread."}
    row = entry["codes"].get(district.zfill(2))
    if row is None:
        return {"status": "unknown_code", "code": code, "state": entry["name"], "confidence": None, "chars_used": len(used),
                "message": f"{code} is not in the list of {entry['name']} RTO codes, so a character may be misread (or the list is out of date)."}
    return {"status": "match", "code": code, "state": entry["name"], "office": row["office"], "area": row["area"], "confidence": conf, "chars_used": len(used),
            "message": f"{code} is a real RTO code: {entry['name']}, {row['area']} ({row['office']}). Average reader confidence over its {len(used)} characters."}


def attach(result: AnalysisResult) -> AnalysisResult:
    for t in result.tracks:
        if t.match is not None and t.frame_reads:
            t.rto = check(t.match.fused)
    return result
