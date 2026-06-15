#!/usr/bin/env python3
"""Create the supervised training-eligible row set without using quality labels as features."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = EXPERIMENT_ROOT / "data/supervised_scale_with_quality_tags.csv"
DEFAULT_OUTPUT = EXPERIMENT_ROOT / "data/supervised_scale_training_eligible_rows.csv"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/supervised_scale_training_eligibility_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--allowed-buckets",
        default="full_body_likely,torso_or_partial_body",
        help="Comma-separated image_quality_bucket values eligible for the first supervised model.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input)
    allowed_buckets = {value.strip() for value in args.allowed_buckets.split(",") if value.strip()}
    local_exists = df["local_image_path"].fillna("").astype(str).map(lambda value: Path(value).exists())
    mask = (
        df["is_downloaded_image"].astype(bool)
        & local_exists
        & df["person_visible"].astype(bool)
        & ~df["multiple_people"].astype(bool)
        & df["image_quality_bucket"].isin(allowed_buckets)
    )
    out = df[mask].copy()
    report = {
        "input": str(args.input),
        "output": str(args.output),
        "input_rows": int(len(df)),
        "eligible_rows": int(len(out)),
        "eligible_train_rows": int((out["split"] == "train").sum()),
        "eligible_test_rows": int((out["split"] == "test").sum()),
        "allowed_buckets": sorted(allowed_buckets),
        "input_quality_buckets": df["image_quality_bucket"].value_counts(dropna=False).to_dict(),
        "eligible_quality_buckets": out["image_quality_bucket"].value_counts(dropna=False).to_dict(),
        "excluded_counts": {
            "not_downloaded_or_missing_local_file": int((~(df["is_downloaded_image"].astype(bool) & local_exists)).sum()),
            "not_person_visible": int((~df["person_visible"].astype(bool)).sum()),
            "multiple_people": int(df["multiple_people"].astype(bool).sum()),
            "bucket_not_allowed": int((~df["image_quality_bucket"].isin(allowed_buckets)).sum()),
        },
        "eligible_weight_bins": out["weight_bin"].value_counts(dropna=False).sort_index().to_dict()
        if "weight_bin" in out
        else {},
        "eligible_source_hosts_top_20": out["image_host"].value_counts().head(20).to_dict()
        if "image_host" in out
        else {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

