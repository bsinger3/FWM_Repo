#!/usr/bin/env python3
"""Build an isolated ground-truth dataset for image-based weight experiments."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = REPO_ROOT.parent
PIPELINE_SCRIPTS_DIR = REPO_ROOT / "data-pipelines" / "scripts"
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import cv_annotated_pending_human_review_root, raw_scraped_data_root  # noqa: E402

DEFAULT_SEARCH_ROOTS = [
    raw_scraped_data_root(),
    cv_annotated_pending_human_review_root() / "amazon_legacy_step_4_human_review_and_visibility_decisions",
]
DEFAULT_OUTPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/ground_truth_manifest.csv"
DEFAULT_REPORT = REPO_ROOT / "experiments/weight_estimation_cv/reports/ground_truth_manifest_summary.json"

KEEP_COLUMNS = [
    "row_id",
    "source_file",
    "source_row_number",
    "source_site_display",
    "image_url",
    "product_page_url_display",
    "image_source_type",
    "height_in",
    "weight_lbs",
    "bmi",
    "size_display",
    "clothing_type_id",
    "product_title_raw",
    "product_category_raw",
    "product_variant_raw",
    "person_count_yolo_detect",
    "main_person_height_pct_yolo_detect",
    "main_person_bbox_area_pct_yolo_detect",
    "body_coverage_score_yolo_pose",
    "has_face_yunet",
    "user_comment",
]

WEIGHT_RANGE_RE = re.compile(
    r"\b\d{2,3}(?:\.\d+)?\s*(?:-|to|–|—)\s*\d{2,3}(?:\.\d+)?\s*(?:lbs?|pounds?|kgs?|kilograms?)?\b",
    re.IGNORECASE,
)
NON_CURRENT_WEIGHT_RE = re.compile(
    r"\b(?:lost|loss|gained|gain(?:ed|ing)?|down\s+\d+|up\s+\d+|goal\s+weight|pre[- ]?pregnancy|baby|toddler|child|daughter|son|fabric\s+weight|item\s+weighs?)\b",
    re.IGNORECASE,
)
WEIGHT_UNIT_RE = re.compile(r"\b(?:lbs?|pounds?|kgs?|kilograms?)\b", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--max-rows-per-file", type=int, default=0)
    parser.add_argument("--min-height", type=float, default=48.0)
    parser.add_argument("--max-height", type=float, default=84.0)
    parser.add_argument("--min-weight", type=float, default=70.0)
    parser.add_argument("--max-weight", type=float, default=350.0)
    return parser.parse_args()


def normalize_url(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path or ""
    return urlunsplit((scheme, netloc, path, "", ""))


def parse_number(value: object) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def parse_height(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    feet_match = re.search(r"(\d)\s*(?:'|ft|feet)\s*(\d{1,2})?", text, re.IGNORECASE)
    if feet_match:
        feet = int(feet_match.group(1))
        inches = int(feet_match.group(2) or 0)
        return float(feet * 12 + inches)
    value_num = parse_number(text)
    return value_num


def parse_weight(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or WEIGHT_RANGE_RE.search(text):
        return None
    value_num = parse_number(text)
    if value_num is None:
        return None
    if re.search(r"\b(?:kgs?|kilograms?)\b", text, re.IGNORECASE):
        return value_num * 2.2046226218
    return value_num


def is_exact_weight_candidate(row: dict[str, str], weight: float) -> bool:
    context = " ".join(
        str(row.get(key) or "")
        for key in ("weight_raw", "weight_display_display", "weight_lbs_display", "user_comment")
    )
    if WEIGHT_RANGE_RE.search(context):
        return False
    if NON_CURRENT_WEIGHT_RE.search(context):
        weight_text = str(int(weight)) if float(weight).is_integer() else str(weight)
        nearby = re.search(rf"\b(?:i\s*(?:am|'m)|weigh|weight)\D{{0,24}}{re.escape(weight_text)}\b", context, re.IGNORECASE)
        if not nearby:
            return False
    return True


def candidate_csv_files(search_roots: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            name = path.name.lower()
            if "summary" in name or "checkpoint" in name:
                continue
            paths.append(path)
    return sorted(paths)


def row_hash(path: Path, row_number: int, image_url: str, height: float, weight: float) -> str:
    payload = f"{path}:{row_number}:{image_url}:{height:.3f}:{weight:.3f}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def main() -> None:
    args = parse_args()
    files = candidate_csv_files(DEFAULT_SEARCH_ROOTS)
    if args.limit_files:
        files = files[: args.limit_files]

    rows: list[dict[str, object]] = []
    skipped = Counter()
    source_counts = Counter()
    seen_keys: set[tuple[str, float, float]] = set()

    for path in files:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                headers = set(reader.fieldnames or [])
                if not {"height_in_display", "weight_lbs_display"} & headers:
                    skipped["missing_measurement_columns"] += 1
                    continue
                if not {"original_url_display", "image_url_to_use", "raw_scraped_image_url"} & headers:
                    skipped["missing_image_columns"] += 1
                    continue
                for row_number, row in enumerate(reader, start=2):
                    if args.max_rows_per_file and row_number > args.max_rows_per_file + 1:
                        break
                    image_url = normalize_url(
                        row.get("image_url_to_use")
                        or row.get("original_url_display")
                        or row.get("raw_scraped_image_url")
                        or ""
                    )
                    if not image_url:
                        skipped["missing_image_url"] += 1
                        continue
                    height = parse_height(row.get("height_in_display") or row.get("height_raw"))
                    weight = parse_weight(row.get("weight_lbs_display") or row.get("weight_display_display") or row.get("weight_raw"))
                    if height is None or not (args.min_height <= height <= args.max_height):
                        skipped["invalid_height"] += 1
                        continue
                    if weight is None or not (args.min_weight <= weight <= args.max_weight):
                        skipped["invalid_weight"] += 1
                        continue
                    if not is_exact_weight_candidate(row, weight):
                        skipped["not_exact_current_weight"] += 1
                        continue
                    dedupe_key = (image_url, round(height, 2), round(weight, 2))
                    if dedupe_key in seen_keys:
                        skipped["duplicate_image_height_weight"] += 1
                        continue
                    seen_keys.add(dedupe_key)
                    bmi = weight * 703.0 / (height * height)
                    output_row = {
                        "row_id": row_hash(path, row_number, image_url, height, weight),
                        "source_file": str(path),
                        "source_row_number": row_number,
                        "source_site_display": row.get("source_site_display", ""),
                        "image_url": image_url,
                        "product_page_url_display": row.get("product_page_url_display", ""),
                        "image_source_type": row.get("image_source_type", ""),
                        "height_in": round(height, 3),
                        "weight_lbs": round(weight, 3),
                        "bmi": round(bmi, 4),
                        "size_display": row.get("size_display", ""),
                        "clothing_type_id": row.get("clothing_type_id", ""),
                        "product_title_raw": row.get("product_title_raw", ""),
                        "product_category_raw": row.get("product_category_raw", ""),
                        "product_variant_raw": row.get("product_variant_raw", ""),
                        "person_count_yolo_detect": row.get("person_count_yolo_detect", ""),
                        "main_person_height_pct_yolo_detect": row.get("main_person_height_pct_yolo_detect", ""),
                        "main_person_bbox_area_pct_yolo_detect": row.get("main_person_bbox_area_pct_yolo_detect", ""),
                        "body_coverage_score_yolo_pose": row.get("body_coverage_score_yolo_pose", ""),
                        "has_face_yunet": row.get("has_face_yunet", ""),
                        "user_comment": row.get("user_comment", ""),
                    }
                    rows.append(output_row)
                    source_counts[str(path)] += 1
        except UnicodeDecodeError:
            skipped["decode_error"] += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=KEEP_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    weights = [float(row["weight_lbs"]) for row in rows]
    heights = [float(row["height_in"]) for row in rows]
    report = {
        "rows": len(rows),
        "files_scanned": len(files),
        "skipped": dict(skipped),
        "top_sources": source_counts.most_common(25),
        "weight_lbs": {
            "min": min(weights) if weights else None,
            "max": max(weights) if weights else None,
            "avg": round(sum(weights) / len(weights), 2) if weights else None,
        },
        "height_in": {
            "min": min(heights) if heights else None,
            "max": max(heights) if heights else None,
            "avg": round(sum(heights) / len(heights), 2) if heights else None,
        },
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
