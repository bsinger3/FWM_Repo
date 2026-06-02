#!/usr/bin/env python3
"""Compare first fit-image sorter output against available ground truth."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SORTER_DIR = REPO_ROOT / "outputs/cv_experiments/fit_image_sorter_2026_05_27"
SORTER_CSV = SORTER_DIR / "fit_image_sorter_results.csv"
GROUND_TRUTH_CSV = REPO_ROOT / "outputs/cv_experiments/ground_truth_labeling_broad/labeled_2026_05_25/usable_labeled_ground_truth_normalized.csv"
REPORT_MD = SORTER_DIR / "fit_image_sorter_ground_truth_comparison.md"
MISSES_CSV = SORTER_DIR / "fit_image_sorter_known_reject_misses.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    sorter_rows = read_csv(SORTER_CSV)
    gt_by_key = {row["review_row_key"]: row for row in read_csv(GROUND_TRUTH_CSV)}

    cross = Counter()
    misses = []
    for row in sorter_rows:
        gt = gt_by_key.get(row.get("review_row_key", ""), {})
        gt_decision = (gt.get("final_human_decision") or "<missing>").upper()
        cross[(row.get("sort_decision", ""), gt_decision)] += 1
        if row.get("sort_decision") == "APPROVE_CANDIDATE" and gt_decision == "REJECTED":
            item = dict(row)
            item["ground_truth_primary_reason_code"] = gt.get("primary_reason_code", "")
            item["ground_truth_secondary_reason_code"] = gt.get("secondary_reason_code", "")
            item["ground_truth_labeler_notes"] = gt.get("labeler_notes", "")
            misses.append(item)

    with MISSES_CSV.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "review_row_key",
            "ground_truth_primary_reason_code",
            "ground_truth_secondary_reason_code",
            "sort_decision",
            "primary_action",
            "reason_codes",
            "debug_summary",
            "original_url_display",
            "sort_image_url",
            "ground_truth_labeler_notes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in misses:
            writer.writerow({field: row.get(field, "") for field in fieldnames})

    miss_reasons = Counter(row.get("ground_truth_primary_reason_code") or "<blank>" for row in misses)
    lines = [
        "# Fit Image Sorter vs Ground Truth",
        "",
        f"- sorter rows: `{len(sorter_rows)}`",
        f"- known rejected rows incorrectly marked `APPROVE_CANDIDATE`: `{len(misses)}`",
        f"- miss CSV: `{MISSES_CSV}`",
        "",
        "## Decision Cross Tab",
        "",
        "| sorter decision | ground truth decision | rows |",
        "| --- | --- | ---: |",
    ]
    for (sort_decision, gt_decision), count in sorted(cross.items()):
        lines.append(f"| `{sort_decision}` | `{gt_decision}` | {count} |")

    lines.extend(["", "## Known Reject Misses By Primary Reason", "", "| reason | misses |", "| --- | ---: |"])
    for reason, count in miss_reasons.most_common():
        lines.append(f"| `{reason}` | {count} |")

    if misses:
        interpretation = (
            "The sorter still has known rejected rows escaping as `APPROVE_CANDIDATE`. "
            "Those misses should become the next threshold or LLM-routing fixes."
        )
    else:
        interpretation = (
            "No known rejected rows escaped as `APPROVE_CANDIDATE`. In this version, "
            "objective checks only assign routing/actions; final approval still requires "
            "the `LLM_APPROVAL_CONFIRMATION` stage."
        )
    lines.extend(["", "## Interpretation", "", interpretation, ""])
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(REPORT_MD)


if __name__ == "__main__":
    main()
