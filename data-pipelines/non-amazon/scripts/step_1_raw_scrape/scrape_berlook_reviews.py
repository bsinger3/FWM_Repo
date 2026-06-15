#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[4] / "data-pipelines" / "scripts" / "00_raw_scrape" / "non_amazon" / "scrape_berlook_reviews.py"
sys.path.insert(0, str(TARGET.parent))
runpy.run_path(str(TARGET), run_name="__main__")
