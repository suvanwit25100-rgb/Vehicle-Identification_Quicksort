"""Multi-frame character fusion.

Each plate slot collects confidence-weighted votes from every frame. An
"unknown" pseudo-vote (unknown_prior) sits in the denominator, so thin or
low-quality evidence cannot reach the acceptance bar. A slot that fails the
confidence or margin test stays unknown; its best guesses are kept only as
labelled alternatives for the report, never as the answer.
"""

from .schemas import ABSENT, ABSENT_SLOT, PLATE_LEN, FrameRead, FusedPlate, SlotResult

# Indian format: state(2 letters) RTO(digit + digit-or-letter, e.g. DL 1L, DL 8C) series(2 letters) number(4 digits).
# Kind "A" accepts either class and is never corrected.
SLOT_KINDS = "LLDALLDDDD"
assert len(SLOT_KINDS) == PLATE_LEN

LETTERS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
DIGITS = set("0123456789")
LETTER_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"}
DIGIT_TO_LETTER = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G"}
COERCE_DISCOUNT = 0.8


def _coerce(ch: str, kind: str, index: int = -1) -> tuple[str | None, bool]:
    ch = ch.upper()
    if ch == ABSENT:
        return (ABSENT, False) if index == ABSENT_SLOT else (None, False)
    if kind == "A":
        return (ch, False) if ch in LETTERS or ch in DIGITS else (None, False)
    if kind == "L":
        if ch in LETTERS:
            return ch, False
        if ch in DIGIT_TO_LETTER:
            return DIGIT_TO_LETTER[ch], True
    else:
        if ch in DIGITS:
            return ch, False
        if ch in LETTER_TO_DIGIT:
            return LETTER_TO_DIGIT[ch], True
    return None, False


def _frame_weights(frames: list[FrameRead]) -> dict[int, float]:
    max_sharp = max((f.sharpness for f in frames), default=0.0)
    max_area = max((f.plate_area for f in frames), default=0.0)
    out = {}
    for f in frames:
        s = max(0.1, f.sharpness / max_sharp) if max_sharp > 0 else 1.0
        a = max(0.1, f.plate_area / max_area) if max_area > 0 else 1.0
        out[f.frame_id] = s * a
    return out


def _decide(index, votes, support, slot_accept, slot_margin, unknown_prior) -> SlotResult:
    if not votes:
        return SlotResult(index=index, char=None, confidence=0.0)
    total = sum(votes.values()) + unknown_prior
    ranked = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)
    top_ch, top_w = ranked[0]
    second_w = ranked[1][1] if len(ranked) > 1 else 0.0
    conf = top_w / total
    margin = (top_w - second_w) / total
    alternatives = {c: round(w / total, 4) for c, w in ranked[:3]}
    if conf >= slot_accept and margin >= slot_margin:
        return SlotResult(
            index=index,
            char=top_ch,
            confidence=round(conf, 4),
            support_frames=sorted(support[top_ch]),
            alternatives=alternatives,
        )
    return SlotResult(index=index, char=None, confidence=round(conf, 4), alternatives=alternatives)


def fuse_frames(
    frames: list[FrameRead],
    *,
    slot_accept: float = 0.60,
    slot_margin: float = 0.25,
    unknown_prior: float = 0.30,
) -> FusedPlate:
    weights = _frame_weights(frames)
    slots = []
    for i, kind in enumerate(SLOT_KINDS):
        votes: dict[str, float] = {}
        support: dict[str, list[int]] = {}
        for f in frames:
            read = f.chars[i]
            if read is None:
                continue
            ch, coerced = _coerce(read.char, kind, i)
            if ch is None:
                continue
            w = read.conf * weights[f.frame_id] * (COERCE_DISCOUNT if coerced else 1.0)
            votes[ch] = votes.get(ch, 0.0) + w
            support.setdefault(ch, []).append(f.frame_id)
        slots.append(_decide(i, votes, support, slot_accept, slot_margin, unknown_prior))
    return FusedPlate(slots=slots)
