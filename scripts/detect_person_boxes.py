#!/usr/bin/env python3
"""Detect the main person's bounding box (and pose keypoints) per image.

Reads an ndjson of {id, url, review_row_key, clothing_type_id} rows, downloads
each image, runs YOLO person detection + pose, and writes an ndjson of detection
results. This is the bbox feed for the auto-crop solver
(scripts/lib/detection-crop.mjs) — the CV-gate pipeline computes these boxes but
discards the coordinates.

Downloads run concurrently and inference runs in batches so the full ~45k set is
practical; --resume skips ids already in the output so a long run can restart.

  FWM_Data/_venv_cv/bin/python scripts/detect_person_boxes.py \
    --input /tmp/crop_worklist.ndjson --output /tmp/crop_bboxes_full.ndjson \
    --detect-model FWM_Data/_models/yolov8n.pt \
    --pose-model FWM_Data/_models/yolov8n-pose.pt --resume
"""

import argparse
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image

UA = "FWMDevAutoCropDetect/0.2 (+https://friendswithmeasurements.com)"
# COCO keypoint indices used to anchor head, torso, hips, knees and feet.
KEYPOINTS = {
    "nose": 0,
    "left_shoulder": 5,
    "right_shoulder": 6,
    "left_hip": 11,
    "right_hip": 12,
    "left_knee": 13,
    "right_knee": 14,
    "left_ankle": 15,
    "right_ankle": 16,
}


def fetch_image(url, timeout):
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def main_person_record(detect_result, pose_result):
    """Build the bbox + keypoints sub-record for one image's CV results."""
    rec = {}
    boxes = detect_result.boxes
    if boxes is None or len(boxes) == 0:
        rec["person_count"] = 0
        return rec
    xyxy = boxes.xyxy.tolist()
    confs = boxes.conf.tolist()

    def score(idx):
        x1, y1, x2, y2 = xyxy[idx]
        return confs[idx] * max(0.0, x2 - x1) * max(0.0, y2 - y1)

    best = max(range(len(xyxy)), key=score)
    x1, y1, x2, y2 = xyxy[best]
    rec["person_count"] = len(xyxy)
    rec["confidence"] = round(confs[best], 4)
    rec["bbox_xyxy"] = [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)]

    if pose_result is not None and pose_result.keypoints is not None and len(pose_result.keypoints) > 0:
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        kxy = pose_result.keypoints.xy.tolist()
        kconf = pose_result.keypoints.conf.tolist() if pose_result.keypoints.conf is not None else None

        def near(idx):
            pts = kxy[idx]
            xs = [p[0] for p in pts if p[0] > 0]
            ys = [p[1] for p in pts if p[1] > 0]
            if not xs:
                return 1e9
            pcx, pcy = sum(xs) / len(xs), sum(ys) / len(ys)
            return (pcx - cx) ** 2 + (pcy - cy) ** 2

        pi = min(range(len(kxy)), key=near)
        pts, pcf = kxy[pi], (kconf[pi] if kconf else [1.0] * len(kxy[pi]))

        def kp(idx):
            if idx < len(pts) and pcf[idx] > 0.3 and pts[idx][0] > 0:
                return [round(pts[idx][0], 1), round(pts[idx][1], 1), round(pcf[idx], 3)]
            return None

        rec["keypoints"] = {name: kp(idx) for name, idx in KEYPOINTS.items()}
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--detect-model", required=True)
    ap.add_argument("--pose-model", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-conf", type=float, default=0.35)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--workers", type=int, default=16, help="concurrent image downloads")
    ap.add_argument("--batch", type=int, default=16, help="images per inference batch")
    ap.add_argument("--resume", action="store_true", help="skip ids already in --output and append")
    args = ap.parse_args()

    from ultralytics import YOLO

    detect = YOLO(args.detect_model)
    pose = YOLO(args.pose_model) if args.pose_model else None

    rows = []
    with open(args.input) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if args.limit:
        rows = rows[: args.limit]

    done = set()
    mode = "w"
    if args.resume and os.path.exists(args.output):
        with open(args.output) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        done.add(json.loads(line).get("id"))
                    except json.JSONDecodeError:
                        pass
        mode = "a"
    rows = [r for r in rows if r.get("id") not in done]
    total = len(rows)
    print(f"{total} rows to process ({len(done)} already done){' [resume]' if args.resume else ''}", file=sys.stderr)

    def download(row):
        try:
            img = fetch_image(row["url"], args.timeout)
            return row, img, None
        except Exception as exc:  # noqa: BLE001 — record and continue
            return row, None, str(exc)[:300]

    written = 0
    out = open(args.output, mode)
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            batch = []  # list of (row, img)
            for row, img, err in pool.map(download, rows):
                rec = {
                    "id": row.get("id"),
                    "url": row.get("url"),
                    "review_row_key": row.get("review_row_key"),
                    "clothing_type_id": row.get("clothing_type_id"),
                }
                if img is None:
                    rec["error"] = err
                    out.write(json.dumps(rec) + "\n")
                    written += 1
                else:
                    batch.append((row, img, rec))
                if len(batch) >= args.batch:
                    written += flush_batch(batch, detect, pose, args, out)
                    batch = []
                    out.flush()
                    print(f"{written}/{total}", file=sys.stderr, flush=True)
            if batch:
                written += flush_batch(batch, detect, pose, args, out)
    finally:
        out.close()
    print(f"Wrote {written} detection rows to {args.output}")


def flush_batch(batch, detect, pose, args, out):
    images = [img for (_row, img, _rec) in batch]
    det_results = detect.predict(images, verbose=False, classes=[0], conf=args.min_conf)
    pose_results = (
        pose.predict(images, verbose=False, conf=args.min_conf) if pose is not None else [None] * len(images)
    )
    n = 0
    for (row, img, rec), dres, pres in zip(batch, det_results, pose_results):
        rec["img_width"], rec["img_height"] = img.size
        try:
            rec.update(main_person_record(dres, pres))
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"cv:{str(exc)[:280]}"
        out.write(json.dumps(rec) + "\n")
        n += 1
    return n


if __name__ == "__main__":
    main()
