#!/usr/bin/env python3
"""Create a reproducible, source-balanced evaluation sample."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/ground_truth_manifest.csv"
DEFAULT_OUTPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/eval_sample.csv"
DEFAULT_REPORT = REPO_ROOT / "experiments/weight_estimation_cv/reports/eval_sample_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--target-rows", type=int, default=1200)
    parser.add_argument("--max-per-source", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260609)
    parser.add_argument("--test-size", type=float, default=0.25)
    return parser.parse_args()


def url_host(url: str) -> str:
    return urlsplit(str(url or "")).netloc.lower()


def image_cache_name(row_id: str, image_url: str) -> str:
    digest = hashlib.sha1(f"{row_id}:{image_url}".encode("utf-8")).hexdigest()[:16]
    suffix = Path(urlsplit(str(image_url)).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    return f"{digest}{suffix}"


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input)
    df = df.drop_duplicates(subset=["image_url", "height_in", "weight_lbs"]).copy()
    df["source_group"] = df["source_file"].astype(str).str.replace(r"/[^/]+$", "", regex=True)
    df["image_host"] = df["image_url"].map(url_host)
    df["weight_bin"] = pd.cut(
        df["weight_lbs"],
        bins=[69, 100, 120, 140, 160, 180, 210, 250, 351],
        labels=["70-100", "101-120", "121-140", "141-160", "161-180", "181-210", "211-250", "251-350"],
    ).astype(str)
    df["stratum"] = df["source_group"] + "|" + df["weight_bin"]

    sampled_parts = []
    per_stratum = max(1, args.target_rows // max(1, df["stratum"].nunique()))
    for _, group in df.groupby("stratum", sort=False):
        capped_parts = []
        for _, source_group in group.groupby("source_file", sort=False):
            capped_parts.append(source_group.sample(min(len(source_group), args.max_per_source), random_state=args.seed))
        source_capped = pd.concat(capped_parts, ignore_index=True)
        take = min(len(source_capped), max(per_stratum, min(8, len(source_capped))))
        sampled_parts.append(source_capped.sample(take, random_state=args.seed))

    sample = pd.concat(sampled_parts, ignore_index=True).drop_duplicates(subset=["image_url", "height_in", "weight_lbs"])
    if len(sample) > args.target_rows:
        sample = sample.sample(args.target_rows, random_state=args.seed)

    groups = sample["source_group"].fillna(sample["source_file"]).astype(str)
    splitter = GroupShuffleSplit(n_splits=1, test_size=args.test_size, random_state=args.seed)
    train_idx, test_idx = next(splitter.split(sample, groups=groups))
    sample["split"] = "train"
    sample.loc[sample.index[test_idx], "split"] = "test"
    sample["image_cache_file"] = [
        image_cache_name(row.row_id, row.image_url) for row in sample.itertuples(index=False)
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(args.output, index=False)

    report = {
        "rows": int(len(sample)),
        "train_rows": int((sample["split"] == "train").sum()),
        "test_rows": int((sample["split"] == "test").sum()),
        "source_files": int(sample["source_file"].nunique()),
        "source_groups": int(sample["source_group"].nunique()),
        "image_hosts": sample["image_host"].value_counts().head(20).to_dict(),
        "weight_bins": sample["weight_bin"].value_counts().sort_index().to_dict(),
        "weight_lbs": {
            "min": float(sample["weight_lbs"].min()),
            "max": float(sample["weight_lbs"].max()),
            "avg": round(float(sample["weight_lbs"].mean()), 2),
        },
        "height_in": {
            "min": float(sample["height_in"].min()),
            "max": float(sample["height_in"].max()),
            "avg": round(float(sample["height_in"].mean()), 2),
        },
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
