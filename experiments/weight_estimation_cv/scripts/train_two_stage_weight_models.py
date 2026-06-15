#!/usr/bin/env python3
"""Train two-stage high-weight-aware weight estimators.

The first stage estimates the probability that a row belongs to a higher-weight
band. The second stage combines a global regressor with specialized high-weight
regressors by either routing or probability blending.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    average_precision_score,
    precision_recall_fscore_support,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline

from train_supervised_hybrid_weight_models import (
    RANDOM_SEED,
    APPROVED_METADATA,
    load_frame,
    metrics,
    preprocessor,
    slice_metrics,
)


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROWS = EXPERIMENT_ROOT / "data/supervised_scale_vit_base_patch16_clip_224_openai_person_crop_embedding_rows.csv"
DEFAULT_EMBEDDINGS = EXPERIMENT_ROOT / "data/features/supervised_scale_vit_base_patch16_clip_224_openai_person_crop_embeddings.npz"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/supervised_scale_two_stage_model_metrics.json"
DEFAULT_SUMMARY = EXPERIMENT_ROOT / "reports/supervised_scale_two_stage_model_summary_2026-06-09.md"

THRESHOLDS = [181.0, 211.0, 251.0]


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


def make_inverse_bin_weights(train: pd.DataFrame) -> np.ndarray:
    counts = train["weight_bin"].value_counts(dropna=False)
    weights = 1.0 / train["weight_bin"].map(counts).astype(float).to_numpy()
    return weights / weights.mean()


def model_fit_predict(
    train: pd.DataFrame,
    test: pd.DataFrame,
    numeric: list[str],
    categorical: list[str],
    estimator,
    train_filter: np.ndarray | None = None,
    sample_weight: np.ndarray | None = None,
) -> tuple[Pipeline, np.ndarray]:
    work = train if train_filter is None else train.loc[train_filter].copy()
    y = work["weight_lbs"].to_numpy(dtype=float)
    pipe = Pipeline([("prep", preprocessor(numeric, categorical)), ("model", estimator)])
    fit_kwargs = {}
    if sample_weight is not None:
        fit_kwargs["model__sample_weight"] = sample_weight if train_filter is None else sample_weight[train_filter]
    pipe.fit(work[numeric + categorical], y, **fit_kwargs)
    pred = pipe.predict(test[numeric + categorical])
    return pipe, pred


def classifier_metrics(y_true: np.ndarray, proba: np.ndarray) -> dict[str, object]:
    out: dict[str, object] = {
        "positive_rows": int(y_true.sum()),
        "negative_rows": int((~y_true.astype(bool)).sum()),
        "roc_auc": round(float(roc_auc_score(y_true, proba)), 4) if len(np.unique(y_true)) > 1 else float("nan"),
        "average_precision": round(float(average_precision_score(y_true, proba)), 4)
        if len(np.unique(y_true)) > 1
        else float("nan"),
        "thresholds": {},
    }
    for cutoff in [0.1, 0.2, 0.3, 0.4, 0.5]:
        pred = proba >= cutoff
        precision, recall, f1, _ = precision_recall_fscore_support(y_true, pred, average="binary", zero_division=0)
        out["thresholds"][str(cutoff)] = {
            "predicted_positive_rows": int(pred.sum()),
            "precision": round(float(precision), 4),
            "recall": round(float(recall), 4),
            "f1": round(float(f1), 4),
        }
    return out


def evaluate_prediction(name: str, test: pd.DataFrame, pred: np.ndarray, extra: dict[str, object] | None = None) -> dict[str, object]:
    y_true = test["weight_lbs"].to_numpy(dtype=float)
    result = {
        "model": name,
        **metrics(y_true, pred),
        "high_weight_rollup": high_weight_rollup(test, pred),
    }
    if extra:
        result.update(extra)
    return result


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


def train_classifier(
    train: pd.DataFrame,
    test: pd.DataFrame,
    numeric: list[str],
    categorical: list[str],
    threshold: float,
    kind: str,
) -> tuple[Pipeline, np.ndarray, dict[str, object]]:
    y_train = (train["weight_lbs"].to_numpy(dtype=float) >= threshold).astype(int)
    y_test = (test["weight_lbs"].to_numpy(dtype=float) >= threshold).astype(int)
    if kind == "logistic":
        estimator = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=RANDOM_SEED)
    elif kind == "hist_gradient":
        estimator = HistGradientBoostingClassifier(max_iter=120, min_samples_leaf=18, random_state=RANDOM_SEED)
    else:
        raise ValueError(f"Unknown classifier: {kind}")
    pipe = Pipeline([("prep", preprocessor(numeric, categorical)), ("model", estimator)])
    pipe.fit(train[numeric + categorical], y_train)
    proba = pipe.predict_proba(test[numeric + categorical])[:, 1]
    result = {
        "classifier": kind,
        "threshold_lbs": threshold,
        "train_positive_rows": int(y_train.sum()),
        **classifier_metrics(y_test, proba),
    }
    return pipe, proba, result


def run_experiment(frame: pd.DataFrame, args: argparse.Namespace) -> dict[str, object]:
    train = frame[frame["split"].eq("train")].copy()
    test = frame[frame["split"].eq("test")].copy().reset_index(drop=True)
    pc_cols = [column for column in frame.columns if column.startswith("clip_pc_")]
    numeric = pc_cols + ["height_in"]
    categorical = ["size_display"]
    inverse_weights = make_inverse_bin_weights(train)

    _, global_pred = model_fit_predict(
        train,
        test,
        numeric,
        categorical,
        Ridge(alpha=80.0),
    )
    _, global_weighted_pred = model_fit_predict(
        train,
        test,
        numeric,
        [],
        Ridge(alpha=80.0),
        sample_weight=inverse_weights,
    )
    predictions = [
        evaluate_prediction("global_ridge_clip_pca_height_size", test, global_pred),
        evaluate_prediction("global_inverse_weighted_ridge_clip_pca_height", test, global_weighted_pred),
    ]

    classifiers = []
    routed_results = []
    for threshold in THRESHOLDS:
        high_filter = train["weight_lbs"].to_numpy(dtype=float) >= threshold
        if int(high_filter.sum()) < 50:
            continue
        _, high_pred = model_fit_predict(
            train,
            test,
            numeric,
            [],
            Ridge(alpha=80.0),
            train_filter=high_filter,
            sample_weight=inverse_weights,
        )
        high_model_result = evaluate_prediction(
            f"specialist_ridge_clip_pca_height_train_gte_{int(threshold)}",
            test,
            high_pred,
            {"specialist_train_rows": int(high_filter.sum()), "specialist_threshold_lbs": threshold},
        )
        predictions.append(high_model_result)

        for classifier_kind in ["logistic", "hist_gradient"]:
            _, proba, clf_result = train_classifier(train, test, numeric, categorical, threshold, classifier_kind)
            classifiers.append(clf_result)
            for route_cutoff in [0.15, 0.25, 0.35, 0.5]:
                routed = np.where(proba >= route_cutoff, high_pred, global_pred)
                routed_results.append(
                    evaluate_prediction(
                        f"route_gte_{int(threshold)}_{classifier_kind}_cutoff_{route_cutoff}",
                        test,
                        routed,
                        {
                            "route_threshold_lbs": threshold,
                            "classifier": classifier_kind,
                            "route_cutoff": route_cutoff,
                            "routed_rows": int((proba >= route_cutoff).sum()),
                        },
                    )
                )
            for blend_power in [1.0, 1.5, 2.0]:
                blend_weight = np.clip(proba, 0.0, 1.0) ** blend_power
                blended = (blend_weight * high_pred) + ((1.0 - blend_weight) * global_pred)
                routed_results.append(
                    evaluate_prediction(
                        f"blend_gte_{int(threshold)}_{classifier_kind}_power_{blend_power}",
                        test,
                        blended,
                        {
                            "route_threshold_lbs": threshold,
                            "classifier": classifier_kind,
                            "blend_power": blend_power,
                            "mean_blend_weight": round(float(np.mean(blend_weight)), 4),
                        },
                    )
                )

    all_results = sorted(predictions + routed_results, key=lambda item: item["mae_lbs"])
    high_sorted = sorted(
        predictions + routed_results,
        key=lambda item: item["high_weight_rollup"].get("gte_211", {}).get("mae_lbs", float("inf")),
    )
    return {
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "approved_metadata_features": APPROVED_METADATA,
        "feature_set": {"numeric": numeric, "categorical": categorical},
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
        "classifier_metrics": classifiers,
        "results": all_results,
        "results_by_211_mae": high_sorted,
        "slice_metrics": [
            {"model": result["model"], "slices": slice_metrics(test, np.asarray([]))}
            for result in []
        ],
    }


def write_summary(report: dict[str, object], path: Path) -> None:
    experiment = report["experiment"]
    best = experiment["results"][0]
    best_high = experiment["results_by_211_mae"][0]
    lines = [
        "# Two-Stage Weight Model Experiment",
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
        f"- Overall MAE: {best['mae_lbs']} lbs",
        f"- Median absolute error: {best['median_abs_error_lbs']} lbs",
        f"- Within 30 lbs: {best['within_30_lbs']}",
        f"- 211+ MAE: {best['high_weight_rollup']['gte_211']['mae_lbs']} lbs",
        "",
        "## Best 211+ lb MAE",
        "",
        f"- Model: `{best_high['model']}`",
        f"- Overall MAE: {best_high['mae_lbs']} lbs",
        f"- 211+ MAE: {best_high['high_weight_rollup']['gte_211']['mae_lbs']} lbs",
        f"- 211+ signed error: {best_high['high_weight_rollup']['gte_211']['mean_signed_error_lbs']} lbs",
        "",
        "## Classifier Metrics",
        "",
        "| Classifier | Threshold | Positives | ROC AUC | Avg Precision | P@0.5 | R@0.5 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in experiment["classifier_metrics"]:
        at_half = item["thresholds"]["0.5"]
        lines.append(
            f"| `{item['classifier']}` | {item['threshold_lbs']} | {item['positive_rows']} | "
            f"{item['roc_auc']} | {item['average_precision']} | {at_half['precision']} | {at_half['recall']} |"
        )

    lines.extend(
        [
            "",
            "## Top Overall Models",
            "",
            "| Rank | Model | MAE | Median AE | Within 30 | 211+ MAE | 211+ Signed Error |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for idx, item in enumerate(experiment["results"][:15], start=1):
        high = item["high_weight_rollup"].get("gte_211", {})
        lines.append(
            f"| {idx} | `{item['model']}` | {item['mae_lbs']} | {item['median_abs_error_lbs']} | "
            f"{item['within_30_lbs']} | {high.get('mae_lbs', '')} | {high.get('mean_signed_error_lbs', '')} |"
        )

    lines.extend(
        [
            "",
            "## Top 211+ lb Models",
            "",
            "| Rank | Model | Overall MAE | Within 30 | 211+ MAE | 211+ Median AE | 211+ Signed Error |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for idx, item in enumerate(experiment["results_by_211_mae"][:15], start=1):
        high = item["high_weight_rollup"].get("gte_211", {})
        lines.append(
            f"| {idx} | `{item['model']}` | {item['mae_lbs']} | {item['within_30_lbs']} | "
            f"{high.get('mae_lbs', '')} | {high.get('median_abs_error_lbs', '')} | {high.get('mean_signed_error_lbs', '')} |"
        )
    lines.extend(
        [
            "",
            "## Feature Guardrails",
            "",
            "The two-stage pass uses CLIP PCA components plus height and size for classification, and CLIP PCA plus height for high-weight specialist regressors.",
            "Weight thresholds are used only for classifier labels, specialist training subsets, routing, and evaluation slices.",
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
                "best_211": report["experiment"]["results_by_211_mae"][0],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
