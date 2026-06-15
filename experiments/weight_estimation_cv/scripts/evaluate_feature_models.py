#!/usr/bin/env python3
"""Evaluate pretrained image feature models on held-out weight labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SAMPLE = REPO_ROOT / "experiments/weight_estimation_cv/data/eval_sample_with_images.csv"
DEFAULT_FEATURE_DIR = REPO_ROOT / "experiments/weight_estimation_cv/data/features"
DEFAULT_OUTPUT = REPO_ROOT / "experiments/weight_estimation_cv/reports/feature_model_metrics.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--feature-dir", type=Path, default=DEFAULT_FEATURE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--alphas", nargs="+", type=float, default=[0.1, 1.0, 10.0, 100.0, 1000.0])
    return parser.parse_args()


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "mae_lbs": round(float(mean_absolute_error(y_true, y_pred)), 3),
        "rmse_lbs": round(float(mean_squared_error(y_true, y_pred) ** 0.5), 3),
        "r2": round(float(r2_score(y_true, y_pred)), 4),
        "within_10_lbs": round(float(np.mean(np.abs(y_true - y_pred) <= 10.0)), 4),
        "within_15_lbs": round(float(np.mean(np.abs(y_true - y_pred) <= 15.0)), 4),
        "within_20_lbs": round(float(np.mean(np.abs(y_true - y_pred) <= 20.0)), 4),
    }


def weight_from_bmi(bmi: np.ndarray, height_in: np.ndarray) -> np.ndarray:
    return bmi * (height_in ** 2) / 703.0


def load_feature_frame(feature_path: Path) -> pd.DataFrame:
    data = np.load(feature_path, allow_pickle=False)
    row_ids = data["row_ids"].astype(str)
    features = data["features"].astype("float32")
    columns = [f"f_{index}" for index in range(features.shape[1])]
    frame = pd.DataFrame(features, columns=columns)
    frame.insert(0, "row_id", row_ids)
    return frame


def build_tabular_preprocessor(numeric_features: list[str], categorical_features: list[str]) -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            (
                "numeric",
                Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]),
                numeric_features,
            ),
            (
                "categorical",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="constant", fill_value="")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=4)),
                    ]
                ),
                categorical_features,
            ),
        ],
        remainder="drop",
    )


def fit_predict_ridge(
    train_x: np.ndarray,
    train_y: np.ndarray,
    test_x: np.ndarray,
    alphas: list[float],
) -> tuple[np.ndarray, float]:
    best_alpha = alphas[0]
    best_mae = float("inf")
    best_pred = None
    rng = np.random.default_rng(20260609)
    train_indices = np.arange(len(train_x))
    rng.shuffle(train_indices)
    cutoff = max(1, int(len(train_indices) * 0.8))
    inner_train = train_indices[:cutoff]
    inner_val = train_indices[cutoff:]
    if len(inner_val) == 0:
        inner_val = inner_train
    scaler = StandardScaler()
    train_scaled = scaler.fit_transform(train_x)
    test_scaled = scaler.transform(test_x)
    for alpha in alphas:
        model = Ridge(alpha=alpha)
        model.fit(train_scaled[inner_train], train_y[inner_train])
        val_pred = model.predict(train_scaled[inner_val])
        val_mae = mean_absolute_error(train_y[inner_val], val_pred)
        if val_mae < best_mae:
            best_mae = float(val_mae)
            best_alpha = alpha
    final = Ridge(alpha=best_alpha)
    final.fit(train_scaled, train_y)
    best_pred = final.predict(test_scaled)
    return best_pred, best_alpha


def evaluate_feature_file(feature_path: Path, sample: pd.DataFrame, alphas: list[float]) -> list[dict[str, object]]:
    model_name = feature_path.name.replace("_features.npz", "")
    feature_frame = load_feature_frame(feature_path)
    df = sample.merge(feature_frame, on="row_id", how="inner")
    feature_cols = [column for column in df.columns if column.startswith("f_")]
    for column in ["height_in", "weight_lbs", "bmi"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in ["size_display", "clothing_type_id", "source_site_display"]:
        df[column] = df[column].fillna("").astype(str)

    train = df[df["split"] == "train"].copy()
    test = df[df["split"] == "test"].copy()
    results: list[dict[str, object]] = []
    y_train_bmi = train["bmi"].to_numpy(dtype=float)
    y_test_weight = test["weight_lbs"].to_numpy(dtype=float)

    scenarios = [
        ("image_only_predict_bmi", feature_cols, [], []),
        ("image_height_predict_bmi", feature_cols + ["height_in"], [], []),
        ("image_height_size_category_predict_bmi", feature_cols + ["height_in"], ["size_display", "clothing_type_id", "source_site_display"], []),
    ]

    for scenario, numeric_features, categorical_features, _ in scenarios:
        if categorical_features:
            prep = build_tabular_preprocessor(numeric_features, categorical_features)
            train_x = prep.fit_transform(train[numeric_features + categorical_features])
            test_x = prep.transform(test[numeric_features + categorical_features])
            if hasattr(train_x, "toarray"):
                train_x = train_x.toarray()
            if hasattr(test_x, "toarray"):
                test_x = test_x.toarray()
        else:
            train_x = train[numeric_features].to_numpy(dtype="float32")
            test_x = test[numeric_features].to_numpy(dtype="float32")
        pred_bmi, alpha = fit_predict_ridge(train_x, y_train_bmi, test_x, alphas)
        pred_weight = weight_from_bmi(pred_bmi, test["height_in"].to_numpy(dtype=float))
        results.append(
            {
                "model": model_name,
                "scenario": scenario,
                "target": "bmi",
                "alpha": alpha,
                "feature_dim": int(train_x.shape[1]),
                "rows_train": int(len(train)),
                "rows_test": int(len(test)),
                **metrics(y_test_weight, pred_weight),
            }
        )
    return results


def main() -> None:
    args = parse_args()
    sample = pd.read_csv(args.sample)
    sample = sample[sample["download_status"].isin(["downloaded", "cached"])].copy()
    all_results: list[dict[str, object]] = []
    for feature_path in sorted(args.feature_dir.glob("*_features.npz")):
        all_results.extend(evaluate_feature_file(feature_path, sample, args.alphas))

    payload = {
        "sample": str(args.sample),
        "feature_dir": str(args.feature_dir),
        "results": sorted(all_results, key=lambda item: item["mae_lbs"]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
