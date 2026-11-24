#!/bin/sh
# Start the API. Data lives in EXLEX_DATA_DIR (put a persistent disk there); seed files are copied in on first start.
set -e
DATA="${EXLEX_DATA_DIR:-/app/backend/data}"
mkdir -p "$DATA"
[ -f "$DATA/calibration_report.json" ] || cp /app/backend/data/calibration_report.json "$DATA/" 2>/dev/null || true
exec uvicorn app.main:app --app-dir /app/backend --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
