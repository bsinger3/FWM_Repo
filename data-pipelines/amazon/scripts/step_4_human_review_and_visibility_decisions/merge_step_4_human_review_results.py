#!/usr/bin/env python3
import argparse
from pathlib import Path

from csv_output_validation import validate_csv_file
from cv_rules_workflow_lib import (
    CV_RULES_DIR,
    FINAL_OUTPUT_COLUMNS,
    FINAL_RESOLVED_DIR,
    HUMAN_REVIEW_COLUMNS,
    read_csv_rows,
    resolve_final_rows,
    write_csv_rows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge an edited combined Step 4 review queue back into the rules-applied batch outputs."
    )
    parser.add_argument("--batch-name", required=True, help="Batch name used in the workflow output paths.")
    parser.add_argument("--edited-review-queue", type=Path, required=True, help="Path to the edited combined review CSV.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rules_dir = CV_RULES_DIR / args.batch_name
    if not rules_dir.exists():
        raise SystemExit("Rules-applied batch directory not found: {}".format(rules_dir))

    review_path = args.edited_review_queue.resolve()
    if not review_path.exists():
        raise SystemExit("Edited review queue not found: {}".format(review_path))
    validate_csv_file(review_path, "step4_review_queue")

    _review_headers, edited_review_rows = read_csv_rows(review_path)
    output_dir = FINAL_RESOLVED_DIR / args.batch_name
    resolved_total = 0

    for input_path in sorted(rules_dir.glob("*.csv")):
        fieldnames, rows = read_csv_rows(input_path)
        resolved_rows = resolve_final_rows(rows, edited_review_rows)
        output_fields = list(fieldnames)
        for column in HUMAN_REVIEW_COLUMNS + FINAL_OUTPUT_COLUMNS:
            if column not in output_fields:
                output_fields.append(column)
        write_csv_rows(
            output_dir / input_path.name,
            output_fields,
            resolved_rows,
            validation_profile="step4_final_resolved",
        )
        resolved_total += len(resolved_rows)

    print("Wrote resolved batch files to {}".format(output_dir))
    print("Resolved rows: {}".format(resolved_total))


if __name__ == "__main__":
    main()
