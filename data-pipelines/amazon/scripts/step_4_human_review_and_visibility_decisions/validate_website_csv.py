#!/usr/bin/env python3
import argparse
from pathlib import Path

from csv_output_validation import CsvValidationError, validate_csv_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Amazon website-bound CSV files for header integrity and column value types. "
            "This catches problems like duplicate headers, shifted columns, and bad data types."
        )
    )
    parser.add_argument("paths", nargs="+", type=Path, help="One or more CSV files to validate.")
    parser.add_argument(
        "--profile",
        default="auto",
        choices=[
            "auto",
            "step2_normalized",
            "step3_raw_input",
            "step3_machine_annotated",
            "step4_manual_chunk",
            "step4_cv_enriched",
            "step4_cv_rules",
            "step4_review_queue",
            "step4_final_resolved",
            "step5_publish_ready",
        ],
        help="Validation profile. Use `auto` to infer the schema from the header.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    failures = 0
    for path in args.paths:
        resolved = path.resolve()
        if not resolved.exists():
            print("MISSING {}".format(resolved))
            failures += 1
            continue
        try:
            profile, row_count = validate_csv_file(resolved, args.profile)
        except CsvValidationError as exc:
            print("FAIL {}".format(resolved))
            print(str(exc))
            failures += 1
            continue
        print("OK {} [{} rows, profile={}]".format(resolved, row_count, profile))

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
