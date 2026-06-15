#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def fwm_data_dir() -> Path:
    configured = os.environ.get("FWM_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (repo_root().parent / "FWM_Data").resolve()


def raw_scraped_data_root() -> Path:
    return fwm_data_dir() / "00_raw_scraped_data"


def cleaned_normalized_data_root() -> Path:
    return fwm_data_dir() / "01_cleaned_normalized_data"


def supabase_qualified_data_root() -> Path:
    return fwm_data_dir() / "02_supabase_qualified_data"


def cv_annotated_pending_human_review_root() -> Path:
    return fwm_data_dir() / "03_cv_annotated_pending_human_review"


def human_reviewed_ready_to_publish_root() -> Path:
    return fwm_data_dir() / "04_human_reviewed_ready_to_publish"


def reports_root() -> Path:
    return fwm_data_dir() / "_reports"


def archive_root() -> Path:
    return fwm_data_dir() / "_archive"


def legacy_raw_run_dir(source_slug: str, run_id: str = "legacy_pre_2026-06-15") -> Path:
    return raw_scraped_data_root() / source_slug / run_id
