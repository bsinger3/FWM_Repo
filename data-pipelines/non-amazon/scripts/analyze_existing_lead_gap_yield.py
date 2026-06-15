#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[3] / "data-pipelines" / "scripts" / "02_qualify_for_supabase" / "non_amazon" / "analyze_existing_lead_gap_yield.py"
sys.path.insert(0, str(TARGET.parent))
runpy.run_path(str(TARGET), run_name="__main__")
