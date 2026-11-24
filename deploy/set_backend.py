"""Point the Vercel front end at your backend: python3 deploy/set_backend.py https://exlex-api.onrender.com

Edits vercel.json (the /api rewrites) and backend/app/static/config.js (where video uploads go). Run it once, commit, push."""
import json
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
if len(sys.argv) != 2 or not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?", sys.argv[1].rstrip("/")):
    sys.exit("Usage: python3 deploy/set_backend.py https://your-backend-address   (https, no path)")
url = sys.argv[1].rstrip("/")

v = root / "vercel.json"
cfg = json.loads(v.read_text())
for r in cfg["rewrites"]:
    r["destination"] = re.sub(r"^https://[^/]+", url, r["destination"])
v.write_text(json.dumps(cfg, indent=2) + "\n")

c = root / "backend" / "app" / "static" / "config.js"
c.write_text(re.sub(r'uploadBase: "[^"]*"', f'uploadBase: "{url}"', c.read_text()))
print("vercel.json and config.js now point at", url)
