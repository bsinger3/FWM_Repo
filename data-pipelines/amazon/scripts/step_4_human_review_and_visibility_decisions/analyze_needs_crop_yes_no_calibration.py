#!/usr/bin/env python3
"""Analyze human yes/no NEEDS_CROP calibration labels against YOLO features."""

from __future__ import annotations

import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
EXP_DIR = REPO_ROOT / "outputs/cv_experiments/yolo_segmentation_crop_reasons_broad_2026_05_25"
LABELED_CSV = EXP_DIR / "needs_crop_calibration_labeled_2026_05_25/needs_crop_yes_no_review_queue_labeled.csv"
OUT_DIR = EXP_DIR / "needs_crop_calibration_labeled_2026_05_25"
METRICS_CSV = OUT_DIR / "needs_crop_yes_no_threshold_metrics.csv"
ROWS_CSV = OUT_DIR / "needs_crop_yes_no_scored_rows.csv"
REPORT_MD = OUT_DIR / "needs_crop_yes_no_calibration_report.md"


def read_rows() -> list[dict[str, str]]:
    with LABELED_CSV.open(newline="", encoding="utf-8-sig") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if (row.get("needs_crop_yes_no") or "").strip().upper() in {"YES", "NO"}
        ]


def to_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except ValueError:
        return default


def answer_yes(row: dict[str, str]) -> bool:
    return (row.get("needs_crop_yes_no") or "").strip().upper() == "YES"


def score_threshold(rows: list[dict[str, str]], feature: str, threshold: float, op: str) -> dict[str, object]:
    def pred(row: dict[str, str]) -> bool:
        value = to_float(row.get(feature), default=999.0 if op == "lt" else -999.0)
        return value < threshold if op == "lt" else value > threshold

    positives = [row for row in rows if answer_yes(row)]
    negatives = [row for row in rows if not answer_yes(row)]
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
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows = read_rows()
    metrics: list[dict[str, object]] = []
    for threshold in [0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25, 0.30, 0.35]:
        metrics.append(score_threshold(rows, "seg_mask_area_pct", threshold, "lt"))
    for threshold in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
        metrics.append(score_threshold(rows, "seg_bbox_area_pct", threshold, "lt"))
    for threshold in [0.65, 0.70, 0.75, 0.80, 0.85]:
        metrics.append(score_threshold(rows, "seg_bbox_height_pct", threshold, "lt"))

    scored_rows: list[dict[str, object]] = []
    for row in rows:
        scored = dict(row)
        scored["truth_needs_crop_yes"] = answer_yes(row)
        scored["pred_mask_area_lt_0_20"] = to_float(row.get("seg_mask_area_pct"), default=999.0) < 0.20
        scored["pred_mask_area_lt_0_25"] = to_float(row.get("seg_mask_area_pct"), default=999.0) < 0.25
        scored["pred_bbox_area_lt_0_45"] = to_float(row.get("seg_bbox_area_pct"), default=999.0) < 0.45
        scored_rows.append(scored)

    write_csv(METRICS_CSV, metrics)
    write_csv(ROWS_CSV, scored_rows)

    best = sorted(
        metrics,
        key=lambda row: (
            -float(row["recall"] or 0),
            -float(row["specificity"] or 0),
            -float(row["precision"] or 0),
        ),
    )[:8]
    answer_counts = {
        "YES": sum(1 for row in rows if answer_yes(row)),
        "NO": sum(1 for row in rows if not answer_yes(row)),
    }
    lines = [
        "# NEEDS_CROP Yes/No Calibration",
        "",
        f"- reviewed rows: `{len(rows)}`",
        f"- answer counts: `{answer_counts}`",
        "",
        "## Best Thresholds",
        "",
        "| feature | op | threshold | recall | precision | false positive rate | specificity | TP | FN | FP | TN |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in best:
        lines.append(
            "| `{}` | `{}` | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                row["feature"],
                row["operator"],
                row["threshold"],
                row["recall"],
                row["precision"],
                row["false_positive_rate"],
                row["specificity"],
                row["tp"],
                row["fn"],
                row["fp"],
                row["tn"],
            )
        )

    selected = [row for row in metrics if row["feature"] == "seg_mask_area_pct" and row["threshold"] == 0.2][0]
    lines.extend(
        [
            "",
            "## Current Rule",
            "",
            "Current rule: `seg_mask_area_pct < 0.20`.",
            "",
            f"- recall: `{selected['recall']}`",
            f"- precision: `{selected['precision']}`",
            f"- false positive rate: `{selected['false_positive_rate']}`",
            f"- confusion matrix: TP `{selected['tp']}`, FN `{selected['fn']}`, FP `{selected['fp']}`, TN `{selected['tn']}`",
            "",
            "## Interpretation",
            "",
            "This yes/no calibration queue was intentionally enriched for likely crop cases, so it is good for tuning recall/missed-crop behavior but not for estimating real-world prevalence. Because only two rows were labeled `NO`, false-positive estimates are still very unstable. The next queue should include more model-negative and approved-control rows if we want a reliable production threshold.",
            "",
        ]
    )
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(REPORT_MD)


if __name__ == "__main__":
    main()
