#!/usr/bin/env python3
"""Analyze the completed combined rejection-reason yes/no ground truth."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = REPO_ROOT / "outputs/cv_experiments/combined_reason_ground_truth_2026_05_25"
LABELED_DIR = OUT_DIR / "labeled_2026_05_27"
LABELED_CSV = LABELED_DIR / "combined_rejection_reason_yes_no_review_queue_labeled.csv"
SUMMARY_CSV = LABELED_DIR / "combined_rejection_reason_yes_no_summary.csv"
REPORT_MD = LABELED_DIR / "combined_rejection_reason_yes_no_report.md"


def normalize_answer(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"Y", "YES", "TRUE", "1"}:
        return "YES"
    if text in {"N", "NO", "FALSE", "0"}:
        return "NO"
    if text in {"UNSURE", "UNKNOWN", "MAYBE", "?"}:
        return "UNSURE"
    return "<blank>"


def read_rows() -> list[dict[str, str]]:
    with LABELED_CSV.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    rows = read_rows()
    by_reason: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        by_reason[row.get("rejection_reason", "")][normalize_answer(row.get("answer_yes_no"))] += 1

    summary_rows = []
    for reason in sorted(by_reason):
        counts = by_reason[reason]
        total = sum(counts.values())
        summary_rows.append(
            {
                "rejection_reason": reason,
                "rows": total,
                "yes": counts.get("YES", 0),
                "no": counts.get("NO", 0),
                "unsure": counts.get("UNSURE", 0),
                "blank": counts.get("<blank>", 0),
                "yes_rate": round(counts.get("YES", 0) / total, 3) if total else "",
            }
        )

    with SUMMARY_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    total_counts = Counter(normalize_answer(row.get("answer_yes_no")) for row in rows)
    lines = [
        "# Combined Rejection Reason Yes/No Ground Truth",
        "",
        f"- labeled rows: `{len(rows)}`",
        f"- answer counts: `{dict(total_counts)}`",
        f"- source CSV: `{LABELED_CSV}`",
        "",
        "## Counts By Reason",
        "",
        "| reason | rows | YES | NO | UNSURE | YES rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(
            f"| `{row['rejection_reason']}` | {row['rows']} | {row['yes']} | {row['no']} | {row['unsure']} | {row['yes_rate']} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "`LOW_RESOLUTION` labels should be interpreted only after image URL upgrade has been attempted. If a larger image URL can be resolved, downstream image approval should use the larger URL and re-evaluate the resolution label.",
            "",
        ]
    )
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(REPORT_MD)


if __name__ == "__main__":
    main()
