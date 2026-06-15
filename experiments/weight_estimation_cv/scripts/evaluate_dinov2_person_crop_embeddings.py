#!/usr/bin/env python3
"""Evaluate DINOv2 embeddings on YOLO main-person crops."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parents[1] / "cache/huggingface"))
os.environ.setdefault("XDG_CACHE_HOME", str(Path(__file__).resolve().parents[1] / "cache"))
os.environ.setdefault("TORCH_HOME", str(Path(__file__).resolve().parents[1] / "cache/torch"))
os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(__file__).resolve().parents[1] / "cache/ultralytics"))
os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / "cache/matplotlib"))

import cv2
import numpy as np
import pandas as pd
import timm
import torch
from PIL import Image
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from timm.data import create_transform, resolve_model_data_config
from tqdm import tqdm
from ultralytics import YOLO


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPERIMENT_ROOT.parents[1]
PROJECT_ROOT = REPO_ROOT.parent
DEFAULT_INPUT = EXPERIMENT_ROOT / "data/eval_sample_with_quality_tags.csv"
DEFAULT_DETECT_MODEL = PROJECT_ROOT / "FWM_Data/models/yolov8n.pt"
DEFAULT_EMBEDDINGS = EXPERIMENT_ROOT / "data/features/dinov2_small_person_crop_embeddings.npz"
DEFAULT_ROWS = EXPERIMENT_ROOT / "data/dinov2_small_person_crop_embedding_rows.csv"
DEFAULT_ATTEMPTS = EXPERIMENT_ROOT / "data/dinov2_small_person_crop_attempt_rows.csv"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/dinov2_small_person_crop_metrics.json"


SUBSETS = {
    "person_crop_all": lambda df: pd.Series(True, index=df.index),
    "prior_person_visible": lambda df: df["person_visible"].astype(bool),
    "prior_full_body_likely": lambda df: df["full_body_likely"].astype(bool),
    "prior_torso_or_partial_body": lambda df: df["torso_or_partial_body"].astype(bool),
}

GEOMETRY_FEATURES = [
    "image_width_downloaded",
    "image_height_downloaded",
    "face_count",
    "largest_face_area_pct",
    "person_count",
    "main_person_conf",
    "main_person_area_pct",
    "main_person_width_pct",
    "main_person_height_pct",
    "main_person_aspect_ratio",
    "crop_x1_pct",
    "crop_y1_pct",
    "crop_x2_pct",
    "crop_y2_pct",
    "crop_area_pct",
    "crop_width_pct",
    "crop_height_pct",
    "crop_aspect_ratio",
    "crop_person_conf",
    "crop_person_count",
]

CATEGORICAL_FEATURES = ["size_display", "clothing_type_id", "source_site_display", "image_quality_bucket"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--detect-model", type=Path, default=DEFAULT_DETECT_MODEL)
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--rows", type=Path, default=DEFAULT_ROWS)
    parser.add_argument("--attempts", type=Path, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--yolo-batch-size", type=int, default=8)
    parser.add_argument("--chunk-size", type=int, default=64)
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def load_embedding_model(device: str) -> tuple[torch.nn.Module, object]:
    model = timm.create_model("vit_small_patch14_dinov2", pretrained=True, num_classes=0)
    model.to(device)
    model.eval()
    transform = create_transform(**resolve_model_data_config(model), is_training=False)
    return model, transform


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
        area = width * height
        people.append((area, float(conf), x1, y1, x2, y2))
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


def crop_from_box(result, box: dict[str, float], padding: float) -> Image.Image | None:
    image = result.orig_img
    if image is None:
        return None
    image_h, image_w = image.shape[:2]
    pad_x = int(box["width"] * padding)
    pad_y = int(box["height"] * padding)
    x1 = max(0, int(box["x1"]) - pad_x)
    y1 = max(0, int(box["y1"]) - pad_y)
    x2 = min(image_w, int(box["x2"]) + pad_x)
    y2 = min(image_h, int(box["y2"]) + pad_y)
    if x2 <= x1 or y2 <= y1:
        return None
    crop = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
    return Image.fromarray(crop)


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


def extract_embeddings(args: argparse.Namespace) -> tuple[pd.DataFrame, np.ndarray, dict[str, int], int]:
    if args.embeddings.exists() and args.rows.exists() and not args.limit:
        rows = pd.read_csv(args.rows)
        attempts = pd.read_csv(args.attempts) if args.attempts.exists() else rows
        return (
            rows,
            np.load(args.embeddings)["embeddings"],
            attempts["crop_status"].value_counts(dropna=False).to_dict(),
            int(len(attempts)),
        )

    df = pd.read_csv(args.input)
    work = df[df["is_downloaded_image"].astype(bool)].copy()
    work = work[work["local_image_path"].map(lambda value: Path(str(value)).exists())].copy()
    if args.limit:
        work = work.head(args.limit).copy()

    detector = YOLO(str(args.detect_model))
    embedder, transform = load_embedding_model(args.device)
    paths = work["local_image_path"].astype(str).tolist()
    rows_by_path = {str(row.local_image_path): row for row in work.itertuples(index=False)}

    rows = []
    tensors: list[torch.Tensor] = []
    embeddings: list[np.ndarray] = []

    def flush_batch() -> None:
        if not tensors:
            return
        batch = torch.stack(tensors).to(args.device)
        with torch.no_grad():
            out = embedder(batch).detach().cpu().numpy().astype(np.float32)
        embeddings.extend([row for row in out])
        tensors.clear()

    processed = 0
    for start in range(0, len(paths), args.chunk_size):
        chunk = paths[start : start + args.chunk_size]
        for result_index, result in enumerate(
            detector(chunk, batch=args.yolo_batch_size, device=args.device, imgsz=args.imgsz, verbose=False, stream=True)
        ):
            path = chunk[result_index]
            row = rows_by_path[path]._asdict()
            box = choose_person_box(result)
            if box is None:
                rows.append({**row, "crop_status": "no_person", "embedding_index": -1})
                continue
            crop = crop_from_box(result, box, padding=0.04)
            if crop is None:
                rows.append({**row, **crop_metrics(box), "crop_status": "crop_failed", "embedding_index": -1})
                continue
            rows.append({**row, **crop_metrics(box), "crop_status": "ok", "embedding_index": len(embeddings) + len(tensors)})
            tensors.append(transform(crop.convert("RGB")))
            if len(tensors) >= args.batch_size:
                flush_batch()
        processed += len(chunk)
        print(f"processed person crops {processed}/{len(paths)}", flush=True)
    flush_batch()

    row_df = pd.DataFrame(rows)
    ok_rows = row_df[row_df["embedding_index"] >= 0].copy()
    matrix = np.vstack(embeddings) if embeddings else np.empty((0, 384), dtype=np.float32)
    if not args.limit:
        args.embeddings.parent.mkdir(parents=True, exist_ok=True)
        args.rows.parent.mkdir(parents=True, exist_ok=True)
        args.attempts.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(args.embeddings, embeddings=matrix)
        ok_rows.to_csv(args.rows, index=False)
        row_df.to_csv(args.attempts, index=False)
    return ok_rows, matrix, row_df["crop_status"].value_counts(dropna=False).to_dict(), int(len(row_df))


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


def build_frame(rows: pd.DataFrame, embeddings: np.ndarray) -> pd.DataFrame:
    emb_cols = [f"emb_{idx:03d}" for idx in range(embeddings.shape[1])]
    emb_df = pd.DataFrame(embeddings, columns=emb_cols)
    return pd.concat([rows.reset_index(drop=True), emb_df], axis=1)


def preprocessor(numeric: list[str], categorical: list[str]) -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ("numeric", Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]), numeric),
            (
                "categorical",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="constant", fill_value="")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=4)),
                    ]
                ),
                categorical,
            ),
        ]
    )


def evaluate_one(name: str, estimator, train: pd.DataFrame, test: pd.DataFrame, features: list[str], target: str) -> dict[str, object]:
    estimator.fit(train[features], train[target])
    pred_target = estimator.predict(test[features])
    pred_weight = weight_from_bmi(pred_target, test["height_in"].to_numpy(dtype=float)) if target == "bmi" else pred_target
    return {
        "model": name,
        "target": target,
        "features_count": len(features),
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        **metrics(test["weight_lbs"].to_numpy(dtype=float), pred_weight),
    }


def evaluate_subset(name: str, frame: pd.DataFrame) -> dict[str, object]:
    subset = frame[SUBSETS[name](frame)].copy()
    train = subset[subset["split"] == "train"].copy()
    test = subset[subset["split"] == "test"].copy()
    emb_cols = [column for column in frame.columns if column.startswith("emb_")]

    numeric_cols = sorted(set(["height_in", "weight_lbs", "bmi"] + GEOMETRY_FEATURES + emb_cols))
    for column in numeric_cols:
        if column in train:
            train[column] = pd.to_numeric(train[column], errors="coerce")
            test[column] = pd.to_numeric(test[column], errors="coerce")
    for column in CATEGORICAL_FEATURES:
        train[column] = train[column].fillna("").astype(str)
        test[column] = test[column].fillna("").astype(str)

    if len(train) < 20 or len(test) < 10:
        return {
            "subset": name,
            "rows": int(len(subset)),
            "rows_train": int(len(train)),
            "rows_test": int(len(test)),
            "skipped": "too_few_rows",
        }

    baseline_numeric = ["height_in"]
    geometry_numeric = [column for column in GEOMETRY_FEATURES if column in frame.columns] + ["height_in"]
    embedding_numeric = emb_cols + ["height_in"]
    embedding_geometry_numeric = emb_cols + geometry_numeric

    specs = [
        ("baseline_ridge_height_metadata_predict_bmi", baseline_numeric, CATEGORICAL_FEATURES, Ridge(alpha=10.0), "bmi"),
        ("baseline_ridge_height_geometry_metadata_predict_bmi", geometry_numeric, CATEGORICAL_FEATURES, Ridge(alpha=10.0), "bmi"),
        ("ridge_crop_dinov2_embedding_height_predict_bmi", embedding_numeric, [], Ridge(alpha=50.0), "bmi"),
        (
            "ridge_crop_dinov2_embedding_height_metadata_predict_bmi",
            embedding_numeric,
            CATEGORICAL_FEATURES,
            Ridge(alpha=50.0),
            "bmi",
        ),
        (
            "ridge_crop_dinov2_embedding_geometry_metadata_predict_bmi",
            embedding_geometry_numeric,
            CATEGORICAL_FEATURES,
            Ridge(alpha=50.0),
            "bmi",
        ),
        (
            "random_forest_crop_dinov2_embedding_height_predict_bmi",
            embedding_numeric,
            [],
            RandomForestRegressor(n_estimators=300, min_samples_leaf=8, random_state=20260609, n_jobs=-1),
            "bmi",
        ),
        (
            "random_forest_crop_dinov2_embedding_geometry_predict_bmi",
            embedding_geometry_numeric,
            [],
            RandomForestRegressor(n_estimators=300, min_samples_leaf=8, random_state=20260609, n_jobs=-1),
            "bmi",
        ),
        (
            "hist_gradient_crop_dinov2_embedding_height_predict_bmi",
            embedding_numeric,
            [],
            HistGradientBoostingRegressor(max_iter=200, min_samples_leaf=12, random_state=20260609),
            "bmi",
        ),
        (
            "hist_gradient_crop_dinov2_embedding_geometry_predict_bmi",
            embedding_geometry_numeric,
            [],
            HistGradientBoostingRegressor(max_iter=200, min_samples_leaf=12, random_state=20260609),
            "bmi",
        ),
    ]
    results = []
    for model_name, numeric, categorical, estimator, target in specs:
        features = numeric + categorical
        model = Pipeline([("prep", preprocessor(numeric, categorical)), ("model", estimator)])
        results.append(evaluate_one(model_name, model, train, test, features, target))
    return {
        "subset": name,
        "rows": int(len(subset)),
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "results": sorted(results, key=lambda item: item["mae_lbs"]),
    }


def main() -> None:
    args = parse_args()
    rows, embeddings, status_counts, attempted_rows = extract_embeddings(args)
    frame = build_frame(rows, embeddings)
    report = {
        "model": "timm/vit_small_patch14_dinov2 YOLO person-crop embeddings + FWM regressors",
        "input": str(args.input),
        "detect_model": str(args.detect_model),
        "embeddings": str(args.embeddings),
        "rows_file": str(args.rows),
        "attempts_file": str(args.attempts),
        "attempted_rows": attempted_rows,
        "rows": int(len(frame)),
        "status_counts": status_counts,
        "subsets": [evaluate_subset(name, frame) for name in SUBSETS],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
