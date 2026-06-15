#!/usr/bin/env python3
"""Export person/face geometry features and summarize their benchmark metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = EXPERIMENT_ROOT / "data/eval_sample_with_quality_tags.csv"
DEFAULT_BASELINES = EXPERIMENT_ROOT / "reports/subset_baseline_metrics.json"
DEFAULT_OUTPUT = EXPERIMENT_ROOT / "data/geometry_features.csv"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/geometry_feature_metrics.json"


GEOMETRY_COLUMNS = [
    "image_width_downloaded",
    "image_height_downloaded",
    "face_count",
    "largest_face_area_pct",
    "largest_face_width_pct",
    "largest_face_height_pct",
    "person_count",
    "main_person_conf",
    "main_person_area_pct",
    "main_person_width_pct",
    "main_person_height_pct",
    "main_person_aspect_ratio",
    "face_visible",
    "large_face_visible",
    "person_visible",
    "full_body_likely",
    "torso_or_partial_body",
    "multiple_people",
    "low_signal",
    "image_quality_bucket",
]

ID_COLUMNS = [
    "row_id",
    "split",
    "height_in",
    "weight_lbs",
    "bmi",
    "size_display",
    "clothing_type_id",
    "source_site_display",
    "local_image_path",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--baselines", type=Path, default=DEFAULT_BASELINES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def result_lookup(payload: dict, subset: str, model_name: str) -> dict[str, object] | None:
    for item in payload.get("subsets", []):
        if item.get("subset") != subset:
            continue
        for result in item.get("results", []):
            if result.get("model") == model_name:
                return result
    return None


def best_result(payload: dict, subset: str) -> dict[str, object] | None:
    for item in payload.get("subsets", []):
        if item.get("subset") == subset and item.get("results"):
            return sorted(item["results"], key=lambda row: row["mae_lbs"])[0]
    return None


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input)
    columns = [column for column in ID_COLUMNS + GEOMETRY_COLUMNS if column in df.columns]
    out = df[df["is_downloaded_image"].astype(bool)][columns].copy()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)

    payload = json.loads(args.baselines.read_text())
    subsets = ["person_visible", "full_body_likely", "torso_or_partial_body", "all_downloaded"]
    comparisons = {}
    for subset in subsets:
        metadata = result_lookup(payload, subset, "ridge_height_metadata_predict_bmi")
        geometry = result_lookup(payload, subset, "ridge_height_geometry_metadata_predict_bmi")
        comparisons[subset] = {
            "best": best_result(payload, subset),
            "height_metadata": metadata,
            "height_geometry_metadata": geometry,
            "geometry_delta_mae_lbs": round(geometry["mae_lbs"] - metadata["mae_lbs"], 3)
            if metadata and geometry
            else None,
        }

    report = {
        "input": str(args.input),
        "output": str(args.output),
        "rows": int(len(out)),
        "geometry_columns": GEOMETRY_COLUMNS,
        "comparisons": comparisons,
        "decision": (
            "Simple YOLO/OpenCV geometry is not strong enough as a standalone next step; "
            "move to person-crop foundation embeddings."
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
