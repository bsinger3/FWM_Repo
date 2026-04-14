#!/usr/bin/env python3
import csv
from pathlib import Path
from typing import Dict, List


PIPELINE_ROOT = Path(__file__).resolve().parents[2]
STEP4_DIR = PIPELINE_ROOT / "data" / "step_4_human_review_and_visibility_decisions"
OUTPUT_DIR = STEP4_DIR / "capped_measurement_person_chunks"
REPORT_PATH = PIPELINE_ROOT / "docs" / "step_4_capped_measurement_person_chunks_report.md"

INPUT_GLOB = "images_to_approve_part_*.csv"
OUTPUT_BASENAME = "images_to_approve_capped_measurement_person"
CHUNK_SIZE = 3000
TRUE_VALUES = {"1", "true", "yes", "y", "t"}
MEASUREMENT_FIELDS = [
    "height_raw",
    "weight_raw",
    "height_in_display",
    "weight_display_display",
    "weight_lbs_display",
    "inseam_inches_display",
    "waist_raw_display",
    "waist_in",
    "hips_raw",
    "hips_in_display",
    "bust_in_number_display",
    "cupsize_display",
]


def is_true(value: str) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def has_measurement_value(row: Dict[str, str]) -> bool:
    measurement_count = (row.get("measurement_count_REVIEWONLY") or "").strip()
    if measurement_count:
        try:
            if float(measurement_count) > 0:
                return True
        except ValueError:
            pass

    for field_name in MEASUREMENT_FIELDS:
        if (row.get(field_name) or "").strip():
            return True
    return False


def iter_input_files() -> List[Path]:
    return sorted(STEP4_DIR.glob(INPUT_GLOB))


def load_filtered_rows(files: List[Path]) -> List[Dict[str, str]]:
    filtered_rows: List[Dict[str, str]] = []
    for path in files:
        with path.open("r", encoding="utf-8", newline="") as infile:
            reader = csv.DictReader(infile)
            if not reader.fieldnames:
                raise SystemExit("Missing CSV header in {}".format(path))
            for row in reader:
                if not is_true(row.get("has_person", "")):
                    continue
                if is_true(row.get("exceeds_cap", "")):
                    continue
                if not has_measurement_value(row):
                    continue
                filtered_rows.append(row)
    return filtered_rows


def write_chunk(path: Path, header: List[str], rows: List[Dict[str, str]]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=header)
        writer.writeheader()
        writer.writerows({name: row.get(name, "") for name in header} for row in rows)
    temp_path.replace(path)


def write_report(total_rows: int, kept_rows: int, chunk_count: int) -> None:
    lines = [
        "# Step 4 Capped Measurement Person Chunks Report",
        "",
        "This report describes the derived Step 4 chunk set created for upload preparation.",
        "",
        "Filter rules:",
        "",
        "- keep only rows where `has_person = true`",
        "- remove rows where `exceeds_cap = 1`",
        "- keep only rows with at least one measurement value",
        "- preserve the Step 4 column layout",
        "",
        "- source rows scanned: `{}`".format(total_rows),
        "- rows kept after filtering: `{}`".format(kept_rows),
        "- output chunk count: `{}`".format(chunk_count),
        "- output folder: `{}`".format(OUTPUT_DIR),
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    files = iter_input_files()
    if not files:
        raise SystemExit("No Step 4 chunk files found.")

    with files[0].open("r", encoding="utf-8", newline="") as infile:
        reader = csv.DictReader(infile)
        if not reader.fieldnames:
            raise SystemExit("Missing CSV header in {}".format(files[0]))
        header = list(reader.fieldnames)

    total_rows = 0
    for path in files:
        with path.open("r", encoding="utf-8", newline="") as infile:
            reader = csv.DictReader(infile)
            for _ in reader:
                total_rows += 1

    filtered_rows = load_filtered_rows(files)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for old_file in OUTPUT_DIR.glob("*.csv"):
        old_file.unlink()

    chunk_count = 0
    for start in range(0, len(filtered_rows), CHUNK_SIZE):
        chunk_count += 1
        chunk_rows = filtered_rows[start : start + CHUNK_SIZE]
        output_path = OUTPUT_DIR / "{}_part_{:03d}.csv".format(OUTPUT_BASENAME, chunk_count)
        write_chunk(output_path, header, chunk_rows)

    write_report(total_rows, len(filtered_rows), chunk_count)
    print("Wrote {} rows into {} chunk files at {}".format(len(filtered_rows), chunk_count, OUTPUT_DIR))
    print("Wrote {}".format(REPORT_PATH))


if __name__ == "__main__":
    main()
