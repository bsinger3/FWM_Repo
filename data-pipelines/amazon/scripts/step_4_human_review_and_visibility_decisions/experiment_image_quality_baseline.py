#!/usr/bin/env python3
"""Baseline image-quality and URL-recovery experiment for Step 4 ground truth."""

from __future__ import annotations

import argparse
import csv
import math
import time
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from PIL import Image, ImageStat


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = REPO_ROOT.parent
DATA_ROOT = PROJECT_ROOT / "FWM_Data"

PART001 = DATA_ROOT / "amazon/data/step_4_human_review_and_visibility_decisions/manual_chunks/backup/images_to_approve_part_001_SORTED_FacialDetectionGT_RejectionReasons1.csv"
PART002 = DATA_ROOT / "amazon/data/step_4_human_review_and_visibility_decisions/part_002_REVIEWED.csv"
OUT_DIR = REPO_ROOT / "outputs/cv_experiments/image_quality_baseline"


def larger_image_url_candidates(url: str) -> List[str]:
    candidates = [url]
    try:
        parts = urlsplit(url)
    except Exception:
        return candidates
    if "media-amazon.com" not in parts.netloc and "images-amazon.com" not in parts.netloc:
        return candidates
    filename = parts.path.rsplit("/", 1)[-1]
    if "._" not in filename:
        return candidates
    stem, _transform = filename.split("._", 1)
    extension = ""
    for candidate_extension in (".jpg", ".jpeg", ".png", ".webp"):
        if filename.lower().endswith(candidate_extension):
            extension = filename[-len(candidate_extension) :]
            break
    if not extension:
        return candidates
    canonical_path = parts.path.rsplit("/", 1)[0] + "/" + stem + extension
    canonical_url = urlunsplit((parts.scheme, parts.netloc, canonical_path, parts.query, parts.fragment))
    if canonical_url != url:
        candidates.insert(0, canonical_url)
    return list(dict.fromkeys(candidates))


def load_rows(limit_per_class: int) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []

    part001 = pd.read_csv(PART001, dtype=str, keep_default_na=False)
    for label, frame in part001.groupby("image_approved? (1=Approved,2=NotApproved)", sort=False):
        if label not in {"1", "2"}:
            continue
        sample = frame.head(limit_per_class)
        for _, row in sample.iterrows():
            rows.append(
                {
                    "dataset": "part001",
                    "review_row_key": f"part001::{int(row.name) + 2}",
                    "image_url": row.get("original_url_display", ""),
                    "human_label": "APPROVE" if label == "1" else "REJECT",
                    "human_reason": row.get("Reason_for_Rejection", ""),
                    "has_person_existing": row.get("has_person", ""),
                    "has_face_yunet_existing": row.get("has_face_yunet", ""),
                    "face_ground_truth": row.get("has_face_GroundTruth (1=face,2=noFace)", ""),
                    "person_count_yolo_detect": "",
                    "main_person_height_pct_yolo_detect": "",
                    "main_person_bbox_area_pct_yolo_detect": "",
                    "body_coverage_score_yolo_pose": "",
                    "cv_reason_code": "",
                }
            )

    part002 = pd.read_csv(PART002, dtype=str, keep_default_na=False)
    manual_col = "Manual_approval(1=approved,2=reject, 3=ApprovedANDLabel'Pretty\")"
    approved = part002[part002[manual_col].isin(["1", "3"])].head(limit_per_class)
    rejected = part002[part002[manual_col] == "2"].head(limit_per_class)
    for frame, label in ((approved, "APPROVE"), (rejected, "REJECT")):
        for _, row in frame.iterrows():
            rows.append(
                {
                    "dataset": "part002",
                    "review_row_key": row.get("review_row_key", ""),
                    "image_url": row.get("original_url_display", ""),
                    "human_label": label,
                    "human_reason": row.get("Rejection Reason_Manual", ""),
                    "has_person_existing": "",
                    "has_face_yunet_existing": row.get("has_face_yunet", ""),
                    "face_ground_truth": row.get("FacePresent?_GroundTruth (1=FacePresent,2=NoFace)", ""),
                    "person_count_yolo_detect": row.get("person_count_yolo_detect", ""),
                    "main_person_height_pct_yolo_detect": row.get("main_person_height_pct_yolo_detect", ""),
                    "main_person_bbox_area_pct_yolo_detect": row.get("main_person_bbox_area_pct_yolo_detect", ""),
                    "body_coverage_score_yolo_pose": row.get("body_coverage_score_yolo_pose", ""),
                    "cv_reason_code": row.get("cv_reason_code", ""),
                }
            )
    return [row for row in rows if str(row.get("image_url") or "").strip()]


def fetch_image(url: str, timeout: float, retries: int) -> Tuple[Optional[Image.Image], Dict[str, object]]:
    attempts = []
    best: Optional[Tuple[Image.Image, str, int]] = None
    last_error = ""
    for candidate in larger_image_url_candidates(url):
        for attempt in range(retries):
            try:
                request = Request(
                    candidate,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123 Safari/537.36"
                    },
                )
                with urlopen(request, timeout=timeout) as response:
                    data = response.read()
                image = Image.open(BytesIO(data)).convert("RGB")
                pixels = image.size[0] * image.size[1]
                attempts.append({"url": candidate, "ok": True, "width": image.size[0], "height": image.size[1], "bytes": len(data)})
                if best is None or pixels > best[2]:
                    best = (image, candidate, pixels)
                break
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                last_error = repr(exc)
                attempts.append({"url": candidate, "ok": False, "error": last_error})
                if attempt + 1 < retries:
                    time.sleep(0.25 * (attempt + 1))
    if best is None:
        return None, {"fetch_ok": False, "fetch_error": last_error, "candidate_count": len(larger_image_url_candidates(url))}
    image, selected_url, _pixels = best
    original_candidate = attempts[-1] if attempts else {}
    return image, {
        "fetch_ok": True,
        "selected_url": selected_url,
        "url_was_upgraded": selected_url != url,
        "candidate_count": len(larger_image_url_candidates(url)),
        "loaded_width": image.size[0],
        "loaded_height": image.size[1],
        "loaded_pixels": image.size[0] * image.size[1],
        "attempts": attempts,
        "original_candidate_ok": bool(original_candidate.get("ok")),
    }


def laplacian_variance(gray: np.ndarray) -> float:
    gray = gray.astype(np.float32)
    center = -4 * gray[1:-1, 1:-1]
    lap = center + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    return float(np.var(lap))


def edge_density(gray: np.ndarray) -> float:
    gray = gray.astype(np.float32)
    dx = np.abs(gray[:, 1:] - gray[:, :-1])
    dy = np.abs(gray[1:, :] - gray[:-1, :])
    return float((np.mean(dx > 20) + np.mean(dy > 20)) / 2)


def quality_metrics(image: Image.Image) -> Dict[str, object]:
    thumb = image.copy()
    thumb.thumbnail((768, 768))
    arr = np.asarray(thumb)
    gray_img = thumb.convert("L")
    gray = np.asarray(gray_img)
    stat = ImageStat.Stat(gray_img)
    luminance = gray.astype(np.float32)
    dark_pct = float(np.mean(luminance < 35))
    bright_pct = float(np.mean(luminance > 245))
    contrast = float(stat.stddev[0])
    hsv = thumb.convert("HSV")
    hsv_arr = np.asarray(hsv)
    saturation_mean = float(np.mean(hsv_arr[:, :, 1]))
    return {
        "width": image.size[0],
        "height": image.size[1],
        "pixels": image.size[0] * image.size[1],
        "aspect_ratio": round(image.size[0] / image.size[1], 3) if image.size[1] else "",
        "luminance_mean": round(float(stat.mean[0]), 2),
        "luminance_median": round(float(np.median(luminance)), 2),
        "contrast_std": round(contrast, 2),
        "dark_pixel_pct": round(dark_pct, 4),
        "bright_pixel_pct": round(bright_pct, 4),
        "saturation_mean": round(saturation_mean, 2),
        "laplacian_variance": round(laplacian_variance(gray), 2),
        "edge_density": round(edge_density(gray), 4),
    }


def flag_row(metrics: Dict[str, object]) -> Dict[str, object]:
    if not metrics.get("fetch_ok"):
        return {
            "quality_flags": "INVALID_OR_DEAD_IMAGE_URL",
            "quality_risk_score": 100,
        }
    flags = []
    width = float(metrics.get("width") or 0)
    height = float(metrics.get("height") or 0)
    pixels = float(metrics.get("pixels") or 0)
    lum = float(metrics.get("luminance_mean") or 0)
    contrast = float(metrics.get("contrast_std") or 0)
    dark = float(metrics.get("dark_pixel_pct") or 0)
    bright = float(metrics.get("bright_pixel_pct") or 0)
    blur = float(metrics.get("laplacian_variance") or 0)
    if min(width, height) < 300 or pixels < 180_000:
        flags.append("LOW_RESOLUTION")
    if lum < 65 or dark > 0.30:
        flags.append("TOO_DARK")
    if bright > 0.18:
        flags.append("TOO_BRIGHT_OR_WASHED_OUT")
    if blur < 55:
        flags.append("BLURRY_OR_LOW_DETAIL")
    if contrast < 28:
        flags.append("LOW_CONTRAST")
    score = min(100, 25 * len(flags) + (15 if metrics.get("url_was_upgraded") else 0))
    return {
        "quality_flags": ";".join(flags),
        "quality_risk_score": score,
    }


def summarize(output_rows: List[Dict[str, object]]) -> str:
    total = len(output_rows)
    loaded = sum(1 for row in output_rows if row.get("fetch_ok"))
    upgraded = sum(1 for row in output_rows if row.get("url_was_upgraded"))
    labels = Counter(str(row.get("human_label") or "") for row in output_rows)
    flags = Counter()
    for row in output_rows:
        for flag in str(row.get("quality_flags") or "").split(";"):
            if flag:
                flags[flag] += 1

    lines = [
        "# Image Quality Baseline Experiment",
        "",
        f"- rows evaluated: `{total}`",
        f"- images loaded: `{loaded}`",
        f"- URL upgraded to larger candidate: `{upgraded}`",
        f"- human labels: `{dict(labels)}`",
        "",
        "## Quality Flag Counts",
        "",
        "| flag | count |",
        "| --- | ---: |",
    ]
    for flag, count in flags.most_common():
        lines.append(f"| `{flag}` | {count} |")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This baseline uses only URL recovery and objective image metrics. It does not run new object, pose, or segmentation models.",
            "- Flags are intentionally rough first-pass candidates for calibration, not production rejection thresholds.",
            "- Low resolution is evaluated after trying larger Amazon URL variants.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-per-class", type=int, default=75)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_rows(args.limit_per_class)
    output_rows: List[Dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        image, fetch = fetch_image(str(row["image_url"]), args.timeout, args.retries)
        combined = dict(row)
        combined.update({key: value for key, value in fetch.items() if key != "attempts"})
        if image is not None:
            combined.update(quality_metrics(image))
        combined.update(flag_row(combined))
        output_rows.append(combined)
        if index % 50 == 0:
            print(f"processed {index}/{len(rows)}")

    csv_path = OUT_DIR / "image_quality_baseline_results.csv"
    md_path = OUT_DIR / "image_quality_baseline_report.md"
    fieldnames = sorted({key for row in output_rows for key in row.keys()})
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)
    md_path.write_text(summarize(output_rows), encoding="utf-8")
    print(csv_path)
    print(md_path)


if __name__ == "__main__":
    main()
