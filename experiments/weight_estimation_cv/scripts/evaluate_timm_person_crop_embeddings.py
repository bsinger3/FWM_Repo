#!/usr/bin/env python3
"""Evaluate a timm image encoder on saved YOLO person crops."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parents[1] / "cache/huggingface"))
os.environ.setdefault("XDG_CACHE_HOME", str(Path(__file__).resolve().parents[1] / "cache"))
os.environ.setdefault("TORCH_HOME", str(Path(__file__).resolve().parents[1] / "cache/torch"))
os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / "cache/matplotlib"))

import numpy as np
import pandas as pd
import timm
import torch
from PIL import Image, ImageFile
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from timm.data import create_transform, resolve_model_data_config
from tqdm import tqdm

ImageFile.LOAD_TRUNCATED_IMAGES = True


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATTEMPTS = EXPERIMENT_ROOT / "data/dinov2_small_person_crop_attempt_rows.csv"

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


def slugify(value: str) -> str:
    value = value.replace(".", "_").replace("/", "_").replace("-", "_")
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", default="vit_base_patch16_clip_224.openai")
    parser.add_argument("--attempts", type=Path, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--embeddings", type=Path)
    parser.add_argument("--rows", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def output_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, str]:
    slug = slugify(args.model_name)
    embeddings = args.embeddings or EXPERIMENT_ROOT / f"data/features/{slug}_person_crop_embeddings.npz"
    rows = args.rows or EXPERIMENT_ROOT / f"data/{slug}_person_crop_embedding_rows.csv"
    report = args.report or EXPERIMENT_ROOT / f"reports/{slug}_person_crop_metrics.json"
    return embeddings, rows, report, slug


def load_model(model_name: str, device: str) -> tuple[torch.nn.Module, object, int]:
    model = timm.create_model(model_name, pretrained=True, num_classes=0)
    model.to(device)
    model.eval()
    transform = create_transform(**resolve_model_data_config(model), is_training=False)
    return model, transform, int(getattr(model, "num_features", 0) or 0)


def crop_saved_box(row: pd.Series) -> Image.Image:
    image = Image.open(str(row["local_image_path"])).convert("RGB")
    width, height = image.size
    x1 = max(0, min(width, int(float(row["crop_x1_pct"]) * width)))
    y1 = max(0, min(height, int(float(row["crop_y1_pct"]) * height)))
    x2 = max(0, min(width, int(float(row["crop_x2_pct"]) * width)))
    y2 = max(0, min(height, int(float(row["crop_y2_pct"]) * height)))
    if x2 <= x1 or y2 <= y1:
        raise ValueError("empty_crop")
    return image.crop((x1, y1, x2, y2))


def extract_embeddings(args: argparse.Namespace) -> tuple[pd.DataFrame, np.ndarray, Path, Path, Path, str]:
    embeddings_path, rows_path, report_path, slug = output_paths(args)
    if embeddings_path.exists() and rows_path.exists() and not args.limit:
        return pd.read_csv(rows_path), np.load(embeddings_path)["embeddings"], embeddings_path, rows_path, report_path, slug

    attempts = pd.read_csv(args.attempts)
    work = attempts[attempts["crop_status"].eq("ok")].copy()
    if args.limit:
        work = work.head(args.limit).copy()

    model, transform, feature_dim = load_model(args.model_name, args.device)
    rows = []
    tensors: list[torch.Tensor] = []
    embeddings: list[np.ndarray] = []

    def flush_batch() -> None:
        if not tensors:
            return
        batch = torch.stack(tensors).to(args.device)
        with torch.no_grad():
            out = model(batch).detach().cpu().numpy().astype(np.float32)
        embeddings.extend([row for row in out])
        tensors.clear()

    for _, row in tqdm(work.iterrows(), total=len(work), desc=f"{slug} person crops"):
        status = "ok"
        try:
            tensor = transform(crop_saved_box(row))
        except Exception as exc:  # noqa: BLE001 - record bad crops and continue.
            status = f"crop_failed:{type(exc).__name__}"
            rows.append({**row.to_dict(), "embedding_status": status, "embedding_index": -1})
            continue
        rows.append({**row.to_dict(), "embedding_status": status, "embedding_index": len(embeddings) + len(tensors)})
        tensors.append(tensor)
        if len(tensors) >= args.batch_size:
            flush_batch()
    flush_batch()

    row_df = pd.DataFrame(rows)
    ok_rows = row_df[row_df["embedding_index"] >= 0].copy()
    matrix = np.vstack(embeddings) if embeddings else np.empty((0, feature_dim), dtype=np.float32)
    if not args.limit:
        embeddings_path.parent.mkdir(parents=True, exist_ok=True)
        rows_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(embeddings_path, embeddings=matrix)
        ok_rows.to_csv(rows_path, index=False)
    return ok_rows, matrix, embeddings_path, rows_path, report_path, slug


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


def build_frame(rows: pd.DataFrame, embeddings: np.ndarray) -> pd.DataFrame:
    emb_cols = [f"emb_{idx:04d}" for idx in range(embeddings.shape[1])]
    emb_df = pd.DataFrame(embeddings, columns=emb_cols)
    return pd.concat([rows.reset_index(drop=True), emb_df], axis=1)


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


def evaluate_subset(name: str, frame: pd.DataFrame, slug: str) -> dict[str, object]:
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
        return {"subset": name, "rows": int(len(subset)), "rows_train": int(len(train)), "rows_test": int(len(test)), "skipped": "too_few_rows"}

    baseline_numeric = ["height_in"]
    geometry_numeric = [column for column in GEOMETRY_FEATURES if column in frame.columns] + ["height_in"]
    embedding_numeric = emb_cols + ["height_in"]
    embedding_geometry_numeric = emb_cols + geometry_numeric
    specs = [
        ("baseline_ridge_height_metadata_predict_bmi", baseline_numeric, CATEGORICAL_FEATURES, Ridge(alpha=10.0), "bmi"),
        ("baseline_ridge_height_geometry_metadata_predict_bmi", geometry_numeric, CATEGORICAL_FEATURES, Ridge(alpha=10.0), "bmi"),
        (f"ridge_{slug}_embedding_height_predict_bmi", embedding_numeric, [], Ridge(alpha=80.0), "bmi"),
        (f"ridge_{slug}_embedding_height_metadata_predict_bmi", embedding_numeric, CATEGORICAL_FEATURES, Ridge(alpha=80.0), "bmi"),
        (f"ridge_{slug}_embedding_geometry_metadata_predict_bmi", embedding_geometry_numeric, CATEGORICAL_FEATURES, Ridge(alpha=80.0), "bmi"),
        (
            f"random_forest_{slug}_embedding_height_predict_bmi",
            embedding_numeric,
            [],
            RandomForestRegressor(n_estimators=250, min_samples_leaf=8, random_state=20260609, n_jobs=-1),
            "bmi",
        ),
        (
            f"hist_gradient_{slug}_embedding_height_predict_bmi",
            embedding_numeric,
            [],
            HistGradientBoostingRegressor(max_iter=160, min_samples_leaf=12, random_state=20260609),
            "bmi",
        ),
    ]
    results = []
    for model_name, numeric, categorical, estimator, target in specs:
        model = Pipeline([("prep", preprocessor(numeric, categorical)), ("model", estimator)])
        results.append(evaluate_one(model_name, model, train, test, numeric + categorical, target))
    return {
        "subset": name,
        "rows": int(len(subset)),
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "results": sorted(results, key=lambda item: item["mae_lbs"]),
    }


def main() -> None:
    args = parse_args()
    rows, embeddings, embeddings_path, rows_path, report_path, slug = extract_embeddings(args)
    frame = build_frame(rows, embeddings)
    report = {
        "model": args.model_name,
        "slug": slug,
        "attempts": str(args.attempts),
        "embeddings": str(embeddings_path),
        "rows_file": str(rows_path),
        "rows": int(len(frame)),
        "embedding_dim": int(embeddings.shape[1]) if embeddings.ndim == 2 else 0,
        "status_counts": rows["embedding_status"].value_counts(dropna=False).to_dict(),
        "subsets": [evaluate_subset(name, frame, slug) for name in SUBSETS],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
