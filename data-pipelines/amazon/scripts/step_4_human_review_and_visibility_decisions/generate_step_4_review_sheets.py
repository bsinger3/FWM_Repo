#!/usr/bin/env python3
import csv
import hashlib
import re
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
STEP4_HELPER_COLUMNS = ["Approved for publishing", "Flag_errors", "exceeds_cap"]
CAP_PER_REVIEWER_PRODUCT = 3
TRUE_VALUES = {"1", "true", "yes", "y", "t"}


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
    transformed.setdefault("exceeds_cap", "")
    return transformed


def iter_step3_chunk_files():
    for path in sorted(STEP3_INPUT_DIR.glob("images_to_approve_part_*.csv")):
        yield path


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_profile_url(value: str) -> str:
    value = value.strip().lower()
    if not value:
        return ""
    value = value.split("?", 1)[0].rstrip("/")
    if not value:
        return ""
    return value.rsplit("/", 1)[-1] or value


def normalize_comment_text(value: str) -> str:
    value = value.strip().lower()
    if not value:
        return ""
    value = re.sub(r"[^\w\s]", " ", value)
    value = normalize_whitespace(value)
    return value


def stable_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def build_reviewer_identity(row: dict[str, str]) -> str:
    profile_key = normalize_profile_url(row.get("reviewer_profile_url", ""))
    comment_key = normalize_comment_text(row.get("user_comment", ""))
    parts = []
    if profile_key:
        parts.append(f"profile:{profile_key}")
    if comment_key:
        parts.append(f"comment:{stable_hash(comment_key)}")
    return "::".join(parts)


def normalize_product_key(row: dict[str, str]) -> str:
    return normalize_whitespace(row.get("product_page_url_display", "").strip().lower())


def is_true(value: str) -> bool:
    return value.strip().lower() in TRUE_VALUES


def rank_row(row_record: dict[str, object]) -> tuple[int, int, int, int, tuple[int, int]]:
    row = row_record["row"]
    return (
        0 if is_true(row.get("has_face_yunet", "")) else 1,
        0 if is_true(row.get("has_person", "")) else 1,
        0 if is_true(row.get("lighting_ok", "")) else 1,
        0 if is_true(row.get("full_lower_body_visible", "")) else 1,
        row_record["position"],
    )


def annotate_exceeds_cap(all_rows: list[dict[str, object]]) -> None:
    grouped_rows: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row_record in all_rows:
        row = row_record["row"]
        product_key = normalize_product_key(row)
        reviewer_key = build_reviewer_identity(row)
        if not product_key or not reviewer_key:
            row["exceeds_cap"] = ""
            continue
        grouped_rows.setdefault((product_key, reviewer_key), []).append(row_record)

    for group_rows in grouped_rows.values():
        ranked_rows = sorted(group_rows, key=rank_row)
        for index, row_record in enumerate(ranked_rows):
            row_record["row"]["exceeds_cap"] = "1" if index >= CAP_PER_REVIEWER_PRODUCT else ""


def load_all_rows(files: list[Path]) -> tuple[list[str], list[dict[str, object]]]:
    output_header = None
    all_rows: list[dict[str, object]] = []

    for file_index, input_path in enumerate(files):
        with input_path.open("r", newline="", encoding="utf-8-sig") as infile:
            reader = csv.DictReader(infile)
            if not reader.fieldnames:
                raise SystemExit(f"No CSV header found in {input_path}")
            if output_header is None:
                output_header = build_output_header(reader.fieldnames)
            for row_index, row in enumerate(reader):
                all_rows.append(
                    {
                        "input_path": input_path,
                        "position": (file_index, row_index),
                        "row": transform_row(row),
                    }
                )

    if output_header is None:
        raise SystemExit("No Step 3 rows found to convert.")
    return output_header, all_rows


def write_review_sheet(output_path: Path, output_header: list[str], rows: list[dict[str, str]]) -> tuple[int, int]:
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

    output_header, all_rows = load_all_rows(files)
    annotate_exceeds_cap(all_rows)

    rows_by_input_path: dict[Path, list[dict[str, str]]] = {path: [] for path in files}
    for row_record in all_rows:
        rows_by_input_path[row_record["input_path"]].append(row_record["row"])

    for input_path in files:
        output_path = STEP4_OUTPUT_DIR / input_path.name
        rows, columns = write_review_sheet(output_path, output_header, rows_by_input_path[input_path])
        print(f"{output_path.name}: rows={rows} columns={columns}")


if __name__ == "__main__":
    main()
