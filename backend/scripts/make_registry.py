"""Generate a deterministic synthetic vehicle registry for development and demos.

Includes deliberate near-duplicate plates (one digit apart) so the ambiguity
path gets exercised, and a few flagged rows (stolen, expired documents).
"""

import csv
import random
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "registry.csv"
SEED = 42
N_ROWS = 300
N_NEAR_DUPLICATES = 12

STATES = {"CG": (1, 30), "MH": (1, 50), "DL": (1, 14), "UP": (10, 85), "KA": (1, 60),
          "WB": (1, 90), "BR": (1, 50), "RJ": (1, 45), "MP": (1, 70), "OD": (1, 35)}
SERIES_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"

VEHICLES = {
    "car": (["Maruti Swift", "Maruti Dzire", "Maruti Baleno", "Hyundai i20", "Hyundai Verna",
             "Honda City", "Tata Tiago"],
            ["white", "silver", "grey", "black", "red", "blue", "maroon"]),
    "suv": (["Mahindra Scorpio", "Mahindra XUV700", "Tata Nexon", "Hyundai Creta", "Toyota Fortuner"],
            ["white", "black", "silver", "grey", "red", "brown"]),
    "two_wheeler": (["Hero Splendor", "Honda Activa", "Bajaj Pulsar", "TVS Apache", "Royal Enfield Classic"],
                    ["black", "red", "blue", "grey", "silver"]),
    "auto_rickshaw": (["Bajaj RE", "Piaggio Ape"], ["yellow", "green"]),
    "truck": (["Ashok Leyland 1616", "Eicher Pro", "BharatBenz 2823"],
              ["blue", "red", "green", "white", "yellow"]),
    "tempo": (["Tata Ace", "Mahindra Bolero Pickup"], ["white", "blue", "silver"]),
    "bus": (["Tata Starbus", "Ashok Leyland Viking"], ["white", "yellow", "red"]),
    "tractor": (["Mahindra 575", "Sonalika DI 750"], ["red", "blue"]),
}
BODY_WEIGHTS = {"car": 30, "suv": 18, "two_wheeler": 26, "auto_rickshaw": 8,
                "truck": 8, "tempo": 5, "bus": 3, "tractor": 2}


def make_plate(rng: random.Random) -> str:
    state = rng.choice(list(STATES))
    lo, hi = STATES[state]
    series = "".join(rng.choice(SERIES_LETTERS) for _ in range(2))
    rto = f"{rng.randint(lo, hi):02d}"
    if state == "DL" and rng.random() < 0.5:
        rto = f"{rng.randint(1, 9)}{rng.choice('CLSPAT')}"  # Delhi zones, e.g. DL 1L, DL 8C
    return f"{state}{rto}{series}{rng.randint(1000, 9999)}"


def make_flags(rng: random.Random) -> str:
    flags = []
    if rng.random() < 0.03:
        flags.append("stolen")
    if rng.random() < 0.08:
        flags.append("insurance_expired")
    if rng.random() < 0.10:
        flags.append("puc_expired")
    return ";".join(flags)


def make_vehicle(rng: random.Random) -> tuple[str, str, str, str]:
    body = rng.choices(list(BODY_WEIGHTS), weights=list(BODY_WEIGHTS.values()))[0]
    models, colours = VEHICLES[body]
    make_model = rng.choice(models)
    make, _, model = make_model.partition(" ")
    return body, rng.choice(colours), make, model


def main() -> None:
    rng = random.Random(SEED)
    rows, seen = [], set()
    while len(rows) < N_ROWS - N_NEAR_DUPLICATES:
        plate = make_plate(rng)
        if plate in seen:
            continue
        seen.add(plate)
        body, colour, make, model = make_vehicle(rng)
        rows.append({"plate": plate, "colour": colour, "body_type": body,
                     "make": make, "model": model, "flags": make_flags(rng)})

    for _ in range(N_NEAR_DUPLICATES):
        base = rng.choice(rows)
        pos = rng.choice([6, 7, 8, 9])
        digit = rng.choice([d for d in "0123456789" if d != base["plate"][pos]])
        plate = base["plate"][:pos] + digit + base["plate"][pos + 1:]
        if plate in seen:
            continue
        seen.add(plate)
        if rng.random() < 0.5:
            body, colour, make, model = make_vehicle(rng)
        else:
            body, colour, make, model = base["body_type"], base["colour"], base["make"], base["model"]
        rows.append({"plate": plate, "colour": colour, "body_type": body,
                     "make": make, "model": model, "flags": make_flags(rng)})

    rng.shuffle(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = ["reg_id", "plate", "colour", "body_type", "make", "model", "flags"]
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for i, r in enumerate(rows, 1):
            w.writerow({"reg_id": f"REG{i:04d}", **r})
    print(f"wrote {len(rows)} rows to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
