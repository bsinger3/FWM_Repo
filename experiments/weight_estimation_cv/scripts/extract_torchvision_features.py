#!/usr/bin/env python3
"""Extract pretrained torchvision image features for the evaluation sample."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
os.environ.setdefault("TORCH_HOME", str(REPO_ROOT / "experiments/weight_estimation_cv/cache/torch"))
os.environ.setdefault("HF_HOME", str(REPO_ROOT / "experiments/weight_estimation_cv/cache/huggingface"))

import numpy as np
import torch
from PIL import Image
from torch import nn
from torchvision.models import (
    EfficientNet_B0_Weights,
    MobileNet_V3_Small_Weights,
    ResNet18_Weights,
    efficientnet_b0,
    mobilenet_v3_small,
    resnet18,
)
from tqdm import tqdm


DEFAULT_INPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/eval_sample_with_images.csv"
DEFAULT_FEATURE_DIR = REPO_ROOT / "experiments/weight_estimation_cv/data/features"
DEFAULT_REPORT = REPO_ROOT / "experiments/weight_estimation_cv/reports/torchvision_feature_summary.json"


MODEL_BUILDERS = {
    "resnet18": (resnet18, ResNet18_Weights.IMAGENET1K_V1, "fc"),
    "mobilenet_v3_small": (mobilenet_v3_small, MobileNet_V3_Small_Weights.IMAGENET1K_V1, "classifier"),
    "efficientnet_b0": (efficientnet_b0, EfficientNet_B0_Weights.IMAGENET1K_V1, "classifier"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--feature-dir", type=Path, default=DEFAULT_FEATURE_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--models", nargs="+", default=list(MODEL_BUILDERS))
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--device", default="auto")
    return parser.parse_args()


def choose_device(requested: str) -> torch.device:
    if requested != "auto":
        return torch.device(requested)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def read_rows(path: Path, limit: int) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row.get("download_status") in {"downloaded", "cached"} and Path(row.get("local_image_path", "")).exists()
        ]
    return rows[:limit] if limit else rows


def build_model(name: str, device: torch.device):
    if name not in MODEL_BUILDERS:
        raise ValueError(f"Unsupported model: {name}")
    builder, weights, head_attr = MODEL_BUILDERS[name]
    model = builder(weights=weights)
    if head_attr == "fc":
        model.fc = nn.Identity()
    elif head_attr == "classifier":
        model.classifier = nn.Identity()
    model.eval().to(device)
    return model, weights.transforms()


def load_batch(rows: list[dict[str, str]], transform) -> tuple[torch.Tensor, list[str], list[str]]:
    tensors = []
    row_ids = []
    errors = []
    for row in rows:
        try:
            with Image.open(row["local_image_path"]) as image:
                tensors.append(transform(image.convert("RGB")))
                row_ids.append(row["row_id"])
        except Exception as exc:
            errors.append(f"{row.get('row_id')}: {type(exc).__name__}: {str(exc)[:100]}")
    if not tensors:
        return torch.empty(0), row_ids, errors
    return torch.stack(tensors), row_ids, errors


def extract_for_model(name: str, rows: list[dict[str, str]], args: argparse.Namespace, device: torch.device) -> dict[str, object]:
    model, transform = build_model(name, device)
    all_features = []
    all_row_ids = []
    errors = []
    with torch.inference_mode():
        for start in tqdm(range(0, len(rows), args.batch_size), desc=name):
            batch_rows = rows[start : start + args.batch_size]
            batch, row_ids, batch_errors = load_batch(batch_rows, transform)
            errors.extend(batch_errors)
            if batch.numel() == 0:
                continue
            output = model(batch.to(device))
            if output.ndim > 2:
                output = torch.flatten(output, start_dim=1)
            all_features.append(output.detach().cpu().numpy().astype("float32"))
            all_row_ids.extend(row_ids)

    features = np.concatenate(all_features, axis=0) if all_features else np.empty((0, 0), dtype="float32")
    out_path = args.feature_dir / f"{name}_features.npz"
    np.savez_compressed(out_path, row_ids=np.array(all_row_ids), features=features)
    return {
        "model": name,
        "rows": len(all_row_ids),
        "feature_dim": int(features.shape[1]) if features.ndim == 2 and features.size else 0,
        "errors": errors[:20],
        "output": str(out_path),
    }


def main() -> None:
    args = parse_args()
    args.feature_dir.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    rows = read_rows(args.input, args.limit)
    device = choose_device(args.device)
    summaries = []
    for name in args.models:
        summaries.append(extract_for_model(name, rows, args, device))
    payload = {"input": str(args.input), "device": str(device), "candidate_rows": len(rows), "models": summaries}
    args.report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
