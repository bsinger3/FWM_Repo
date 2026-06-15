#!/usr/bin/env python3
"""Create a larger source/weight-balanced sample for supervised CV experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = EXPERIMENT_ROOT / "data/ground_truth_manifest.csv"
DEFAULT_OUTPUT = EXPERIMENT_ROOT / "data/supervised_scale_sample.csv"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/supervised_scale_sample_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--target-rows", type=int, default=20000)
    parser.add_argument("--max-per-source-file", type=int, default=1000)
    parser.add_argument("--max-per-source-group", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=20260609)
    parser.add_argument("--test-size", type=float, default=0.25)
    return parser.parse_args()


def url_host(url: object) -> str:
    return urlsplit(str(url or "")).netloc.lower()


def image_cache_name(row_id: object, image_url: object) -> str:
    digest = hashlib.sha1(f"{row_id}:{image_url}".encode("utf-8")).hexdigest()[:16]
    suffix = Path(urlsplit(str(image_url or "")).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    return f"{digest}{suffix}"


def source_group(source_file: object) -> str:
    value = str(source_file or "")
    path = Path(value)
    if len(path.parts) >= 2:
        return str(path.parent)
    return value


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input, low_memory=False)
    df = df.drop_duplicates(subset=["image_url", "height_in", "weight_lbs"]).copy()
    df = df[df["image_url"].fillna("").astype(str).str.startswith(("http://", "https://"))].copy()
    df = df[df["height_in"].notna() & df["weight_lbs"].notna() & df["bmi"].notna()].copy()
    df["source_group"] = df["source_file"].map(source_group)
    df["image_host"] = df["image_url"].map(url_host)
    df["weight_bin"] = pd.cut(
        df["weight_lbs"],
        bins=[69, 100, 120, 140, 160, 180, 210, 250, 351],
        labels=["70-100", "101-120", "121-140", "141-160", "161-180", "181-210", "211-250", "251-350"],
    ).astype(str)
    df = df[df["weight_bin"].ne("nan")].copy()

    capped_files = []
    for _, group in df.groupby("source_file", sort=False):
        capped_files.append(group.sample(min(len(group), args.max_per_source_file), random_state=args.seed))
    capped = pd.concat(capped_files, ignore_index=True)

    capped_groups = []
    for _, group in capped.groupby("source_group", sort=False):
        capped_groups.append(group.sample(min(len(group), args.max_per_source_group), random_state=args.seed))
    capped = pd.concat(capped_groups, ignore_index=True)

    per_bin = max(1, args.target_rows // capped["weight_bin"].nunique())
    sampled_parts = []
    for _, group in capped.groupby("weight_bin", sort=True):
        sampled_parts.append(group.sample(min(len(group), per_bin), random_state=args.seed))
    sample = pd.concat(sampled_parts, ignore_index=True)

    if len(sample) < args.target_rows:
        sample_keys = set(zip(sample["image_url"], sample["height_in"], sample["weight_lbs"]))
        remaining = capped[
            ~capped[["image_url", "height_in", "weight_lbs"]]
            .apply(lambda row: (row["image_url"], row["height_in"], row["weight_lbs"]) in sample_keys, axis=1)
        ]
        if len(remaining):
            add = remaining.sample(min(len(remaining), args.target_rows - len(sample)), random_state=args.seed)
            sample = pd.concat([sample, add], ignore_index=True)

    if len(sample) > args.target_rows:
        sample = sample.sample(args.target_rows, random_state=args.seed).copy()

    groups = sample["source_group"].fillna(sample["source_file"]).astype(str)
    splitter = GroupShuffleSplit(n_splits=1, test_size=args.test_size, random_state=args.seed)
    train_idx, test_idx = next(splitter.split(sample, groups=groups))
    sample["split"] = "train"
    sample.loc[sample.index[test_idx], "split"] = "test"
    sample["image_cache_file"] = [
        image_cache_name(row.row_id, row.image_url) for row in sample.itertuples(index=False)
    ]

    report = {
        "input": str(args.input),
        "output": str(args.output),
        "rows": int(len(sample)),
        "train_rows": int((sample["split"] == "train").sum()),
        "test_rows": int((sample["split"] == "test").sum()),
        "source_files": int(sample["source_file"].nunique()),
        "source_groups": int(sample["source_group"].nunique()),
        "image_hosts": sample["image_host"].value_counts().head(30).to_dict(),
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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(args.output, index=False)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
