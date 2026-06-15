#!/usr/bin/env python3
"""Evaluate non-image and existing-CV baselines for weight/BMI prediction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/eval_sample_with_images.csv"
DEFAULT_OUTPUT = REPO_ROOT / "experiments/weight_estimation_cv/reports/tabular_baseline_metrics.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--downloaded-only", action="store_true")
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


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input)
    if args.downloaded_only:
        df = df[df["download_status"].isin(["downloaded", "cached"])].copy()
    for column in [
        "height_in",
        "weight_lbs",
        "bmi",
        "person_count_yolo_detect",
        "main_person_height_pct_yolo_detect",
        "main_person_bbox_area_pct_yolo_detect",
        "body_coverage_score_yolo_pose",
        "image_width_downloaded",
        "image_height_downloaded",
    ]:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    train = df[df["split"] == "train"].copy()
    test = df[df["split"] == "test"].copy()
    for column in ["size_display", "clothing_type_id", "source_site_display", "has_face_yunet"]:
        if column in train:
            train[column] = train[column].fillna("").astype(str)
            test[column] = test[column].fillna("").astype(str)
    y_train = train["weight_lbs"].to_numpy(dtype=float)
    y_test = test["weight_lbs"].to_numpy(dtype=float)

    results: list[dict[str, object]] = []
    mean_pred = np.full_like(y_test, y_train.mean(), dtype=float)
    results.append({"model": "mean_weight", "target": "weight_lbs", "features": [], "rows_train": int(len(train)), "rows_test": int(len(test)), **metrics(y_test, mean_pred)})

    mean_bmi = train["bmi"].mean()
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
            "ridge_height_size_category_predict_bmi",
            ["height_in"],
            ["size_display", "clothing_type_id", "source_site_display"],
            Ridge(alpha=10.0),
            "bmi",
        ),
        (
            "ridge_height_existing_cv_predict_bmi",
            [
                "height_in",
                "person_count_yolo_detect",
                "main_person_height_pct_yolo_detect",
                "main_person_bbox_area_pct_yolo_detect",
                "body_coverage_score_yolo_pose",
                "image_width_downloaded",
                "image_height_downloaded",
            ],
            ["size_display", "clothing_type_id", "source_site_display", "has_face_yunet"],
            Ridge(alpha=10.0),
            "bmi",
        ),
        (
            "random_forest_height_size_category_predict_bmi",
            ["height_in", "image_width_downloaded", "image_height_downloaded"],
            ["size_display", "clothing_type_id", "source_site_display"],
            RandomForestRegressor(n_estimators=250, min_samples_leaf=6, random_state=20260609, n_jobs=-1),
            "bmi",
        ),
    ]

    for name, numeric_features, categorical_features, estimator, target in specs:
        features = numeric_features + categorical_features
        model = Pipeline([("prep", build_preprocessor(numeric_features, categorical_features)), ("model", estimator)])
        results.append(evaluate_model(name, model, train, test, features, target))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "input": str(args.input),
        "downloaded_only": args.downloaded_only,
        "rows": int(len(df)),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "results": sorted(results, key=lambda item: item["mae_lbs"]),
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
