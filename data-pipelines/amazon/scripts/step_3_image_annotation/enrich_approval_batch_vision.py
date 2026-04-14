#!/usr/bin/env python3
import argparse
import csv
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


NEW_COLUMNS = [
    "has_person",
    "has_face_yunet",
    "lighting_ok",
    "full_lower_body_visible",
]

PIPELINE_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PIPELINE_ROOT / "data" / "step_3_image_annotation"
DEFAULT_INPUT = (
    DATA_DIR
    / "raw_inputs"
    / "images_to_approve.csv"
)
MODEL_DIR = PIPELINE_ROOT / "models"
SAMPLE_OUTPUT_PATH = PIPELINE_ROOT / "docs" / "images_intake_sample - sampleOutput1.csv"
REVIEWONLY_SUFFIX = "_REVIEWONLY"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich an approval-batch CSV with cheap computer-vision signals based on "
            "the image in original_url_display."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Path to the source CSV. Defaults to the main approval batch file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output CSV path. If omitted, the input file is updated in place.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional row limit for testing. 0 means process every row.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Image download timeout in seconds.",
    )
    parser.add_argument(
        "--backup-suffix",
        default=".bak",
        help="Suffix used for the in-place backup file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress and failures to stderr.",
    )
    return parser.parse_args()


def import_dependencies():
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-codex")
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ModuleNotFoundError as exc:
        missing = exc.name or "required package"
        raise SystemExit(
            "Missing dependency: "
            f"{missing}. Install with:\n"
            "  python3 -m pip install opencv-python numpy"
        ) from exc
    return cv2, np


def bool_to_str(value: bool) -> str:
    return "true" if value else "false"


def load_sample_columns() -> set[str]:
    with SAMPLE_OUTPUT_PATH.open("r", newline="", encoding="utf-8-sig") as infile:
        reader = csv.reader(infile)
        header = next(reader)
    return {column.strip() for column in header if column.strip()}


SAMPLE_COLUMNS = load_sample_columns()


def normalize_reviewonly_name(fieldname: str) -> str:
    name = str(fieldname or "").strip()
    if not name:
        return f"blank{REVIEWONLY_SUFFIX}"
    if name in SAMPLE_COLUMNS:
        return name
    if REVIEWONLY_SUFFIX in name:
        return name
    return f"{name}{REVIEWONLY_SUFFIX}"


def insert_columns_after(fieldnames: list[str], anchor: str, new_columns: Iterable[str]) -> list[str]:
    if anchor not in fieldnames:
        raise SystemExit(f"Required column not found: {anchor}")
    result = [name for name in fieldnames if name not in new_columns]
    insert_at = result.index(anchor) + 1
    for offset, column in enumerate(new_columns):
        result.insert(insert_at + offset, column)
    return result


def fetch_image_bgr(url: str, timeout: float, cv2, np):
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            )
        },
    )
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("cv2.imdecode returned None")
    return image


def download_file(url: str, destination: Path, timeout: float) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            )
        },
    )
    with urlopen(request, timeout=timeout) as response, destination.open("wb") as outfile:
        shutil.copyfileobj(response, outfile)


def compute_lighting_ok(image_bgr, cv2, np) -> bool:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    dark_ratio = float(np.mean(gray < 40))
    bright_ratio = float(np.mean(gray > 245))
    return (
        70.0 <= brightness <= 220.0
        and contrast >= 35.0
        and dark_ratio <= 0.45
        and bright_ratio <= 0.35
    )


def compute_has_person(person_detections) -> bool:
    return bool(person_detections)


def compute_has_face_yunet(face_detections) -> bool:
    return bool(face_detections)


def compute_full_lower_body_visible(person_detections, image_height: int) -> bool:
    if not person_detections:
        return False
    for x, y, w, h in person_detections:
        if float(y + h) / float(image_height) >= 0.78:
            return True
    return False


def detect_people(person_detector, image_bgr):
    rects, _weights = person_detector.detectMultiScale(
        image_bgr,
        winStride=(8, 8),
        padding=(8, 8),
        scale=1.05,
    )
    return [tuple(int(v) for v in rect) for rect in rects]


def detect_faces_yunet(face_detector, image_bgr):
    height, width = image_bgr.shape[:2]
    face_detector.setInputSize((width, height))
    _ok, faces = face_detector.detect(image_bgr)
    if faces is None:
        return []
    return faces.tolist()


def enrich_row(url: str, timeout: float, detectors: dict, cv2, np) -> dict[str, str]:
    person_detector = detectors["person"]
    face_detector = detectors["face_yunet"]

    image_bgr = fetch_image_bgr(url, timeout, cv2, np)
    image_height = image_bgr.shape[0]
    person_detections = detect_people(person_detector, image_bgr)
    face_detections = detect_faces_yunet(face_detector, image_bgr)
    return {
        "has_person": bool_to_str(compute_has_person(person_detections)),
        "has_face_yunet": bool_to_str(compute_has_face_yunet(face_detections)),
        "lighting_ok": bool_to_str(compute_lighting_ok(image_bgr, cv2, np)),
        "full_lower_body_visible": bool_to_str(compute_full_lower_body_visible(person_detections, image_height)),
    }


def process_csv(
    input_path: Path,
    output_path: Path,
    limit: int,
    timeout: float,
    verbose: bool,
) -> None:
    cv2, np = import_dependencies()
    person_detector = cv2.HOGDescriptor()
    person_detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    yunet_model_path = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
    if not yunet_model_path.exists():
        raise SystemExit(f"YuNet model not found: {yunet_model_path}")
    face_detector = cv2.FaceDetectorYN.create(
        str(yunet_model_path),
        "",
        (320, 320),
        0.8,
        0.3,
        5000,
    )

    try:
        with input_path.open("r", newline="", encoding="utf-8-sig") as infile:
            reader = csv.DictReader(infile)
            if not reader.fieldnames:
                raise SystemExit(f"No CSV header found in {input_path}")
            normalized_input_fields = [normalize_reviewonly_name(field) for field in reader.fieldnames]
            normalized_target_columns = [normalize_reviewonly_name(column) for column in NEW_COLUMNS]
            output_fields = insert_columns_after(
                normalized_input_fields,
                "original_url_display",
                normalized_target_columns,
            )
            rows = list(reader)

        detectors = {"person": person_detector, "face_yunet": face_detector}
        processed = 0

        with output_path.open("w", newline="", encoding="utf-8") as outfile:
            writer = csv.DictWriter(outfile, fieldnames=output_fields)
            writer.writeheader()

            for index, row in enumerate(rows, start=1):
                url = (row.get("original_url_display") or "").strip()
                normalized_row = {}
                for field, value in row.items():
                    normalized_row[normalize_reviewonly_name(field)] = value
                default_values = {column: normalized_row.get(column, "") for column in output_fields}
                normalized_row.update(default_values)

                if url and (limit <= 0 or processed < limit):
                    try:
                        enriched = enrich_row(url, timeout, detectors, cv2, np)
                        for key, value in enriched.items():
                            normalized_row[normalize_reviewonly_name(key)] = value
                    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
                        if verbose:
                            print(f"[row {index}] failed for {url}: {exc}", file=sys.stderr)
                    processed += 1

                ordered_row = {field: normalized_row.get(field, "") for field in output_fields}
                writer.writerow(ordered_row)

                if verbose and processed and processed % 25 == 0:
                    print(f"Analyzed {processed} images", file=sys.stderr)
    finally:
        pass


def main() -> None:
    args = parse_args()
    input_path = args.input.resolve()

    if not input_path.exists():
        raise SystemExit(f"Input CSV not found: {input_path}")

    if args.output:
        output_path = args.output.resolve()
    else:
        backup_path = input_path.with_name(input_path.name + args.backup_suffix)
        shutil.copy2(input_path, backup_path)
        output_path = input_path
        print(f"Backup created: {backup_path}", file=sys.stderr)

    process_csv(
        input_path=input_path,
        output_path=output_path,
        limit=args.limit,
        timeout=args.timeout,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
