#!/usr/bin/env python3
"""Evaluate objective image-quality metrics against newly labeled reason data."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from experiment_image_quality_baseline import fetch_image, flag_row, quality_metrics  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[4]
GROUND_TRUTH_CSV = REPO_ROOT / "outputs/cv_experiments/ground_truth_labeling/labeled_image_rejection_reason_queue.csv"
OUT_DIR = REPO_ROOT / "outputs/cv_experiments/labeled_quality_reasons"

REASON_COLUMNS = [
    "TOO_DARK",
    "TOO_BRIGHT_OR_WASHED_OUT",
    "LOW_RESOLUTION",
    "GRAINY_OR_NOISY",
    "BLURRY_OR_MOTION_BLUR",
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


def quality_rules() -> List[Rule]:
    return [
        ("fetch_failed", lambda row: not bool(row.get("fetch_ok"))),
        ("luminance_mean_lt_45", lambda row: (to_float(row.get("luminance_mean")) or 999) < 45),
        ("luminance_mean_lt_55", lambda row: (to_float(row.get("luminance_mean")) or 999) < 55),
        ("luminance_mean_lt_65", lambda row: (to_float(row.get("luminance_mean")) or 999) < 65),
        ("dark_pixel_pct_gt_0.20", lambda row: (to_float(row.get("dark_pixel_pct")) or 0) > 0.20),
        ("dark_pixel_pct_gt_0.30", lambda row: (to_float(row.get("dark_pixel_pct")) or 0) > 0.30),
        ("dark_pixel_pct_gt_0.40", lambda row: (to_float(row.get("dark_pixel_pct")) or 0) > 0.40),
        ("bright_pixel_pct_gt_0.18", lambda row: (to_float(row.get("bright_pixel_pct")) or 0) > 0.18),
        ("min_dimension_lt_300", lambda row: min(to_float(row.get("width")) or 99999, to_float(row.get("height")) or 99999) < 300),
        ("pixels_lt_180k", lambda row: (to_float(row.get("pixels")) or 999999999) < 180_000),
        ("laplacian_variance_lt_55", lambda row: (to_float(row.get("laplacian_variance")) or 999999) < 55),
        ("laplacian_variance_lt_100", lambda row: (to_float(row.get("laplacian_variance")) or 999999) < 100),
    ]


def evaluate_reason(rows: List[Dict[str, object]], reason: str, rule_name: str, predicate: Callable[[Dict[str, object]], bool]) -> Dict[str, object]:
    usable = [row for row in rows if row.get("final_human_decision_norm") in {"APPROVED", "REJECTED"}]
    positives = [row for row in usable if row.get(f"truth_{reason}") is True]
    negatives = [row for row in usable if row.get(f"truth_{reason}") is False]

    tp = sum(1 for row in positives if predicate(row))
    fn = sum(1 for row in positives if not predicate(row))
    fp = sum(1 for row in negatives if predicate(row))
    tn = sum(1 for row in negatives if not predicate(row))
    approved_negatives = [row for row in negatives if row.get("final_human_decision_norm") == "APPROVED"]
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
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(rows: List[Dict[str, object]], metrics: List[Dict[str, object]]) -> None:
    decisions = Counter(row.get("final_human_decision_norm") or "<blank>" for row in rows)
    reason_counts = {
        reason: sum(1 for row in rows if row.get(f"truth_{reason}") is True)
        for reason in REASON_COLUMNS
    }

    lines = [
        "# Labeled Image-Quality Reason Experiment",
        "",
        "## Ground Truth Loaded",
        "",
        f"- labeled rows: `{len(rows)}`",
        f"- decision counts: `{dict(decisions)}`",
        f"- images fetched successfully: `{sum(1 for row in rows if row.get('fetch_ok'))}`",
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
            "`TOO_DARK` is close to enough new labels for a first objective-metric calibration, but still needs a few more positives before we treat accuracy numbers as stable. `LOW_RESOLUTION`, `TOO_BRIGHT_OR_WASHED_OUT`, `BLURRY_OR_MOTION_BLUR`, and `GRAINY_OR_NOISY` still need positive labels before we treat accuracy numbers as meaningful. Invalid image URLs should be handled as scraper/link hygiene before human visual labeling, not as a rejection reason in this ground-truth set.",
            "",
        ]
    )
    (OUT_DIR / "labeled_quality_reason_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    global OUT_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth-csv", default=str(GROUND_TRUTH_CSV))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--timeout", type=float, default=4.0)
    parser.add_argument("--retries", type=int, default=1)
    args = parser.parse_args()

    ground_truth_csv = Path(args.ground_truth_csv)
    OUT_DIR = Path(args.out_dir)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    source_rows = [
        row
        for row in read_rows(ground_truth_csv)
        if row.get("original_url_display", "").strip()
        and normalize_decision(row.get("final_human_decision", "")) in {"APPROVED", "REJECTED"}
    ]
    for index, row in enumerate(source_rows, start=1):
        combined: Dict[str, object] = dict(row)
        combined["final_human_decision_norm"] = normalize_decision(row.get("final_human_decision", ""))
        for reason in REASON_COLUMNS:
            combined[f"truth_{reason}"] = truth_has_reason(row, reason)
        image, fetch = fetch_image(row.get("original_url_display", ""), args.timeout, args.retries)
        combined.update({key: value for key, value in fetch.items() if key != "attempts"})
        if image is not None:
            combined.update(quality_metrics(image))
        combined.update(flag_row(combined))
        rows.append(combined)
        if index % 50 == 0:
            print(f"processed {index}/{len(source_rows)}", flush=True)

    metrics = [
        evaluate_reason(rows, reason, rule_name, predicate)
        for reason in REASON_COLUMNS
        for rule_name, predicate in quality_rules()
    ]
    row_fieldnames = sorted({key for row in rows for key in row})
    with (OUT_DIR / "labeled_quality_reason_rows.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=row_fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    write_csv(OUT_DIR / "labeled_quality_reason_metrics.csv", metrics)
    write_report(rows, metrics)
    print(f"Wrote {OUT_DIR}")


if __name__ == "__main__":
    main()
