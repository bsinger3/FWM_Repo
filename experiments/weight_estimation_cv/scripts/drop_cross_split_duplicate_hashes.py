#!/usr/bin/env python3
"""Drop downloaded rows with perceptual-hash groups spanning train and test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = EXPERIMENT_ROOT / "data/clip_scale_eval_sample_hardened.csv"
DEFAULT_OUTPUT = EXPERIMENT_ROOT / "data/clip_scale_eval_sample_hardened_no_hash_leaks.csv"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/clip_scale_drop_hash_leaks_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--hash-column", default="image_average_hash")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input)
    usable = df[df[args.hash_column].fillna("").astype(str).ne("")]
    split_counts = usable.groupby(args.hash_column)["split"].nunique()
    leaking_hashes = set(split_counts[split_counts > 1].index.astype(str))
    drop_mask = df[args.hash_column].fillna("").astype(str).isin(leaking_hashes)
    out = df[~drop_mask].copy()

    report = {
        "input": str(args.input),
        "output": str(args.output),
        "hash_column": args.hash_column,
        "input_rows": int(len(df)),
        "output_rows": int(len(out)),
        "dropped_rows": int(drop_mask.sum()),
        "dropped_hash_groups": int(len(leaking_hashes)),
        "dropped_by_split": df[drop_mask]["split"].value_counts().to_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

