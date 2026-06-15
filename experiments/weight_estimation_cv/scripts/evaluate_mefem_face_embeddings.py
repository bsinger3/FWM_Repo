#!/usr/bin/env python3
"""Evaluate MeFEm face embeddings with FWM-trained regressors."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault(
    "HF_HOME",
    str(Path(__file__).resolve().parents[1] / "cache/huggingface"),
)
os.environ.setdefault(
    "XDG_CACHE_HOME",
    str(Path(__file__).resolve().parents[1] / "cache"),
)

import cv2
import numpy as np
import pandas as pd
import timm
import torch
from huggingface_hub import hf_hub_download
from PIL import Image
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from torchvision import transforms as T
from tqdm import tqdm


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = EXPERIMENT_ROOT / "data/eval_sample_with_quality_tags.csv"
DEFAULT_WEIGHTS = EXPERIMENT_ROOT / "models/mefem/MeFEm-S.pth.tar"
DEFAULT_EMBEDDINGS = EXPERIMENT_ROOT / "data/features/mefem_s_face_embeddings.npz"
DEFAULT_ROWS = EXPERIMENT_ROOT / "data/mefem_s_face_embedding_rows.csv"
DEFAULT_REPORT = EXPERIMENT_ROOT / "reports/mefem_s_face_embedding_metrics.json"
DEFAULT_BASELINES = EXPERIMENT_ROOT / "reports/subset_baseline_metrics.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--rows", type=Path, default=DEFAULT_ROWS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--baselines", type=Path, default=DEFAULT_BASELINES)
    parser.add_argument("--download-weights", action="store_true")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def ensure_weights(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    downloaded = hf_hub_download(repo_id="boretsyury/MeFEm", filename="MeFEm-S.pth.tar", local_dir=str(path.parent))
    if Path(downloaded) != path:
        Path(downloaded).replace(path)


def load_model(weights_path: Path, device: str) -> torch.nn.Module:
    model = timm.create_model("vit_small_patch16_224", pretrained=False, num_classes=0, global_pool="token")
    state = torch.load(weights_path, map_location=device)
    model.load_state_dict(state)
    model.to(device)
    model.eval()
    return model


def face_cascade() -> cv2.CascadeClassifier:
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(str(cascade_path))
    if cascade.empty():
        raise RuntimeError(f"Could not load OpenCV face cascade at {cascade_path}")
    return cascade


def crop_largest_face(path: Path, cascade: cv2.CascadeClassifier, padding: float = 0.55) -> tuple[Image.Image | None, str]:
    image = cv2.imread(str(path))
    if image is None:
        return None, "read_failed"
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5, minSize=(24, 24))
    if len(faces) == 0:
        return None, "no_face_on_second_pass"
    x, y, w, h = sorted(faces, key=lambda box: box[2] * box[3], reverse=True)[0]
    pad_x = int(w * padding)
    pad_y = int(h * padding)
    image_h, image_w = image.shape[:2]
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(image_w, x + w + pad_x)
    y2 = min(image_h, y + h + pad_y)
    crop = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
    return Image.fromarray(crop), "ok"


def extract_embeddings(args: argparse.Namespace) -> tuple[pd.DataFrame, np.ndarray]:
    if args.embeddings.exists() and args.rows.exists() and not args.limit:
        rows = pd.read_csv(args.rows)
        matrix = np.load(args.embeddings)["embeddings"]
        return rows, matrix

    if args.download_weights:
        ensure_weights(args.weights)
    if not args.weights.exists():
        raise FileNotFoundError(f"Missing weights: {args.weights}. Re-run with --download-weights.")

    df = pd.read_csv(args.input)
    work = df[df["is_downloaded_image"].astype(bool) & df["face_visible"].astype(bool)].copy()
    if args.limit:
        work = work.head(args.limit).copy()

    transform = T.Compose(
        [
            T.Resize((224, 224)),
            T.ToTensor(),
            T.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
        ]
    )
    cascade = face_cascade()
    model = load_model(args.weights, args.device)

    row_records: list[dict[str, object]] = []
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

    for _, row in tqdm(work.iterrows(), total=len(work), desc="MeFEm-S crops"):
        crop, status = crop_largest_face(Path(str(row["local_image_path"])), cascade)
        if crop is None:
            row_records.append({**row.to_dict(), "mefem_status": status, "embedding_index": -1})
            continue
        row_records.append({**row.to_dict(), "mefem_status": status, "embedding_index": len(embeddings) + len(tensors)})
        tensors.append(transform(crop.convert("RGB")))
        if len(tensors) >= args.batch_size:
            flush_batch()
    flush_batch()

    rows = pd.DataFrame(row_records)
    ok_rows = rows[rows["embedding_index"] >= 0].copy()
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
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    for item in payload.get("subsets", []):
        if item.get("subset") == subset and item.get("results"):
            return sorted(item["results"], key=lambda row: row["mae_lbs"])[0]
    return None


def build_frame(rows: pd.DataFrame, embeddings: np.ndarray) -> pd.DataFrame:
    emb_cols = [f"emb_{idx:03d}" for idx in range(embeddings.shape[1])]
    emb_df = pd.DataFrame(embeddings, columns=emb_cols)
    meta = rows.reset_index(drop=True).copy()
    return pd.concat([meta, emb_df], axis=1)


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


def evaluate_regressors(rows: pd.DataFrame, embeddings: np.ndarray, args: argparse.Namespace) -> dict[str, object]:
    frame = build_frame(rows, embeddings)
    for column in ["height_in", "weight_lbs", "bmi"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in ["size_display", "clothing_type_id", "source_site_display", "image_quality_bucket"]:
        frame[column] = frame[column].fillna("").astype(str)

    train = frame[frame["split"] == "train"].copy()
    test = frame[frame["split"] == "test"].copy()
    emb_cols = [column for column in frame.columns if column.startswith("emb_")]
    categorical = ["size_display", "clothing_type_id", "source_site_display", "image_quality_bucket"]

    specs = []
    for target in ["bmi", "weight_lbs"]:
        specs.extend(
            [
                (f"ridge_mefem_s_embedding_predict_{target}", emb_cols, [], Ridge(alpha=50.0), target),
                (f"ridge_mefem_s_embedding_height_predict_{target}", emb_cols + ["height_in"], [], Ridge(alpha=50.0), target),
                (
                    f"ridge_mefem_s_embedding_height_metadata_predict_{target}",
                    emb_cols + ["height_in"],
                    categorical,
                    Ridge(alpha=50.0),
                    target,
                ),
                (
                    f"elasticnet_mefem_s_embedding_height_metadata_predict_{target}",
                    emb_cols + ["height_in"],
                    categorical,
                    ElasticNet(alpha=0.05, l1_ratio=0.15, max_iter=5000, random_state=20260609),
                    target,
                ),
            ]
        )

    # Tree models use a PCA-free dense numeric representation but skip sparse one-hot metadata.
    specs.extend(
        [
            (
                "random_forest_mefem_s_embedding_height_predict_bmi",
                emb_cols + ["height_in"],
                [],
                RandomForestRegressor(n_estimators=300, min_samples_leaf=8, random_state=20260609, n_jobs=-1),
                "bmi",
            ),
            (
                "hist_gradient_mefem_s_embedding_height_predict_bmi",
                emb_cols + ["height_in"],
                [],
                HistGradientBoostingRegressor(max_iter=200, min_samples_leaf=12, random_state=20260609),
                "bmi",
            ),
        ]
    )

    results = []
    for model_name, numeric, categorical_cols, estimator, target in specs:
        model = Pipeline([("prep", preprocessor(numeric, categorical_cols)), ("model", estimator)])
        results.append(evaluate_one(model_name, model, train, test, numeric + categorical_cols, target))

    return {
        "model": "boretsyury/MeFEm MeFEm-S embeddings + FWM regressors",
        "weights_path": str(args.weights),
        "input": str(args.input),
        "embeddings": str(args.embeddings),
        "rows_file": str(args.rows),
        "rows": int(len(frame)),
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "status_counts": rows["mefem_status"].value_counts(dropna=False).to_dict(),
        "baseline_face_visible": best_baseline(args.baselines, "face_visible"),
        "results": sorted(results, key=lambda item: item["mae_lbs"]),
    }


def main() -> None:
    args = parse_args()
    rows, embeddings = extract_embeddings(args)
    report = evaluate_regressors(rows, embeddings, args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
