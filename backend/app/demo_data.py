"""Demo reports for the officer portal, so it is not empty when shown.

They are built from analyses that really are stored (their own evidence frames and fused plates), filed under made-up places and
times, and stored with source="demo". They are labelled "demo" everywhere in the portal, never counted by the monitor (which shows
measured data only), and can be removed in one step. Nothing here pretends to be a real citizen report.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .complaints import ComplaintStore
from .schemas import AnalysisResult

PLACES = [
    ("Telibandha Chowk, Raipur", 21.2399, 81.6523), ("Pandri bus stand, Raipur", 21.2330, 81.6410), ("VIP Road, Raipur", 21.2327, 81.6969),
    ("Mowa overbridge, Raipur", 21.2650, 81.6640), ("NH30 near Mandir Hasaud", 21.2865, 81.7880), ("Sector 21, Naya Raipur", 21.1650, 81.7870),
    ("Shankar Nagar, Raipur", 21.2370, 81.6600), ("Bhatagaon, Raipur", 21.2120, 81.6360),
]
SCENARIOS = [
    ("dangerous_driving", "Overtook on a blind bend and forced oncoming traffic to brake.", "new"),
    ("traffic_violation", "Jumped the red signal while the junction was busy.", "under_review"),
    ("suspicious_vehicle", "Parked for hours near the gate with no one inside.", "verified"),
    ("hit_and_run", "Clipped a two-wheeler and drove off without stopping.", "forwarded"),
    ("dangerous_driving", "Driving the wrong way on the service road.", "closed"),
    ("traffic_violation", "No number plate light and plate partly covered.", "rejected"),
]


def _tracks(data_dir: Path):
    for f in sorted((data_dir / "jobs").glob("*/result.json")) if (data_dir / "jobs").exists() else []:
        try:
            r = AnalysisResult.model_validate_json(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        for t in r.tracks:
            ev = f.parent / t.evidence_frame if t.evidence_frame else None
            if ev and ev.exists() and t.match.fused.known_count >= 7:
                crop = next((f.parent / n for n in t.plate_crops if (f.parent / n).exists()), None)
                yield r.job_id, t, ev, crop


def seed(data_dir: Path, store: ComplaintStore, count: int = 10, rng_seed: int = 7) -> int:
    if store.demo_count():
        raise ValueError("Demo reports are already loaded. Remove them first.")
    pool = list(_tracks(data_dir))
    if not pool:
        raise ValueError("No stored analysis with a readable plate and an evidence image to build demo reports from. Analyse a clip first.")
    rng = random.Random(rng_seed)
    now = datetime.now(timezone.utc)
    made = 0
    for i in range(count):
        job_id, t, ev, crop = pool[i % len(pool)] if i < len(pool) * 2 else rng.choice(pool)
        cat, text, status = SCENARIOS[i % len(SCENARIOS)]
        place, lat, lon = PLACES[i % len(PLACES)]
        when = now - timedelta(hours=rng.randint(2, 6 * 24) if i % 3 else rng.randint(1, 20))     # a few recent ones, so related-report grouping shows
        cid = store.flag_track(job_id, t.track_id, {"category": cat, "description": f"[demo] {text}", "location_text": place, "observed_at": when.isoformat(timespec="seconds")},
                               ev.read_bytes(), crop.read_bytes() if crop else None, t.match.fused.model_dump_json(), t.match.pattern, t.colour, bool(crop),
                               source="demo", lat=lat + rng.uniform(-0.004, 0.004), lon=lon + rng.uniform(-0.004, 0.004), created_at=when.isoformat(timespec="seconds"), status=status)
        made += bool(cid)
    return made
