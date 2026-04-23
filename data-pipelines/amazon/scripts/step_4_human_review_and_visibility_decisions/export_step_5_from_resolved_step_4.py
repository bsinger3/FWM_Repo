#!/usr/bin/env python3
import argparse
from pathlib import Path

from csv_output_validation import validate_csv_file
from cv_rules_workflow_lib import (
    FINAL_RESOLVED_DIR,
    STEP5_FINAL_DIR,
    export_step5_rows,
    read_csv_rows,
    unresolved_review_count,
    write_csv_rows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Step 5-ready approved rows from a resolved Step 4 batch."
    )
    parser.add_argument("--batch-name", required=True, help="Batch name used in the workflow output paths.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    resolved_dir = FINAL_RESOLVED_DIR / args.batch_name
    if not resolved_dir.exists():
        raise SystemExit("Resolved batch directory not found: {}".format(resolved_dir))

    output_dir = STEP5_FINAL_DIR / args.batch_name
    exported_rows = 0

    for input_path in sorted(resolved_dir.glob("*.csv")):
        validate_csv_file(input_path, "step4_final_resolved")
        fieldnames, rows = read_csv_rows(input_path)
        unresolved = unresolved_review_count(rows)
        if unresolved:
            raise SystemExit(
                "Cannot export {} because {} review rows are unresolved in {}".format(
                    args.batch_name, unresolved, input_path.name
                )
            )
        step5_rows = export_step5_rows(rows)
        if not step5_rows:
            continue
        step5_headers = list(step5_rows[0].keys())
        write_csv_rows(
            output_dir / input_path.name,
            step5_headers,
            step5_rows,
            validation_profile="step5_publish_ready",
        )
        exported_rows += len(step5_rows)

    print("Wrote Step 5-ready files to {}".format(output_dir))
    print("Exported approved rows: {}".format(exported_rows))


if __name__ == "__main__":
    main()
