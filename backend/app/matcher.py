"""Registry matching, scoring and the refusal gate.

plate_fit  = sum(confidence of matched known slots) / PLATE_LEN, so fewer or
             weaker readable characters lower the score by design.
penalty    = sum(confidence of mismatched known slots) / PLATE_LEN.
score      = w_plate*plate_fit + w_colour*colour_fit + w_body*body_fit
             - mismatch_penalty*penalty, clamped to [0, 1].
Attribute weights are renormalised when colour or body evidence is absent.
The score is an uncalibrated confidence until tuned on held-out clips.
"""

from .config import DepartmentConfig
from .vision.attributes import NEAR_BODY
from .schemas import ABSENT, PLATE_LEN, Candidate, FusedPlate, MatchResult, RegistryRow, to_slots

SIMILAR_COLOURS = {
    frozenset(p)
    for p in [("white", "silver"), ("silver", "grey"), ("black", "grey"), ("red", "maroon")]
}
NEAR_COLOUR_CREDIT = 0.5
TOP_K = 5
LISTED_FLOOR = 0.25


def _colour_fit(row_colour: str, probs: dict[str, float]) -> float:
    fit = probs.get(row_colour, 0.0)
    for other, p in probs.items():
        if other != row_colour and frozenset((row_colour, other)) in SIMILAR_COLOURS:
            fit += NEAR_COLOUR_CREDIT * p
    return min(1.0, fit)


def _ranges(indices: list[int]) -> str:
    if not indices:
        return "none"
    nums = sorted(i + 1 for i in indices)
    parts, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(f"{start}-{prev}" if start != prev else f"{start}")
        start = prev = n
    parts.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ", ".join(parts)


def _score_row(row, fused, colour, body, cfg) -> Candidate | None:
    rp = to_slots(row.plate)
    if len(rp) != PLATE_LEN:
        return None   # a registry plate that does not fit the plate format cannot be compared position by position
    known = [s for s in fused.slots if s.char]
    matched = [s for s in known if rp[s.index] == s.char]
    mismatched = [s for s in known if rp[s.index] != s.char]
    if len(mismatched) > cfg.max_known_mismatches:
        return None

    plate_fit = sum(s.confidence for s in matched) / PLATE_LEN
    penalty = sum(s.confidence for s in mismatched) / PLATE_LEN

    w = cfg.weights
    wp, wc, wb = w.plate, (w.colour if colour else 0.0), (w.body if body else 0.0)
    norm = wp + wc + wb
    wp, wc, wb = wp / norm, wc / norm, wb / norm

    colour_fit = _colour_fit(row.colour, colour) if colour else 0.0
    body_fit = body.get(row.body_type, 0.0) if body else 0.0
    close_type = None
    if body:
        for other, credit in NEAR_BODY.get(row.body_type, {}).items():
            if body.get(other, 0.0) * credit > body_fit:
                body_fit, close_type = body[other] * credit, other

    score = wp * plate_fit + wc * colour_fit + wb * body_fit - w.mismatch_penalty * penalty
    score = max(0.0, min(1.0, score))

    unknown = [s.index for s in fused.slots if not s.char]
    shown = lambda ch: "no letter" if ch == ABSENT else f"'{ch}'"
    n_matched, n_known = sum(s.char != ABSENT for s in matched), sum(s.char != ABSENT for s in known)
    reasons = [
        f"Plate: {n_matched} of {n_known} readable characters agree (positions {_ranges([s.index for s in matched])}).",
    ]
    if mismatched:
        reasons.append(
            f"Mismatch at position {_ranges([s.index for s in mismatched])}: registry has "
            + ", ".join(f"{shown(rp[s.index])} where {shown(s.char)} was read" for s in mismatched)
            + "; score reduced."
        )
    if unknown:
        reasons.append(
            f"Positions {_ranges(unknown)} were unreadable and are marked unknown, not guessed."
        )
    if colour:
        top_c = max(colour, key=colour.get)
        verdict = "agrees with" if _colour_fit(row.colour, colour) >= 0.5 else "differs from"
        reasons.append(
            f"Colour: detected {top_c} (p={colour[top_c]:.2f}) {verdict} registered {row.colour}."
        )
    if body:
        top_b = max(body, key=body.get)
        verdict = "agrees with" if row.body_type == top_b else "differs from"
        reasons.append(
            f"Body type: detected {top_b} (p={body[top_b]:.2f}) {verdict} registered {row.body_type}."
            + (f" These two look alike on camera, so it earns half credit." if close_type and row.body_type != top_b else "")
        )
    if row.flags:
        reasons.append("Registry flags: " + ", ".join(row.flags) + ".")

    return Candidate(
        reg_id=row.reg_id,
        plate=row.plate,
        slots=rp,
        colour=row.colour,
        body_type=row.body_type,
        make=row.make,
        model=row.model,
        flags=row.flags,
        confidence=round(score, 4),
        components={
            "plate_fit": round(plate_fit, 4),
            "colour_fit": round(colour_fit, 4),
            "body_fit": round(body_fit, 4),
            "mismatch_penalty": round(penalty, 4),
        },
        matched_slots=[s.index for s in matched],
        mismatched_slots=[s.index for s in mismatched],
        unknown_slots=unknown,
        reasons=reasons,
    )


_INDEX: dict[tuple[int, int], tuple] = {}
PREFILTER_ABOVE = 5000      # a small registry is scored row by row; a large one is narrowed with numpy first


def _plate_matrix(registry):
    """Registry plates as a (rows, 10) array of character codes, built once per registry list. Rows whose plate is not ten slots are left out."""
    key = (id(registry), len(registry))
    if key not in _INDEX:
        import numpy as np

        keep, rows = [], []
        for i, r in enumerate(registry):
            p = to_slots(r.plate)
            if len(p) == PLATE_LEN:
                keep.append(i)
                rows.append(p.encode("ascii", "replace"))
        _INDEX.clear()                                   # one registry at a time is enough
        _INDEX[key] = (np.array(keep, dtype=np.int64), np.frombuffer(b"".join(rows), dtype=np.uint8).reshape(-1, PLATE_LEN))
    return _INDEX[key]


def _candidates(registry, fused, cfg):
    """Rows with at most cfg.max_known_mismatches clashes against the characters actually read. The same rule _score_row applies, just fast."""
    if len(registry) <= PREFILTER_ABOVE:
        return registry
    import numpy as np

    keep, mat = _plate_matrix(registry)
    known = [s for s in fused.slots if s.char]
    idx = np.array([s.index for s in known], dtype=np.int64)
    chars = np.array([ord(s.char) for s in known], dtype=np.uint8)
    clashes = (mat[:, idx] != chars).sum(axis=1)
    return [registry[i] for i in keep[clashes <= cfg.max_known_mismatches]]


def match_registry(
    fused: FusedPlate,
    colour: dict[str, float] | None,
    body: dict[str, float] | None,
    registry: list[RegistryRow],
    cfg: DepartmentConfig,
) -> MatchResult:
    base = dict(pattern=fused.pattern, fused=fused)

    if fused.known_count < cfg.min_known_chars:
        return MatchResult(
            status="insufficient_evidence",
            message=(
                f"Only {fused.known_count} of {PLATE_LEN} plate characters are readable; "
                f"{cfg.name} requires at least {cfg.min_known_chars}. No match attempted."
            ),
            candidates=[],
            **base,
        )

    scored = [c for row in _candidates(registry, fused, cfg) if (c := _score_row(row, fused, colour, body, cfg))]
    scored.sort(key=lambda c: (-c.confidence, -c.components["plate_fit"], c.reg_id))
    listed = [c for c in scored if c.confidence >= LISTED_FLOOR][:TOP_K]

    if not listed or listed[0].confidence < cfg.match_threshold:
        if listed:
            message = (f"No confident match: best score {listed[0].confidence:.2f} is below the "
                       f"{cfg.name} threshold of {cfg.match_threshold:.2f}.")
        else:
            message = "No confident match: no registry entry fits the readable characters closely enough."
        return MatchResult(
            status="no_confident_match",
            message=message,
            candidates=[],
            **base,
        )

    if len(listed) > 1 and listed[0].confidence - listed[1].confidence < cfg.ambiguity_margin:
        return MatchResult(
            status="ambiguous",
            message="Several registry entries fit about equally well; verify manually.",
            candidates=listed,
            **base,
        )

    return MatchResult(
        status="match",
        message=f"Top candidate {listed[0].plate} at confidence {listed[0].confidence:.2f}.",
        candidates=listed,
        **base,
    )
