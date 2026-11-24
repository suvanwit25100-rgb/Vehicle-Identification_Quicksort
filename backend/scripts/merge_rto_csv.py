"""Merge the team's rto_codes.csv (State/UT, RTO Code, Office / District) into data/rto_codes.json.

The CSV is primary. Wikipedia entries (make_rto_codes.py) fill codes the CSV lacks. Codes with a letter suffix (HP-08AA, TN-57W) and rows that are not
codes are skipped. Several rows for one code (AP-39 Tirupati and Krishna) are joined into one place text.
Usage: python scripts/merge_rto_csv.py data/source/rto_codes_user.csv
"""
import csv
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "rto_codes.json"


def main(src: str) -> None:
    data = json.loads(OUT.read_text(encoding="utf-8"))
    states = data["states"]
    for st in states.values():                                      # normalise the Wikipedia entries to one "place" text
        for k, v in st["codes"].items():
            if "place" not in v:
                v["place"] = f"{v['area']} ({v['office']})" if v.get("office") and v["office"] != v["area"] else v["area"]
                v["source"] = "wikipedia"
    seen: dict[tuple[str, str], list[str]] = {}
    names: dict[str, str] = {}
    for r in csv.DictReader(open(src, encoding="utf-8-sig", newline="")):
        m = re.fullmatch(r"([A-Z]{2})-(\d{1,3})", (r.get("RTO Code") or "").strip())
        if not m:
            continue
        seen.setdefault((m.group(1), m.group(2).zfill(2)), []).append((r.get("Office / District") or "").strip())
        names[m.group(1)] = (r.get("State/UT") or "").strip()
    for (st, num), places in seen.items():
        entry = states.setdefault(st, {"name": names[st], "codes": {}})
        entry["codes"][num] = {"place": "; ".join(dict.fromkeys(p for p in places if p)), "source": "team csv"}
    data["source"] = ("Team rto_codes.csv (primary), gaps filled from Wikipedia 'List of Regional Transport Office districts in India' "
                      "(CC BY-SA 4.0, volunteer-edited), merged 2026-11-24")
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    n = {k: sum(1 for s in states.values() for v in s["codes"].values() if v["source"] == k) for k in ("team csv", "wikipedia")}
    print(len(states), "states;", sum(len(s["codes"]) for s in states.values()), "codes;", n)


if __name__ == "__main__":
    main(sys.argv[1])
