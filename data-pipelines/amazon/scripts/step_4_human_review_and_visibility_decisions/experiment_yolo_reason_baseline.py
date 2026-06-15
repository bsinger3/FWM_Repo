#!/usr/bin/env python3
"""Reason-specific baseline analysis for existing YOLO/CV columns."""

from __future__ import annotations
import sys

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
PIPELINE_SCRIPTS_DIR = REPO_ROOT / "data-pipelines" / "scripts"
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, cv_annotated_pending_human_review_root  # noqa: E402

LEGACY_OUTPUTS_ARCHIVE = archive_root() / "old_outputs" / "repo_outputs_archive" / "supabase_output_cleanup_2026_05_29"
CV_EXPERIMENTS_DIR = LEGACY_OUTPUTS_ARCHIVE / "cv_experiments"

PROJECT_ROOT = REPO_ROOT.parent
DATA_ROOT = PROJECT_ROOT / "FWM_Data"
AMAZON_STEP4 = cv_annotated_pending_human_review_root() / "amazon_legacy_step_4_human_review_and_visibility_decisions"
PART001 = AMAZON_STEP4 / "manual_chunks/backup/images_to_approve_part_001_SORTED_FacialDetectionGT_RejectionReasons1.csv"
PART002 = AMAZON_STEP4 / "part_002_REVIEWED.csv"
QUALITY_RESULTS = CV_EXPERIMENTS_DIR / "image_quality_baseline/image_quality_baseline_results.csv"
OUT_DIR = CV_EXPERIMENTS_DIR / "yolo_reason_baseline"


REASON_PATTERNS = [
    ("PERSON_TOO_FAR", [r"too far", r"far away", r"far from", r"too small", r"figure is too small"]),
    ("TOO_DARK", [r"too dark", r"dark and grainy", r"dark to see"]),
    ("BAD_ANGLE", [r"bad angle", r"weird angle", r"strange angle"]),
    ("GARMENT_CUT_OFF", [r"cut ?off", r"cuttoff", r"can't see full garment", r"entire garment", r"bottom of", r"top and bottom"]),
    ("GARMENT_TOP_COVERED", [r"top of .*covered", r"top .*covered"]),
    ("TARGET_WEARER_AMBIGUOUS", [r"two people", r"too many people", r"multiple people", r"who is wearing"]),
    ("BACKGROUND_CLUTTER", [r"clutter", r"busy"]),
    ("CATALOG_OR_ALTERED_BACKGROUND", [r"catalog", r"background.*altered", r"background removed", r"turned white"]),
    ("ROTATED_OR_WRONG_ORIENTATION", [r"rotation", r"rotated"]),
    ("NO_PERSON_VISIBLE", [r"no human", r"no person"]),
    ("FILTER_OR_MARKUP", [r"filter", r"line drawing", r"drawing", r"sticker", r"emoji"]),
    ("INVALID_OR_DEAD_IMAGE_URL", [r"url is not valid", r"not valid"]),
    ("BAD_ASPECT_RATIO_OR_BARS", [r"aspect ratio", r"black bar"]),
    ("BACKGROUND_VISUALLY_OFFPUTTING", [r"ugly photo"]),
]


def classify_reason(text: str) -> List[str]:
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not normalized:
        return []
    codes = []
    for code, patterns in REASON_PATTERNS:
        if any(re.search(pattern, normalized) for pattern in patterns):
            codes.append(code)
    return codes or ["OTHER_EXPLICIT_REASON"]


def load_explicit_reason_rows() -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    part001 = pd.read_csv(PART001, dtype=str, keep_default_na=False)
    for idx, row in part001.iterrows():
        label = row.get("image_approved? (1=Approved,2=NotApproved)", "")
        reason = row.get("Reason_for_Rejection", "")
        if label != "2" or not reason.strip():
            continue
        rows.append(
            {
                "dataset": "part001",
                "review_row_key": f"part001::{idx + 2}",
                "image_url": row.get("original_url_display", ""),
                "human_reason": reason,
                "reason_codes": ";".join(classify_reason(reason)),
                "has_person_existing": row.get("has_person", ""),
                "has_face_yunet": row.get("has_face_yunet", ""),
                "person_count_yolo_detect": "",
                "main_person_height_pct_yolo_detect": "",
                "main_person_bbox_area_pct_yolo_detect": "",
                "body_coverage_score_yolo_pose": "",
                "cv_reason_code": "",
            }
        )

    part002 = pd.read_csv(PART002, dtype=str, keep_default_na=False)
    manual_col = "Manual_approval(1=approved,2=reject, 3=ApprovedANDLabel'Pretty\")"
    for _, row in part002.iterrows():
        if row.get(manual_col, "") != "2":
            continue
        reason = row.get("Rejection Reason_Manual", "")
        if not reason.strip():
            continue
        rows.append(
            {
                "dataset": "part002",
                "review_row_key": row.get("review_row_key", ""),
                "image_url": row.get("original_url_display", ""),
                "human_reason": reason,
                "reason_codes": ";".join(classify_reason(reason)),
                "has_person_existing": "",
                "has_face_yunet": row.get("has_face_yunet", ""),
                "person_count_yolo_detect": row.get("person_count_yolo_detect", ""),
                "main_person_height_pct_yolo_detect": row.get("main_person_height_pct_yolo_detect", ""),
                "main_person_bbox_area_pct_yolo_detect": row.get("main_person_bbox_area_pct_yolo_detect", ""),
                "body_coverage_score_yolo_pose": row.get("body_coverage_score_yolo_pose", ""),
                "cv_reason_code": row.get("cv_reason_code", ""),
            }
        )
    return pd.DataFrame(rows)


def add_quality_flags(df: pd.DataFrame) -> pd.DataFrame:
    if not QUALITY_RESULTS.exists():
        df["quality_flags"] = ""
        return df
    quality = pd.read_csv(QUALITY_RESULTS, dtype=str, keep_default_na=False)
    quality = quality[["image_url", "quality_flags", "width", "height", "luminance_mean", "dark_pixel_pct", "laplacian_variance"]].drop_duplicates("image_url")
    return df.merge(quality, how="left", on="image_url")


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def reason_summary(df: pd.DataFrame) -> pd.DataFrame:
    exploded = df.assign(reason_code=df["reason_codes"].str.split(";")).explode("reason_code")
    exploded = exploded[exploded["reason_code"].fillna("") != ""]
    summaries = []
    for code, group in exploded.groupby("reason_code"):
        summaries.append(
            {
                "reason_code": code,
                "labeled_examples": len(group),
                "enough_for_accuracy_claim": "YES" if len(group) >= 30 else "NO",
                "person_count_median": numeric(group["person_count_yolo_detect"]).median(),
                "subject_height_median": numeric(group["main_person_height_pct_yolo_detect"]).median(),
                "subject_area_median": numeric(group["main_person_bbox_area_pct_yolo_detect"]).median(),
                "body_coverage_median": numeric(group["body_coverage_score_yolo_pose"]).median(),
                "has_existing_yolo_metrics": int(numeric(group["person_count_yolo_detect"]).notna().sum()),
                "quality_flags_seen": ";".join(
                    flag
                    for flag, _count in Counter(
                        flag
                        for flags in group.get("quality_flags", pd.Series(dtype=str)).fillna("")
                        for flag in str(flags).split(";")
                        if flag
                    ).most_common()
                ),
                "example_reasons": " | ".join(group["human_reason"].drop_duplicates().head(4).tolist()),
            }
        )
    return pd.DataFrame(summaries).sort_values(["enough_for_accuracy_claim", "labeled_examples"], ascending=[True, False])


def threshold_eval_part002() -> pd.DataFrame:
    part002 = pd.read_csv(PART002, dtype=str, keep_default_na=False)
    manual_col = "Manual_approval(1=approved,2=reject, 3=ApprovedANDLabel'Pretty\")"
    labeled = part002[part002[manual_col].isin(["1", "2", "3"])].copy()
    labeled["manual_reject"] = labeled[manual_col] == "2"
    labeled["subject_height"] = numeric(labeled["main_person_height_pct_yolo_detect"])
    labeled["subject_area"] = numeric(labeled["main_person_bbox_area_pct_yolo_detect"])
    labeled["body_coverage"] = numeric(labeled["body_coverage_score_yolo_pose"])
    rules = [
        ("height_lt_0_60", labeled["subject_height"] < 0.60),
        ("height_lt_0_70", labeled["subject_height"] < 0.70),
        ("height_lt_0_80", labeled["subject_height"] < 0.80),
        ("area_lt_0_25", labeled["subject_area"] < 0.25),
        ("area_lt_0_35", labeled["subject_area"] < 0.35),
        ("body_coverage_lt_66_7", labeled["body_coverage"] < 66.7),
        ("body_coverage_lt_75", labeled["body_coverage"] < 75.0),
    ]
    rows = []
    for name, pred in rules:
        valid = pred.notna()
        pred = pred.fillna(False)
        actual = labeled["manual_reject"]
        tp = int((pred & actual).sum())
        fp = int((pred & ~actual).sum())
        fn = int((~pred & actual).sum())
        tn = int((~pred & ~actual).sum())
        rows.append(
            {
                "rule": name,
                "tp_reject": tp,
                "fp_approved_flagged": fp,
                "fn_reject_missed": fn,
                "tn_approved_clear": tn,
                "precision": round(tp / (tp + fp), 3) if tp + fp else "",
                "recall": round(tp / (tp + fn), 3) if tp + fn else "",
                "approved_false_flag_rate": round(fp / (fp + tn), 3) if fp + tn else "",
                "note": "Generic reject-prediction threshold over all Part 002 labels; not reason-specific.",
            }
        )
    return pd.DataFrame(rows)


def write_report(summary: pd.DataFrame, thresholds: pd.DataFrame, explicit_rows: pd.DataFrame) -> str:
    enough = summary[summary["enough_for_accuracy_claim"] == "YES"]
    not_enough = summary[summary["enough_for_accuracy_claim"] == "NO"]
    lines = [
        "# YOLO / Existing CV Reason Baseline",
        "",
        "## Ground Truth Sufficiency",
        "",
        f"- explicit rejected rows with human reason text: `{len(explicit_rows)}`",
        f"- reason buckets with at least 30 examples: `{len(enough)}`",
        f"- reason buckets below 30 examples: `{len(not_enough)}`",
        "",
        "At this stage, only reason buckets with at least about 30 explicit examples should be treated as accuracy-evaluable. Smaller buckets are useful for ideation and smoke tests, but not for claims.",
        "",
        "## Reason Bucket Counts",
        "",
        "| reason_code | labeled examples | enough for accuracy claim | has YOLO metric rows | example reasons |",
        "| --- | ---: | --- | ---: | --- |",
    ]
    for _, row in summary.iterrows():
        lines.append(
            "| `{}` | {} | {} | {} | {} |".format(
                row["reason_code"],
                int(row["labeled_examples"]),
                row["enough_for_accuracy_claim"],
                int(row["has_existing_yolo_metrics"]),
                str(row["example_reasons"]).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Threshold Smoke Test On All Part 002 Labels",
            "",
            "| rule | precision | recall | approved false-flag rate | tp reject | fp approved |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for _, row in thresholds.iterrows():
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} |".format(
                row["rule"], row["precision"], row["recall"], row["approved_false_flag_rate"], row["tp_reject"], row["fp_approved_flagged"]
            )
        )
    lines.extend(
        [
            "",
            "## Findings",
            "",
            "- `PERSON_TOO_FAR` has enough explicit labels to evaluate first.",
            "- Most other reason buckets do not yet have enough explicit labels for accuracy claims.",
            "- Generic YOLO subject-size thresholds are too blunt for direct rejection: they catch some rejects but flag approved rows too.",
            "- Existing `body_coverage_score_yolo_pose` is not discriminative in Part 002 because most labeled rows sit at the same score.",
            "",
            "## Ground Truth Need",
            "",
            "We need a new labeling sheet for the under-specified buckets: garment cut off, top covered, bad angle, clutter/background, catalog/altered background, no human/product-only, overlays/markup, and dirty/off-putting background.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    explicit_rows = add_quality_flags(load_explicit_reason_rows())
    summary = reason_summary(explicit_rows)
    thresholds = threshold_eval_part002()

    explicit_path = OUT_DIR / "explicit_reason_rows.csv"
    summary_path = OUT_DIR / "reason_bucket_summary.csv"
    thresholds_path = OUT_DIR / "part002_yolo_threshold_smoke_test.csv"
    report_path = OUT_DIR / "yolo_reason_baseline_report.md"
    explicit_rows.to_csv(explicit_path, index=False)
    summary.to_csv(summary_path, index=False)
    thresholds.to_csv(thresholds_path, index=False)
    report_path.write_text(write_report(summary, thresholds, explicit_rows), encoding="utf-8")
    print(explicit_path)
    print(summary_path)
    print(thresholds_path)
    print(report_path)


if __name__ == "__main__":
    main()
