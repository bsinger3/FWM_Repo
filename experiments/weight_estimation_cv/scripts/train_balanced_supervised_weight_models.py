#!/usr/bin/env python3
"""Run bin-balanced and sample-weighted variants of the supervised weight model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline

from train_supervised_hybrid_weight_models import (
    RANDOM_SEED,
    APPROVED_METADATA,
    load_frame,
    metrics,
    preprocessor,
    slice_metrics,
    weight_from_bmi,
)


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROWS = EXPERIMENT_ROOT / "data/supervised_scale_vit_base_patch16_clip_224_openai_person_crop_embedding_rows.csv"
DEFAULT_EMBEDDINGS = EXPERIMENT_ROOT / "data/features/supervised_scale_vit_base_patch16_clip_224_openai_person_crop_embeddings.npz"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/supervised_scale_balanced_model_metrics.json"
DEFAULT_SUMMARY = EXPERIMENT_ROOT / "reports/supervised_scale_balanced_model_summary_2026-06-09.md"


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


def make_sample_weights(train: pd.DataFrame, scheme: str) -> np.ndarray | None:
    if scheme == "none":
        return None
    counts = train["weight_bin"].value_counts(dropna=False)
    row_counts = train["weight_bin"].map(counts).astype(float).to_numpy()
    if scheme == "inverse_bin":
        weights = 1.0 / row_counts
    elif scheme == "sqrt_inverse_bin":
        weights = 1.0 / np.sqrt(row_counts)
    elif scheme == "capped_inverse_bin":
        weights = 1.0 / row_counts
        weights = np.minimum(weights / weights.mean(), 3.0)
        return weights / weights.mean()
    else:
        raise ValueError(f"Unknown weighting scheme: {scheme}")
    return weights / weights.mean()


def target_values(frame: pd.DataFrame, target: str) -> np.ndarray:
    if target == "weight_lbs":
        return frame["weight_lbs"].to_numpy(dtype=float)
    if target == "bmi":
        return frame["bmi"].to_numpy(dtype=float)
    if target == "log_weight":
        return np.log(frame["weight_lbs"].to_numpy(dtype=float))
    raise ValueError(f"Unknown target: {target}")


def to_predicted_weight(pred_target: np.ndarray, test: pd.DataFrame, target: str) -> np.ndarray:
    if target == "weight_lbs":
        return pred_target
    if target == "bmi":
        return weight_from_bmi(pred_target, test["height_in"].to_numpy(dtype=float))
    if target == "log_weight":
        return np.exp(pred_target)
    raise ValueError(f"Unknown target: {target}")


def evaluate_model(
    model_name: str,
    estimator,
    train: pd.DataFrame,
    test: pd.DataFrame,
    numeric: list[str],
    categorical: list[str],
    target: str,
    weight_scheme: str,
) -> tuple[dict[str, object], np.ndarray]:
    pipe = Pipeline([("prep", preprocessor(numeric, categorical)), ("model", estimator)])
    sample_weight = make_sample_weights(train, weight_scheme)
    fit_kwargs = {"model__sample_weight": sample_weight} if sample_weight is not None else {}
    pipe.fit(train[numeric + categorical], target_values(train, target), **fit_kwargs)
    pred_target = pipe.predict(test[numeric + categorical])
    pred_weight = to_predicted_weight(pred_target, test, target)
    result = {
        "model": model_name,
        "target": target,
        "weight_scheme": weight_scheme,
        "numeric_features": numeric,
        "categorical_features": categorical,
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        **metrics(test["weight_lbs"].to_numpy(dtype=float), pred_weight),
    }
    return result, pred_weight


def high_weight_rollup(test: pd.DataFrame, pred_weight: np.ndarray) -> dict[str, object]:
    output = {}
    for label, minimum in [("gte_181", 181.0), ("gte_211", 211.0), ("gte_251", 251.0)]:
        mask = test["weight_lbs"].to_numpy(dtype=float) >= minimum
        if int(mask.sum()) < 30:
            continue
        y_true = test.loc[mask, "weight_lbs"].to_numpy(dtype=float)
        y_pred = pred_weight[mask]
        output[label] = {
            "rows": int(mask.sum()),
            **metrics(y_true, y_pred),
            "mean_signed_error_lbs": round(float(np.mean(y_pred - y_true)), 3),
        }
    return output


def run_experiment(frame: pd.DataFrame, args: argparse.Namespace) -> dict[str, object]:
    train = frame[frame["split"].eq("train")].copy()
    test = frame[frame["split"].eq("test")].copy().reset_index(drop=True)
    pc_cols = [column for column in frame.columns if column.startswith("clip_pc_")]
    train_counts = train["weight_bin"].value_counts().sort_index().to_dict()
    test_counts = test["weight_bin"].value_counts().sort_index().to_dict()

    feature_sets = [
        ("height_size", ["height_in"], ["size_display"]),
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
    weight_schemes = ["none", "sqrt_inverse_bin", "capped_inverse_bin", "inverse_bin"]
    targets = ["weight_lbs", "bmi", "log_weight"]

    results = []
    prediction_slices = []
    for feature_name, numeric, categorical in feature_sets:
        for estimator_name, estimator in estimator_specs:
            for target in targets:
                for weight_scheme in weight_schemes:
                    name = f"{estimator_name}_{feature_name}_{weight_scheme}_predict_{target.replace('_lbs', '')}"
                    result, pred_weight = evaluate_model(
                        name,
                        clone(estimator),
                        train,
                        test,
                        numeric,
                        categorical,
                        target,
                        weight_scheme,
                    )
                    result["feature_set"] = feature_name
                    result["high_weight_rollup"] = high_weight_rollup(test, pred_weight)
                    results.append(result)
                    prediction_slices.append(
                        {
                            "model": name,
                            "target": target,
                            "feature_set": feature_name,
                            "weight_scheme": weight_scheme,
                            "slices": slice_metrics(test, pred_weight),
                        }
                    )
    return {
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "train_weight_bin_counts": {str(k): int(v) for k, v in train_counts.items()},
        "test_weight_bin_counts": {str(k): int(v) for k, v in test_counts.items()},
        "approved_metadata_features": APPROVED_METADATA,
        "weight_schemes": weight_schemes,
        "targets": targets,
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
        "results": sorted(results, key=lambda item: item["mae_lbs"]),
        "results_by_high_weight_mae": sorted(
            results,
            key=lambda item: item["high_weight_rollup"].get("gte_211", {}).get("mae_lbs", float("inf")),
        ),
        "slice_metrics": prediction_slices,
    }


def write_summary(report: dict[str, object], path: Path) -> None:
    experiment = report["experiment"]
    results = experiment["results"]
    high_weight_results = experiment["results_by_high_weight_mae"]
    best = results[0]
    best_high = high_weight_results[0]
    lines = [
        "# Balanced Supervised Weight Model Experiment",
        "",
        "## Dataset",
        "",
        f"- Train rows: {experiment['rows_train']:,}",
        f"- Test rows: {experiment['rows_test']:,}",
        f"- PCA dimensions: {report['embedding_info']['pca_dims']}",
        "",
        "## Best Overall MAE",
        "",
        f"- Model: `{best['model']}`",
        f"- MAE: {best['mae_lbs']} lbs",
        f"- Median absolute error: {best['median_abs_error_lbs']} lbs",
        f"- Within 30 lbs: {best['within_30_lbs']}",
        "",
        "## Best 211+ lb MAE",
        "",
        f"- Model: `{best_high['model']}`",
        f"- Overall MAE: {best_high['mae_lbs']} lbs",
        f"- 211+ lb MAE: {best_high['high_weight_rollup']['gte_211']['mae_lbs']} lbs",
        f"- 211+ lb mean signed error: {best_high['high_weight_rollup']['gte_211']['mean_signed_error_lbs']} lbs",
        "",
        "## Top Overall Models",
        "",
        "| Rank | Model | Target | Weighting | MAE | Median AE | Within 30 | 211+ MAE | 211+ Signed Error |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for idx, item in enumerate(results[:15], start=1):
        high = item["high_weight_rollup"].get("gte_211", {})
        lines.append(
            f"| {idx} | `{item['model']}` | `{item['target']}` | `{item['weight_scheme']}` | "
            f"{item['mae_lbs']} | {item['median_abs_error_lbs']} | {item['within_30_lbs']} | "
            f"{high.get('mae_lbs', '')} | {high.get('mean_signed_error_lbs', '')} |"
        )
    lines.extend(
        [
            "",
            "## Top 211+ lb Models",
            "",
            "| Rank | Model | Target | Weighting | Overall MAE | 211+ MAE | 211+ Median AE | 211+ Signed Error |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for idx, item in enumerate(high_weight_results[:15], start=1):
        high = item["high_weight_rollup"].get("gte_211", {})
        lines.append(
            f"| {idx} | `{item['model']}` | `{item['target']}` | `{item['weight_scheme']}` | "
            f"{item['mae_lbs']} | {high.get('mae_lbs', '')} | {high.get('median_abs_error_lbs', '')} | "
            f"{high.get('mean_signed_error_lbs', '')} |"
        )
    lines.extend(
        [
            "",
            "## Feature Guardrails",
            "",
            "This pass uses the same approved features as the first supervised experiment: CLIP PCA components, height, optional size text, and optional source-site text.",
            "Weight bins are used only to compute sample weights and evaluation slices, not as prediction features.",
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
    print(
        json.dumps(
            {
                "report": str(args.report),
                "summary": str(args.summary),
                "best_overall": report["experiment"]["results"][0],
                "best_high_weight": report["experiment"]["results_by_high_weight_mae"][0],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
