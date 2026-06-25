#!/usr/bin/env python3
"""Detect a face + smile per image, for the prettiness scorer's face_visible /
smile signals (see data-pipelines/docs/face_smile_detection_pass_plan.md).

Reads an ndjson of {id, url, review_row_key, ...} rows (e.g. the person-detection
output crop_bboxes_full.ndjson), downloads each image, finds the main face, and
scores whether the subject is smiling. Writes an ndjson keyed by id; the prettiness
scorer joins it as an overlay so face_visible_score / smile_score light up.

Backends, swappable so we can de-risk the plumbing with zero downloads and upgrade
the models later:
  - face:  haar  (cv2 bundled haarcascade_frontalface_default.xml, no download)
           yunet (cv2.FaceDetectorYN + face_detection_yunet_2023mar.onnx) — the
                  validated detector (F1 0.914 in the legacy ground-truth report)
  - smile: haar  (cv2 bundled haarcascade_smile.xml, no download — noisy, smoke
                  test only)
           onnx  (an FER/smile classifier loaded via cv2.dnn.readNetFromONNX, run
                  on the face crop; "happy"/"smiling" probability -> smile_score)

  FWM_Data/_venv_cv/bin/python scripts/detect_faces_smiles.py \
    --input ../FWM_Data/_cache/crop_bboxes_full.ndjson \
    --output ../FWM_Data/_cache/face_smile_full.ndjson --resume
"""

import argparse
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import requests

UA = "FWMDevFaceSmileDetect/0.1 (+https://friendswithmeasurements.com)"


def squash(weight, center=1.0, scale=1.0):
    """Map a Haar cascade levelWeight (~ -3..5) to a 0..1 pseudo-confidence."""
    try:
        return round(1.0 / (1.0 + math.exp(-(float(weight) - center) / scale)), 4)
    except (OverflowError, ValueError):
        return 0.0


def fetch_bgr(url, timeout):
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    resp.raise_for_status()
    arr = np.frombuffer(resp.content, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("decode failed")
    return img


class HaarFace:
    def __init__(self):
        self.cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def detect(self, gray):
        """Return list of (x, y, w, h, conf) faces, best-first by area."""
        faces, _rej, weights = self.cascade.detectMultiScale3(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(28, 28), outputRejectLevels=True
        )
        out = []
        for (x, y, w, h), wt in zip(faces, weights if len(weights) else [1.0] * len(faces)):
            out.append((int(x), int(y), int(w), int(h), squash(wt[0] if hasattr(wt, "__len__") else wt)))
        out.sort(key=lambda f: f[2] * f[3], reverse=True)
        return out


class YuNetFace:
    def __init__(self, model_path):
        # Input size is set per-image in detect().
        self.det = cv2.FaceDetectorYN.create(model_path, "", (320, 320), score_threshold=0.6)

    def detect(self, gray, bgr=None):
        img = bgr if bgr is not None else cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        h, w = img.shape[:2]
        self.det.setInputSize((w, h))
        _, faces = self.det.detect(img)
        out = []
        if faces is not None:
            for f in faces:
                x, y, fw, fh = (int(v) for v in f[:4])
                out.append((x, y, fw, fh, round(float(f[-1]), 4)))
        out.sort(key=lambda f: f[2] * f[3], reverse=True)
        return out


class HaarSmile:
    def __init__(self):
        self.cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_smile.xml")

    def score(self, gray, face):
        """Smile on the lower half of the face ROI. Returns (smile_bool, score)."""
        x, y, w, h, _ = face
        roi = gray[y + h // 2 : y + h, x : x + w]
        if roi.size == 0:
            return False, 0.0
        # Faces are tiny in full-body shots, so the mouth ROI can be ~15px — too
        # small for the smile cascade. Upscale to a workable size first.
        rh, rw = roi.shape[:2]
        if rw < 120:
            scale = 120.0 / max(1, rw)
            roi = cv2.resize(roi, (int(rw * scale), int(rh * scale)), interpolation=cv2.INTER_LINEAR)
        smiles, _rej, weights = self.cascade.detectMultiScale3(
            roi, scaleFactor=1.7, minNeighbors=22, minSize=(30, 18), outputRejectLevels=True
        )
        if len(smiles) == 0:
            return False, 0.0
        best = max((w[0] if hasattr(w, "__len__") else w) for w in weights) if len(weights) else 1.0
        s = squash(best, center=2.0, scale=1.2)
        return s >= 0.5, s


class OnnxSmile:
    """FER+ emotion classifier (cv2.dnn). smile_score = P(happiness) over the whole
    face crop. FER+ emotion order: neutral, happiness, surprise, sadness, anger,
    disgust, fear, contempt -> happiness is index 1."""

    HAPPY_IDX = 1

    def __init__(self, model_path):
        self.net = cv2.dnn.readNetFromONNX(model_path)

    def score(self, gray, face):
        x, y, w, h, _ = face
        roi = gray[y : y + h, x : x + w]
        if roi.size == 0:
            return False, 0.0
        face64 = cv2.resize(roi, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
        self.net.setInput(face64.reshape(1, 1, 64, 64))
        logits = self.net.forward().flatten()
        ex = np.exp(logits - logits.max())
        probs = ex / ex.sum()
        happy = float(probs[self.HAPPY_IDX])
        return bool(int(np.argmax(probs)) == self.HAPPY_IDX), round(happy, 4)


def in_person_box(face, person_box, img_w, img_h):
    """True if the face center sits inside the person bbox (xyxy in source px)."""
    if not person_box:
        return True
    x, y, w, h, _ = face
    cx, cy = x + w / 2, y + h / 2
    x1, y1, x2, y2 = person_box
    return x1 <= cx <= x2 and y1 <= cy <= y2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--face-backend", choices=["haar", "yunet"], default="haar")
    ap.add_argument("--face-model", default=None, help="YuNet onnx (required for --face-backend yunet)")
    ap.add_argument("--smile-backend", choices=["haar", "onnx"], default="haar")
    ap.add_argument("--smile-model", default=None, help="FER/smile onnx (required for --smile-backend onnx)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--person-only", action="store_true", help="only keep faces inside the person bbox")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    if args.face_backend == "yunet" and not args.face_model:
        ap.error("--face-backend yunet requires --face-model")
    if args.smile_backend == "onnx" and not args.smile_model:
        ap.error("--smile-backend onnx requires --smile-model")
    face_det = YuNetFace(args.face_model) if args.face_backend == "yunet" else HaarFace()
    smile_det = OnnxSmile(args.smile_model) if args.smile_backend == "onnx" else HaarSmile()

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
    print(f"{total} rows ({len(done)} already done) face={args.face_backend} smile={args.smile_backend}", file=sys.stderr)

    # Downloads run concurrently; detection runs SERIALLY in the main thread —
    # the OpenCV Haar cascade objects are not thread-safe and crash under a pool.
    def download(row):
        rec = {"id": row.get("id"), "review_row_key": row.get("review_row_key"), "url": row.get("url")}
        try:
            return row, rec, fetch_bgr(row["url"], args.timeout), None
        except Exception as exc:  # noqa: BLE001
            return row, rec, None, str(exc)[:200]

    def detect(row, rec, bgr):
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        faces = face_det.detect(gray, bgr) if isinstance(face_det, YuNetFace) else face_det.detect(gray)
        if args.person_only:
            faces = [f for f in faces if in_person_box(f, row.get("bbox_xyxy"), w, h)]
        rec["img_w"], rec["img_h"] = w, h
        if not faces:
            rec.update(has_face=False, face_count=0, smile=None, smile_score=None, backend=args.face_backend)
            return rec
        best = faces[0]
        x, y, fw, fh, conf = best
        smile_bool, smile_score = smile_det.score(gray, best)
        rec.update(
            has_face=True,
            face_count=len(faces),
            face_conf=conf,
            face_box_xyxy=[x, y, x + fw, y + fh],
            face_frac=round((fw * fh) / float(w * h), 4),
            smile=smile_bool,
            smile_score=smile_score,
            backend=f"{args.face_backend}+{args.smile_backend}",
        )
        return rec

    written = 0
    out = open(args.output, mode)
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for row, rec, bgr, err in pool.map(download, rows):
                if bgr is None:
                    rec["error"] = err
                else:
                    try:
                        rec = detect(row, rec, bgr)
                    except Exception as exc:  # noqa: BLE001 — record and continue
                        rec["error"] = f"detect: {str(exc)[:200]}"
                out.write(json.dumps(rec) + "\n")
                written += 1
                if written % 50 == 0:
                    out.flush()
                    print(f"{written}/{total}", file=sys.stderr, flush=True)
    finally:
        out.close()
    print(f"done: wrote {written}", file=sys.stderr)


if __name__ == "__main__":
    main()
