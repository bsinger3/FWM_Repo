#!/usr/bin/env python3
"""Create reusable YOLO person-crop boxes for downloaded experiment images."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(__file__).resolve().parents[1] / "cache/ultralytics"))
os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / "cache/matplotlib"))

import pandas as pd
from ultralytics import YOLO


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPERIMENT_ROOT.parents[1]
PROJECT_ROOT = REPO_ROOT.parent
DEFAULT_INPUT = EXPERIMENT_ROOT / "data/eval_sample_with_quality_tags.csv"
DEFAULT_DETECT_MODEL = PROJECT_ROOT / "FWM_Data/_models/yolov8n.pt"
DEFAULT_ATTEMPTS = EXPERIMENT_ROOT / "data/person_crop_attempt_rows.csv"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/person_crop_attempt_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--detect-model", type=Path, default=DEFAULT_DETECT_MODEL)
    parser.add_argument("--attempts", type=Path, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--chunk-size", type=int, default=64)
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def choose_person_box(result) -> dict[str, float] | None:
    image_h, image_w = result.orig_shape
    people = []
    if result.boxes is None or not len(result.boxes):
        return None
    for cls, xyxy, conf in zip(result.boxes.cls.cpu().tolist(), result.boxes.xyxy.cpu().tolist(), result.boxes.conf.cpu().tolist()):
        if int(cls) != 0 or float(conf) < 0.25:
            continue
        x1, y1, x2, y2 = [float(value) for value in xyxy]
        width = max(0.0, x2 - x1)
        height = max(0.0, y2 - y1)
        people.append((width * height, float(conf), x1, y1, x2, y2))
    if not people:
        return None
    _, conf, x1, y1, x2, y2 = sorted(people, reverse=True)[0]
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    return {
        "image_w": float(image_w),
        "image_h": float(image_h),
        "person_count": float(len(people)),
        "conf": conf,
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "width": width,
        "height": height,
        "area": width * height,
    }


def crop_metrics(box: dict[str, float]) -> dict[str, float]:
    image_w = box["image_w"]
    image_h = box["image_h"]
    return {
        "crop_x1_pct": box["x1"] / image_w if image_w else 0.0,
        "crop_y1_pct": box["y1"] / image_h if image_h else 0.0,
        "crop_x2_pct": box["x2"] / image_w if image_w else 0.0,
        "crop_y2_pct": box["y2"] / image_h if image_h else 0.0,
        "crop_area_pct": box["area"] / (image_w * image_h) if image_w and image_h else 0.0,
        "crop_width_pct": box["width"] / image_w if image_w else 0.0,
        "crop_height_pct": box["height"] / image_h if image_h else 0.0,
        "crop_aspect_ratio": box["height"] / box["width"] if box["width"] else 0.0,
        "crop_person_conf": box["conf"],
        "crop_person_count": box["person_count"],
    }


def empty_crop_metrics() -> dict[str, object]:
    return {
        "crop_x1_pct": "",
        "crop_y1_pct": "",
        "crop_x2_pct": "",
        "crop_y2_pct": "",
        "crop_area_pct": "",
        "crop_width_pct": "",
        "crop_height_pct": "",
        "crop_aspect_ratio": "",
        "crop_person_conf": "",
        "crop_person_count": "",
    }


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input)
    work = df[df["is_downloaded_image"].astype(bool)].copy()
    work = work[work["local_image_path"].map(lambda value: Path(str(value)).exists())].copy()
    if args.limit:
        work = work.head(args.limit).copy()

    detector = YOLO(str(args.detect_model))
    paths = work["local_image_path"].astype(str).tolist()
    rows_by_path = {str(row.local_image_path): row for row in work.itertuples(index=False)}
    rows = []
    processed = 0

    for start in range(0, len(paths), args.chunk_size):
        chunk = paths[start : start + args.chunk_size]
        for result_index, result in enumerate(
            detector(chunk, batch=args.batch_size, device=args.device, imgsz=args.imgsz, verbose=False, stream=True)
        ):
            path = chunk[result_index]
            row = rows_by_path[path]._asdict()
            box = choose_person_box(result)
            if box is None:
                rows.append({**row, **empty_crop_metrics(), "crop_status": "no_person"})
                continue
            rows.append({**row, **crop_metrics(box), "crop_status": "ok"})
        processed += len(chunk)
        print(f"processed person crop attempts {processed}/{len(paths)}", flush=True)

    out = pd.DataFrame(rows)
    report = {
        "input": str(args.input),
        "attempts": str(args.attempts),
        "attempted_rows": int(len(out)),
        "status_counts": out["crop_status"].value_counts(dropna=False).to_dict() if len(out) else {},
        "by_split": {
            split: group["crop_status"].value_counts(dropna=False).to_dict()
            for split, group in out.groupby("split")
        } if len(out) else {},
    }

    args.attempts.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.attempts, index=False)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
