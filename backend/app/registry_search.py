"""Officer search of the registry by partial plate, colour, body type and make.

It is a lookup tool, not a match: it lists registry rows that fit what the officer typed and says why. A plate with unknown characters
(?) matches anything in those positions; a character that is known must agree. The demo registry is synthetic.
"""

from __future__ import annotations

import re

from .schemas import ABSENT, PLATE_LEN, RegistryRow, to_slots
from .watchlist import compare

MIN_KNOWN = 3


def clean_query(text: str) -> str | None:
    """The query as ten slots (shorter ones are padded with unknowns on the right), or None when there is no plate."""
    t = re.sub(r"[^A-Z0-9?]", "", text.upper())
    if not t:
        return None
    slots = to_slots(t) if "?" not in t else t
    if len(slots) > PLATE_LEN:
        raise ValueError("A plate has at most 10 characters.")
    if sum(c not in "?-" for c in slots) < MIN_KNOWN:
        raise ValueError(f"Give at least {MIN_KNOWN} known characters, or the list would be most of the registry.")
    return slots.ljust(PLATE_LEN, "?")


def search(rows: list[RegistryRow], plate: str = "", colour: str = "", body_type: str = "", make: str = "", limit: int = 50) -> dict:
    q = clean_query(plate)
    colour, body_type, make = colour.strip().lower(), body_type.strip().lower(), make.strip().lower()
    if not (q or colour or body_type or make):
        raise ValueError("Give a plate, a colour, a body type or a make to search for.")
    out = []
    for r in rows:
        reasons, score = [], 0
        if q:
            agree, clash = compare(q, to_slots(r.plate).ljust(PLATE_LEN, "?"))
            if clash or agree < min(MIN_KNOWN, sum(c not in "?-" for c in q)):
                continue
            known = sum(c not in "?-" for c in q)
            reasons.append(f"Plate: all {known} typed characters agree" + ("" if known == PLATE_LEN else f", the other {PLATE_LEN - known} positions were left open"))
            score += agree
        if colour:
            if r.colour.lower() != colour:
                continue
            reasons.append(f"Colour is {r.colour}")
        if body_type:
            if r.body_type.lower() != body_type:
                continue
            reasons.append(f"Body type is {r.body_type.replace('_', ' ')}")
        if make:
            if make not in f"{r.make} {r.model}".lower():
                continue
            reasons.append(f"Make or model contains '{make}'")
        out.append({"reg_id": r.reg_id, "plate": r.plate, "colour": r.colour, "body_type": r.body_type, "make": r.make, "model": r.model,
                    "flags": r.flags, "reasons": reasons, "_score": score})
    out.sort(key=lambda x: (-x["_score"], x["plate"]))
    total = len(out)
    for x in out:
        x.pop("_score")
    return {"total": total, "shown": min(total, limit), "results": out[:limit]}


def facets(rows: list[RegistryRow]) -> dict:
    return {"colours": sorted({r.colour for r in rows}), "body_types": sorted({r.body_type for r in rows}), "rows": len(rows)}
