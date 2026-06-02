#!/usr/bin/env python3
"""Evaluate YOLO segmentation mask features against labeled crop/angle reasons."""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from experiment_image_quality_baseline import fetch_image  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[4]
GROUND_TRUTH_CSV = REPO_ROOT / "outputs/cv_experiments/ground_truth_labeling/labeled_image_rejection_reason_queue.csv"
OUT_DIR = REPO_ROOT / "outputs/cv_experiments/yolo_segmentation_crop_reasons"
CACHE_DIR = OUT_DIR / "image_cache"
DEFAULT_MODEL_PATH = REPO_ROOT / "outputs/cv_experiments/model_cache/yolo11n-seg.pt"

REASONS = [
    "NEEDS_CROP",
    "BAD_ANGLE_TOP_DOWN",
    "GARMENT_TOP_COVERED",
    "GARMENT_BOTTOM_CUT_OFF",
    "GARMENT_TOO_PARTIAL",
    "GARMENT_CUT_OFF",
    "GARMENT_OBSCURED",
    "NOT_WORN_BY_PERSON",
    "NO_PERSON_VISIBLE",
]


def read_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def normalize_decision(value: str) -> str:
    text = (value or "").strip().upper()
    return text if text in {"APPROVED", "REJECTED"} else ""


def normalize_reason(value: str) -> str:
    return (value or "").strip().upper()


def truth_has_reason(row: Dict[str, str], reason: str) -> bool:
    if normalize_reason(row.get("primary_reason_code", "")) == reason:
        return True
    if normalize_reason(row.get("secondary_reason_code", "")) == reason:
        return True
    value = (row.get(reason, "") or "").strip().lower()
    return value in {"true", "yes", "1", "x", "checked"}


def to_float(value: object) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except ValueError:
        return None


def image_cache_path(url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.jpg"


def load_or_fetch_image(url: str, timeout: float, retries: int):
    from PIL import Image

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = image_cache_path(url)
    if path.exists():
        return Image.open(path).convert("RGB"), {"fetch_ok": True, "loaded_from_cache": True}
    image, fetch = fetch_image(url, timeout=timeout, retries=retries)
    if image is not None:
        image.save(path, quality=92)
    fetch["loaded_from_cache"] = False
    return image, fetch


def best_person_mask_features(result, np) -> Dict[str, object]:
    if result is None or result.boxes is None or len(result.boxes) == 0:
        return {"seg_person_count": 0}
    if result.masks is None or result.masks.data is None:
        return {"seg_person_count": 0}

    boxes = result.boxes
    classes = boxes.cls.detach().cpu().numpy().astype(int)
    confidences = boxes.conf.detach().cpu().numpy()
    xyxy = boxes.xyxy.detach().cpu().numpy()
    masks = result.masks.data.detach().cpu().numpy()
    height, width = result.orig_shape

    person_indexes = [idx for idx, class_id in enumerate(classes) if class_id == 0 and confidences[idx] >= 0.25]
    if not person_indexes:
        return {"seg_person_count": 0}

    best_index = max(person_indexes, key=lambda idx: float((xyxy[idx][2] - xyxy[idx][0]) * (xyxy[idx][3] - xyxy[idx][1])))
    mask = masks[best_index] > 0.5
    if mask.shape != (height, width):
        import cv2

        mask = cv2.resize(mask.astype("uint8"), (width, height), interpolation=cv2.INTER_NEAREST).astype(bool)

    ys, xs = np.where(mask)
    if len(xs) == 0 or len(ys) == 0:
        return {"seg_person_count": len(person_indexes)}

    x1, y1, x2, y2 = xyxy[best_index]
    mask_x1, mask_x2 = int(xs.min()), int(xs.max())
    mask_y1, mask_y2 = int(ys.min()), int(ys.max())
    edge = max(2, int(round(min(width, height) * 0.03)))
    mask_pixels = int(mask.sum())
    top_band = int(mask[:edge, :].sum())
    bottom_band = int(mask[-edge:, :].sum())
    left_band = int(mask[:, :edge].sum())
    right_band = int(mask[:, -edge:].sum())
    edge_band_pixels = top_band + bottom_band + left_band + right_band
    bbox_area = float(max(0.0, x2 - x1) * max(0.0, y2 - y1))
    mask_bbox_area = float((mask_x2 - mask_x1 + 1) * (mask_y2 - mask_y1 + 1))

    return {
        "seg_person_count": len(person_indexes),
        "seg_person_confidence": round(float(confidences[best_index]), 4),
        "seg_bbox_x1_pct": round(float(x1 / width), 4),
        "seg_bbox_y1_pct": round(float(y1 / height), 4),
        "seg_bbox_x2_pct": round(float(x2 / width), 4),
        "seg_bbox_y2_pct": round(float(y2 / height), 4),
        "seg_bbox_width_pct": round(float((x2 - x1) / width), 4),
        "seg_bbox_height_pct": round(float((y2 - y1) / height), 4),
        "seg_bbox_area_pct": round(float(bbox_area / (width * height)), 4),
        "seg_mask_area_pct": round(float(mask_pixels / (width * height)), 4),
        "seg_mask_bbox_area_pct": round(float(mask_bbox_area / (width * height)), 4),
        "seg_mask_fill_ratio": round(float(mask_pixels / mask_bbox_area), 4) if mask_bbox_area else "",
        "seg_mask_top_gap_pct": round(float(mask_y1 / height), 4),
        "seg_mask_bottom_gap_pct": round(float((height - 1 - mask_y2) / height), 4),
        "seg_mask_left_gap_pct": round(float(mask_x1 / width), 4),
        "seg_mask_right_gap_pct": round(float((width - 1 - mask_x2) / width), 4),
        "seg_mask_touches_top": int(mask_y1 <= edge),
        "seg_mask_touches_bottom": int(mask_y2 >= height - 1 - edge),
        "seg_mask_touches_left": int(mask_x1 <= edge),
        "seg_mask_touches_right": int(mask_x2 >= width - 1 - edge),
        "seg_mask_edge_contact_count": int((mask_y1 <= edge) + (mask_y2 >= height - 1 - edge) + (mask_x1 <= edge) + (mask_x2 >= width - 1 - edge)),
        "seg_mask_edge_band_pct": round(float(edge_band_pixels / mask_pixels), 4) if mask_pixels else "",
        "seg_image_width": width,
        "seg_image_height": height,
    }


Rule = Tuple[str, Callable[[Dict[str, object]], bool]]


def rules() -> List[Rule]:
    return [
        ("no_person_segmented", lambda row: (to_float(row.get("seg_person_count")) or 0) == 0),
        ("mask_touches_top", lambda row: int(to_float(row.get("seg_mask_touches_top")) or 0) == 1),
        ("mask_touches_bottom", lambda row: int(to_float(row.get("seg_mask_touches_bottom")) or 0) == 1),
        ("mask_touches_top_or_bottom", lambda row: int(to_float(row.get("seg_mask_touches_top")) or 0) == 1 or int(to_float(row.get("seg_mask_touches_bottom")) or 0) == 1),
        ("mask_edge_contact_gte_2", lambda row: (to_float(row.get("seg_mask_edge_contact_count")) or 0) >= 2),
        ("mask_edge_band_pct_gt_0.10", lambda row: (to_float(row.get("seg_mask_edge_band_pct")) or 0) > 0.10),
        ("mask_top_gap_lt_0.04", lambda row: (to_float(row.get("seg_mask_top_gap_pct")) or 1) < 0.04),
        ("mask_bottom_gap_lt_0.04", lambda row: (to_float(row.get("seg_mask_bottom_gap_pct")) or 1) < 0.04),
        ("mask_top_or_bottom_gap_lt_0.04", lambda row: (to_float(row.get("seg_mask_top_gap_pct")) or 1) < 0.04 or (to_float(row.get("seg_mask_bottom_gap_pct")) or 1) < 0.04),
        ("mask_area_lt_0.20", lambda row: (to_float(row.get("seg_mask_area_pct")) or 1) < 0.20),
        ("mask_area_lt_0.30", lambda row: (to_float(row.get("seg_mask_area_pct")) or 1) < 0.30),
        ("bbox_height_lt_0.70", lambda row: (to_float(row.get("seg_bbox_height_pct")) or 1) < 0.70),
        ("bbox_height_lt_0.80", lambda row: (to_float(row.get("seg_bbox_height_pct")) or 1) < 0.80),
        ("bbox_area_lt_0.35", lambda row: (to_float(row.get("seg_bbox_area_pct")) or 1) < 0.35),
        ("bbox_area_lt_0.45", lambda row: (to_float(row.get("seg_bbox_area_pct")) or 1) < 0.45),
    ]


def evaluate_reason(rows: List[Dict[str, object]], reason: str, rule_name: str, predicate: Callable[[Dict[str, object]], bool]) -> Dict[str, object]:
    usable = [row for row in rows if row.get("final_human_decision_norm") in {"APPROVED", "REJECTED"}]
    positives = [row for row in usable if row.get(f"truth_{reason}") is True]
    negatives = [row for row in usable if row.get(f"truth_{reason}") is False]
    approved_negatives = [row for row in negatives if row.get("final_human_decision_norm") == "APPROVED"]
    tp = sum(1 for row in positives if predicate(row))
    fn = sum(1 for row in positives if not predicate(row))
    fp = sum(1 for row in negatives if predicate(row))
    tn = sum(1 for row in negatives if not predicate(row))
    fp_approved = sum(1 for row in approved_negatives if predicate(row))
    tn_approved = sum(1 for row in approved_negatives if not predicate(row))
    return {
        "reason": reason,
        "rule": rule_name,
        "positive_rows": len(positives),
        "negative_rows": len(negatives),
        "approved_negative_rows": len(approved_negatives),
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "fp_approved": fp_approved,
        "tn_approved": tn_approved,
        "recall": round(tp / (tp + fn), 3) if tp + fn else "",
        "precision": round(tp / (tp + fp), 3) if tp + fp else "",
        "approved_false_flag_rate": round(fp_approved / (fp_approved + tn_approved), 3) if fp_approved + tn_approved else "",
    }


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_report(rows: List[Dict[str, object]], metrics: List[Dict[str, object]], model_name: str) -> None:
    decisions = Counter(row.get("final_human_decision_norm") or "<blank>" for row in rows)
    reason_counts = {reason: sum(1 for row in rows if row.get(f"truth_{reason}") is True) for reason in REASONS}
    segmented = sum(1 for row in rows if (to_float(row.get("seg_person_count")) or 0) > 0)
    lines = [
        "# YOLO Segmentation Crop / Angle Experiment",
        "",
        f"- model: `{model_name}`",
        f"- labeled rows: `{len(rows)}`",
        f"- decision counts: `{dict(decisions)}`",
        f"- rows with person segmentation: `{segmented}`",
        "",
        "## Reason Coverage",
        "",
        "| reason | positive rows | enough for directional experiment |",
        "| --- | ---: | --- |",
    ]
    for reason, count in sorted(reason_counts.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"| `{reason}` | {count} | {'YES' if count >= 20 else 'NO'} |")

    lines.extend(["", "## Best Rules By Reason", ""])
    for reason in REASONS:
        reason_metrics = [row for row in metrics if row["reason"] == reason and row["recall"] != ""]
        best = sorted(
            reason_metrics,
            key=lambda row: (
                -float(row["recall"]),
                float(row["approved_false_flag_rate"] if row["approved_false_flag_rate"] != "" else 1),
                -float(row["precision"] if row["precision"] != "" else 0),
            ),
        )[:6]
        lines.extend(
            [
                f"### {reason}",
                "",
                "| rule | recall | precision | approved false-flag rate |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for row in best:
            lines.append(f"| `{row['rule']}` | {row['recall']} | {row['precision']} | {row['approved_false_flag_rate']} |")
        lines.append("")

    lines.extend(
        [
            "## Recommendation",
            "",
            "YOLO segmentation mask geometry should be treated as an additional review-priority signal, not a standalone rejection rule, unless a threshold shows both useful recall and a low approved false-flag rate. Mask edge contact is especially relevant for crop/cut-off detection; top-down angle likely needs pose/keypoint orientation features rather than segmentation alone.",
            "",
        ]
    )
    (OUT_DIR / "yolo_segmentation_crop_reason_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    global OUT_DIR
    global CACHE_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth-csv", default=str(GROUND_TRUTH_CSV))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--model", default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--timeout", type=float, default=4.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()

    ground_truth_csv = Path(args.ground_truth_csv)
    OUT_DIR = Path(args.out_dir)
    CACHE_DIR = OUT_DIR / "image_cache"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/Ultralytics")
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-codex")

    import numpy as np
    from ultralytics import YOLO

    model = YOLO(args.model)
    rows: List[Dict[str, object]] = []
    source_rows = [
        row
        for row in read_rows(ground_truth_csv)
        if row.get("original_url_display", "").strip()
        and normalize_decision(row.get("final_human_decision", "")) in {"APPROVED", "REJECTED"}
    ]
    for index, row in enumerate(source_rows, start=1):
        combined: Dict[str, object] = dict(row)
        combined["final_human_decision_norm"] = normalize_decision(row.get("final_human_decision", ""))
        for reason in REASONS:
            combined[f"truth_{reason}"] = truth_has_reason(row, reason)
        image, fetch = load_or_fetch_image(row.get("original_url_display", ""), args.timeout, args.retries)
        combined.update({key: value for key, value in fetch.items() if key != "attempts"})
        if image is None:
            combined.update({"seg_person_count": 0})
        else:
            result = model.predict(image, imgsz=args.imgsz, verbose=False, device="cpu")[0]
            combined.update(best_person_mask_features(result, np))
        rows.append(combined)
        if index % 25 == 0:
            print(f"processed {index}/{len(source_rows)}", flush=True)

    metrics = [evaluate_reason(rows, reason, rule_name, predicate) for reason in REASONS for rule_name, predicate in rules()]
    row_fieldnames = sorted({key for row in rows for key in row})
    with (OUT_DIR / "yolo_segmentation_crop_reason_rows.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=row_fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    write_csv(OUT_DIR / "yolo_segmentation_crop_reason_metrics.csv", metrics)
    write_report(rows, metrics, args.model)
    print(f"Wrote {OUT_DIR}")


if __name__ == "__main__":
    main()
