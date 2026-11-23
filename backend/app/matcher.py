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
from .schemas import PLATE_LEN, Candidate, FusedPlate, MatchResult, RegistryRow

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
    known = [s for s in fused.slots if s.char]
    matched = [s for s in known if row.plate[s.index] == s.char]
    mismatched = [s for s in known if row.plate[s.index] != s.char]
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

    score = wp * plate_fit + wc * colour_fit + wb * body_fit - w.mismatch_penalty * penalty
    score = max(0.0, min(1.0, score))

    unknown = [s.index for s in fused.slots if not s.char]
    reasons = [
        f"Plate: {len(matched)} of {len(known)} readable characters agree (positions {_ranges([s.index for s in matched])}).",
    ]
    if mismatched:
        reasons.append(
            f"Mismatch at position {_ranges([s.index for s in mismatched])}: registry has "
            + ", ".join(f"'{row.plate[s.index]}' where '{s.char}' was read" for s in mismatched)
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
        )
    if row.flags:
        reasons.append("Registry flags: " + ", ".join(row.flags) + ".")

    return Candidate(
        reg_id=row.reg_id,
        plate=row.plate,
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

    scored = [c for row in registry if (c := _score_row(row, fused, colour, body, cfg))]
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
