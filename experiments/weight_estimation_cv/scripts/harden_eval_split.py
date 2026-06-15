#!/usr/bin/env python3
"""Add stable IDs, duplicate diagnostics, and a hardened split snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/eval_sample_with_images.csv"
DEFAULT_OUTPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/eval_sample_hardened.csv"
DEFAULT_REPORT = REPO_ROOT / "experiments/weight_estimation_cv/reports/split_hygiene_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def sha1_text(value: str, length: int = 16) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def file_sha1(path_value: object) -> str:
    path = Path(str(path_value or ""))
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def average_hash(path_value: object, hash_size: int = 8) -> str:
    path = Path(str(path_value or ""))
    if not path.exists() or not path.is_file():
        return ""
    try:
        with Image.open(path) as image:
            image = image.convert("L").resize((hash_size, hash_size))
            pixels = list(image.getdata())
    except Exception:
        return ""
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= avg else "0" for pixel in pixels)
    return f"{int(bits, 2):0{hash_size * hash_size // 4}x}"


def host(url: object) -> str:
    return urlsplit(str(url or "")).netloc.lower()


def split_leak_count(df: pd.DataFrame, column: str) -> int:
    if column not in df:
        return 0
    values = df[df[column].fillna("").astype(str) != ""].groupby(column)["split"].nunique()
    return int((values > 1).sum())


def duplicate_summary(df: pd.DataFrame, column: str) -> dict[str, int]:
    if column not in df:
        return {"groups": 0, "rows": 0, "cross_split_groups": 0}
    usable = df[df[column].fillna("").astype(str) != ""]
    counts = usable[column].value_counts()
    duplicate_values = counts[counts > 1].index
    duplicate_rows = usable[usable[column].isin(duplicate_values)]
    return {
        "groups": int(len(duplicate_values)),
        "rows": int(len(duplicate_rows)),
        "cross_split_groups": split_leak_count(duplicate_rows, column),
    }


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input)

    if "row_id" not in df:
        df["row_id"] = [
            sha1_text(f"{row.image_url}|{row.height_in}|{row.weight_lbs}|{index}", 20)
            for index, row in enumerate(df.itertuples(index=False))
        ]

    df["stable_image_url_id"] = df["image_url"].fillna("").astype(str).map(lambda value: sha1_text(value, 20))
    df["stable_eval_row_id"] = [
        sha1_text(f"{row.row_id}|{row.image_url}|{row.height_in}|{row.weight_lbs}", 24)
        for row in df.itertuples(index=False)
    ]
    df["image_host_hardened"] = df["image_url"].map(host)
    df["is_downloaded_image"] = df["download_status"].isin(["downloaded", "cached"])
    df["image_file_sha1"] = df["local_image_path"].map(file_sha1)
    df["image_average_hash"] = df["local_image_path"].map(average_hash)

    exact_key_cols = [column for column in ["image_url", "height_in", "weight_lbs"] if column in df]
    exact_duplicate_rows = int(df.duplicated(subset=exact_key_cols, keep=False).sum()) if exact_key_cols else 0

    downloaded = df[df["is_downloaded_image"]].copy()
    report = {
        "input": str(args.input),
        "output": str(args.output),
        "rows": int(len(df)),
        "downloaded_rows": int(len(downloaded)),
        "train_rows": int((df["split"] == "train").sum()),
        "test_rows": int((df["split"] == "test").sum()),
        "exact_url_height_weight_duplicate_rows": exact_duplicate_rows,
        "duplicates": {
            "image_url": duplicate_summary(df, "image_url"),
            "image_file_sha1": duplicate_summary(downloaded, "image_file_sha1"),
            "image_average_hash": duplicate_summary(downloaded, "image_average_hash"),
            "row_id": duplicate_summary(df, "row_id"),
        },
        "cross_split_leaks": {
            "image_url": split_leak_count(df, "image_url"),
            "image_file_sha1": split_leak_count(downloaded, "image_file_sha1"),
            "image_average_hash": split_leak_count(downloaded, "image_average_hash"),
            "row_id": split_leak_count(df, "row_id"),
        },
        "split_download_status": (
            df.groupby(["split", "download_status"]).size().unstack(fill_value=0).to_dict(orient="index")
        ),
        "hosts_top_20": df["image_host_hardened"].value_counts().head(20).to_dict(),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
