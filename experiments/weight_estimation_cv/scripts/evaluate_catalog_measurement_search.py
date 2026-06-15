#!/usr/bin/env python3
"""Evaluate inferred catalog weights for measurement-based website search.

Users search by measurements, not by submitting images. This script treats the
held-out split as catalog images with hidden weights, assigns inferred weights to
those catalog images, then simulates measurement queries from ground-truth rows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from train_supervised_hybrid_weight_models import load_frame
from train_two_stage_weight_models import make_inverse_bin_weights, model_fit_predict, train_classifier


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROWS = EXPERIMENT_ROOT / "data/supervised_scale_vit_base_patch16_clip_224_openai_person_crop_embedding_rows.csv"
DEFAULT_EMBEDDINGS = EXPERIMENT_ROOT / "data/features/supervised_scale_vit_base_patch16_clip_224_openai_person_crop_embeddings.npz"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/supervised_scale_catalog_measurement_search_metrics.json"
DEFAULT_SUMMARY = EXPERIMENT_ROOT / "reports/supervised_scale_catalog_measurement_search_summary_2026-06-09.md"

TOP_KS = [20, 50, 100]
WEIGHT_TOLERANCE = 30.0
HEIGHT_TOLERANCE = 3.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, default=DEFAULT_ROWS)
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--pca-dims", type=int, default=96)
    return parser.parse_args()


def norm_size(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower()


def fit_catalog_predictions(train: pd.DataFrame, catalog: pd.DataFrame, numeric: list[str]) -> dict[str, np.ndarray]:
    inverse_weights = make_inverse_bin_weights(train)
    _, global_pred = model_fit_predict(train, catalog, numeric, ["size_display"], Ridge(alpha=80.0))
    _, weighted_pred = model_fit_predict(
        train,
        catalog,
        numeric,
        [],
        Ridge(alpha=80.0),
        sample_weight=inverse_weights,
    )
    high_filter = train["weight_lbs"].to_numpy(dtype=float) >= 211.0
    _, specialist_211 = model_fit_predict(
        train,
        catalog,
        numeric,
        [],
        Ridge(alpha=80.0),
        train_filter=high_filter,
        sample_weight=inverse_weights,
    )
    _, proba_211, _ = train_classifier(train, catalog, numeric, ["size_display"], 211.0, "logistic")
    return {
        "global_point": global_pred,
        "weighted_global_point": weighted_pred,
        "two_stage_blend_point": (proba_211 * specialist_211) + ((1.0 - proba_211) * global_pred),
        "oracle_true_weight": catalog["weight_lbs"].to_numpy(dtype=float),
        "proba_211": proba_211,
    }


def rank_catalog(
    strategy: str,
    query: pd.Series,
    catalog: pd.DataFrame,
    preds: dict[str, np.ndarray],
    catalog_height: np.ndarray,
    catalog_size: np.ndarray,
) -> np.ndarray:
    query_weight = float(query["weight_lbs"])
    query_height = float(query["height_in"])
    query_size = str(query["size_display_norm"])
    height_delta = np.abs(catalog_height - query_height)
    size_penalty = np.where(catalog_size == query_size, 0.0, 1.5)

    if strategy == "height_size_only":
        score = height_delta + size_penalty
    elif strategy in ["global_point", "weighted_global_point", "two_stage_blend_point", "oracle_true_weight"]:
        weight_delta = np.abs(preds[strategy] - query_weight)
        score = weight_delta + (height_delta * 2.0) + size_penalty
    elif strategy == "height_size_global_weight_boost":
        weight_delta = np.abs(preds["global_point"] - query_weight)
        score = height_delta + size_penalty + (weight_delta * 0.08)
    elif strategy == "height_size_two_stage_weight_boost":
        weight_delta = np.abs(preds["two_stage_blend_point"] - query_weight)
        score = height_delta + size_penalty + (weight_delta * 0.08)
    elif strategy == "height_size_weighted_global_boost":
        weight_delta = np.abs(preds["weighted_global_point"] - query_weight)
        score = height_delta + size_penalty + (weight_delta * 0.08)
    elif strategy == "two_stage_candidate_boost":
        global_delta = np.abs(preds["global_point"] - query_weight)
        blend_delta = np.abs(preds["two_stage_blend_point"] - query_weight)
        high_boost_delta = np.where(preds["proba_211"] >= 0.15, np.minimum(global_delta, blend_delta), global_delta)
        score = high_boost_delta + (height_delta * 2.0) + size_penalty
    else:
        raise ValueError(f"Unknown strategy: {strategy}")
    return np.argsort(score, kind="stable")


def evaluate_strategy(strategy: str, catalog: pd.DataFrame, preds: dict[str, np.ndarray]) -> dict[str, object]:
    weights = catalog["weight_lbs"].to_numpy(dtype=float)
    heights = catalog["height_in"].to_numpy(dtype=float)
    sizes = catalog["size_display_norm"].to_numpy()
    buckets = {
        "all": np.ones(len(catalog), dtype=bool),
        "lt_181": weights < 181.0,
        "gte_181": weights >= 181.0,
        "gte_211": weights >= 211.0,
        "gte_251": weights >= 251.0,
    }
    collected: dict[str, list[dict[str, float]]] = {name: [] for name in buckets}

    for query_idx, query in catalog.iterrows():
        order = rank_catalog(strategy, query, catalog, preds, heights, sizes)
        target_rank = int(np.where(order == query_idx)[0][0]) + 1
        query_weight = float(query["weight_lbs"])
        query_height = float(query["height_in"])
        relevant = (np.abs(weights - query_weight) <= WEIGHT_TOLERANCE) & (
            np.abs(heights - query_height) <= HEIGHT_TOLERANCE
        )
        row_metrics: dict[str, float] = {
            "target_rank": float(target_rank),
            "target_rank_percentile": float(target_rank / len(catalog)),
        }
        for top_k in TOP_KS:
            top = order[:top_k]
            row_metrics[f"target_in_top_{top_k}"] = float(target_rank <= top_k)
            row_metrics[f"precision_at_{top_k}"] = float(np.mean(relevant[top]))
            row_metrics[f"has_relevant_at_{top_k}"] = float(np.any(relevant[top]))
            row_metrics[f"mean_true_weight_delta_at_{top_k}"] = float(np.mean(np.abs(weights[top] - query_weight)))
            row_metrics[f"mean_true_height_delta_at_{top_k}"] = float(np.mean(np.abs(heights[top] - query_height)))
        for bucket, mask in buckets.items():
            if mask[query_idx]:
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
    ranked_all = sorted(strategies, key=lambda item: item["slices"]["all"]["precision_at_50"], reverse=True)
    ranked_211 = sorted(
        [item for item in strategies if "gte_211" in item["slices"]],
        key=lambda item: item["slices"]["gte_211"]["precision_at_50"],
        reverse=True,
    )
    lines = [
        "# Catalog Measurement Search Evaluation",
        "",
        "## Dataset",
        "",
        f"- Train rows used to fit inference models: {report['rows_train']:,}",
        f"- Held-out catalog/query rows: {report['rows_catalog']:,}",
        f"- PCA dimensions: {report['embedding_info']['pca_dims']}",
        "",
        "## What This Simulates",
        "",
        "Users input measurements to search the image database. This evaluation treats held-out catalog images as if their weights were missing, assigns inferred catalog weights, then checks whether those images and nearby measurement matches rank well for measurement-based searches.",
        "",
        "## Overall Catalog Search",
        "",
        "| Rank | Strategy | Target in Top 50 | P@50 | Mean Weight Delta@50 | Mean Height Delta@50 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for idx, item in enumerate(ranked_all, start=1):
        values = item["slices"]["all"]
        lines.append(
            f"| {idx} | `{item['strategy']}` | {values['target_in_top_50']} | {values['precision_at_50']} | "
            f"{values['mean_true_weight_delta_at_50']} | {values['mean_true_height_delta_at_50']} |"
        )
    lines.extend(
        [
            "",
            "## 211+ Catalog Search",
            "",
            "| Rank | Strategy | Target in Top 50 | P@50 | Mean Weight Delta@50 | Mean Height Delta@50 |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for idx, item in enumerate(ranked_211, start=1):
        values = item["slices"]["gte_211"]
        lines.append(
            f"| {idx} | `{item['strategy']}` | {values['target_in_top_50']} | {values['precision_at_50']} | "
            f"{values['mean_true_weight_delta_at_50']} | {values['mean_true_height_delta_at_50']} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "The oracle strategy uses the held-out catalog image's true weight and is only an upper bound.",
            "Precision@K means the share of top-K returned catalog images within +/-30 lbs and +/-3 inches of the measurement query.",
            "Target-in-top-K asks whether the exact held-out catalog image that generated the synthetic query appears in the top K.",
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
    catalog = frame[frame["split"].eq("test")].copy().reset_index(drop=True)
    pc_cols = [column for column in frame.columns if column.startswith("clip_pc_")]
    numeric = pc_cols + ["height_in"]
    preds = fit_catalog_predictions(train, catalog, numeric)
    strategies = [
        "height_size_only",
        "global_point",
        "weighted_global_point",
        "two_stage_blend_point",
        "two_stage_candidate_boost",
        "height_size_global_weight_boost",
        "height_size_two_stage_weight_boost",
        "height_size_weighted_global_boost",
        "oracle_true_weight",
    ]
    report = {
        "embedding_info": embedding_info,
        "rows_train": int(len(train)),
        "rows_catalog": int(len(catalog)),
        "strategies": [evaluate_strategy(strategy, catalog, preds) for strategy in strategies],
        "strategy_notes": {
            "height_size_only": "Search without inferred catalog weight.",
            "global_point": "Search with global inferred catalog weight.",
            "weighted_global_point": "Search with inverse-bin weighted inferred catalog weight.",
            "two_stage_blend_point": "Search with logistic 211+ probability blend of global and specialist catalog weights.",
            "two_stage_candidate_boost": "Use blended catalog weight for likely 211+ catalog images when it improves query distance.",
            "height_size_global_weight_boost": "Keep height/size primary and use global inferred catalog weight as a light ranking boost.",
            "height_size_two_stage_weight_boost": "Keep height/size primary and use two-stage blended catalog weight as a light ranking boost.",
            "height_size_weighted_global_boost": "Keep height/size primary and use weighted global catalog weight as a light ranking boost.",
            "oracle_true_weight": "Upper bound using held-out true catalog weight.",
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_summary(report, args.summary)
    print(json.dumps({"report": str(args.report), "summary": str(args.summary)}, indent=2))


if __name__ == "__main__":
    main()
