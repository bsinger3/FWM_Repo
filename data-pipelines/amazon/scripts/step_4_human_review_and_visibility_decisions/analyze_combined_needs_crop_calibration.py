#!/usr/bin/env python3
"""Analyze combined NEEDS_CROP yes/no calibration and control labels."""

from __future__ import annotations
import sys

import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
PIPELINE_SCRIPTS_DIR = REPO_ROOT / "data-pipelines" / "scripts"
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, cv_annotated_pending_human_review_root  # noqa: E402

LEGACY_OUTPUTS_ARCHIVE = archive_root() / "old_outputs" / "repo_outputs_archive" / "supabase_output_cleanup_2026_05_29"
CV_EXPERIMENTS_DIR = LEGACY_OUTPUTS_ARCHIVE / "cv_experiments"

EXP_DIR = CV_EXPERIMENTS_DIR / "yolo_segmentation_crop_reasons_broad_2026_05_25"
POSITIVE_ENRICHED_CSV = EXP_DIR / "needs_crop_calibration_labeled_2026_05_25/needs_crop_yes_no_review_queue_labeled.csv"
CONTROL_CSV = EXP_DIR / "needs_crop_control_labeled_2026_05_25/needs_crop_yes_no_control_review_queue_labeled.csv"
OUT_DIR = EXP_DIR / "needs_crop_combined_calibration_2026_05_25"
METRICS_CSV = OUT_DIR / "combined_needs_crop_threshold_metrics.csv"
ROWS_CSV = OUT_DIR / "combined_needs_crop_scored_rows.csv"
REPORT_MD = OUT_DIR / "combined_needs_crop_calibration_report.md"


def read_labeled(path: Path, source: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = []
        for row in csv.DictReader(handle):
            answer = (row.get("needs_crop_yes_no") or "").strip().upper()
            if answer not in {"YES", "NO"}:
                continue
            row["calibration_source"] = source
            row["needs_crop_answer_norm"] = answer
            rows.append(row)
        return rows


def to_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except ValueError:
        return default


def is_yes(row: dict[str, str]) -> bool:
    return row.get("needs_crop_answer_norm") == "YES"


def score_threshold(rows: list[dict[str, str]], feature: str, threshold: float, op: str) -> dict[str, object]:
    def pred(row: dict[str, str]) -> bool:
        value = to_float(row.get(feature), default=999.0 if op == "lt" else -999.0)
        return value < threshold if op == "lt" else value > threshold

    positives = [row for row in rows if is_yes(row)]
    negatives = [row for row in rows if not is_yes(row)]
    tp = sum(1 for row in positives if pred(row))
    fn = sum(1 for row in positives if not pred(row))
    fp = sum(1 for row in negatives if pred(row))
    tn = sum(1 for row in negatives if not pred(row))
    return {
        "feature": feature,
        "operator": op,
        "threshold": threshold,
        "positive_rows": len(positives),
        "negative_rows": len(negatives),
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "recall": round(tp / (tp + fn), 3) if tp + fn else "",
        "precision": round(tp / (tp + fp), 3) if tp + fp else "",
        "false_positive_rate": round(fp / (fp + tn), 3) if fp + tn else "",
        "specificity": round(tn / (fp + tn), 3) if fp + tn else "",
        "accuracy": round((tp + tn) / len(rows), 3) if rows else "",
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = read_labeled(POSITIVE_ENRICHED_CSV, "positive_enriched") + read_labeled(CONTROL_CSV, "control")

    metrics: list[dict[str, object]] = []
    for threshold in [0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25, 0.30, 0.35]:
        metrics.append(score_threshold(rows, "seg_mask_area_pct", threshold, "lt"))
    for threshold in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
        metrics.append(score_threshold(rows, "seg_bbox_area_pct", threshold, "lt"))
    for threshold in [0.65, 0.70, 0.75, 0.80, 0.85]:
        metrics.append(score_threshold(rows, "seg_bbox_height_pct", threshold, "lt"))

    scored = []
    for row in rows:
        item = dict(row)
        item["truth_needs_crop_yes"] = is_yes(row)
        item["pred_mask_area_lt_0_18"] = to_float(row.get("seg_mask_area_pct"), default=999.0) < 0.18
        item["pred_mask_area_lt_0_20"] = to_float(row.get("seg_mask_area_pct"), default=999.0) < 0.20
        item["pred_mask_area_lt_0_22"] = to_float(row.get("seg_mask_area_pct"), default=999.0) < 0.22
        item["pred_mask_area_lt_0_25"] = to_float(row.get("seg_mask_area_pct"), default=999.0) < 0.25
        scored.append(item)

    write_csv(METRICS_CSV, metrics)
    write_csv(ROWS_CSV, scored)

    by_accuracy = sorted(
        metrics,
        key=lambda row: (
            -float(row["accuracy"] or 0),
            -float(row["recall"] or 0),
            -float(row["precision"] or 0),
        ),
    )[:8]
    by_recall_with_reasonable_fp = sorted(
        [row for row in metrics if float(row["false_positive_rate"] or 1) <= 0.25],
        key=lambda row: (-float(row["recall"] or 0), -float(row["precision"] or 0)),
    )[:8]
    current = [row for row in metrics if row["feature"] == "seg_mask_area_pct" and row["threshold"] == 0.2][0]
    answer_counts = {
        "YES": sum(1 for row in rows if is_yes(row)),
        "NO": sum(1 for row in rows if not is_yes(row)),
    }
    source_counts = {}
    for row in rows:
        source_counts[row["calibration_source"]] = source_counts.get(row["calibration_source"], 0) + 1

    lines = [
        "# Combined NEEDS_CROP Calibration",
        "",
        f"- reviewed rows: `{len(rows)}`",
        f"- answer counts: `{answer_counts}`",
        f"- source counts: `{source_counts}`",
        "",
        "## Best Thresholds By Accuracy",
        "",
        "| feature | op | threshold | recall | precision | false positive rate | specificity | accuracy | TP | FN | FP | TN |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in by_accuracy:
        lines.append(
            "| `{}` | `{}` | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                row["feature"], row["operator"], row["threshold"], row["recall"], row["precision"],
                row["false_positive_rate"], row["specificity"], row["accuracy"], row["tp"], row["fn"], row["fp"], row["tn"]
            )
        )

    lines.extend(
        [
            "",
            "## Highest Recall With False Positive Rate <= 25%",
            "",
            "| feature | op | threshold | recall | precision | false positive rate | specificity | accuracy |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in by_recall_with_reasonable_fp:
        lines.append(
            f"| `{row['feature']}` | `{row['operator']}` | {row['threshold']} | {row['recall']} | {row['precision']} | {row['false_positive_rate']} | {row['specificity']} | {row['accuracy']} |"
        )

    lines.extend(
        [
            "",
            "## Current Rule",
            "",
            "Current rule: `seg_mask_area_pct < 0.20`.",
            "",
            f"- recall: `{current['recall']}`",
            f"- precision: `{current['precision']}`",
            f"- false positive rate: `{current['false_positive_rate']}`",
            f"- specificity: `{current['specificity']}`",
            f"- accuracy: `{current['accuracy']}`",
            f"- confusion matrix: TP `{current['tp']}`, FN `{current['fn']}`, FP `{current['fp']}`, TN `{current['tn']}`",
            "",
            "## Recommendation",
            "",
            "`seg_mask_area_pct < 0.20` is a reasonable review-priority threshold: it catches most crop-needed images while keeping false positives materially lower than the more aggressive thresholds. It should not be used as an automatic rejection rule yet. The next production shape should be a two-tier rule: a conservative auto-crop/review-priority threshold around `0.18-0.20`, plus a higher-recall borderline band up to about `0.25` for manual review or LLM confirmation.",
            "",
        ]
    )
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(REPORT_MD)


if __name__ == "__main__":
    main()
