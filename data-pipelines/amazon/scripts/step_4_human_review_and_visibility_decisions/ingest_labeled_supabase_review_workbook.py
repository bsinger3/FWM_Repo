#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[4] / "data-pipelines" / "scripts" / "04_human_review_publish" / "amazon" / "ingest_labeled_supabase_review_workbook.py"
sys.path.insert(0, str(TARGET.parent))
runpy.run_path(str(TARGET), run_name="__main__")
