"""Build a small TEST registry from plates the system read in the stored sample-clip analyses.

This is not government data and not a real vehicle register. It exists so a demo can show a real read
being matched, with reasons. Colour and body type come from the same detector, so a match here proves the
plumbing, not accuracy. Every screen that lists registry data says so. Make and model are unknown ("-").
Usage: python scripts/make_clip_registry.py   (writes data/registry_clip_test.csv)
"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "registry_clip_test.csv"


def hamming(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b))


def main() -> None:
    seen, colour, body = Counter(), defaultdict(Counter), defaultdict(Counter)
    for f in DATA.glob("jobs/*/result.json"):
        for t in json.loads(f.read_text()).get("tracks", []):
            m = t.get("match")
            if not m or not t.get("frame_reads"):
                continue
            slots = [s["char"] for s in m["fused"]["slots"]]
            if any(c is None for c in slots):
                continue                                   # only fully read plates: nothing guessed
            plate = "".join(c for c in slots if c != "-")
            seen[plate] += 1
            for name, dist in (("c", t.get("colour")), ("b", t.get("body_type"))):
                if dist:
                    (colour if name == "c" else body)[plate][max(dist, key=dist.get)] += 1
    rows = []
    for plate, _n in seen.most_common():
        if any(hamming(plate, r[1]) <= 1 for r in rows):   # a one-character variant is the same vehicle misread
            continue
        rows.append((f"TEST{len(rows) + 1:04d}", plate, colour[plate].most_common(1)[0][0] if colour[plate] else "grey",
                     body[plate].most_common(1)[0][0] if body[plate] else "car", "-", "-", ""))
    with OUT.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["reg_id", "plate", "colour", "body_type", "make", "model", "flags"])
        w.writerows(rows)
    print(f"wrote {len(rows)} test rows to {OUT}")


if __name__ == "__main__":
    main()
