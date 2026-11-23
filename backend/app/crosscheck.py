"""Cross-check a fused plate against an independent second reader.

A second reader that agrees is a strong sign (on synthetic plates the two readers were right about 98% of the time when they
agreed); one that disagrees is a reason for a person to look. It never overrides the fused plate and never fills in an unknown
position: it only adds a verdict. The second reader's text is aligned to the same ten slots as the first, so a plate with a
different length is compared fairly instead of being shifted.
"""

from __future__ import annotations

from collections import Counter

from .schemas import FusedPlate, SecondReading

MIN_AGREE = 4  # known characters that must agree before we call it agreement


def cross_check(fused: FusedPlate, reading: str, reader: str) -> SecondReading:
    from .vision.plate_text import align_to_slots  # local import: plate_text imports fusion

    reading = "".join(c for c in reading.upper() if c.isalnum() and c.isascii())
    if not reading or fused.known_count == 0:
        return SecondReading(reader=reader, reading=reading, verdict="inconclusive", agree=0, clash=0)
    other = align_to_slots([(c, 1.0) for c in reading])
    agree = clash = 0
    for mine, theirs in zip(fused.slots, other):
        if mine.char and theirs is not None:
            if mine.char == theirs.char:
                agree += 1
            else:
                clash += 1
    if clash:
        verdict = "disagrees"
    elif agree >= min(MIN_AGREE, fused.known_count):
        verdict = "agrees"
    else:
        verdict = "inconclusive"
    return SecondReading(reader=reader, reading=reading, verdict=verdict, agree=agree, clash=clash)


def pick_reading(readings: list[str]) -> str:
    """The most common non-empty reading across a vehicle's sharpest plate crops; ties go to the first (sharpest)."""
    counts = Counter(r for r in readings if r)
    if not counts:
        return ""
    best = max(counts.values())
    return next(r for r in readings if r and counts[r] == best)
