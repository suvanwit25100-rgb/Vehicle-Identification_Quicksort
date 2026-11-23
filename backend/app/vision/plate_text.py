"""Map an OCR character string onto the fixed 10 plate slots.

Never guesses: a read that cannot be placed with certainty leaves its slots
as None (unknown). Format: SS DD LL NNNN, with older series of 1-3 letters
and 1-4 digits tolerated only when the layout makes the placement certain.

An extra or missing character at the edge of a read shifts every slot after it.
Such a read is slid against the format and re-placed only when one offset fits
clearly better than all others; ties and weak fits are left as they were.
"""

import re

from app.fusion import DIGITS, LETTERS, SLOT_KINDS
from app.schemas import ABSENT, ABSENT_SLOT, PLATE_LEN, CharRead

SHAPE = re.compile(r"^([A-Z]{2})(\d[0-9A-Z])([A-Z]{1,3})(\d{1,4})$")
MAX_SHIFT = 3
MIN_SHIFT_GAIN = 2
MIN_PLACED_WHEN_LENGTH_OFF = 8
ABSENT_DISCOUNT = 0.9   # the marker is inferred from the layout, so it is slightly less certain than the letter that implies it


def _fits(ch: str, kind: str) -> bool:
    return True if kind == "A" else ch in (LETTERS if kind == "L" else DIGITS)


def _fit(text: str, offset: int) -> tuple[int, int]:
    """(score, incompatible) for placing text[i] at slot i + offset."""
    good = bad = 0
    for i, ch in enumerate(text):
        j = i + offset
        if 0 <= j < PLATE_LEN:
            if _fits(ch, SLOT_KINDS[j]):
                good += 1
            else:
                bad += 1
    return good - bad, bad


def best_offset(text: str) -> int | None:
    """Offset that clearly fits the plate format best, or None if there isn't one."""
    n = len(text)
    fits = {o: _fit(text, o) for o in range(-MAX_SHIFT, MAX_SHIFT + 1)}
    ranked = sorted(fits, key=lambda o: fits[o][0], reverse=True)
    best, runner = ranked[0], ranked[1]
    unique = fits[best][0] > fits[runner][0]
    if n == PLATE_LEN:
        if best != 0 and unique and fits[best][0] >= fits[0][0] + MIN_SHIFT_GAIN:
            return best
        return 0
    placed = sum(0 <= i + best < PLATE_LEN for i in range(n))
    if unique and fits[best][1] == 0 and placed >= MIN_PLACED_WHEN_LENGTH_OFF:
        return best
    return None


def _place_at(chars: list[tuple[str, float]], offset: int) -> list[CharRead | None]:
    slots: list[CharRead | None] = [None] * PLATE_LEN
    for i, (c, conf) in enumerate(chars):
        j = i + offset
        if 0 <= j < PLATE_LEN:
            slots[j] = CharRead(char=c, conf=min(1.0, max(0.0, conf)))
    return slots


def align_to_slots(chars: list[tuple[str, float]]) -> list[CharRead | None]:
    chars = [(c.upper(), conf) for c, conf in chars if c.isalnum() and c.isascii()]
    text = "".join(c for c, _ in chars)

    if len(chars) == PLATE_LEN:
        return _place_at(chars, best_offset(text) or 0)

    m = SHAPE.match(text)
    if not m:
        offset = best_offset(text) if len(chars) in (PLATE_LEN - 1, PLATE_LEN + 1) else None
        return _place_at(chars, offset) if offset is not None else [None] * PLATE_LEN

    slots: list[CharRead | None] = [None] * PLATE_LEN
    state, rto, series, number = m.groups()
    pos = 0

    def place(start_slot: int, n: int, certain: bool):
        nonlocal pos
        if certain:
            for k in range(n):
                c, conf = chars[pos + k]
                slots[start_slot + k] = CharRead(char=c, conf=min(1.0, max(0.0, conf)))
        pos += n

    place(0, 2, True)
    place(2, 2, True)
    if len(series) == 1 and len(number) == 4:
        # nine characters: the single series letter takes the first series slot and the second is marked absent
        c, conf = chars[pos]
        conf = min(1.0, max(0.0, conf))
        slots[4] = CharRead(char=c, conf=conf)
        slots[ABSENT_SLOT] = CharRead(char=ABSENT, conf=conf * ABSENT_DISCOUNT)
        pos += 1
    else:
        place(4, len(series), len(series) == 2)
    place(6, len(number), len(number) == 4)
    return slots
