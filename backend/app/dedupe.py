"""Group reports that are about the same vehicle: the same plate, filed close together in time.

Two reports are related when their plates cannot be told apart (no clash, at least MIN_AGREE characters agree; unknown characters count for
neither side) and they were filed within WINDOW_HOURS of each other. Several citizens reporting one incident then show up as one case.
"""

from __future__ import annotations

from datetime import datetime

from .schemas import to_slots
from .watchlist import compare

MIN_AGREE = 7
WINDOW_HOURS = 24


def plate_slots(row) -> str | None:
    """The best plate we have for a report in ten slots: what the citizen typed if it fits the format, else the system read."""
    typed = "".join((row["plate_confirmed"] or "").upper().split())
    cand = to_slots(typed) if typed else ""
    if len(cand) != 10:
        cand = row["plate_read"] or ""
    if len(cand) != 10 or sum(c not in "?-" for c in cand) < MIN_AGREE:
        return None
    return cand


def _when(row) -> datetime | None:
    try:
        return datetime.fromisoformat(row["created_at"])
    except (TypeError, ValueError):
        return None


def related_map(rows) -> dict[str, list[str]]:
    """report id -> ids of the other reports about the same vehicle in the same window."""
    items = [(r["id"], plate_slots(r), _when(r)) for r in rows]
    items = [(i, p, t) for i, p, t in items if p and t]
    out: dict[str, list[str]] = {}
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            (ia, pa, ta), (ib, pb, tb) = items[a], items[b]
            if abs((ta - tb).total_seconds()) > WINDOW_HOURS * 3600:
                continue
            agree, clash = compare(pa, pb)
            if not clash and agree >= MIN_AGREE:
                out.setdefault(ia, []).append(ib)
                out.setdefault(ib, []).append(ia)
    return out
