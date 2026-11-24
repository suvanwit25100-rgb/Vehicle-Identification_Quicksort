"""Tests and calibration run on the 300-row synthetic registry, whatever the app uses by default."""
import os
from pathlib import Path

os.environ.setdefault("EXLEX_REGISTRY", str(Path(__file__).resolve().parent.parent / "data" / "registry.csv"))
