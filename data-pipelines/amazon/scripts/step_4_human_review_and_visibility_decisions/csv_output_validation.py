#!/usr/bin/env python3
import csv
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_ROOT = SCRIPT_DIR.parents[1]
SAMPLE_OUTPUT_PATH = PIPELINE_ROOT / "docs" / "images_intake_sample - sampleOutput1.csv"

STEP2_NORMALIZED_COLUMNS = [
    "created_at_display",
    "id",
    "original_url_display",
    "product_page_url_display",
    "monetized_product_url_display",
    "height_raw",
    "weight_raw",
    "user_comment",
    "date_review_submitted_raw",
    "height_in_display",
    "review_date",
    "source_site_display",
    "status_code",
    "fetched_at",
    "updated_at",
    "brand",
    "waist_raw_display",
    "hips_raw",
    "age_raw",
    "waist_in",
    "hips_in_display",
    "age_years_display",
    "search_fts",
    "weight_display_display",
    "weight_raw_needs_correction",
    "clothing_type_id",
    "reviewer_profile_url",
    "reviewer_name_raw",
    "inseam_inches_display",
    "color_canonical",
    "color_display",
    "size_display",
    "bust_in_number_display",
    "cupsize_display",
    "weight_lbs_display",
    "weight_lbs_raw_issue",
]

STEP3_RAW_INPUT_COLUMNS = STEP2_NORMALIZED_COLUMNS + ["measurement_count"]

STEP3_MACHINE_ANNOTATED_COLUMNS = [
    "created_at_display",
    "id",
    "original_url_display",
    "has_person_REVIEWONLY",
    "has_face_yunet_REVIEWONLY",
    "lighting_ok_REVIEWONLY",
    "full_lower_body_visible_REVIEWONLY",
    "product_page_url_display",
    "monetized_product_url_display",
    "height_raw",
    "weight_raw",
    "user_comment",
    "date_review_submitted_raw",
    "height_in_display",
    "review_date",
    "source_site_display",
    "status_code",
    "fetched_at",
    "updated_at",
    "brand",
    "waist_raw_display",
    "hips_raw",
    "age_raw",
    "waist_in",
    "hips_in_display",
    "age_years_display",
    "search_fts",
    "weight_display_display",
    "weight_raw_needs_correction",
    "clothing_type_id",
    "reviewer_profile_url",
    "reviewer_name_raw",
    "inseam_inches_display",
    "color_canonical_REVIEWONLY",
    "color_display",
    "size_display",
    "bust_in_number_display",
    "cupsize_display",
    "weight_lbs_display",
    "weight_lbs_raw_issue_REVIEWONLY",
    "measurement_count_REVIEWONLY",
]

STEP4_MANUAL_COLUMNS = [
    "created_at_display",
    "id",
    "original_url_display",
    "has_person",
    "has_face_yunet",
    "lighting_ok",
    "full_lower_body_visible",
    "Approved for publishing",
    "Flag_errors",
    "exceeds_cap",
    "product_page_url_display",
    "monetized_product_url_display",
    "height_raw",
    "weight_raw",
    "user_comment",
    "date_review_submitted_raw",
    "height_in_display",
    "review_date",
    "source_site_display",
    "status_code",
    "fetched_at",
    "updated_at",
    "brand",
    "waist_raw_display",
    "hips_raw",
    "age_raw",
    "waist_in",
    "hips_in_display",
    "age_years_display",
    "search_fts",
    "weight_display_display",
    "weight_raw_needs_correction",
    "clothing_type_id",
    "reviewer_profile_url",
    "reviewer_name_raw",
    "inseam_inches_display",
    "color_canonical_REVIEWONLY",
    "color_display",
    "size_display",
    "bust_in_number_display",
    "cupsize_display",
    "weight_lbs_display",
    "weight_lbs_raw_issue_REVIEWONLY",
    "measurement_count_REVIEWONLY",
]

STEP4_CV_METADATA_COLUMNS = [
    "source_file",
    "source_row_number",
    "review_row_key",
]

STEP4_CV_REQUIRED_COLUMNS = [
    "person_count_yolo_detect",
    "main_person_height_pct_yolo_detect",
    "main_person_bbox_area_pct_yolo_detect",
    "body_coverage_score_yolo_pose",
    "has_face_yunet",
]

STEP4_CV_OPTIONAL_COLUMNS = [
    "has_face_scrfd",
    "person_count_yolo_pose",
    "main_person_height_pct_yolo_pose",
    "main_person_bbox_area_pct_yolo_pose",
]

STEP4_RULE_OUTPUT_COLUMNS = [
    "cv_decision",
    "cv_reason_code",
    "cv_reason_summary",
]

STEP4_HUMAN_REVIEW_COLUMNS = [
    "human_decision",
    "human_reason_note",
]

STEP4_FINAL_OUTPUT_COLUMNS = [
    "final_decision",
    "final_reason_code",
    "final_reason_summary",
]

STEP4_REVIEW_QUEUE_COLUMNS = [
    "review_row_key",
    "source_file",
    "source_row_number",
    "original_url_display",
    "product_page_url_display",
    "reviewer_profile_url",
    "reviewer_name_raw",
    "cv_decision",
    "cv_reason_code",
    "cv_reason_summary",
    "human_decision",
    "human_reason_note",
    "user_comment",
    "height_raw",
    "weight_raw",
    "has_face_yunet",
    "person_count_yolo_detect",
    "main_person_height_pct_yolo_detect",
    "main_person_bbox_area_pct_yolo_detect",
    "body_coverage_score_yolo_pose",
]

STEP4_CV_ENRICHED_COLUMNS = STEP4_MANUAL_COLUMNS + STEP4_CV_METADATA_COLUMNS + [
    "person_count_yolo_detect",
    "main_person_height_pct_yolo_detect",
    "main_person_bbox_area_pct_yolo_detect",
    "body_coverage_score_yolo_pose",
    "has_face_scrfd",
    "person_count_yolo_pose",
    "main_person_height_pct_yolo_pose",
    "main_person_bbox_area_pct_yolo_pose",
]

STEP4_CV_RULES_COLUMNS = STEP4_CV_ENRICHED_COLUMNS + STEP4_RULE_OUTPUT_COLUMNS
STEP4_FINAL_RESOLVED_COLUMNS = STEP4_CV_RULES_COLUMNS + STEP4_HUMAN_REVIEW_COLUMNS + STEP4_FINAL_OUTPUT_COLUMNS

BOOL_COLUMNS = {
    "has_person",
    "has_face_yunet",
    "lighting_ok",
    "full_lower_body_visible",
    "exceeds_cap",
    "has_face_scrfd",
    "has_person_REVIEWONLY",
    "has_face_yunet_REVIEWONLY",
    "lighting_ok_REVIEWONLY",
    "full_lower_body_visible_REVIEWONLY",
}

NUMERIC_COLUMNS = {
    "height_in_display",
    "waist_in",
    "hips_in_display",
    "inseam_inches_display",
    "bust_in_number_display",
    "main_person_height_pct_yolo_detect",
    "main_person_bbox_area_pct_yolo_detect",
    "body_coverage_score_yolo_pose",
    "main_person_height_pct_yolo_pose",
    "main_person_bbox_area_pct_yolo_pose",
}

INTEGER_COLUMNS = {
    "source_row_number",
    "person_count_yolo_detect",
    "person_count_yolo_pose",
    "measurement_count_REVIEWONLY",
    "measurement_count",
}

URL_COLUMNS = {
    "original_url_display",
    "product_page_url_display",
    "monetized_product_url_display",
    "reviewer_profile_url",
}

UUID_COLUMNS = {"id"}
TEXT_COLUMNS = {"Approved for publishing", "Flag_errors", "cv_reason_summary", "human_reason_note", "final_reason_summary"}

DECISION_COLUMNS = {
    "cv_decision": {"APPROVE", "REJECT", "REVIEW"},
    "human_decision": {"APPROVE", "REJECT"},
    "final_decision": {"APPROVE", "REJECT"},
}

REASON_CODE_COLUMNS = {
    "cv_reason_code": {
        "NO_PERSON",
        "MULTIPLE_PEOPLE",
        "LOW_BODY_COVERAGE",
        "SUBJECT_TOO_SMALL",
        "SMALL_SUBJECT_NO_FACE",
        "CLEAR_PASS",
        "FACE_PRESENT_SMALL_SUBJECT_CLEAR",
        "MISSING_CV_DATA",
        "BORDERLINE_BODY_COVERAGE",
        "BORDERLINE_SUBJECT_SIZE",
        "BORDERLINE_NO_FACE",
        "BORDERLINE_COMPOSITION",
    },
    "final_reason_code": {"NO_PERSON", "MULTIPLE_PEOPLE", "LOW_BODY_COVERAGE", "SUBJECT_TOO_SMALL", "SMALL_SUBJECT_NO_FACE", "CLEAR_PASS", "FACE_PRESENT_SMALL_SUBJECT_CLEAR", "MISSING_CV_DATA", "BORDERLINE_BODY_COVERAGE", "BORDERLINE_SUBJECT_SIZE", "BORDERLINE_NO_FACE", "BORDERLINE_COMPOSITION", "HUMAN_OVERRIDE"},
}

PROFILE_HEADERS = {
    "step2_normalized": STEP2_NORMALIZED_COLUMNS,
    "step3_raw_input": STEP3_RAW_INPUT_COLUMNS,
    "step3_machine_annotated": STEP3_MACHINE_ANNOTATED_COLUMNS,
    "step4_manual_chunk": STEP4_MANUAL_COLUMNS,
    "step4_cv_enriched": STEP4_CV_ENRICHED_COLUMNS,
    "step4_cv_rules": STEP4_CV_RULES_COLUMNS,
    "step4_review_queue": STEP4_REVIEW_QUEUE_COLUMNS,
    "step4_final_resolved": STEP4_FINAL_RESOLVED_COLUMNS,
}

REVIEW_ROW_KEY_RE = re.compile(r"^.+\.csv::[0-9]+$")
CLOTHING_TYPE_RE = re.compile(r"^[a-z0-9_]+$")


@dataclass
class ValidationIssue:
    message: str
    row_number: Optional[int] = None
    column: Optional[str] = None


class CsvValidationError(Exception):
    def __init__(self, profile: str, issues: Sequence[ValidationIssue]):
        self.profile = profile
        self.issues = list(issues)
        super().__init__(build_error_text(profile, issues))


def load_step5_header() -> List[str]:
    with SAMPLE_OUTPUT_PATH.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.reader(infile)
        header = next(reader, None)
    if not header:
        raise SystemExit("Could not read Step 5 sample header from {}".format(SAMPLE_OUTPUT_PATH))
    return header


PROFILE_HEADERS["step5_publish_ready"] = load_step5_header()


def build_error_text(profile: str, issues: Sequence[ValidationIssue]) -> str:
    lines = ["CSV validation failed for profile `{}`:".format(profile)]
    for issue in issues[:20]:
        parts = []
        if issue.row_number is not None:
            parts.append("row {}".format(issue.row_number))
        if issue.column:
            parts.append("column `{}`".format(issue.column))
        prefix = " ({})".format(", ".join(parts)) if parts else ""
        lines.append("- {}{}".format(issue.message, prefix))
    remaining = len(issues) - 20
    if remaining > 0:
        lines.append("- ... plus {} more issue(s)".format(remaining))
    return "\n".join(lines)


def infer_profile(fieldnames: Sequence[str]) -> Optional[str]:
    field_list = list(fieldnames)
    for profile, expected in PROFILE_HEADERS.items():
        if field_list == expected:
            return profile
    return None


def validate_csv_records(fieldnames: Sequence[str], rows: Sequence[Dict[str, object]], profile: str) -> None:
    issues: List[ValidationIssue] = []
    expected_header = PROFILE_HEADERS.get(profile)
    actual_header = list(fieldnames)

    if expected_header is None:
        raise SystemExit("Unknown CSV validation profile: {}".format(profile))

    issues.extend(validate_header(actual_header, expected_header))

    if not issues:
        for index, row in enumerate(rows, start=2):
            for column in expected_header:
                issues.extend(validate_value(column, row.get(column, ""), index, profile))
                if len(issues) >= 100:
                    raise CsvValidationError(profile, issues)

    if issues:
        raise CsvValidationError(profile, issues)


def validate_csv_file(path: Path, profile: str = "auto") -> Tuple[str, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.reader(infile)
        header = next(reader, None)
        if header is None:
            raise CsvValidationError(profile, [ValidationIssue("CSV is empty")])
        resolved_profile = infer_profile(header) if profile == "auto" else profile
        if not resolved_profile:
            raise CsvValidationError("auto", [ValidationIssue("Could not infer CSV profile from header")])

        expected_header = PROFILE_HEADERS[resolved_profile]
        issues = validate_header(header, expected_header)
        row_count = 0

        for row_number, values in enumerate(reader, start=2):
            row_count += 1
            if len(values) != len(header):
                issues.append(
                    ValidationIssue(
                        "Expected {} columns but found {}".format(len(header), len(values)),
                        row_number=row_number,
                    )
                )
                if len(issues) >= 100:
                    break
                continue

            row_dict = dict(zip(header, values))
            for column in expected_header:
                issues.extend(validate_value(column, row_dict.get(column, ""), row_number, resolved_profile))
                if len(issues) >= 100:
                    break
            if len(issues) >= 100:
                break

    if issues:
        raise CsvValidationError(resolved_profile, issues)
    return resolved_profile, row_count


def validate_header(actual_header: Sequence[str], expected_header: Sequence[str]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    duplicates = find_duplicates(actual_header)
    for duplicate in duplicates:
        issues.append(ValidationIssue("Duplicate header `{}`".format(duplicate), column=duplicate))

    if list(actual_header) == list(expected_header):
        return issues

    actual_set = set(actual_header)
    expected_set = set(expected_header)

    for column in expected_header:
        if column not in actual_set:
            issues.append(ValidationIssue("Missing expected header `{}`".format(column), column=column))

    for column in actual_header:
        if column not in expected_set:
            issues.append(ValidationIssue("Unexpected header `{}`".format(column), column=column))

    shared = [column for column in actual_header if column in expected_set]
    if shared != [column for column in expected_header if column in actual_set]:
        issues.append(ValidationIssue("Header order does not match expected schema"))

    return issues


def find_duplicates(values: Sequence[str]) -> List[str]:
    seen = set()
    duplicates = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def validate_value(column: str, value: object, row_number: int, profile: str) -> List[ValidationIssue]:
    text = str(value or "").strip()
    issues: List[ValidationIssue] = []

    if column in {"source_file", "review_row_key", "cv_decision", "cv_reason_code", "cv_reason_summary"} and profile in {
        "step4_cv_enriched",
        "step4_cv_rules",
        "step4_review_queue",
        "step4_final_resolved",
    }:
        if not text and column in {"source_file", "review_row_key"}:
            issues.append(ValidationIssue("Value should not be blank", row_number=row_number, column=column))
            return issues

    if column == "source_row_number" and profile in {"step4_cv_enriched", "step4_cv_rules", "step4_review_queue", "step4_final_resolved"} and not text:
        issues.append(ValidationIssue("Value should not be blank", row_number=row_number, column=column))
        return issues

    if not text:
        return issues

    if column in BOOL_COLUMNS:
        if text.lower() not in {"true", "false"}:
            issues.append(ValidationIssue("Expected boolean `true` or `false`", row_number=row_number, column=column))
        return issues

    if column == "Approved for publishing":
        if text not in {"0", "1", "true", "false"}:
            issues.append(ValidationIssue("Expected approval flag such as `1`, `0`, `true`, or `false`", row_number=row_number, column=column))
        return issues

    if column in INTEGER_COLUMNS:
        if not is_integer(text):
            issues.append(ValidationIssue("Expected integer value", row_number=row_number, column=column))
        return issues

    if column in NUMERIC_COLUMNS:
        if not is_numeric(text):
            issues.append(ValidationIssue("Expected numeric value", row_number=row_number, column=column))
        return issues

    if column in URL_COLUMNS:
        if not is_url(text):
            issues.append(ValidationIssue("Expected http(s) URL", row_number=row_number, column=column))
        return issues

    if column in UUID_COLUMNS:
        if not is_uuid(text):
            issues.append(ValidationIssue("Expected UUID", row_number=row_number, column=column))
        return issues

    if column == "review_row_key" and not REVIEW_ROW_KEY_RE.match(text):
        issues.append(ValidationIssue("Expected review row key like `file.csv::123`", row_number=row_number, column=column))
        return issues

    if column == "clothing_type_id" and not CLOTHING_TYPE_RE.match(text):
        issues.append(ValidationIssue("Expected lowercase clothing type id", row_number=row_number, column=column))
        return issues

    if column in DECISION_COLUMNS and text.upper() not in DECISION_COLUMNS[column]:
        issues.append(
            ValidationIssue(
                "Expected one of {}".format(", ".join(sorted(DECISION_COLUMNS[column]))),
                row_number=row_number,
                column=column,
            )
        )
        return issues

    if column in REASON_CODE_COLUMNS and text not in REASON_CODE_COLUMNS[column]:
        issues.append(ValidationIssue("Unexpected reason code", row_number=row_number, column=column))
        return issues

    if column == "final_reason_code":
        final_decision = ""
        if profile == "step4_final_resolved":
            final_decision = ""
        if text == "HUMAN_OVERRIDE":
            return issues

    return issues


def is_integer(text: str) -> bool:
    try:
        int(text)
        return True
    except ValueError:
        return False


def is_numeric(text: str) -> bool:
    try:
        Decimal(text)
        return True
    except InvalidOperation:
        return False


def is_uuid(text: str) -> bool:
    try:
        uuid.UUID(text)
        return True
    except ValueError:
        return False


def is_url(text: str) -> bool:
    parsed = urlparse(text)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
