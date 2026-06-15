#!/usr/bin/env python3
"""Train supervised weight estimators from image embeddings plus approved metadata.

This intentionally excludes crop/framing geometry, clothing type, image-quality
tags, multi-person images, and other operational labels from model features.
Image-quality tags are retained only for evaluation slices.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / "cache/matplotlib"))

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROWS = EXPERIMENT_ROOT / "data/supervised_scale_vit_base_patch16_clip_224_openai_person_crop_embedding_rows.csv"
DEFAULT_EMBEDDINGS = EXPERIMENT_ROOT / "data/features/supervised_scale_vit_base_patch16_clip_224_openai_person_crop_embeddings.npz"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/supervised_scale_hybrid_model_metrics.json"
DEFAULT_SUMMARY = EXPERIMENT_ROOT / "reports/supervised_scale_hybrid_model_summary_2026-06-09.md"

RANDOM_SEED = 20260609
APPROVED_METADATA = ["height_in", "size_display", "source_site_display"]
SLICE_COLUMNS = ["image_quality_bucket", "weight_bin", "height_bin"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, default=DEFAULT_ROWS)
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--pca-dims", type=int, default=96)
    parser.add_argument("--max-iter", type=int, default=180)
    parser.add_argument("--min-samples-leaf", type=int, default=18)
    return parser.parse_args()


def one_hot_encoder() -> OneHotEncoder:
    try:
        return OneHotEncoder(handle_unknown="ignore", min_frequency=4, sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", min_frequency=4, sparse=False)


def weight_from_bmi(bmi: np.ndarray, height_in: np.ndarray) -> np.ndarray:
    return bmi * (height_in**2) / 703.0


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


def make_height_bins(height: pd.Series) -> pd.Series:
    return pd.cut(
        pd.to_numeric(height, errors="coerce"),
        bins=[0, 62, 66, 70, 74, 120],
        labels=["under_5_2", "5_2_to_5_6", "5_6_to_5_10", "5_10_to_6_2", "over_6_2"],
        include_lowest=True,
    ).astype(str)


def as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    normalized = series.fillna(False).astype(str).str.strip().str.lower()
    return normalized.isin(["1", "true", "yes", "y"])


def load_frame(rows_path: Path, embeddings_path: Path, pca_dims: int) -> tuple[pd.DataFrame, dict[str, object]]:
    rows = pd.read_csv(rows_path)
    embeddings = np.load(embeddings_path)["embeddings"].astype(np.float32)
    if len(rows) != len(embeddings):
        raise ValueError(f"Rows/embeddings length mismatch: {len(rows)} rows vs {len(embeddings)} embeddings")

    frame = rows.copy()
    frame["height_in"] = pd.to_numeric(frame["height_in"], errors="coerce")
    frame["weight_lbs"] = pd.to_numeric(frame["weight_lbs"], errors="coerce")
    frame["bmi"] = pd.to_numeric(frame["bmi"], errors="coerce")
    frame["height_bin"] = make_height_bins(frame["height_in"])
    for column in ["size_display", "source_site_display", "image_quality_bucket", "weight_bin"]:
        if column not in frame:
            frame[column] = ""
        frame[column] = frame[column].fillna("").astype(str)

    valid = (
        frame["split"].isin(["train", "test"])
        & frame["height_in"].notna()
        & frame["weight_lbs"].notna()
        & frame["bmi"].notna()
        & frame["embedding_status"].eq("ok")
    )
    if "multiple_people" in frame:
        valid &= ~as_bool(frame["multiple_people"])
    frame = frame[valid].reset_index(drop=True)
    embeddings = embeddings[valid.to_numpy()]

    train_mask = frame["split"].eq("train").to_numpy()
    pca_dims = min(pca_dims, embeddings.shape[1], int(train_mask.sum()) - 1)
    scaler = StandardScaler()
    train_scaled = scaler.fit_transform(embeddings[train_mask])
    pca = PCA(n_components=pca_dims, random_state=RANDOM_SEED)
    pca.fit(train_scaled)
    pcs = pca.transform(scaler.transform(embeddings))
    pc_cols = [f"clip_pc_{idx:03d}" for idx in range(pcs.shape[1])]
    frame = pd.concat([frame, pd.DataFrame(pcs, columns=pc_cols)], axis=1)

    embedding_info = {
        "rows_file": str(rows_path),
        "embeddings_file": str(embeddings_path),
        "embedding_rows_loaded": int(len(rows)),
        "embedding_dim": int(embeddings.shape[1]),
        "pca_dims": int(pca_dims),
        "pca_explained_variance_ratio_sum": round(float(pca.explained_variance_ratio_.sum()), 4),
    }
    return frame, embedding_info


def preprocessor(numeric: list[str], categorical: list[str]) -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ("numeric", Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]), numeric),
            (
                "categorical",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="constant", fill_value="")),
                        ("onehot", one_hot_encoder()),
                    ]
                ),
                categorical,
            ),
        ],
        sparse_threshold=0.0,
    )


def evaluate_model(
    model_name: str,
    estimator,
    train: pd.DataFrame,
    test: pd.DataFrame,
    numeric: list[str],
    categorical: list[str],
    target: str,
) -> tuple[Pipeline, dict[str, object], np.ndarray]:
    pipe = Pipeline([("prep", preprocessor(numeric, categorical)), ("model", estimator)])
    pipe.fit(train[numeric + categorical], train[target])
    pred_target = pipe.predict(test[numeric + categorical])
    pred_weight = weight_from_bmi(pred_target, test["height_in"].to_numpy(dtype=float)) if target == "bmi" else pred_target
    result = {
        "model": model_name,
        "target": target,
        "numeric_features": numeric,
        "categorical_features": categorical,
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        **metrics(test["weight_lbs"].to_numpy(dtype=float), pred_weight),
    }
    return pipe, result, pred_weight


def slice_metrics(test: pd.DataFrame, pred_weight: np.ndarray) -> dict[str, dict[str, dict[str, object]]]:
    y_true = test["weight_lbs"].to_numpy(dtype=float)
    output: dict[str, dict[str, dict[str, object]]] = {}
    for column in SLICE_COLUMNS:
        output[column] = {}
        for value, indexes in test.groupby(column, dropna=False).groups.items():
            idx = np.asarray(list(indexes), dtype=int)
            if len(idx) < 30:
                continue
            output[column][str(value)] = {"rows": int(len(idx)), **metrics(y_true[idx], pred_weight[idx])}
    return output


def run_experiment(frame: pd.DataFrame, args: argparse.Namespace) -> dict[str, object]:
    train = frame[frame["split"].eq("train")].copy()
    test = frame[frame["split"].eq("test")].copy()
    pc_cols = [column for column in frame.columns if column.startswith("clip_pc_")]

    feature_sets = [
        ("height_only", ["height_in"], []),
        ("height_size", ["height_in"], ["size_display"]),
        ("height_size_source", ["height_in"], ["size_display", "source_site_display"]),
        ("clip_pca_height", pc_cols + ["height_in"], []),
        ("clip_pca_height_size", pc_cols + ["height_in"], ["size_display"]),
        ("clip_pca_height_size_source", pc_cols + ["height_in"], ["size_display", "source_site_display"]),
    ]
    estimator_specs = [
        ("ridge", Ridge(alpha=80.0)),
        (
            "hist_gradient",
            HistGradientBoostingRegressor(
                max_iter=args.max_iter,
                min_samples_leaf=args.min_samples_leaf,
                random_state=RANDOM_SEED,
            ),
        ),
    ]

    results = []
    prediction_slices = []
    for feature_name, numeric, categorical in feature_sets:
        for estimator_name, estimator in estimator_specs:
            for target in ["weight_lbs", "bmi"]:
                name = f"{estimator_name}_{feature_name}_predict_{target.replace('_lbs', '')}"
                _, result, pred_weight = evaluate_model(name, clone(estimator), train, test, numeric, categorical, target)
                result["feature_set"] = feature_name
                results.append(result)
                prediction_slices.append(
                    {
                        "model": name,
                        "target": target,
                        "feature_set": feature_name,
                        "slices": slice_metrics(test.reset_index(drop=True), pred_weight),
                    }
                )

    results = sorted(results, key=lambda item: item["mae_lbs"])
    return {
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "approved_metadata_features": APPROVED_METADATA,
        "excluded_feature_families": [
            "clothing_type_id",
            "image_quality_bucket as a feature",
            "multi-person images",
            "crop/framing geometry",
            "image dimensions",
            "person detector geometry",
            "face detector counts/geometry",
            "low-signal operational labels",
        ],
        "results": results,
        "slice_metrics": prediction_slices,
    }


def write_summary(report: dict[str, object], path: Path) -> None:
    results = report["experiment"]["results"]
    best = results[0]
    lines = [
        "# Supervised Weight Model Experiment Checkpoint",
        "",
        "## Dataset",
        "",
        f"- Train rows: {report['experiment']['rows_train']:,}",
        f"- Test rows: {report['experiment']['rows_test']:,}",
        f"- Original embedding dimension: {report['embedding_info']['embedding_dim']}",
        f"- PCA dimensions used for supervised models: {report['embedding_info']['pca_dims']}",
        f"- PCA explained variance ratio: {report['embedding_info']['pca_explained_variance_ratio_sum']}",
        "",
        "## Best Result",
        "",
        f"- Model: `{best['model']}`",
        f"- MAE: {best['mae_lbs']} lbs",
        f"- Median absolute error: {best['median_abs_error_lbs']} lbs",
        f"- RMSE: {best['rmse_lbs']} lbs",
        f"- Within 20 lbs: {best['within_20_lbs']}",
        f"- Within 30 lbs: {best['within_30_lbs']}",
        "",
        "## Top Models",
        "",
        "| Rank | Model | Target | MAE | Median AE | RMSE | Within 20 | Within 30 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for idx, item in enumerate(results[:12], start=1):
        lines.append(
            f"| {idx} | `{item['model']}` | `{item['target']}` | {item['mae_lbs']} | "
            f"{item['median_abs_error_lbs']} | {item['rmse_lbs']} | {item['within_20_lbs']} | {item['within_30_lbs']} |"
        )
    lines.extend(
        [
            "",
            "## Feature Guardrails",
            "",
            "The supervised pass uses image embeddings plus height, optional size text, and optional source-site text.",
            "It excludes clothing type, image quality as a feature, all crop/framing geometry, image dimensions, detector geometry, low-signal labels, and multi-person images.",
            "Image-quality bucket is retained only for evaluation slices.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    frame, embedding_info = load_frame(args.rows, args.embeddings, args.pca_dims)
    report = {
        "embedding_info": embedding_info,
        "experiment": run_experiment(frame, args),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_summary(report, args.summary)
    print(json.dumps({"report": str(args.report), "summary": str(args.summary), "best": report["experiment"]["results"][0]}, indent=2))


if __name__ == "__main__":
    main()
