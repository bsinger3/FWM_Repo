#!/usr/bin/env python3
"""Evaluate simple YOLO geometry rules for PERSON_TOO_FAR."""

from __future__ import annotations
import sys

import csv
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[4]
PIPELINE_SCRIPTS_DIR = REPO_ROOT / "data-pipelines" / "scripts"
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, cv_annotated_pending_human_review_root  # noqa: E402

LEGACY_OUTPUTS_ARCHIVE = archive_root() / "old_outputs" / "repo_outputs_archive" / "supabase_output_cleanup_2026_05_29"
CV_EXPERIMENTS_DIR = LEGACY_OUTPUTS_ARCHIVE / "cv_experiments"

PROJECT_ROOT = REPO_ROOT.parent
DATA_ROOT = PROJECT_ROOT / "FWM_Data"
PART002 = cv_annotated_pending_human_review_root() / "amazon_legacy_step_4_human_review_and_visibility_decisions" / "part_002_REVIEWED.csv"
EXPLICIT_REASONS = CV_EXPERIMENTS_DIR / "yolo_reason_baseline/explicit_reason_rows.csv"
OUT_DIR = CV_EXPERIMENTS_DIR / "person_too_far_yolo"

MANUAL_COL = "Manual_approval(1=approved,2=reject, 3=ApprovedANDLabel'Pretty\")"


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def to_float(value: str) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except ValueError:
        return None


def median(values: Iterable[float]) -> Optional[float]:
    items = sorted(values)
    if not items:
        return None
    midpoint = len(items) // 2
    if len(items) % 2:
        return items[midpoint]
    return (items[midpoint - 1] + items[midpoint]) / 2


def pct(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:.3f}"


def collect_examples() -> List[Dict[str, object]]:
    explicit = read_csv(EXPLICIT_REASONS)
    explicit_by_key = {row["review_row_key"]: row for row in explicit if row.get("dataset") == "part002"}
    person_too_far_keys = {
        key for key, row in explicit_by_key.items() if "PERSON_TOO_FAR" in row.get("reason_codes", "")
    }
    other_reason_keys = set(explicit_by_key) - person_too_far_keys

    rows: List[Dict[str, object]] = []
    for source in read_csv(PART002):
        key = source.get("review_row_key", "")
        manual = source.get(MANUAL_COL, "")
        height = to_float(source.get("main_person_height_pct_yolo_detect", ""))
        area = to_float(source.get("main_person_bbox_area_pct_yolo_detect", ""))
        coverage = to_float(source.get("body_coverage_score_yolo_pose", ""))
        person_count = to_float(source.get("person_count_yolo_detect", ""))
        if height is None and area is None and coverage is None:
            continue

        if key in person_too_far_keys:
            label = "PERSON_TOO_FAR"
            human_reason = explicit_by_key[key].get("human_reason", "")
        elif key in other_reason_keys:
            label = "OTHER_EXPLICIT_REJECT_REASON"
            human_reason = explicit_by_key[key].get("human_reason", "")
        elif manual in {"1", "3"}:
            label = "APPROVED_CONTROL"
            human_reason = ""
        else:
            continue

        rows.append(
            {
                "review_row_key": key,
                "image_url": source.get("original_url_display", ""),
                "label": label,
                "human_reason": human_reason,
                "person_count": person_count,
                "subject_height": height,
                "subject_area": area,
                "body_coverage": coverage,
                "cv_reason_code": source.get("cv_reason_code", ""),
            }
        )
    return rows


Rule = Tuple[str, Callable[[Dict[str, object]], bool]]


def build_rules() -> List[Rule]:
    rules: List[Rule] = []
    for threshold in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
        rules.append(
            (
                f"subject_height_lt_{threshold:.2f}",
                lambda row, threshold=threshold: row["subject_height"] is not None
                and float(row["subject_height"]) < threshold,
            )
        )
    for threshold in [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]:
        rules.append(
            (
                f"subject_area_lt_{threshold:.2f}",
                lambda row, threshold=threshold: row["subject_area"] is not None
                and float(row["subject_area"]) < threshold,
            )
        )
    for height_threshold, area_threshold in [(0.60, 0.25), (0.65, 0.30), (0.70, 0.35), (0.75, 0.35)]:
        rules.append(
            (
                f"height_lt_{height_threshold:.2f}_or_area_lt_{area_threshold:.2f}",
                lambda row, height_threshold=height_threshold, area_threshold=area_threshold: (
                    row["subject_height"] is not None and float(row["subject_height"]) < height_threshold
                )
                or (row["subject_area"] is not None and float(row["subject_area"]) < area_threshold),
            )
        )
    return rules


def evaluate_rule(rows: List[Dict[str, object]], rule_name: str, predicate: Callable[[Dict[str, object]], bool]) -> Dict[str, object]:
    positives = [row for row in rows if row["label"] == "PERSON_TOO_FAR"]
    approved_controls = [row for row in rows if row["label"] == "APPROVED_CONTROL"]
    explicit_other = [row for row in rows if row["label"] == "OTHER_EXPLICIT_REJECT_REASON"]
    negatives = approved_controls + explicit_other

    tp = sum(1 for row in positives if predicate(row))
    fn = sum(1 for row in positives if not predicate(row))
    fp_approved = sum(1 for row in approved_controls if predicate(row))
    tn_approved = sum(1 for row in approved_controls if not predicate(row))
    fp_other = sum(1 for row in explicit_other if predicate(row))
    tn_other = sum(1 for row in explicit_other if not predicate(row))
    fp_total = fp_approved + fp_other
    tn_total = tn_approved + tn_other

    precision = tp / (tp + fp_total) if tp + fp_total else None
    approved_false_flag_rate = fp_approved / (fp_approved + tn_approved) if fp_approved + tn_approved else None
    other_reason_false_flag_rate = fp_other / (fp_other + tn_other) if fp_other + tn_other else None
    return {
        "rule": rule_name,
        "positive_person_too_far_rows": len(positives),
        "approved_control_rows": len(approved_controls),
        "other_explicit_reject_reason_rows": len(explicit_other),
        "tp_person_too_far": tp,
        "fn_person_too_far": fn,
        "fp_approved_flagged": fp_approved,
        "fp_other_reason_flagged": fp_other,
        "tn_approved_clear": tn_approved,
        "tn_other_reason_clear": tn_other,
        "recall_person_too_far": pct(tp / (tp + fn) if tp + fn else None),
        "precision_vs_all_controls": pct(precision),
        "approved_false_flag_rate": pct(approved_false_flag_rate),
        "other_reason_false_flag_rate": pct(other_reason_false_flag_rate),
    }


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_report(rows: List[Dict[str, object]], metrics: List[Dict[str, object]]) -> None:
    labels = {label: [row for row in rows if row["label"] == label] for label in ["PERSON_TOO_FAR", "APPROVED_CONTROL", "OTHER_EXPLICIT_REJECT_REASON"]}
    best_conservative = sorted(
        metrics,
        key=lambda row: (
            float(row["approved_false_flag_rate"] or 1),
            -float(row["recall_person_too_far"] or 0),
        ),
    )[:5]
    best_balanced = sorted(
        metrics,
        key=lambda row: (
            -float(row["recall_person_too_far"] or 0),
            float(row["approved_false_flag_rate"] or 1),
        ),
    )[:5]

    lines = [
        "# PERSON_TOO_FAR YOLO Geometry Experiment",
        "",
        "## Ground Truth",
        "",
        f"- positive `PERSON_TOO_FAR` rows with YOLO geometry: `{len(labels['PERSON_TOO_FAR'])}`",
        f"- approved control rows with YOLO geometry: `{len(labels['APPROVED_CONTROL'])}`",
        f"- other explicit rejection-reason rows with YOLO geometry: `{len(labels['OTHER_EXPLICIT_REJECT_REASON'])}`",
        "",
        "This is enough for a first directional experiment for `PERSON_TOO_FAR`, but still too small for final production thresholds. The false-positive review should focus on approved controls because those are the images we most want to avoid rejecting automatically.",
        "",
        "## Geometry Distributions",
        "",
        "| label | count | median subject height | median subject area | median body coverage |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for label, group in labels.items():
        lines.append(
            "| `{}` | {} | {} | {} | {} |".format(
                label,
                len(group),
                pct(median(float(row["subject_height"]) for row in group if row["subject_height"] is not None)),
                pct(median(float(row["subject_area"]) for row in group if row["subject_area"] is not None)),
                pct(median(float(row["body_coverage"]) for row in group if row["body_coverage"] is not None)),
            )
        )

    lines.extend(
        [
            "",
            "## Most Conservative Rules",
            "",
            "| rule | recall | approved false-flag rate | precision vs all controls |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in best_conservative:
        lines.append(
            f"| `{row['rule']}` | {row['recall_person_too_far']} | {row['approved_false_flag_rate']} | {row['precision_vs_all_controls']} |"
        )

    lines.extend(
        [
            "",
            "## Highest Recall Rules",
            "",
            "| rule | recall | approved false-flag rate | precision vs all controls |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in best_balanced:
        lines.append(
            f"| `{row['rule']}` | {row['recall_person_too_far']} | {row['approved_false_flag_rate']} | {row['precision_vs_all_controls']} |"
        )

    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            "Use YOLO person-box geometry as a review-priority signal for `PERSON_TOO_FAR`, not as an automatic rejection rule yet. A threshold around subject height `< 0.60` is conservative, while `< 0.70` catches more true `PERSON_TOO_FAR` images but starts to flag more approved controls. The next labeling sheet should collect more explicit `PERSON_TOO_FAR` negatives and borderline examples before we freeze a threshold.",
            "",
        ]
    )
    (OUT_DIR / "person_too_far_yolo_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = collect_examples()
    metrics = [evaluate_rule(rows, name, predicate) for name, predicate in build_rules()]
    write_csv(OUT_DIR / "person_too_far_eval_rows.csv", rows)
    write_csv(OUT_DIR / "person_too_far_threshold_metrics.csv", metrics)
    write_report(rows, metrics)
    print(f"Wrote {OUT_DIR}")


if __name__ == "__main__":
    main()
