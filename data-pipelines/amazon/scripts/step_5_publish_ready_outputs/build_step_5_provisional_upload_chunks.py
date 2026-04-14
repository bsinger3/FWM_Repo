#!/usr/bin/env python3
import csv
from pathlib import Path
from typing import Dict, List


PIPELINE_ROOT = Path(__file__).resolve().parents[2]
STEP4_SOURCE_DIR = (
    PIPELINE_ROOT
    / "data"
    / "step_4_human_review_and_visibility_decisions"
    / "capped_measurement_person_chunks"
)
STEP5_DIR = PIPELINE_ROOT / "data" / "step_5_publish_ready_outputs"
OUTPUT_DIR = STEP5_DIR / "pre_human_approval_upload_candidates"
SAMPLE_PATH = PIPELINE_ROOT / "docs" / "images_intake_sample - sampleOutput1.csv"
REPORT_PATH = PIPELINE_ROOT / "docs" / "step_5_provisional_upload_candidates_report.md"

INPUT_GLOB = "images_to_approve_capped_measurement_person_part_*.csv"
OUTPUT_BASENAME = "images_upload_candidates_part"
CHUNK_SIZE = 3000


def load_sample_header() -> List[str]:
    with SAMPLE_PATH.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.reader(infile)
        header = next(reader, None)
    if not header:
        raise SystemExit("Could not read Step 5 sample header from {}".format(SAMPLE_PATH))
    return header


def iter_source_files() -> List[Path]:
    return sorted(STEP4_SOURCE_DIR.glob(INPUT_GLOB))


def load_source_rows(files: List[Path]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for path in files:
        with path.open("r", encoding="utf-8", newline="") as infile:
            reader = csv.DictReader(infile)
            if not reader.fieldnames:
                raise SystemExit("Missing CSV header in {}".format(path))
            rows.extend(reader)
    return rows


def project_row(row: Dict[str, str], header: List[str]) -> Dict[str, str]:
    return {column: row.get(column, "") for column in header}


def write_chunk(path: Path, header: List[str], rows: List[Dict[str, str]]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(path)


def write_report(source_rows: int, output_rows: int, chunk_count: int, header: List[str]) -> None:
    lines = [
        "# Step 5 Provisional Upload Candidates Report",
        "",
        "This report describes the provisional Step 5 upload-candidate chunk set.",
        "",
        "Important note:",
        "",
        "- these files are shaped like Step 5 upload files",
        "- they are derived from the Step 4 capped measurement/person chunk set",
        "- they do **not** enforce the final human `Approved for publishing = 1` gate yet",
        "- they live in a separate provisional subfolder for that reason",
        "",
        "Source rules already applied upstream in Step 4 derived data:",
        "",
        "- `has_person = true`",
        "- `exceeds_cap` not set",
        "- at least one measurement present",
        "",
        "Step 5 shaping rules applied here:",
        "",
        "- keep only the columns present in `images_intake_sample - sampleOutput1.csv`",
        "- preserve the sample column order exactly",
        "- split the result into chunked CSV files",
        "",
        "- source rows scanned: `{}`".format(source_rows),
        "- output rows written: `{}`".format(output_rows),
        "- output chunk count: `{}`".format(chunk_count),
        "- output folder: `{}`".format(OUTPUT_DIR),
        "",
        "Step 5 output header:",
        "",
    ]
    for column in header:
        lines.append("- `{}`".format(column))
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    source_files = iter_source_files()
    if not source_files:
        raise SystemExit("No Step 4 capped measurement/person chunks found in {}".format(STEP4_SOURCE_DIR))

    header = load_sample_header()
    source_rows = load_source_rows(source_files)
    projected_rows = [project_row(row, header) for row in source_rows]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for old_file in OUTPUT_DIR.glob("*.csv"):
        old_file.unlink()

    chunk_count = 0
    for start in range(0, len(projected_rows), CHUNK_SIZE):
        chunk_count += 1
        chunk_rows = projected_rows[start : start + CHUNK_SIZE]
        output_path = OUTPUT_DIR / "{}_{:03d}.csv".format(OUTPUT_BASENAME, chunk_count)
        write_chunk(output_path, header, chunk_rows)

    write_report(len(source_rows), len(projected_rows), chunk_count, header)
    print("Wrote {} rows into {} provisional Step 5 chunk files at {}".format(len(projected_rows), chunk_count, OUTPUT_DIR))
    print("Wrote {}".format(REPORT_PATH))


if __name__ == "__main__":
    main()
