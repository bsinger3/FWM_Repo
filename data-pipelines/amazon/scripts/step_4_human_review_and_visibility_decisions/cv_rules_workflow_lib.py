#!/usr/bin/env python3
import csv
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from csv_output_validation import validate_csv_records


PIPELINE_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PIPELINE_ROOT / "data" / "step_4_human_review_and_visibility_decisions"
REPORTS_DIR = DATA_DIR / "reports"
REVIEW_QUEUE_DIR = DATA_DIR / "review_queue"
CV_ENRICHED_DIR = DATA_DIR / "cv_enriched_batch"
CV_RULES_DIR = DATA_DIR / "cv_rules_applied_batch"
FINAL_RESOLVED_DIR = DATA_DIR / "final_resolved_batch"
STEP5_FINAL_DIR = PIPELINE_ROOT / "data" / "step_5_publish_ready_outputs" / "final_human_approved_batches"
MODEL_DIR = PIPELINE_ROOT / "models"
DEFAULT_VENDOR_DIR = PIPELINE_ROOT.parents[1] / ".codex_vendor"
SAMPLE_OUTPUT_PATH = PIPELINE_ROOT / "docs" / "images_intake_sample - sampleOutput1.csv"

DEFAULT_YOLO_DETECT_MODEL = PIPELINE_ROOT.parents[1] / "yolov8n.pt"
DEFAULT_YOLO_POSE_MODEL = PIPELINE_ROOT.parents[1] / "yolov8n-pose.pt"
DEFAULT_YUNET_MODEL = MODEL_DIR / "face_detection_yunet_2023mar.onnx"

CV_METADATA_COLUMNS = [
    "source_file",
    "source_row_number",
    "review_row_key",
]

REQUIRED_CV_COLUMNS = [
    "person_count_yolo_detect",
    "main_person_height_pct_yolo_detect",
    "main_person_bbox_area_pct_yolo_detect",
    "body_coverage_score_yolo_pose",
    "has_face_yunet",
]

OPTIONAL_CV_COLUMNS = [
    "has_face_scrfd",
    "person_count_yolo_pose",
    "main_person_height_pct_yolo_pose",
    "main_person_bbox_area_pct_yolo_pose",
]

RULE_OUTPUT_COLUMNS = [
    "cv_decision",
    "cv_reason_code",
    "cv_reason_summary",
]

HUMAN_REVIEW_COLUMNS = [
    "human_decision",
    "human_reason_note",
]

FINAL_OUTPUT_COLUMNS = [
    "final_decision",
    "final_reason_code",
    "final_reason_summary",
]

REQUIRED_EXPORT_COLUMNS = CV_METADATA_COLUMNS + REQUIRED_CV_COLUMNS + RULE_OUTPUT_COLUMNS

REJECT_NO_PERSON_COUNT = 0
REJECT_MIN_BODY_COVERAGE = 66.7
REJECT_MIN_SUBJECT_HEIGHT_PCT = 0.50
REJECT_NO_FACE_SMALL_SUBJECT_HEIGHT_PCT = 0.70
REJECT_NO_FACE_SMALL_SUBJECT_AREA_PCT = 0.25
APPROVE_MIN_BODY_COVERAGE = 75.0
APPROVE_MIN_SUBJECT_HEIGHT_PCT = 0.60
APPROVE_MIN_SUBJECT_AREA_PCT = 0.15
APPROVE_FACE_PRESENT_SMALL_SUBJECT_MIN_BODY_COVERAGE = 100.0
APPROVE_FACE_PRESENT_SMALL_SUBJECT_HEIGHT_PCT = 0.55
APPROVE_FACE_PRESENT_SMALL_SUBJECT_AREA_PCT = 0.12

REASON_SUMMARIES = {
    "NO_PERSON": "No person detected",
    "MULTIPLE_PEOPLE": "Multiple people detected",
    "LOW_BODY_COVERAGE": "Too little body visible",
    "SUBJECT_TOO_SMALL": "Person too small in frame",
    "SMALL_SUBJECT_NO_FACE": "Faceless subject is too small or distant",
    "CLEAR_PASS": "Single person, strong framing, enough body visible",
    "FACE_PRESENT_SMALL_SUBJECT_CLEAR": "Face present and framing is clear despite a smaller subject",
    "MISSING_CV_DATA": "Required CV data missing",
    "BORDERLINE_BODY_COVERAGE": "Body visibility is borderline",
    "BORDERLINE_SUBJECT_SIZE": "Person size is borderline",
    "BORDERLINE_NO_FACE": "Borderline framing and no face detected",
    "BORDERLINE_COMPOSITION": "Composition is borderline",
    "HUMAN_OVERRIDE": "Reviewed by human",
}


def bootstrap_vendor_paths(vendor_dir: Path) -> None:
    vendor_subdirs = [
        vendor_dir / "yolo_test",
        vendor_dir / "scrfd_test",
    ]
    for path in reversed(vendor_subdirs):
        if path.exists():
            sys.path.insert(0, str(path))


def import_cv_dependencies():
    os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/Ultralytics")
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-codex")
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        import requests  # type: ignore
        from PIL import Image  # type: ignore
        from ultralytics import YOLO  # type: ignore
    except ModuleNotFoundError as exc:
        missing = exc.name or "required package"
        raise SystemExit(
            "Missing dependency: {}. This workflow expects vendored runtimes under .codex_vendor.".format(missing)
        ) from exc
    return cv2, np, requests, Image, YOLO


def bool_to_str(value: bool) -> str:
    return "true" if value else "false"


def normalize_bool(value) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def normalize_float(value) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def read_csv_rows(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as infile:
        reader = csv.DictReader(infile)
        if not reader.fieldnames:
            raise SystemExit("No CSV header found in {}".format(path))
        rows = list(reader)
        return list(reader.fieldnames), rows


def write_csv_rows(
    path: Path,
    fieldnames: Sequence[str],
    rows: Sequence[Dict[str, object]],
    validation_profile: Optional[str] = None,
) -> None:
    if validation_profile:
        validate_csv_records(fieldnames, rows, validation_profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    temp_path.replace(path)


def ensure_columns(fieldnames: List[str], columns: Iterable[str]) -> List[str]:
    output = list(fieldnames)
    for column in columns:
        if column not in output:
            output.append(column)
    return output


def add_row_identity(rows: Sequence[Dict[str, str]], source_file: Path) -> List[Dict[str, object]]:
    enriched_rows: List[Dict[str, object]] = []
    for row_number, row in enumerate(rows, start=2):
        updated = dict(row)
        updated["source_file"] = source_file.name
        updated["source_row_number"] = row_number
        updated["review_row_key"] = "{}::{}".format(source_file.name, row_number)
        enriched_rows.append(updated)
    return enriched_rows


def fetch_rgb_image(url: str, timeout: float, session, Image):
    last_error = None
    for attempt in range(3):
        try:
            response = session.get(
                url,
                timeout=timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
                    )
                },
            )
            response.raise_for_status()
            return Image.open(BytesIO(response.content)).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= 2:
                break
            time.sleep(0.5 * (attempt + 1))
    raise last_error


def round_or_blank(value):
    if value is None:
        return ""
    return round(float(value), 3)


def detect_faces_yunet(face_detector, image_bgr):
    height, width = image_bgr.shape[:2]
    face_detector.setInputSize((width, height))
    _ok, faces = face_detector.detect(image_bgr)
    if faces is None:
        return []
    return faces.tolist()


def extract_person_metrics(result, image_width: int, image_height: int, min_person_confidence: float) -> Tuple[List[int], List[List[float]]]:
    valid_indexes: List[int] = []
    boxes: List[List[float]] = []
    if result.boxes is None or not len(result.boxes):
        return valid_indexes, boxes

    boxes = result.boxes.xyxy.tolist()
    for index, (cls_value, confidence) in enumerate(zip(result.boxes.cls.tolist(), result.boxes.conf.tolist())):
        if int(cls_value) == 0 and float(confidence) >= min_person_confidence:
            valid_indexes.append(index)
    return valid_indexes, boxes


def summarize_main_person(valid_indexes: List[int], boxes: List[List[float]], image_width: int, image_height: int) -> Tuple[int, float, float, Optional[int]]:
    if not valid_indexes:
        return 0, 0.0, 0.0, None

    best_index = max(
        valid_indexes,
        key=lambda idx: max(0.0, float(boxes[idx][2] - boxes[idx][0])) * max(0.0, float(boxes[idx][3] - boxes[idx][1])),
    )
    x1, y1, x2, y2 = [float(value) for value in boxes[best_index]]
    bbox_width = max(0.0, x2 - x1)
    bbox_height = max(0.0, y2 - y1)
    height_pct = bbox_height / float(image_height) if image_height else 0.0
    area_pct = (bbox_width * bbox_height) / float(image_width * image_height) if image_width and image_height else 0.0
    return len(valid_indexes), height_pct, area_pct, best_index


YOLO_POSE_KEYPOINT_WEIGHTS = {
    0: 1.0,
    5: 1.5,
    6: 1.5,
    11: 1.5,
    12: 1.5,
    13: 1.0,
    14: 1.0,
    15: 1.5,
    16: 1.5,
}


def compute_yolo_coverage_score(keypoint_confidences, min_confidence: float) -> float:
    total_weight = float(sum(YOLO_POSE_KEYPOINT_WEIGHTS.values()))
    visible_weight = 0.0
    for index, weight in YOLO_POSE_KEYPOINT_WEIGHTS.items():
        confidence = float(keypoint_confidences[index])
        if confidence >= min_confidence:
            visible_weight += weight
    return round((visible_weight / total_weight) * 100.0, 1)


def analyze_yolo_detect(image_rgb, model, np, min_person_confidence: float) -> Dict[str, object]:
    result = model.predict(np.array(image_rgb), verbose=False, device="cpu")[0]
    image_height, image_width = image_rgb.size[1], image_rgb.size[0]
    valid_indexes, boxes = extract_person_metrics(result, image_width, image_height, min_person_confidence)
    person_count, height_pct, area_pct, _best_index = summarize_main_person(valid_indexes, boxes, image_width, image_height)
    return {
        "person_count_yolo_detect": person_count,
        "main_person_height_pct_yolo_detect": round_or_blank(height_pct),
        "main_person_bbox_area_pct_yolo_detect": round_or_blank(area_pct),
    }


def analyze_yolo_pose(image_rgb, model, np, min_person_confidence: float, min_keypoint_confidence: float) -> Dict[str, object]:
    result = model.predict(np.array(image_rgb), verbose=False, device="cpu")[0]
    image_height, image_width = image_rgb.size[1], image_rgb.size[0]
    valid_indexes, boxes = extract_person_metrics(result, image_width, image_height, min_person_confidence)
    person_count, height_pct, area_pct, best_index = summarize_main_person(valid_indexes, boxes, image_width, image_height)
    body_coverage_score = 0.0
    if best_index is not None and getattr(result, "keypoints", None) is not None and len(result.keypoints) > best_index:
        confidences = getattr(result.keypoints, "conf", None)
        if confidences is not None:
            body_coverage_score = compute_yolo_coverage_score(confidences[best_index].tolist(), min_keypoint_confidence)
    return {
        "person_count_yolo_pose": person_count,
        "main_person_height_pct_yolo_pose": round_or_blank(height_pct),
        "main_person_bbox_area_pct_yolo_pose": round_or_blank(area_pct),
        "body_coverage_score_yolo_pose": round_or_blank(body_coverage_score),
    }


def create_cv_models(
    cv2,
    YOLO,
    yolo_detect_model: Path,
    yolo_pose_model: Path,
    yunet_model: Path,
):
    person_face_detector = cv2.FaceDetectorYN.create(
        str(yunet_model),
        "",
        (320, 320),
        0.8,
        0.3,
        5000,
    )
    return {
        "face_yunet": person_face_detector,
        "yolo_detect": YOLO(str(yolo_detect_model)),
        "yolo_pose": YOLO(str(yolo_pose_model)),
    }


def enrich_rows_with_cv(
    rows: Sequence[Dict[str, object]],
    models: Dict[str, object],
    cv2,
    np,
    session,
    Image,
    timeout: float,
    min_person_confidence: float,
    min_pose_keypoint_confidence: float,
    limit: int,
    yolo_batch_size: int,
    download_workers: int,
    verbose: bool,
) -> List[Dict[str, object]]:
    def set_blank_outputs(row: Dict[str, object]) -> None:
        for column in REQUIRED_CV_COLUMNS + OPTIONAL_CV_COLUMNS:
            row.setdefault(column, "")

    def download_one(index: int, row: Dict[str, object]):
        url = str(row.get("original_url_display", "") or "").strip()
        image_rgb = fetch_rgb_image(url, timeout, session, Image)
        return index, image_rgb

    enriched_rows: List[Dict[str, object]] = [dict(row) for row in rows]
    process_indexes: List[int] = []

    for index, row in enumerate(enriched_rows):
        url = str(row.get("original_url_display", "") or "").strip()
        if not url:
            set_blank_outputs(row)
            continue
        if limit > 0 and len(process_indexes) >= limit:
            set_blank_outputs(row)
            continue
        process_indexes.append(index)

    processed = 0
    batch_size = max(1, yolo_batch_size)
    worker_count = max(1, download_workers)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for start in range(0, len(process_indexes), batch_size):
            batch_indexes = process_indexes[start : start + batch_size]
            downloaded: List[Tuple[int, object]] = []

            futures = {executor.submit(download_one, idx, enriched_rows[idx]): idx for idx in batch_indexes}
            for future in as_completed(futures):
                idx = futures[future]
                row = enriched_rows[idx]
                url = str(row.get("original_url_display", "") or "").strip()
                try:
                    downloaded.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    set_blank_outputs(row)
                    if verbose:
                        print("[{}] failed for {}: {}".format(row.get("review_row_key", "?"), url, exc), file=sys.stderr)

            downloaded.sort(key=lambda item: item[0])
            if not downloaded:
                continue

            batch_images = [image_rgb for _idx, image_rgb in downloaded]
            detect_results = models["yolo_detect"].predict(batch_images, verbose=False, device="cpu")
            pose_results = models["yolo_pose"].predict(batch_images, verbose=False, device="cpu")

            for (idx, image_rgb), detect_result, pose_result in zip(downloaded, detect_results, pose_results):
                row = enriched_rows[idx]
                image_bgr = np.array(image_rgb)[:, :, ::-1]
                row["has_face_yunet"] = bool_to_str(bool(detect_faces_yunet(models["face_yunet"], image_bgr)))

                image_height, image_width = image_rgb.size[1], image_rgb.size[0]
                valid_indexes, boxes = extract_person_metrics(detect_result, image_width, image_height, min_person_confidence)
                person_count, height_pct, area_pct, _best_index = summarize_main_person(valid_indexes, boxes, image_width, image_height)
                row["person_count_yolo_detect"] = person_count
                row["main_person_height_pct_yolo_detect"] = round_or_blank(height_pct)
                row["main_person_bbox_area_pct_yolo_detect"] = round_or_blank(area_pct)

                pose_valid_indexes, pose_boxes = extract_person_metrics(pose_result, image_width, image_height, min_person_confidence)
                pose_person_count, pose_height_pct, pose_area_pct, pose_best_index = summarize_main_person(
                    pose_valid_indexes, pose_boxes, image_width, image_height
                )
                body_coverage_score = 0.0
                if pose_best_index is not None and getattr(pose_result, "keypoints", None) is not None and len(pose_result.keypoints) > pose_best_index:
                    confidences = getattr(pose_result.keypoints, "conf", None)
                    if confidences is not None:
                        body_coverage_score = compute_yolo_coverage_score(
                            confidences[pose_best_index].tolist(),
                            min_pose_keypoint_confidence,
                        )
                row["person_count_yolo_pose"] = pose_person_count
                row["main_person_height_pct_yolo_pose"] = round_or_blank(pose_height_pct)
                row["main_person_bbox_area_pct_yolo_pose"] = round_or_blank(pose_area_pct)
                row["body_coverage_score_yolo_pose"] = round_or_blank(body_coverage_score)
                row.setdefault("has_face_scrfd", "")

                processed += 1
                if verbose and processed % 25 == 0:
                    print("Processed {} images".format(processed), file=sys.stderr)

    return enriched_rows


def reason_summary(reason_code: str) -> str:
    return REASON_SUMMARIES[reason_code]


def evaluate_cv_rules(row: Dict[str, object]) -> Tuple[str, str, str]:
    person_count = normalize_float(row.get("person_count_yolo_detect"))
    subject_height = normalize_float(row.get("main_person_height_pct_yolo_detect"))
    subject_area = normalize_float(row.get("main_person_bbox_area_pct_yolo_detect"))
    body_coverage = normalize_float(row.get("body_coverage_score_yolo_pose"))
    has_face = normalize_bool(row.get("has_face_yunet"))

    core_values = [person_count, subject_height, body_coverage, has_face]
    if any(value is None for value in core_values):
        code = "MISSING_CV_DATA"
        return "REVIEW", code, reason_summary(code)

    if int(person_count) == REJECT_NO_PERSON_COUNT:
        code = "NO_PERSON"
        return "REJECT", code, reason_summary(code)

    if person_count > 1:
        code = "MULTIPLE_PEOPLE"
        return "REJECT", code, reason_summary(code)

    if body_coverage < REJECT_MIN_BODY_COVERAGE:
        code = "LOW_BODY_COVERAGE"
        return "REJECT", code, reason_summary(code)

    if subject_height < REJECT_MIN_SUBJECT_HEIGHT_PCT:
        code = "SUBJECT_TOO_SMALL"
        return "REJECT", code, reason_summary(code)

    if (
        int(person_count) == 1
        and has_face is False
        and subject_area is not None
        and (
            subject_height < REJECT_NO_FACE_SMALL_SUBJECT_HEIGHT_PCT
            or subject_area < REJECT_NO_FACE_SMALL_SUBJECT_AREA_PCT
        )
    ):
        code = "SMALL_SUBJECT_NO_FACE"
        return "REJECT", code, reason_summary(code)

    if (
        int(person_count) == 1
        and body_coverage >= APPROVE_MIN_BODY_COVERAGE
        and subject_height >= APPROVE_MIN_SUBJECT_HEIGHT_PCT
        and subject_area is not None
        and subject_area >= APPROVE_MIN_SUBJECT_AREA_PCT
    ):
        code = "CLEAR_PASS"
        return "APPROVE", code, reason_summary(code)

    if (
        int(person_count) == 1
        and has_face is True
        and body_coverage >= APPROVE_FACE_PRESENT_SMALL_SUBJECT_MIN_BODY_COVERAGE
        and subject_height >= APPROVE_FACE_PRESENT_SMALL_SUBJECT_HEIGHT_PCT
        and subject_area is not None
        and subject_area >= APPROVE_FACE_PRESENT_SMALL_SUBJECT_AREA_PCT
    ):
        code = "FACE_PRESENT_SMALL_SUBJECT_CLEAR"
        return "APPROVE", code, reason_summary(code)

    if REJECT_MIN_BODY_COVERAGE <= body_coverage < APPROVE_MIN_BODY_COVERAGE:
        code = "BORDERLINE_BODY_COVERAGE"
        return "REVIEW", code, reason_summary(code)

    if REJECT_MIN_SUBJECT_HEIGHT_PCT <= subject_height < APPROVE_MIN_SUBJECT_HEIGHT_PCT:
        code = "BORDERLINE_SUBJECT_SIZE"
        return "REVIEW", code, reason_summary(code)

    if int(person_count) == 1 and not has_face:
        code = "BORDERLINE_NO_FACE"
        return "REVIEW", code, reason_summary(code)

    code = "BORDERLINE_COMPOSITION"
    return "REVIEW", code, reason_summary(code)


def apply_rules(rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    evaluated_rows: List[Dict[str, object]] = []
    for row in rows:
        updated = dict(row)
        decision, code, summary = evaluate_cv_rules(updated)
        updated["cv_decision"] = decision
        updated["cv_reason_code"] = code
        updated["cv_reason_summary"] = summary
        evaluated_rows.append(updated)
    return evaluated_rows


def count_by(rows: Sequence[Dict[str, object]], column: str) -> Counter:
    counter: Counter = Counter()
    for row in rows:
        key = str(row.get(column, "") or "").strip() or "<blank>"
        counter[key] += 1
    return counter


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> List[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def build_batch_report(batch_name: str, rows: Sequence[Dict[str, object]], source_files: Sequence[Path]) -> str:
    totals = count_by(rows, "cv_decision")
    reject_rows = [row for row in rows if row.get("cv_decision") == "REJECT"]
    review_rows = [row for row in rows if row.get("cv_decision") == "REVIEW"]
    reject_reasons = count_by(reject_rows, "cv_reason_code")
    review_reasons = count_by(review_rows, "cv_reason_code")

    per_file_rows = []
    for path in source_files:
        file_rows = [row for row in rows if row.get("source_file") == path.name]
        file_totals = count_by(file_rows, "cv_decision")
        per_file_rows.append([
            path.name,
            len(file_rows),
            file_totals.get("APPROVE", 0),
            file_totals.get("REJECT", 0),
            file_totals.get("REVIEW", 0),
        ])

    lines = [
        "# Step 4 CV Batch Report: {}".format(batch_name),
        "",
        "## Batch Totals",
        "",
        "- total rows processed: `{}`".format(len(rows)),
        "- approve rows: `{}`".format(totals.get("APPROVE", 0)),
        "- reject rows: `{}`".format(totals.get("REJECT", 0)),
        "- review rows: `{}`".format(totals.get("REVIEW", 0)),
        "",
        "## Decision Histogram",
        "",
    ]
    lines.extend(markdown_table(["decision", "count"], [[key, value] for key, value in sorted(totals.items())]))
    lines.extend(["", "## Reject Reasons", ""])
    lines.extend(markdown_table(["reason_code", "count"], [[key, value] for key, value in reject_reasons.most_common()]))
    lines.extend(["", "## Review Reasons", ""])
    lines.extend(markdown_table(["reason_code", "count"], [[key, value] for key, value in review_reasons.most_common()]))
    lines.extend(["", "## Per-File Breakdown", ""])
    lines.extend(markdown_table(["source_file", "rows", "approve", "reject", "review"], per_file_rows))
    lines.append("")
    return "\n".join(lines)


def review_queue_columns(rows: Sequence[Dict[str, object]]) -> List[str]:
    preferred = [
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
    return preferred


def build_review_queue(rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    queue_rows: List[Dict[str, object]] = []
    for row in rows:
        if row.get("cv_decision") != "REVIEW":
            continue
        updated = dict(row)
        updated["human_decision"] = ""
        updated["human_reason_note"] = ""
        queue_rows.append(updated)
    return queue_rows


def load_sample_header() -> List[str]:
    with SAMPLE_OUTPUT_PATH.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.reader(infile)
        header = next(reader, None)
    if not header:
        raise SystemExit("Could not read Step 5 sample header from {}".format(SAMPLE_OUTPUT_PATH))
    return header


def resolve_final_rows(batch_rows: Sequence[Dict[str, object]], edited_review_rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    review_index = {str(row.get("review_row_key", "")): row for row in edited_review_rows}
    resolved: List[Dict[str, object]] = []
    for row in batch_rows:
        updated = dict(row)
        if updated.get("cv_decision") != "REVIEW":
            updated["human_decision"] = updated.get("human_decision", "")
            updated["human_reason_note"] = updated.get("human_reason_note", "")
            updated["final_decision"] = updated.get("cv_decision", "")
            updated["final_reason_code"] = updated.get("cv_reason_code", "")
            updated["final_reason_summary"] = updated.get("cv_reason_summary", "")
            resolved.append(updated)
            continue

        edited = review_index.get(str(updated.get("review_row_key", "")), {})
        human_decision = str(edited.get("human_decision", "") or "").strip().upper()
        human_reason_note = str(edited.get("human_reason_note", "") or "").strip()
        updated["human_decision"] = human_decision
        updated["human_reason_note"] = human_reason_note

        if human_decision in ("APPROVE", "REJECT"):
            updated["final_decision"] = human_decision
            updated["final_reason_code"] = "HUMAN_OVERRIDE"
            updated["final_reason_summary"] = reason_summary("HUMAN_OVERRIDE")
        else:
            updated["final_decision"] = ""
            updated["final_reason_code"] = ""
            updated["final_reason_summary"] = ""
        resolved.append(updated)
    return resolved


def unresolved_review_count(rows: Sequence[Dict[str, object]]) -> int:
    return sum(
        1
        for row in rows
        if str(row.get("cv_decision", "")) == "REVIEW" and not str(row.get("final_decision", "") or "").strip()
    )


def export_step5_rows(rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    header = load_sample_header()
    exported: List[Dict[str, object]] = []
    for row in rows:
        if str(row.get("final_decision", "")) != "APPROVE":
            continue
        projected = {column: row.get(column, "") for column in header}
        if "Approved for publishing" in projected:
            projected["Approved for publishing"] = "1"
        exported.append(projected)
    return exported
