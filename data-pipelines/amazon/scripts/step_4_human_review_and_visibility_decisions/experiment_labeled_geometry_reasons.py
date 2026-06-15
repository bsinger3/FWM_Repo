#!/usr/bin/env python3
"""Evaluate existing YOLO geometry columns against newly labeled reason data."""

from __future__ import annotations
import sys

import csv
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[4]
PIPELINE_SCRIPTS_DIR = REPO_ROOT / "data-pipelines" / "scripts"
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, cv_annotated_pending_human_review_root  # noqa: E402

LEGACY_OUTPUTS_ARCHIVE = archive_root() / "old_outputs" / "repo_outputs_archive" / "supabase_output_cleanup_2026_05_29"
CV_EXPERIMENTS_DIR = LEGACY_OUTPUTS_ARCHIVE / "cv_experiments"

GROUND_TRUTH_CSV = CV_EXPERIMENTS_DIR / "ground_truth_labeling/labeled_image_rejection_reason_queue.csv"
OUT_DIR = CV_EXPERIMENTS_DIR / "labeled_geometry_reasons"

REASON_COLUMNS = [
    "NEEDS_CROP",
    "BAD_ANGLE_TOP_DOWN",
    "GARMENT_TOP_COVERED",
    "GARMENT_TOO_PARTIAL",
    "GARMENT_CUT_OFF",
    "GARMENT_OBSCURED",
    "PERSON_TOO_FAR",
    "TARGET_WEARER_AMBIGUOUS",
    "NOT_WORN_BY_PERSON",
]


def read_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def normalize_decision(value: str) -> str:
    text = (value or "").strip().upper()
    if text in {"APPROVED", "REJECTED"}:
        return text
    return ""


def normalize_reason(value: str) -> str:
    return (value or "").strip().upper()


def truth_has_reason(row: Dict[str, str], reason: str) -> bool:
    if normalize_reason(row.get("primary_reason_code", "")) == reason:
        return True
    if normalize_reason(row.get("secondary_reason_code", "")) == reason:
        return True
    value = (row.get(reason, "") or "").strip().lower()
    return value in {"true", "yes", "1", "x", "checked"}


def to_float(value: object) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except ValueError:
        return None


Rule = Tuple[str, Callable[[Dict[str, object]], bool]]


def geometry_rules() -> List[Rule]:
    rules: List[Rule] = [
        ("cv_borderline_body_coverage", lambda row: "BORDERLINE_BODY_COVERAGE" in str(row.get("cv_reason_code") or "")),
        ("cv_borderline_subject_size", lambda row: "BORDERLINE_SUBJECT_SIZE" in str(row.get("cv_reason_code") or "")),
        ("body_coverage_eq_66_7", lambda row: to_float(row.get("body_coverage_score_yolo_pose")) == 66.7),
        ("body_coverage_lt_75", lambda row: (to_float(row.get("body_coverage_score_yolo_pose")) or 999) < 75),
        ("body_coverage_lt_90", lambda row: (to_float(row.get("body_coverage_score_yolo_pose")) or 999) < 90),
    ]
    for threshold in [0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
        rules.append(
            (
                f"subject_height_lt_{threshold:.2f}",
                lambda row, threshold=threshold: (to_float(row.get("main_person_height_pct_yolo_detect")) or 999) < threshold,
            )
        )
    for threshold in [0.20, 0.25, 0.30, 0.35, 0.40]:
        rules.append(
            (
                f"subject_area_lt_{threshold:.2f}",
                lambda row, threshold=threshold: (to_float(row.get("main_person_bbox_area_pct_yolo_detect")) or 999) < threshold,
            )
        )
    for threshold in [1, 2, 3]:
        rules.append(
            (
                f"person_count_gte_{threshold}",
                lambda row, threshold=threshold: (to_float(row.get("person_count_yolo_detect")) or 0) >= threshold,
            )
        )
    return rules


def evaluate_reason(rows: List[Dict[str, object]], reason: str, rule_name: str, predicate: Callable[[Dict[str, object]], bool]) -> Dict[str, object]:
    usable = [
        row
        for row in rows
        if row.get("final_human_decision_norm") in {"APPROVED", "REJECTED"}
        and (
            to_float(row.get("person_count_yolo_detect")) is not None
            or to_float(row.get("body_coverage_score_yolo_pose")) is not None
        )
    ]
    positives = [row for row in usable if row.get(f"truth_{reason}") is True]
    negatives = [row for row in usable if row.get(f"truth_{reason}") is False]
    approved_negatives = [row for row in negatives if row.get("final_human_decision_norm") == "APPROVED"]

    tp = sum(1 for row in positives if predicate(row))
    fn = sum(1 for row in positives if not predicate(row))
    fp = sum(1 for row in negatives if predicate(row))
    tn = sum(1 for row in negatives if not predicate(row))
    fp_approved = sum(1 for row in approved_negatives if predicate(row))
    tn_approved = sum(1 for row in approved_negatives if not predicate(row))
    return {
        "reason": reason,
        "rule": rule_name,
        "positive_rows": len(positives),
        "negative_rows": len(negatives),
        "approved_negative_rows": len(approved_negatives),
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "fp_approved": fp_approved,
        "tn_approved": tn_approved,
        "recall": round(tp / (tp + fn), 3) if tp + fn else "",
        "precision": round(tp / (tp + fp), 3) if tp + fp else "",
        "approved_false_flag_rate": round(fp_approved / (fp_approved + tn_approved), 3) if fp_approved + tn_approved else "",
    }


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_report(rows: List[Dict[str, object]], metrics: List[Dict[str, object]]) -> None:
    decisions = Counter(row.get("final_human_decision_norm") or "<blank>" for row in rows)
    reason_counts = {
        reason: sum(1 for row in rows if row.get(f"truth_{reason}") is True)
        for reason in REASON_COLUMNS
    }
    lines = [
        "# Labeled Geometry Reason Experiment",
        "",
        "## Ground Truth Loaded",
        "",
        f"- labeled rows: `{len(rows)}`",
        f"- decision counts: `{dict(decisions)}`",
        "",
        "## Reason Coverage",
        "",
        "| reason | positive rows | enough for directional experiment |",
        "| --- | ---: | --- |",
    ]
    for reason, count in sorted(reason_counts.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"| `{reason}` | {count} | {'YES' if count >= 20 else 'NO'} |")

    lines.extend(["", "## Best Rules By Reason", ""])
    for reason in REASON_COLUMNS:
        reason_metrics = [row for row in metrics if row["reason"] == reason and row["recall"] != ""]
        if not reason_metrics:
            continue
        best = sorted(
            reason_metrics,
            key=lambda row: (
                -float(row["recall"]),
                float(row["approved_false_flag_rate"] if row["approved_false_flag_rate"] != "" else 1),
                -float(row["precision"] if row["precision"] != "" else 0),
            ),
        )[:5]
        lines.extend(
            [
                f"### {reason}",
                "",
                "| rule | recall | precision | approved false-flag rate |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for row in best:
            lines.append(f"| `{row['rule']}` | {row['recall']} | {row['precision']} | {row['approved_false_flag_rate']} |")
        lines.append("")

    lines.extend(
        [
            "## Recommendation",
            "",
            "The existing YOLO geometry columns are useful for `PERSON_TOO_FAR` and broad review-priority routing, but they are not specific enough to cleanly separate `NEEDS_CROP`, top-down angles, or covered garment regions. Those need a richer model family, most likely pose/keypoint geometry plus segmentation or crop-boundary analysis.",
            "",
        ]
    )
    (OUT_DIR / "labeled_geometry_reason_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, object]] = []
    for row in read_rows(GROUND_TRUTH_CSV):
        combined: Dict[str, object] = dict(row)
        combined["final_human_decision_norm"] = normalize_decision(row.get("final_human_decision", ""))
        for reason in REASON_COLUMNS:
            combined[f"truth_{reason}"] = truth_has_reason(row, reason)
        rows.append(combined)

    metrics = [
        evaluate_reason(rows, reason, rule_name, predicate)
        for reason in REASON_COLUMNS
        for rule_name, predicate in geometry_rules()
    ]
    write_csv(OUT_DIR / "labeled_geometry_reason_metrics.csv", metrics)
    write_report(rows, metrics)
    print(f"Wrote {OUT_DIR}")


if __name__ == "__main__":
    main()
