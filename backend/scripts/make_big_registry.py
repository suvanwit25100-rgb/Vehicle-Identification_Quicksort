"""Generate a LARGE SYNTHETIC registry (default 500,000 rows) for load and demo. Every row is random: not real vehicles, not real owners.

Plates use real RTO codes from data/rto_codes.json (so the first four characters look right), one or two series letters and four digits.
The demo rows (the 300 random rows, plates read from the sample clip, one hand-typed plate) come first, so the clip still matches.
Output: data/registry_500k.csv (about 35 MB, not committed; regenerate with this script, it is deterministic).
Usage: python scripts/make_big_registry.py [N]
"""
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_registry import BODY_WEIGHTS, VEHICLES, make_flags  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "registry_500k.csv"
SEED = 2026
LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"
STATE_WEIGHT = 1.0


def main(n: int) -> None:
    rto = json.loads((DATA / "rto_codes.json").read_text(encoding="utf-8"))["states"]
    choices = [(st, num) for st, v in rto.items() for num in v["codes"]]        # a state with more offices gets proportionally more vehicles
    rng = random.Random(SEED)
    rows, seen = [], set()
    demo = DATA / "registry_demo.csv"
    if demo.exists():
        for r in csv.DictReader(demo.open(newline="")):
            rows.append([r["plate"], r["colour"], r["body_type"], r["make"], r["model"], r["flags"]])
            seen.add(r["plate"])
    bodies, weights = list(BODY_WEIGHTS), list(BODY_WEIGHTS.values())
    while len(rows) < n:
        st, num = rng.choice(choices)
        series = "".join(rng.choice(LETTERS) for _ in range(1 if rng.random() < 0.08 else 2))
        plate = f"{st}{num}{series}{rng.randint(1000, 9999)}"
        if plate in seen:
            continue
        seen.add(plate)
        body = rng.choices(bodies, weights=weights)[0]
        models, colours = VEHICLES[body]
        make, _, model = rng.choice(models).partition(" ")
        rows.append([plate, rng.choice(colours), body, make, model, make_flags(rng)])
    with OUT.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["reg_id", "plate", "colour", "body_type", "make", "model", "flags"])
        for i, r in enumerate(rows, 1):
            w.writerow([f"SYN{i:06d}", *r])
    print(f"wrote {len(rows):,} rows to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 500_000)
