"""Build data/registry_demo.csv: a DEMO registry for showing how matching works. It is not real vehicle data.

Rows: the 300 random synthetic rows (make_registry.py), the plates the system read in the stored sample-clip analyses (make_clip_registry.py;
make and model "-"), and plates the team typed in by hand after looking at a plate crop (HAND_ENTERED below). The last two groups are built from
the sample clip itself, so a match against them shows the matching and the reasons work, not that the system is accurate.
Usage: python scripts/make_demo_registry.py
"""
import csv
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "registry_demo.csv"
# plate, colour, body_type: read by eye from a plate crop in the sample clip (Kolkata car, vehicle 44); the system itself read it as ??08A-8292
HAND_ENTERED = [("WB06A8292", "grey", "car")]


def main() -> None:
    rows = list(csv.DictReader((DATA / "registry.csv").open(newline="")))
    seen = {r["plate"] for r in rows}
    clip = DATA / "registry_clip_test.csv"
    if clip.exists():
        for r in csv.DictReader(clip.open(newline="")):
            if r["plate"] not in seen:
                rows.append(r)
                seen.add(r["plate"])
    for i, (plate, colour, body) in enumerate(HAND_ENTERED, 1):
        if plate not in seen:
            rows.append({"reg_id": f"HAND{i:04d}", "plate": plate, "colour": colour, "body_type": body, "make": "-", "model": "-", "flags": ""})
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["reg_id", "plate", "colour", "body_type", "make", "model", "flags"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
