"""Build data/registry_500k.csv (500,000 rows) from the Kaggle "Indian Vehicle Registration Data (2020-25)" statistics. SYNTHETIC registry.

What is real: the mix of state, RTO, maker, model and vehicle class (rows are drawn in proportion to the dataset's vehicleCount).
What is made up: every plate (random series letters and digits after the real RTO code), the colour (the dataset has none), the flags, and which
vehicle is which. Nothing here identifies a real vehicle or person. The demo rows (clip plates and the 300 random rows) come first so the clip still matches.
Attribution: see data/source/ATTRIBUTION.md (CC BY 4.0).
Usage: python scripts/make_registry_from_kaggle.py [N]
"""
import csv
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_registry import make_flags  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
SRC = DATA / "source" / "vehicle_registrations_500k.csv"
OUT = DATA / "registry_500k.csv"
LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"
STATE_FIX = {"OR": "OD"}                      # the dataset still says OR for Odisha; plates say OD
SUV_WORDS = ("CRETA", "SCORPIO", "XUV", "NEXON", "FORTUNER", "BREZZA", "SELTOS", "SONET", "VENUE", "HARRIER", "SAFARI", "THAR", "PUNCH", "INNOVA", "ERTIGA",
             "BOLERO", "KUSHAQ", "TAIGUN", "HECTOR", "GLOSTER", "ALCAZAR", "EXTER", "JIMNY", "GRAND VITARA", "HYRYDER", "URBAN CRUISER", "KICKS", "COMPASS", "TUCSON",
             "ENDEAVOUR", "ECOSPORT", "DUSTER", "KIGER", "MAGNITE", "CARENS", "XL6", "TRIBER", "FRONX", "ECOSPORT", "SUMO", "MARAZZO", "XEV", "ZS EV", "NEXON EV")
COLOURS = {"car": ["white", "silver", "grey", "black", "red", "blue", "maroon"], "suv": ["white", "black", "silver", "grey", "red", "brown"],
           "two_wheeler": ["black", "red", "blue", "grey", "silver"], "auto_rickshaw": ["yellow", "green"], "tempo": ["white", "blue", "silver"],
           "truck": ["blue", "red", "green", "white", "yellow"], "bus": ["white", "yellow", "red"], "tractor": ["red", "blue"]}


def body_of(cls: str, category: str, model: str) -> str | None:
    c, cat, m = cls.lower(), category.upper(), model.upper()
    if c in ("m-cycle/scooter", "moped", "motorised cycle (cc > 25cc)"):
        return "two_wheeler"
    if c in ("three wheeler (passenger)", "e-rickshaw(p)", "three wheeler (goods)", "e-rickshaw with cart (g)"):
        return "auto_rickshaw" if "passenger" in c or "(p)" in c else "tempo"
    if c in ("motor car", "motor cab"):
        return "suv" if any(w in m for w in SUV_WORDS) else "car"
    if c == "bus":
        return "bus"
    if c in ("agricultural tractor", "tractor (commercial)"):
        return "tractor"
    if c == "goods carrier":
        return "tempo" if "LIGHT" in cat else "truck"
    return None


def main(n: int) -> None:
    rows, weights = [], []
    skipped = Counter()
    for r in csv.DictReader(SRC.open(newline="", encoding="utf-8-sig")):
        m = re.fullmatch(r"([A-Z]{2})(\d{1,3})", r["rtoCode"])
        body = body_of(r["vehicleClassName"], r["vehicleCategoryName"], r["vehicleModelName"])
        if not m or body is None:
            skipped[r["vehicleClassName"] if m else "bad rto code"] += 1
            continue
        make = " ".join(w.capitalize() for w in r["makerName"].replace(" LTD", "").replace(" PVT", "").replace(" LIMITED", "").replace(" PRIVATE", "").split()[:3])
        rows.append((STATE_FIX.get(m.group(1), m.group(1)) + m.group(2).zfill(2), body, make or "-", r["vehicleModelName"].title()[:40] or "-"))
        weights.append(max(1, int(float(r["vehicleCount"] or 1))))
    rng = random.Random(2026)
    out, seen = [], set()
    demo = DATA / "registry_demo.csv"
    if demo.exists():
        for r in csv.DictReader(demo.open(newline="")):
            out.append([r["plate"], r["colour"], r["body_type"], r["make"], r["model"], r["flags"]])
            seen.add(r["plate"])
    picks = rng.choices(range(len(rows)), weights=weights, k=n)        # in proportion to how many vehicles each row stands for
    for i in picks:
        if len(out) >= n:
            break
        code, body, make, model = rows[i]
        while True:
            series = "".join(rng.choice(LETTERS) for _ in range(1 if rng.random() < 0.08 else 2))
            plate = f"{code}{series}{rng.randint(1000, 9999)}"
            if plate not in seen:
                break
        seen.add(plate)
        out.append([plate, rng.choice(COLOURS[body]), body, make, model, make_flags(rng)])
    while len(out) < n:                                                # rare: the picks ran short because of skipped rows
        code, body, make, model = rows[rng.randrange(len(rows))]
        plate = f"{code}{''.join(rng.choice(LETTERS) for _ in range(2))}{rng.randint(1000, 9999)}"
        if plate not in seen:
            seen.add(plate)
            out.append([plate, rng.choice(COLOURS[body]), body, make, model, make_flags(rng)])
    with OUT.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["reg_id", "plate", "colour", "body_type", "make", "model", "flags"])
        for i, r in enumerate(out, 1):
            w.writerow([f"SYN{i:06d}", *r])
    print(f"wrote {len(out):,} rows to {OUT}; dropped {sum(skipped.values()):,} source rows with no matching body type: {dict(skipped.most_common(5))}", file=sys.stderr)
    print("body mix:", dict(Counter(r[2] for r in out).most_common()), file=sys.stderr)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 500_000)
