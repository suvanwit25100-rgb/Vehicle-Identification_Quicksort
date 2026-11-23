"""Sweep match thresholds on simulated sightings and recommend one per department.

Usage:  python scripts/calibrate.py [--n-pos 800] [--n-neg 1500] [--seed 7]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.calibration import choose_threshold, make_samples, metrics_at, run_matcher  # noqa: E402
from app.config import load_departments  # noqa: E402
from app.registry import load_registry  # noqa: E402

FMR_TARGETS = {"police": 0.05, "morth_nhai": 0.05, "ssb": 0.03, "customs": 0.03, "bsf": 0.01}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-pos", type=int, default=800)
    ap.add_argument("--n-neg", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=Path("data/calibration_report.json"))
    args = ap.parse_args()

    registry = load_registry()
    samples = make_samples(registry, args.n_pos, args.n_neg, args.seed)
    n_pos = sum(s.kind == "pos" for s in samples)
    print(f"{len(samples)} simulated sightings ({n_pos} in registry, {len(samples) - n_pos} not in registry)\n")

    report = {}
    for dept_id, cfg in load_departments().items():
        records = run_matcher(samples, registry, cfg)
        cur = metrics_at(records, cfg.match_threshold)
        rec = choose_threshold(records, FMR_TARGETS[dept_id])
        report[dept_id] = {"target_fmr": FMR_TARGETS[dept_id], "current": cur, "recommended": rec,
                           "sweep": [metrics_at(records, t / 100) for t in range(30, 96, 5)]}
        print(f"{dept_id:11s} target FMR<={FMR_TARGETS[dept_id]:.2f}")
        for label, m in (("current", cur), ("recommended", rec)):
            print(f"   {label:12s} theta={m['theta']:.2f}  recall@1={m['recall_top1']:.3f}  "
                  f"false-match={m['false_match_rate']:.4f} (upper95 {m['false_match_upper95']:.4f})  "
                  f"lookalike-FM={m['lookalike_false_match']}  wrong-return={m['pos_wrong_return']:.3f}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
