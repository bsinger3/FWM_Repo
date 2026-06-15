#!/usr/bin/env python3
"""Evaluate whether inferred weight signals improve search-style retrieval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression, Ridge

from train_supervised_hybrid_weight_models import (
    RANDOM_SEED,
    load_frame,
    preprocessor,
)
from train_two_stage_weight_models import make_inverse_bin_weights, model_fit_predict, train_classifier


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROWS = EXPERIMENT_ROOT / "data/supervised_scale_vit_base_patch16_clip_224_openai_person_crop_embedding_rows.csv"
DEFAULT_EMBEDDINGS = EXPERIMENT_ROOT / "data/features/supervised_scale_vit_base_patch16_clip_224_openai_person_crop_embeddings.npz"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/supervised_scale_search_retrieval_metrics.json"
DEFAULT_SUMMARY = EXPERIMENT_ROOT / "reports/supervised_scale_search_retrieval_summary_2026-06-09.md"

TOP_KS = [20, 50, 100]
TOLERANCES = [20.0, 30.0, 40.0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, default=DEFAULT_ROWS)
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--pca-dims", type=int, default=96)
    parser.add_argument("--limit-test-rows", type=int, default=0)
    return parser.parse_args()


def norm_size(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower()


def fit_global_predictions(train: pd.DataFrame, test: pd.DataFrame, numeric: list[str]) -> dict[str, np.ndarray]:
    inverse_weights = make_inverse_bin_weights(train)
    _, global_pred = model_fit_predict(train, test, numeric, ["size_display"], Ridge(alpha=80.0))
    _, weighted_pred = model_fit_predict(
        train,
        test,
        numeric,
        [],
        Ridge(alpha=80.0),
        sample_weight=inverse_weights,
    )
    high_filter = train["weight_lbs"].to_numpy(dtype=float) >= 211.0
    _, specialist_211 = model_fit_predict(
        train,
        test,
        numeric,
        [],
        Ridge(alpha=80.0),
        train_filter=high_filter,
        sample_weight=inverse_weights,
    )
    _, proba_211, _ = train_classifier(train, test, numeric, ["size_display"], 211.0, "logistic")
    return {
        "global": global_pred,
        "weighted_global": weighted_pred,
        "specialist_211": specialist_211,
        "proba_211": proba_211,
        "blend_211_logistic_power_1": (proba_211 * specialist_211) + ((1.0 - proba_211) * global_pred),
    }


def distance_to_range(values: np.ndarray, low: float, high: float) -> np.ndarray:
    return np.where(values < low, low - values, np.where(values > high, values - high, 0.0))


def rank_candidates(
    strategy: str,
    query_idx: int,
    test: pd.DataFrame,
    train: pd.DataFrame,
    preds: dict[str, np.ndarray],
    train_weight: np.ndarray,
    train_height: np.ndarray,
    train_size: pd.Series,
) -> np.ndarray:
    query_height = float(test.iloc[query_idx]["height_in"])
    query_size = str(test.iloc[query_idx]["size_display_norm"])
    height_tiebreak = np.abs(train_height - query_height) / 12.0
    size_tiebreak = np.where(train_size.to_numpy() == query_size, 0.0, 0.15)

    if strategy == "height_size_only":
        score = height_tiebreak + size_tiebreak
    elif strategy == "global_point":
        score = np.abs(train_weight - preds["global"][query_idx]) + height_tiebreak + size_tiebreak
    elif strategy == "weighted_global_point":
        score = np.abs(train_weight - preds["weighted_global"][query_idx]) + height_tiebreak + size_tiebreak
    elif strategy == "two_stage_blend_point":
        score = np.abs(train_weight - preds["blend_211_logistic_power_1"][query_idx]) + height_tiebreak + size_tiebreak
    elif strategy == "global_range_pm30":
        pred = float(preds["global"][query_idx])
        score = distance_to_range(train_weight, pred - 30.0, pred + 30.0) + height_tiebreak + size_tiebreak
    elif strategy == "candidate_expansion_211":
        global_pred = float(preds["global"][query_idx])
        base_dist = distance_to_range(train_weight, global_pred - 30.0, global_pred + 30.0)
        if float(preds["proba_211"][query_idx]) >= 0.15:
            specialist = float(preds["specialist_211"][query_idx])
            high_dist = distance_to_range(train_weight, specialist - 30.0, specialist + 40.0)
            base_dist = np.minimum(base_dist, high_dist)
        score = base_dist + height_tiebreak + size_tiebreak
    elif strategy == "oracle_true_weight":
        true_weight = float(test.iloc[query_idx]["weight_lbs"])
        score = np.abs(train_weight - true_weight) + height_tiebreak + size_tiebreak
    else:
        raise ValueError(f"Unknown strategy: {strategy}")
    return np.argsort(score, kind="stable")


def evaluate_strategy(strategy: str, train: pd.DataFrame, test: pd.DataFrame, preds: dict[str, np.ndarray]) -> dict[str, object]:
    train_weight = train["weight_lbs"].to_numpy(dtype=float)
    train_height = train["height_in"].to_numpy(dtype=float)
    train_size = train["size_display_norm"]
    y = test["weight_lbs"].to_numpy(dtype=float)

    buckets = {
        "all": np.ones(len(test), dtype=bool),
        "gte_181": y >= 181.0,
        "gte_211": y >= 211.0,
        "gte_251": y >= 251.0,
        "lt_181": y < 181.0,
    }
    collected: dict[str, list[dict[str, float]]] = {name: [] for name in buckets}
    for idx in range(len(test)):
        order = rank_candidates(strategy, idx, test, train, preds, train_weight, train_height, train_size)
        true_weight = y[idx]
        row_metrics: dict[str, float] = {}
        for top_k in TOP_KS:
            top = order[:top_k]
            diffs = np.abs(train_weight[top] - true_weight)
            for tolerance in TOLERANCES:
                row_metrics[f"precision_at_{top_k}_within_{int(tolerance)}"] = float(np.mean(diffs <= tolerance))
                row_metrics[f"has_match_at_{top_k}_within_{int(tolerance)}"] = float(np.any(diffs <= tolerance))
            row_metrics[f"mean_abs_weight_delta_at_{top_k}"] = float(np.mean(diffs))
            row_metrics[f"median_abs_weight_delta_at_{top_k}"] = float(np.median(diffs))
        for bucket, mask in buckets.items():
            if mask[idx]:
                collected[bucket].append(row_metrics)

    output = {"strategy": strategy, "slices": {}}
    for bucket, rows in collected.items():
        if not rows:
            continue
        keys = rows[0].keys()
        output["slices"][bucket] = {
            "rows": int(len(rows)),
            **{key: round(float(np.mean([row[key] for row in rows])), 4) for key in keys},
        }
    return output


def write_summary(report: dict[str, object], path: Path) -> None:
    strategies = report["strategies"]
    metric = "precision_at_50_within_30"
    high_metric = "precision_at_50_within_30"
    ranked_all = sorted(strategies, key=lambda item: item["slices"]["all"][metric], reverse=True)
    ranked_211 = sorted(
        [item for item in strategies if "gte_211" in item["slices"]],
        key=lambda item: item["slices"]["gte_211"][high_metric],
        reverse=True,
    )
    lines = [
        "# Search Retrieval Evaluation",
        "",
        "## Dataset",
        "",
        f"- Train candidate rows: {report['rows_train']:,}",
        f"- Test query rows: {report['rows_test']:,}",
        f"- PCA dimensions: {report['embedding_info']['pca_dims']}",
        "",
        "## Best Strategies",
        "",
        f"- Best non-oracle overall `{metric}`: `{next(item for item in ranked_all if item['strategy'] != 'oracle_true_weight')['strategy']}`",
        f"- Best non-oracle 211+ `{high_metric}`: `{next(item for item in ranked_211 if item['strategy'] != 'oracle_true_weight')['strategy']}`",
        "",
        "## Overall Retrieval",
        "",
        "| Rank | Strategy | P@20 +/-30 | P@50 +/-30 | P@100 +/-30 | Mean Delta@50 | Has Match@50 +/-30 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for idx, item in enumerate(ranked_all, start=1):
        values = item["slices"]["all"]
        lines.append(
            f"| {idx} | `{item['strategy']}` | {values['precision_at_20_within_30']} | "
            f"{values['precision_at_50_within_30']} | {values['precision_at_100_within_30']} | "
            f"{values['mean_abs_weight_delta_at_50']} | {values['has_match_at_50_within_30']} |"
        )
    lines.extend(
        [
            "",
            "## 211+ Retrieval",
            "",
            "| Rank | Strategy | P@20 +/-30 | P@50 +/-30 | P@100 +/-30 | Mean Delta@50 | Has Match@50 +/-30 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for idx, item in enumerate(ranked_211, start=1):
        values = item["slices"]["gte_211"]
        lines.append(
            f"| {idx} | `{item['strategy']}` | {values['precision_at_20_within_30']} | "
            f"{values['precision_at_50_within_30']} | {values['precision_at_100_within_30']} | "
            f"{values['mean_abs_weight_delta_at_50']} | {values['has_match_at_50_within_30']} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "This evaluates search-style retrieval, not displayable weight estimates.",
            "The oracle strategy ranks candidates by the query's true weight and is included only as an upper bound.",
            "Candidate expansion uses the global predicted range and, when the 211+ classifier probability is at least 0.15, also considers a 211+ specialist range.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    frame, embedding_info = load_frame(args.rows, args.embeddings, args.pca_dims)
    frame["size_display_norm"] = norm_size(frame["size_display"])
    train = frame[frame["split"].eq("train")].copy().reset_index(drop=True)
    test = frame[frame["split"].eq("test")].copy().reset_index(drop=True)
    if args.limit_test_rows:
        test = test.head(args.limit_test_rows).copy().reset_index(drop=True)
    pc_cols = [column for column in frame.columns if column.startswith("clip_pc_")]
    numeric = pc_cols + ["height_in"]
    preds = fit_global_predictions(train, test, numeric)
    strategies = [
        "height_size_only",
        "global_point",
        "weighted_global_point",
        "two_stage_blend_point",
        "global_range_pm30",
        "candidate_expansion_211",
        "oracle_true_weight",
    ]
    report = {
        "embedding_info": embedding_info,
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "strategies": [evaluate_strategy(strategy, train, test, preds) for strategy in strategies],
        "strategy_notes": {
            "height_size_only": "Ranks by height proximity with small exact-size tie-break.",
            "global_point": "Ranks by distance to global predicted weight.",
            "weighted_global_point": "Ranks by distance to inverse-bin weighted global predicted weight.",
            "two_stage_blend_point": "Ranks by distance to logistic 211+ probability blend of global and specialist predictions.",
            "global_range_pm30": "Ranks inside global predicted +/-30 lb range first.",
            "candidate_expansion_211": "Ranks inside global range, plus 211+ specialist range when classifier probability >= 0.15.",
            "oracle_true_weight": "Upper bound using the held-out true weight.",
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_summary(report, args.summary)
    print(json.dumps({"report": str(args.report), "summary": str(args.summary)}, indent=2))


if __name__ == "__main__":
    main()
