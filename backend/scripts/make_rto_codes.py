"""Build data/rto_codes.json from the Wikipedia page "List of Regional Transport Office districts in India".

Source: https://en.wikipedia.org/wiki/List_of_Regional_Transport_Office_districts_in_India (text under CC BY-SA 4.0; the code list is
public information). The page is edited by volunteers, so entries can be wrong or out of date. This is a region lookup for the first four
characters of a plate (state letters and district number); it contains no vehicle or owner data.
Usage: python scripts/make_rto_codes.py path/to/raw_wikitext.txt     (fetch with action=raw from the page above)
"""
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "rto_codes.json"


def clean(t: str) -> str:
    t = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"\{\{[^{}]*\}\}", "", t)
    t = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"'''?|<[^>]+>", "", t)
    return re.sub(r"\s+", " ", t).strip(" |")


def main(src: str) -> None:
    lines = Path(src).read_text(encoding="utf-8").splitlines()
    states: dict[str, dict] = {}
    cur = None
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^==\s*([A-Z]{2})\s*[—–-]\s*([^=]+?)\s*==\s*$", line)
        if m:
            cur = m.group(1)
            states[cur] = {"name": clean(m.group(2)), "codes": {}}
        elif cur:
            c = re.match(r"^[|!]\s*(?:scope=\w+\s*\|\s*)?((?:[A-Z]{2}[- ]\d{1,3}\s*(?:<br\s*/?>\s*)?)+)$", line)
            if c:
                office = clean(lines[i + 1]) if i + 1 < len(lines) else ""
                area = clean(lines[i + 2]) if i + 2 < len(lines) else ""
                for st, num in re.findall(r"([A-Z]{2})[- ](\d{1,3})", c.group(1)):
                    if st == cur:
                        states[cur]["codes"].setdefault(num.zfill(2), {"office": office, "area": area})
        i += 1
    states = {k: v for k, v in states.items() if v["codes"]}
    OUT.write_text(json.dumps({"source": "Wikipedia: List of Regional Transport Office districts in India (CC BY-SA 4.0), fetched 2026-11-24",
                               "states": states}, ensure_ascii=False, indent=0, sort_keys=True))
    print(len(states), "states,", sum(len(v["codes"]) for v in states.values()), "codes ->", OUT)


if __name__ == "__main__":
    main(sys.argv[1])
