#!/usr/bin/env python3
"""Evaluate tabular/geometry baselines on image-eligible subsets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/eval_sample_with_quality_tags.csv"
DEFAULT_OUTPUT = REPO_ROOT / "experiments/weight_estimation_cv/reports/subset_baseline_metrics.json"


SUBSETS = {
    "all_downloaded": lambda df: df["is_downloaded_image"],
    "face_visible": lambda df: df["is_downloaded_image"] & df["face_visible"],
    "large_face_visible": lambda df: df["is_downloaded_image"] & df["large_face_visible"],
    "person_visible": lambda df: df["is_downloaded_image"] & df["person_visible"],
    "full_body_likely": lambda df: df["is_downloaded_image"] & df["full_body_likely"],
    "torso_or_partial_body": lambda df: df["is_downloaded_image"] & df["torso_or_partial_body"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


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


def weight_from_bmi(bmi: np.ndarray, height_in: np.ndarray) -> np.ndarray:
    return bmi * (height_in ** 2) / 703.0


def build_preprocessor(numeric_features: list[str], categorical_features: list[str]) -> ColumnTransformer:
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
        ]
    )


def evaluate_model(
    name: str,
    model,
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    target: str,
) -> dict[str, object]:
    model.fit(train[features], train[target])
    pred_target = model.predict(test[features])
    if target == "bmi":
        pred_weight = weight_from_bmi(pred_target, test["height_in"].to_numpy(dtype=float))
    else:
        pred_weight = pred_target
    return {
        "model": name,
        "target": target,
        "features": features,
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        **metrics(test["weight_lbs"].to_numpy(dtype=float), pred_weight),
    }


def evaluate_subset(name: str, df: pd.DataFrame) -> dict[str, object]:
    train = df[df["split"] == "train"].copy()
    test = df[df["split"] == "test"].copy()
    results: list[dict[str, object]] = []
    if len(train) < 20 or len(test) < 10:
        return {
            "subset": name,
            "rows": int(len(df)),
            "rows_train": int(len(train)),
            "rows_test": int(len(test)),
            "results": [],
            "skipped": "too_few_rows",
        }

    y_train = train["weight_lbs"].to_numpy(dtype=float)
    y_test = test["weight_lbs"].to_numpy(dtype=float)
    mean_weight_pred = np.full(len(test), y_train.mean(), dtype=float)
    results.append(
        {
            "model": "mean_weight",
            "target": "weight_lbs",
            "features": [],
            "rows_train": int(len(train)),
            "rows_test": int(len(test)),
            **metrics(y_test, mean_weight_pred),
        }
    )
    mean_bmi = float(train["bmi"].mean())
    results.append(
        {
            "model": "mean_bmi_x_height",
            "target": "bmi",
            "features": ["height_in"],
            "rows_train": int(len(train)),
            "rows_test": int(len(test)),
            **metrics(y_test, weight_from_bmi(np.full(len(test), mean_bmi), test["height_in"].to_numpy(dtype=float))),
        }
    )

    specs = [
        (
            "ridge_height_only_predict_bmi",
            ["height_in"],
            [],
            Ridge(alpha=5.0),
            "bmi",
        ),
        (
            "ridge_height_metadata_predict_bmi",
            ["height_in"],
            ["size_display", "clothing_type_id", "source_site_display", "image_quality_bucket"],
            Ridge(alpha=10.0),
            "bmi",
        ),
        (
            "ridge_height_geometry_metadata_predict_bmi",
            [
                "height_in",
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
            ],
            ["size_display", "clothing_type_id", "source_site_display", "image_quality_bucket"],
            Ridge(alpha=10.0),
            "bmi",
        ),
        (
            "random_forest_height_geometry_metadata_predict_bmi",
            [
                "height_in",
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
            ],
            ["size_display", "clothing_type_id", "source_site_display", "image_quality_bucket"],
            RandomForestRegressor(n_estimators=250, min_samples_leaf=6, random_state=20260609, n_jobs=-1),
            "bmi",
        ),
        (
            "hist_gradient_height_geometry_metadata_predict_bmi",
            [
                "height_in",
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
            ],
            [],
            HistGradientBoostingRegressor(max_iter=200, min_samples_leaf=12, random_state=20260609),
            "bmi",
        ),
    ]

    for model_name, numeric_features, categorical_features, estimator, target in specs:
        features = numeric_features + categorical_features
        model = Pipeline([("prep", build_preprocessor(numeric_features, categorical_features)), ("model", estimator)])
        results.append(evaluate_model(model_name, model, train, test, features, target))

    return {
        "subset": name,
        "rows": int(len(df)),
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "results": sorted(results, key=lambda item: item["mae_lbs"]),
    }


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input)
    numeric_cols = [
        "height_in",
        "weight_lbs",
        "bmi",
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
    ]
    for column in numeric_cols:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in ["is_downloaded_image", "face_visible", "large_face_visible", "person_visible", "full_body_likely", "torso_or_partial_body"]:
        df[column] = df[column].astype(bool)
    for column in ["size_display", "clothing_type_id", "source_site_display", "image_quality_bucket"]:
        df[column] = df[column].fillna("").astype(str)

    subset_payloads = []
    for subset_name, subset_filter in SUBSETS.items():
        subset_df = df[subset_filter(df)].copy()
        subset_payloads.append(evaluate_subset(subset_name, subset_df))

    payload = {
        "input": str(args.input),
        "subsets": subset_payloads,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
