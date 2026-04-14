#!/usr/bin/env python3
import csv
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[2]
STEP3_INPUT_DIR = PIPELINE_ROOT / "data" / "step_3_image_annotation" / "machine_annotated_outputs"
STEP4_OUTPUT_DIR = PIPELINE_ROOT / "data" / "step_4_human_review_and_visibility_decisions"

REVIEW_COLUMN_MAP = {
    "has_person_REVIEWONLY": "has_person",
    "has_face_yunet_REVIEWONLY": "has_face_yunet",
    "lighting_ok_REVIEWONLY": "lighting_ok",
    "full_lower_body_visible_REVIEWONLY": "full_lower_body_visible",
}
REVIEW_COLUMNS = [
    "has_person",
    "has_face_yunet",
    "lighting_ok",
    "full_lower_body_visible",
]
INSERT_AFTER = "full_lower_body_visible"
STEP4_HELPER_COLUMNS = ["Approved for publishing", "Flag_errors"]


def build_output_header(input_header: list[str]) -> list[str]:
    mapped = [REVIEW_COLUMN_MAP.get(name, name) for name in input_header]
    mapped = [name for name in mapped if name != ""]

    output = []
    inserted = False
    for name in mapped:
        output.append(name)
        if name == INSERT_AFTER:
            output.extend(STEP4_HELPER_COLUMNS)
            inserted = True
    if not inserted:
        raise SystemExit(f"Expected review column not found: {INSERT_AFTER}")
    return output


def transform_row(row: dict[str, str]) -> dict[str, str]:
    transformed = {}
    for key, value in row.items():
        output_key = REVIEW_COLUMN_MAP.get(key, key)
        if output_key == "":
            continue
        transformed[output_key] = value
    transformed.setdefault("Approved for publishing", "")
    transformed.setdefault("Flag_errors", "")
    return transformed


def iter_step3_chunk_files():
    for path in sorted(STEP3_INPUT_DIR.glob("images_to_approve_part_*.csv")):
        yield path


def generate_review_sheet(input_path: Path, output_path: Path) -> tuple[int, int]:
    with input_path.open("r", newline="", encoding="utf-8-sig") as infile:
        reader = csv.DictReader(infile)
        if not reader.fieldnames:
            raise SystemExit(f"No CSV header found in {input_path}")
        output_header = build_output_header(reader.fieldnames)
        rows = [transform_row(row) for row in reader]

    temp_output_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with temp_output_path.open("w", newline="", encoding="utf-8") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=output_header)
        writer.writeheader()
        writer.writerows({name: row.get(name, "") for name in output_header} for row in rows)
    temp_output_path.replace(output_path)
    return len(rows), len(output_header)


def main() -> None:
    STEP4_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = list(iter_step3_chunk_files())
    if not files:
        raise SystemExit("No Step 3 chunk files found to convert.")

    for input_path in files:
        output_path = STEP4_OUTPUT_DIR / input_path.name
        rows, columns = generate_review_sheet(input_path, output_path)
        print(f"{output_path.name}: rows={rows} columns={columns}")


if __name__ == "__main__":
    main()
