#!/usr/bin/env python3
"""Evaluate DINOv2 full-image embeddings with FWM-trained regressors."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parents[1] / "cache/huggingface"))
os.environ.setdefault("XDG_CACHE_HOME", str(Path(__file__).resolve().parents[1] / "cache"))
os.environ.setdefault("TORCH_HOME", str(Path(__file__).resolve().parents[1] / "cache/torch"))

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
DEFAULT_INPUT = EXPERIMENT_ROOT / "data/eval_sample_with_quality_tags.csv"
DEFAULT_EMBEDDINGS = EXPERIMENT_ROOT / "data/features/dinov2_small_full_image_embeddings.npz"
DEFAULT_ROWS = EXPERIMENT_ROOT / "data/dinov2_small_full_image_embedding_rows.csv"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/dinov2_small_full_image_metrics.json"
DEFAULT_BASELINES = EXPERIMENT_ROOT / "reports/subset_baseline_metrics.json"


SUBSETS = {
    "all_downloaded": lambda df: pd.Series(True, index=df.index),
    "person_visible": lambda df: df["person_visible"].astype(bool),
    "full_body_likely": lambda df: df["full_body_likely"].astype(bool),
    "torso_or_partial_body": lambda df: df["torso_or_partial_body"].astype(bool),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--rows", type=Path, default=DEFAULT_ROWS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--baselines", type=Path, default=DEFAULT_BASELINES)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def load_model(device: str) -> tuple[torch.nn.Module, object]:
    model = timm.create_model("vit_small_patch14_dinov2", pretrained=True, num_classes=0)
    model.to(device)
    model.eval()
    config = resolve_model_data_config(model)
    transform = create_transform(**config, is_training=False)
    return model, transform


def extract_embeddings(args: argparse.Namespace) -> tuple[pd.DataFrame, np.ndarray]:
    if args.embeddings.exists() and args.rows.exists() and not args.limit:
        return pd.read_csv(args.rows), np.load(args.embeddings)["embeddings"]

    df = pd.read_csv(args.input)
    work = df[df["is_downloaded_image"].astype(bool)].copy()
    if args.limit:
        work = work.head(args.limit).copy()
    model, transform = load_model(args.device)

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

    for _, row in tqdm(work.iterrows(), total=len(work), desc="DINOv2 full images"):
        path = Path(str(row["local_image_path"]))
        status = "ok"
        try:
            image = Image.open(path).convert("RGB")
            tensor = transform(image)
        except Exception as exc:  # noqa: BLE001 - record and skip bad images.
            status = f"read_failed:{type(exc).__name__}"
            rows.append({**row.to_dict(), "dinov2_status": status, "embedding_index": -1})
            continue
        rows.append({**row.to_dict(), "dinov2_status": status, "embedding_index": len(embeddings) + len(tensors)})
        tensors.append(tensor)
        if len(tensors) >= args.batch_size:
            flush_batch()
    flush_batch()

    row_df = pd.DataFrame(rows)
    ok_rows = row_df[row_df["embedding_index"] >= 0].copy()
    matrix = np.vstack(embeddings) if embeddings else np.empty((0, 384), dtype=np.float32)
    if not args.limit:
        args.embeddings.parent.mkdir(parents=True, exist_ok=True)
        args.rows.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(args.embeddings, embeddings=matrix)
        ok_rows.to_csv(args.rows, index=False)
    return ok_rows, matrix


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
    payload = json.loads(path.read_text())
    for item in payload.get("subsets", []):
        if item.get("subset") == subset and item.get("results"):
            return sorted(item["results"], key=lambda row: row["mae_lbs"])[0]
    return None


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


def evaluate_subset(name: str, frame: pd.DataFrame, args: argparse.Namespace) -> dict[str, object]:
    subset = frame[SUBSETS[name](frame)].copy()
    train = subset[subset["split"] == "train"].copy()
    test = subset[subset["split"] == "test"].copy()
    emb_cols = [column for column in frame.columns if column.startswith("emb_")]
    categorical = ["size_display", "clothing_type_id", "source_site_display", "image_quality_bucket"]
    for column in ["height_in", "weight_lbs", "bmi"]:
        train[column] = pd.to_numeric(train[column], errors="coerce")
        test[column] = pd.to_numeric(test[column], errors="coerce")
    for column in categorical:
        train[column] = train[column].fillna("").astype(str)
        test[column] = test[column].fillna("").astype(str)

    if len(train) < 20 or len(test) < 10:
        return {"subset": name, "rows": int(len(subset)), "rows_train": int(len(train)), "rows_test": int(len(test)), "skipped": "too_few_rows"}

    specs = [
        ("ridge_dinov2_embedding_predict_bmi", emb_cols, [], Ridge(alpha=50.0), "bmi"),
        ("ridge_dinov2_embedding_height_predict_bmi", emb_cols + ["height_in"], [], Ridge(alpha=50.0), "bmi"),
        ("ridge_dinov2_embedding_height_metadata_predict_bmi", emb_cols + ["height_in"], categorical, Ridge(alpha=50.0), "bmi"),
        (
            "random_forest_dinov2_embedding_height_predict_bmi",
            emb_cols + ["height_in"],
            [],
            RandomForestRegressor(n_estimators=300, min_samples_leaf=8, random_state=20260609, n_jobs=-1),
            "bmi",
        ),
        (
            "hist_gradient_dinov2_embedding_height_predict_bmi",
            emb_cols + ["height_in"],
            [],
            HistGradientBoostingRegressor(max_iter=200, min_samples_leaf=12, random_state=20260609),
            "bmi",
        ),
    ]
    results = []
    for model_name, numeric, categorical_cols, estimator, target in specs:
        model = Pipeline([("prep", preprocessor(numeric, categorical_cols)), ("model", estimator)])
        results.append(evaluate_one(model_name, model, train, test, numeric + categorical_cols, target))
    return {
        "subset": name,
        "rows": int(len(subset)),
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "baseline": best_baseline(args.baselines, name),
        "results": sorted(results, key=lambda item: item["mae_lbs"]),
    }


def main() -> None:
    args = parse_args()
    rows, embeddings = extract_embeddings(args)
    frame = build_frame(rows, embeddings)
    report = {
        "model": "timm/vit_small_patch14_dinov2 full-image embeddings + FWM regressors",
        "input": str(args.input),
        "embeddings": str(args.embeddings),
        "rows_file": str(args.rows),
        "rows": int(len(frame)),
        "status_counts": rows["dinov2_status"].value_counts(dropna=False).to_dict(),
        "subsets": [evaluate_subset(name, frame, args) for name in SUBSETS],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
