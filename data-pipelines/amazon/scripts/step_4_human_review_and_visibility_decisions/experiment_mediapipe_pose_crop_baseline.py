#!/usr/bin/env python3
"""MediaPipe pose/crop pilot over the image-quality baseline sample."""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

import pandas as pd
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[4]
BASELINE_DIR = REPO_ROOT / "outputs/cv_experiments/image_quality_baseline"
OUT_DIR = REPO_ROOT / "outputs/cv_experiments/mediapipe_pose_crop_baseline"

POSE_LANDMARK_NAMES = [
    "nose",
    "left_eye_inner",
    "left_eye",
    "left_eye_outer",
    "right_eye_inner",
    "right_eye",
    "right_eye_outer",
    "left_ear",
    "right_ear",
    "mouth_left",
    "mouth_right",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_pinky",
    "right_pinky",
    "left_index",
    "right_index",
    "left_thumb",
    "right_thumb",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
]

LOWER_BODY = {"left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle", "left_heel", "right_heel", "left_foot_index", "right_foot_index"}
ANKLE_FOOT = {"left_ankle", "right_ankle", "left_heel", "right_heel", "left_foot_index", "right_foot_index"}
TORSO_HIP = {"left_shoulder", "right_shoulder", "left_hip", "right_hip"}


def import_mediapipe(vendor_dir: str):
    sys.path.insert(0, vendor_dir)
    from mediapipe import Image as MpImage
    from mediapipe import ImageFormat
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    return MpImage, ImageFormat, python, vision


def fetch_rgb(url: str, timeout: float) -> Optional[Image.Image]:
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
        return Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        return None


def make_landmarker(vendor_dir: str, model_path: str):
    MpImage, ImageFormat, python, vision = import_mediapipe(vendor_dir)
    options = vision.PoseLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=model_path, delegate=python.BaseOptions.Delegate.CPU),
        running_mode=vision.RunningMode.IMAGE,
        num_poses=2,
        min_pose_detection_confidence=0.4,
        min_pose_presence_confidence=0.4,
        min_tracking_confidence=0.4,
    )
    return vision.PoseLandmarker.create_from_options(options), MpImage, ImageFormat


def pose_features(result, width: int, height: int, min_presence: float) -> Dict[str, object]:
    if not result.pose_landmarks:
        return {
            "mp_pose_detected": False,
            "mp_pose_count": 0,
            "mp_visible_landmarks": 0,
            "mp_lower_body_visible_count": 0,
            "mp_ankle_foot_visible_count": 0,
            "mp_torso_hip_visible_count": 0,
            "mp_landmark_bbox_height_pct": "",
            "mp_landmark_bbox_area_pct": "",
            "mp_landmark_edge_touch": "",
            "mp_flags": "NO_POSE",
        }

    poses = result.pose_landmarks
    pose = max(poses, key=lambda landmarks: sum(1 for landmark in landmarks if getattr(landmark, "presence", 1.0) >= min_presence))
    visible = []
    xs = []
    ys = []
    for name, landmark in zip(POSE_LANDMARK_NAMES, pose):
        presence = getattr(landmark, "presence", 1.0)
        visibility = getattr(landmark, "visibility", 1.0)
        if presence >= min_presence and visibility >= 0.35:
            visible.append(name)
            xs.append(max(0.0, min(1.0, landmark.x)))
            ys.append(max(0.0, min(1.0, landmark.y)))

    if not xs or not ys:
        return {
            "mp_pose_detected": True,
            "mp_pose_count": len(poses),
            "mp_visible_landmarks": 0,
            "mp_lower_body_visible_count": 0,
            "mp_ankle_foot_visible_count": 0,
            "mp_torso_hip_visible_count": 0,
            "mp_landmark_bbox_height_pct": "",
            "mp_landmark_bbox_area_pct": "",
            "mp_landmark_edge_touch": "",
            "mp_flags": "LOW_KEYPOINT_CONFIDENCE",
        }

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    bbox_h = max_y - min_y
    bbox_w = max_x - min_x
    edge_touch = min_x < 0.03 or max_x > 0.97 or min_y < 0.03 or max_y > 0.97

    visible_set = set(visible)
    lower_count = len(visible_set & LOWER_BODY)
    ankle_foot_count = len(visible_set & ANKLE_FOOT)
    torso_hip_count = len(visible_set & TORSO_HIP)
    flags: List[str] = []
    if len(poses) > 1:
        flags.append("MULTIPLE_POSES")
    if bbox_h < 0.45:
        flags.append("PERSON_TOO_FAR_OR_PARTIAL")
    if edge_touch:
        flags.append("POSE_TOUCHES_EDGE")
    if lower_count < 4:
        flags.append("LOW_LOWER_BODY_KEYPOINTS")
    if ankle_foot_count < 2:
        flags.append("ANKLE_FOOT_NOT_VISIBLE")
    if torso_hip_count < 3:
        flags.append("TORSO_HIP_INCOMPLETE")

    return {
        "mp_pose_detected": True,
        "mp_pose_count": len(poses),
        "mp_visible_landmarks": len(visible),
        "mp_lower_body_visible_count": lower_count,
        "mp_ankle_foot_visible_count": ankle_foot_count,
        "mp_torso_hip_visible_count": torso_hip_count,
        "mp_landmark_bbox_height_pct": round(bbox_h, 3),
        "mp_landmark_bbox_area_pct": round(bbox_h * bbox_w, 3),
        "mp_landmark_edge_touch": edge_touch,
        "mp_flags": ";".join(flags),
    }


def summarize(rows: List[Dict[str, object]]) -> str:
    total = len(rows)
    detected = sum(1 for row in rows if row.get("mp_pose_detected") is True)
    label_counts = pd.Series([row.get("human_label") for row in rows]).value_counts().to_dict()
    flag_counts = {}
    for row in rows:
        for flag in str(row.get("mp_flags") or "").split(";"):
            if flag:
                flag_counts[flag] = flag_counts.get(flag, 0) + 1
    lines = [
        "# MediaPipe Pose/Crop Baseline",
        "",
        f"- rows evaluated: `{total}`",
        f"- pose detected: `{detected}`",
        f"- human labels: `{label_counts}`",
        "",
        "## Pose Flag Counts",
        "",
        "| flag | count |",
        "| --- | ---: |",
    ]
    for flag, count in sorted(flag_counts.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"| `{flag}` | {count} |")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This is a lightweight first pass using MediaPipe Pose Landmarker Lite.",
            "- Flags are heuristic features for evaluation, not production decisions.",
            "- The most useful near-term checks are ankle/foot visibility, edge touch, and pose/keypoint availability.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor-dir", default="/private/tmp/fwm_mediapipe_vendor")
    parser.add_argument("--model-path", default="/private/tmp/fwm_mediapipe_models/pose_landmarker_lite.task")
    parser.add_argument("--limit-per-class", type=int, default=40)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--min-presence", type=float, default=0.35)
    args = parser.parse_args()

    os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/fwm_mpl")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    baseline = pd.read_csv(BASELINE_DIR / "image_quality_baseline_results.csv", dtype=str, keep_default_na=False)
    baseline = baseline[baseline["fetch_ok"].astype(str) == "True"].copy()
    sampled = []
    for label, frame in baseline.groupby("human_label", sort=False):
        sampled.append(frame.head(args.limit_per_class))
    sample = pd.concat(sampled, ignore_index=True)

    landmarker, MpImage, ImageFormat = make_landmarker(args.vendor_dir, args.model_path)
    output_rows: List[Dict[str, object]] = []
    for index, row in sample.iterrows():
        url = row.get("selected_url") or row.get("image_url")
        image = fetch_rgb(url, args.timeout)
        combined = row.to_dict()
        if image is None:
            combined.update({"mp_pose_detected": False, "mp_flags": "IMAGE_FETCH_FAILED"})
        else:
            np_image = np.array(image)
            mp_image = MpImage(image_format=ImageFormat.SRGB, data=np_image)
            result = landmarker.detect(mp_image)
            combined.update(pose_features(result, image.size[0], image.size[1], args.min_presence))
        output_rows.append(combined)
        if (index + 1) % 25 == 0:
            print(f"processed {index + 1}/{len(sample)}")

    csv_path = OUT_DIR / "mediapipe_pose_crop_results.csv"
    report_path = OUT_DIR / "mediapipe_pose_crop_report.md"
    fieldnames = sorted({key for row in output_rows for key in row.keys()})
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)
    report_path.write_text(summarize(output_rows), encoding="utf-8")
    print(csv_path)
    print(report_path)


if __name__ == "__main__":
    import numpy as np

    main()
