#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[4] / "data-pipelines" / "scripts" / "03_cv_annotate" / "amazon" / "build_supabase_image_review_package.py"
sys.path.insert(0, str(TARGET.parent))
runpy.run_path(str(TARGET), run_name="__main__")
