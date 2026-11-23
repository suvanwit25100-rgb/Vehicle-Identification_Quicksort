"""Merge fragments of one vehicle using the plate as the identity signal.

Two tracks are the same vehicle only if their fused plates agree on enough
characters and clash on none. A single clash blocks the merge, and a group is
only grown when every member is compatible with every other member.
"""

MIN_AGREE = 6


def agreement(a: str, b: str) -> tuple[int, int]:
    """(characters both tracks know and agree on, characters both know and disagree on)."""
    agree = sum(x == y and x != "?" for x, y in zip(a, b))
    clash = sum(x != y and "?" not in (x, y) for x, y in zip(a, b))
    return agree, clash


def compatible(a: str, b: str, min_agree: int = MIN_AGREE) -> bool:
    agree, clash = agreement(a, b)
    return clash == 0 and agree >= min_agree


def group_tracks(patterns: dict[int, str], min_agree: int = MIN_AGREE) -> list[list[int]]:
    groups = [[t] for t in sorted(patterns)]
    merged = True
    while merged:
        merged = False
        best = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                pairs = [(patterns[a], patterns[b]) for a in groups[i] for b in groups[j]]
                if all(compatible(pa, pb, min_agree) for pa, pb in pairs):
                    score = min(agreement(pa, pb)[0] for pa, pb in pairs)
                    if best is None or score > best[0]:
                        best = (score, i, j)
        if best:
            _, i, j = best
            groups[i] = sorted(groups[i] + groups[j])
            del groups[j]
            merged = True
    return groups
