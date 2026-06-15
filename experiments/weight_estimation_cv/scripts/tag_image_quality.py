#!/usr/bin/env python3
"""Tag downloaded images with face/person eligibility and coarse quality buckets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault(
    "YOLO_CONFIG_DIR",
    str(Path(__file__).resolve().parents[3] / "experiments/weight_estimation_cv/cache/ultralytics"),
)
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(__file__).resolve().parents[3] / "experiments/weight_estimation_cv/cache/matplotlib"),
)

import cv2
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = REPO_ROOT.parent
DEFAULT_INPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/eval_sample_hardened.csv"
DEFAULT_OUTPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/eval_sample_with_quality_tags.csv"
DEFAULT_REPORT = REPO_ROOT / "experiments/weight_estimation_cv/reports/image_quality_coverage_summary.json"
DEFAULT_DETECT_MODEL = PROJECT_ROOT / "FWM_Data/models/yolov8n.pt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--detect-model", type=Path, default=DEFAULT_DETECT_MODEL)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--chunk-size", type=int, default=64)
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-person", action="store_true")
    return parser.parse_args()


def face_cascade() -> cv2.CascadeClassifier:
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(str(cascade_path))
    if cascade.empty():
        raise RuntimeError(f"Could not load OpenCV face cascade at {cascade_path}")
    return cascade


def detect_faces(path_value: object, cascade: cv2.CascadeClassifier) -> dict[str, object]:
    path = Path(str(path_value or ""))
    if not path.exists():
        return {
            "face_detect_status": "missing_image",
            "face_count": 0,
            "largest_face_area_pct": 0.0,
            "largest_face_width_pct": 0.0,
            "largest_face_height_pct": 0.0,
        }
    try:
        image = cv2.imread(str(path), cv2.IMREAD_REDUCED_COLOR_4)
    except cv2.error:
        image = None
    if image is None:
        return {
            "face_detect_status": "read_failed",
            "face_count": 0,
            "largest_face_area_pct": 0.0,
            "largest_face_width_pct": 0.0,
            "largest_face_height_pct": 0.0,
        }
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5, minSize=(24, 24))
    face_rows = []
    for x, y, w, h in faces:
        area_pct = float(w * h / (width * height)) if width and height else 0.0
        face_rows.append((area_pct, w / width if width else 0.0, h / height if height else 0.0))
    face_rows.sort(reverse=True)
    if not face_rows:
        return {
            "face_detect_status": "ok",
            "face_count": 0,
            "largest_face_area_pct": 0.0,
            "largest_face_width_pct": 0.0,
            "largest_face_height_pct": 0.0,
        }
    area_pct, width_pct, height_pct = face_rows[0]
    return {
        "face_detect_status": "ok",
        "face_count": int(len(face_rows)),
        "largest_face_area_pct": round(area_pct, 6),
        "largest_face_width_pct": round(float(width_pct), 6),
        "largest_face_height_pct": round(float(height_pct), 6),
    }


def empty_person_metrics() -> dict[str, object]:
    return {
        "person_detect_status": "not_run",
        "person_count": 0,
        "main_person_conf": 0.0,
        "main_person_area_pct": 0.0,
        "main_person_width_pct": 0.0,
        "main_person_height_pct": 0.0,
        "main_person_aspect_ratio": 0.0,
    }


def person_metrics_from_result(result) -> dict[str, object]:
    image_h, image_w = result.orig_shape
    people = []
    if result.boxes is not None and len(result.boxes):
        for cls, xyxy, conf in zip(
            result.boxes.cls.cpu().tolist(),
            result.boxes.xyxy.cpu().tolist(),
            result.boxes.conf.cpu().tolist(),
        ):
            if int(cls) != 0 or float(conf) < 0.25:
                continue
            x1, y1, x2, y2 = [float(value) for value in xyxy]
            width = max(0.0, x2 - x1)
            height = max(0.0, y2 - y1)
            area_pct = (width * height) / float(image_w * image_h) if image_w and image_h else 0.0
            height_pct = height / float(image_h) if image_h else 0.0
            width_pct = width / float(image_w) if image_w else 0.0
            aspect = height / width if width else 0.0
            people.append((area_pct, height_pct, width_pct, aspect, float(conf)))
    people.sort(reverse=True)
    if not people:
        out = empty_person_metrics()
        out["person_detect_status"] = "ok"
        return out
    area_pct, height_pct, width_pct, aspect, conf = people[0]
    return {
        "person_detect_status": "ok",
        "person_count": int(len(people)),
        "main_person_conf": round(conf, 6),
        "main_person_area_pct": round(area_pct, 6),
        "main_person_width_pct": round(width_pct, 6),
        "main_person_height_pct": round(height_pct, 6),
        "main_person_aspect_ratio": round(aspect, 6),
    }


def classify(row: pd.Series) -> dict[str, object]:
    face_visible = bool(row["face_count"] >= 1 and row["largest_face_area_pct"] >= 0.0025)
    large_face_visible = bool(row["face_count"] >= 1 and row["largest_face_area_pct"] >= 0.01)
    person_visible = bool(row["person_count"] >= 1 and row["main_person_conf"] >= 0.25)
    full_body_likely = bool(
        person_visible
        and row["main_person_height_pct"] >= 0.62
        and row["main_person_area_pct"] >= 0.12
        and row["main_person_aspect_ratio"] >= 1.35
    )
    torso_or_partial_body = bool(
        person_visible
        and not full_body_likely
        and (row["main_person_area_pct"] >= 0.07 or row["main_person_height_pct"] >= 0.35)
    )
    low_signal = bool(not face_visible and not person_visible)
    multiple_people = bool(row["person_count"] > 1)
    if full_body_likely:
        bucket = "full_body_likely"
    elif torso_or_partial_body:
        bucket = "torso_or_partial_body"
    elif person_visible:
        bucket = "person_visible_low_coverage"
    elif face_visible:
        bucket = "face_only_or_small_person"
    else:
        bucket = "low_signal"
    return {
        "face_visible": face_visible,
        "large_face_visible": large_face_visible,
        "person_visible": person_visible,
        "full_body_likely": full_body_likely,
        "torso_or_partial_body": torso_or_partial_body,
        "multiple_people": multiple_people,
        "low_signal": low_signal,
        "image_quality_bucket": bucket,
    }


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input)
    if args.limit:
        df = df.head(args.limit).copy()

    cascade = face_cascade()
    face_rows = []
    for index, path in enumerate(df["local_image_path"], start=1):
        face_rows.append(detect_faces(path, cascade))
        if index % 100 == 0:
            print(f"processed face detection {index}/{len(df)}", flush=True)
    face_df = pd.DataFrame(face_rows)
    df = pd.concat([df.reset_index(drop=True), face_df], axis=1)

    for key, value in empty_person_metrics().items():
        df[key] = value

    eligible = df[df["is_downloaded_image"] & df["local_image_path"].map(lambda value: Path(str(value)).exists())].copy()
    if not args.skip_person:
        from ultralytics import YOLO

        model = YOLO(str(args.detect_model))
        paths = eligible["local_image_path"].astype(str).tolist()
        path_to_index = {str(row.local_image_path): index for index, row in eligible.iterrows()}
        processed = 0
        for chunk_start in range(0, len(paths), args.chunk_size):
            chunk = paths[chunk_start : chunk_start + args.chunk_size]
            for result_index, result in enumerate(model(
                chunk,
                batch=args.batch_size,
                device=args.device,
                imgsz=args.imgsz,
                verbose=False,
                stream=True,
            )):
                metrics = person_metrics_from_result(result)
                target_index = path_to_index[chunk[result_index]]
                for key, value in metrics.items():
                    df.at[target_index, key] = value
            processed += len(chunk)
            print(f"processed YOLO person detection {processed}/{len(paths)}", flush=True)

    class_rows = [classify(row) for _, row in df.iterrows()]
    df = pd.concat([df.reset_index(drop=True), pd.DataFrame(class_rows)], axis=1)

    report = {
        "input": str(args.input),
        "output": str(args.output),
        "rows": int(len(df)),
        "downloaded_rows": int(df["is_downloaded_image"].sum()),
        "face_visible_rows": int(df["face_visible"].sum()),
        "large_face_visible_rows": int(df["large_face_visible"].sum()),
        "person_visible_rows": int(df["person_visible"].sum()),
        "full_body_likely_rows": int(df["full_body_likely"].sum()),
        "torso_or_partial_body_rows": int(df["torso_or_partial_body"].sum()),
        "multiple_people_rows": int(df["multiple_people"].sum()),
        "low_signal_rows": int(df["low_signal"].sum()),
        "quality_buckets": df["image_quality_bucket"].value_counts().to_dict(),
        "by_split": {
            split: {
                "rows": int(len(group)),
                "downloaded_rows": int(group["is_downloaded_image"].sum()),
                "face_visible_rows": int(group["face_visible"].sum()),
                "person_visible_rows": int(group["person_visible"].sum()),
                "full_body_likely_rows": int(group["full_body_likely"].sum()),
                "torso_or_partial_body_rows": int(group["torso_or_partial_body"].sum()),
            }
            for split, group in df.groupby("split")
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
