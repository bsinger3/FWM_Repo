#!/usr/bin/env python3
"""Evaluate the free face-to-bmi-vit checkpoint on FWM face-visible rows."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

os.environ.setdefault(
    "TORCH_HOME",
    str(Path(__file__).resolve().parents[1] / "cache/torch"),
)

import cv2
import numpy as np
import pandas as pd
import torch
from PIL import Image
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from torchvision import transforms as T
from torchvision.models import vit_h_14
from torchvision.transforms import InterpolationMode, ToTensor
from tqdm import tqdm


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = EXPERIMENT_ROOT / "data/eval_sample_with_quality_tags.csv"
DEFAULT_PREDICTIONS = EXPERIMENT_ROOT / "data/face_to_bmi_vit_predictions.csv"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/face_to_bmi_vit_metrics.json"
DEFAULT_BASELINES = EXPERIMENT_ROOT / "reports/subset_baseline_metrics.json"
DEFAULT_WEIGHTS = EXPERIMENT_ROOT / "models/face_to_bmi_vit/weights/aug_epoch_7.pt"
WEIGHTS_URL = "https://face-to-bmi-weights.s3.us-east.cloud-object-storage.appdomain.cloud/aug_epoch_7.pt"


class BMIHead(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.linear1 = torch.nn.Linear(1280, 640)
        self.linear2 = torch.nn.Linear(640, 320)
        self.linear3 = torch.nn.Linear(320, 160)
        self.linear4 = torch.nn.Linear(160, 80)
        self.linear5 = torch.nn.Linear(80, 1)
        self.gelu = torch.nn.GELU()
        self.dropout = torch.nn.Dropout(0.5)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.dropout(self.gelu(self.linear1(x)))
        x = self.gelu(self.linear2(x))
        x = self.gelu(self.linear3(x))
        x = self.gelu(self.linear4(x))
        return self.gelu(self.linear5(x))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--baselines", type=Path, default=DEFAULT_BASELINES)
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--download-weights", action="store_true")
    parser.add_argument("--split", choices=["all", "train", "test"], default="all")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--device", default="cpu")
    return parser.parse_args()


def download_weights(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 2_000_000_000:
        return
    tmp = path.with_suffix(path.suffix + ".partial")
    resume_at = tmp.stat().st_size if tmp.exists() else 0
    request = urllib.request.Request(WEIGHTS_URL)
    if resume_at:
        request.add_header("Range", f"bytes={resume_at}-")
    with urllib.request.urlopen(request) as response, tmp.open("ab") as out:
        total = int(response.headers.get("Content-Length", "0")) + resume_at
        with tqdm(total=total, initial=resume_at, unit="B", unit_scale=True, desc=path.name) as bar:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                bar.update(len(chunk))
    tmp.replace(path)


def build_model(device: str, weights_path: Path) -> torch.nn.Module:
    model = vit_h_14(weights=None, image_size=518)
    model.heads = BMIHead()
    state = torch.load(weights_path, map_location=device)
    model.load_state_dict(state)
    model.to(device)
    model.eval()
    return model


def face_cascade() -> cv2.CascadeClassifier:
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(str(cascade_path))
    if cascade.empty():
        raise RuntimeError(f"Could not load OpenCV face cascade at {cascade_path}")
    return cascade


def crop_largest_face(path: Path, cascade: cv2.CascadeClassifier, padding: float = 0.55) -> tuple[Image.Image | None, str]:
    image = cv2.imread(str(path))
    if image is None:
        return None, "read_failed"
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5, minSize=(24, 24))
    if len(faces) == 0:
        return None, "no_face_on_second_pass"
    x, y, w, h = sorted(faces, key=lambda box: box[2] * box[3], reverse=True)[0]
    pad_x = int(w * padding)
    pad_y = int(h * padding)
    image_h, image_w = image.shape[:2]
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(image_w, x + w + pad_x)
    y2 = min(image_h, y + h + pad_y)
    crop = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
    return Image.fromarray(crop), "ok"


def weight_from_bmi(bmi: np.ndarray, height_in: np.ndarray) -> np.ndarray:
    return bmi * (height_in ** 2) / 703.0


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    abs_error = np.abs(y_true - y_pred)
    return {
        "mae_lbs": round(float(mean_absolute_error(y_true, y_pred)), 3),
        "median_abs_error_lbs": round(float(np.median(abs_error)), 3),
        "rmse_lbs": round(float(mean_squared_error(y_true, y_pred) ** 0.5), 3),
        "r2": round(float(r2_score(y_true, y_pred)), 4) if len(y_true) >= 2 else float("nan"),
        "within_10_lbs": round(float(np.mean(abs_error <= 10.0)), 4),
        "within_20_lbs": round(float(np.mean(abs_error <= 20.0)), 4),
        "within_30_lbs": round(float(np.mean(abs_error <= 30.0)), 4),
    }


def best_baseline(path: Path, subset: str) -> dict[str, object] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    for item in payload.get("subsets", []):
        if item.get("subset") == subset and item.get("results"):
            return sorted(item["results"], key=lambda row: row["mae_lbs"])[0]
    return None


def main() -> None:
    args = parse_args()
    if args.download_weights:
        download_weights(args.weights)
    if not args.weights.exists():
        raise FileNotFoundError(f"Missing weights: {args.weights}. Re-run with --download-weights.")

    device = args.device
    transform = T.Compose(
        [
            T.Resize([518], interpolation=InterpolationMode.BICUBIC),
            T.CenterCrop([518]),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )
    model = build_model(device, args.weights)
    cascade = face_cascade()

    df = pd.read_csv(args.input)
    mask = df["is_downloaded_image"].astype(bool) & df["face_visible"].astype(bool)
    if args.split != "all":
        mask &= df["split"].eq(args.split)
    work = df[mask].copy()
    if args.limit:
        work = work.head(args.limit).copy()

    rows = []
    for _, row in tqdm(work.iterrows(), total=len(work), desc="face-to-bmi-vit"):
        path = Path(str(row["local_image_path"]))
        crop, status = crop_largest_face(path, cascade)
        pred_bmi = np.nan
        pred_weight_lbs = np.nan
        if crop is not None:
            image = ToTensor()(crop.convert("RGB"))
            image = transform(image).unsqueeze(0).to(device)
            with torch.no_grad():
                pred_bmi = float(model(image).item())
            pred_weight_lbs = float(weight_from_bmi(np.array([pred_bmi]), np.array([float(row["height_in"])]))[0])
        rows.append(
            {
                "row_id": row["row_id"],
                "split": row["split"],
                "height_in": row["height_in"],
                "weight_lbs": row["weight_lbs"],
                "bmi": row["bmi"],
                "local_image_path": row["local_image_path"],
                "face_to_bmi_vit_status": status,
                "pred_bmi": pred_bmi,
                "pred_weight_lbs": pred_weight_lbs,
            }
        )

    pred_df = pd.DataFrame(rows)
    args.predictions.parent.mkdir(parents=True, exist_ok=True)
    pred_df.to_csv(args.predictions, index=False)

    report: dict[str, object] = {
        "model": "liujie-zheng/face-to-bmi-vit",
        "weights_url": WEIGHTS_URL,
        "weights_path": str(args.weights),
        "input": str(args.input),
        "predictions": str(args.predictions),
        "attempted_rows": int(len(pred_df)),
        "status_counts": pred_df["face_to_bmi_vit_status"].value_counts(dropna=False).to_dict(),
        "baseline_face_visible": best_baseline(args.baselines, "face_visible"),
        "baseline_large_face_visible": best_baseline(args.baselines, "large_face_visible"),
    }
    for subset_name, subset_mask in {
        "face_visible_all_predicted": pred_df["pred_weight_lbs"].notna(),
        "face_visible_test_predicted": pred_df["pred_weight_lbs"].notna() & (pred_df["split"] == "test"),
    }.items():
        subset = pred_df[subset_mask].copy()
        if len(subset):
            report[subset_name] = {
                "rows": int(len(subset)),
                **metrics(
                    subset["weight_lbs"].to_numpy(dtype=float),
                    subset["pred_weight_lbs"].to_numpy(dtype=float),
                ),
            }
        else:
            report[subset_name] = {"rows": 0, "skipped": "no_predictions"}

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
