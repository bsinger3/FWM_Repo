#!/usr/bin/env python3
"""Append YOLO person/pose metrics to the cached-image evaluation sample."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(__file__).resolve().parents[3] / "experiments/weight_estimation_cv/cache/ultralytics"))

from ultralytics import YOLO


REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = REPO_ROOT.parent
DEFAULT_INPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/eval_sample_with_images.csv"
DEFAULT_OUTPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/eval_sample_with_images_yolo.csv"
DEFAULT_REPORT = REPO_ROOT / "experiments/weight_estimation_cv/reports/yolo_metric_summary.json"
DEFAULT_DETECT_MODEL = PROJECT_ROOT / "FWM_Data/_models/yolov8n.pt"
DEFAULT_POSE_MODEL = PROJECT_ROOT / "FWM_Data/_models/yolov8n-pose.pt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--detect-model", type=Path, default=DEFAULT_DETECT_MODEL)
    parser.add_argument("--pose-model", type=Path, default=DEFAULT_POSE_MODEL)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def material_person_metrics(result) -> dict[str, str]:
    boxes = result.boxes
    image_h, image_w = result.orig_shape
    person_boxes = []
    if boxes is not None and len(boxes):
        for cls, xyxy, conf in zip(boxes.cls.cpu().tolist(), boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist()):
            if int(cls) == 0 and float(conf) >= 0.25:
                x1, y1, x2, y2 = [float(value) for value in xyxy]
                width = max(0.0, x2 - x1)
                height = max(0.0, y2 - y1)
                area_pct = (width * height) / float(image_w * image_h) if image_w and image_h else 0.0
                height_pct = height / float(image_h) if image_h else 0.0
                person_boxes.append((height_pct, area_pct, conf))
    person_boxes.sort(reverse=True)
    if not person_boxes:
        return {
            "yolo_person_count": "0",
            "yolo_main_person_height_pct": "0",
            "yolo_main_person_area_pct": "0",
            "yolo_main_person_conf": "0",
        }
    best_height, best_area, best_conf = person_boxes[0]
    return {
        "yolo_person_count": str(len(person_boxes)),
        "yolo_main_person_height_pct": f"{best_height:.4f}",
        "yolo_main_person_area_pct": f"{best_area:.4f}",
        "yolo_main_person_conf": f"{best_conf:.4f}",
    }


def pose_metrics(result) -> dict[str, str]:
    keypoints = result.keypoints
    if keypoints is None or len(keypoints) == 0:
        return {"yolo_pose_person_count": "0", "yolo_pose_visible_keypoint_pct": "0", "yolo_pose_mean_conf": "0"}
    conf = keypoints.conf
    if conf is None:
        return {"yolo_pose_person_count": str(len(keypoints)), "yolo_pose_visible_keypoint_pct": "", "yolo_pose_mean_conf": ""}
    person_scores = conf.cpu().numpy()
    visible = person_scores >= 0.25
    best_index = int(visible.sum(axis=1).argmax())
    best = person_scores[best_index]
    return {
        "yolo_pose_person_count": str(len(keypoints)),
        "yolo_pose_visible_keypoint_pct": f"{float((best >= 0.25).mean()):.4f}",
        "yolo_pose_mean_conf": f"{float(best.mean()):.4f}",
    }


def main() -> None:
    args = parse_args()
    rows = read_rows(args.input)
    if args.limit:
        rows = rows[: args.limit]
    eligible = [row for row in rows if row.get("download_status") in {"downloaded", "cached"} and Path(row.get("local_image_path", "")).exists()]
    paths = [row["local_image_path"] for row in eligible]

    detect_model = YOLO(str(args.detect_model))
    pose_model = YOLO(str(args.pose_model))
    row_by_id = {row["row_id"]: row for row in rows}
    eligible_by_path = {row["local_image_path"]: row for row in eligible}

    for result in detect_model(paths, batch=args.batch_size, device=args.device, verbose=False, stream=True):
        source = eligible_by_path[str(result.path)]
        row_by_id[source["row_id"]].update(material_person_metrics(result))
    for result in pose_model(paths, batch=args.batch_size, device=args.device, verbose=False, stream=True):
        source = eligible_by_path[str(result.path)]
        row_by_id[source["row_id"]].update(pose_metrics(result))

    fieldnames = list(rows[0].keys())
    for column in [
        "yolo_person_count",
        "yolo_main_person_height_pct",
        "yolo_main_person_area_pct",
        "yolo_main_person_conf",
        "yolo_pose_person_count",
        "yolo_pose_visible_keypoint_pct",
        "yolo_pose_mean_conf",
    ]:
        if column not in fieldnames:
            fieldnames.append(column)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    counts = {"rows": len(rows), "eligible_images": len(eligible), "output": str(args.output)}
    args.report.write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
