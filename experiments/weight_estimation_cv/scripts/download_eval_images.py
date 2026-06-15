#!/usr/bin/env python3
"""Download evaluation images into the isolated experiment cache."""

from __future__ import annotations

import argparse
import csv
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/eval_sample.csv"
DEFAULT_IMAGE_DIR = REPO_ROOT / "experiments/weight_estimation_cv/cache/images"
DEFAULT_OUTPUT = REPO_ROOT / "experiments/weight_estimation_cv/data/eval_sample_with_images.csv"
DEFAULT_REPORT = REPO_ROOT / "experiments/weight_estimation_cv/reports/download_eval_images_summary.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--image-dir", type=Path, default=DEFAULT_IMAGE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_image(path: Path) -> tuple[bool, int, int, str]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return True, image.width, image.height, image.format or ""
    except Exception:
        return False, 0, 0, ""


def download_one(row: dict[str, str], image_dir: Path, timeout: float) -> dict[str, str]:
    out = dict(row)
    cache_file = image_dir / row["image_cache_file"]
    out["local_image_path"] = str(cache_file)
    out["download_status"] = "pending"
    out["download_error"] = ""
    out["image_width_downloaded"] = ""
    out["image_height_downloaded"] = ""
    out["image_format_downloaded"] = ""

    if cache_file.exists() and cache_file.stat().st_size > 0:
        ok, width, height, fmt = validate_image(cache_file)
        if ok:
            out.update(
                {
                    "download_status": "cached",
                    "image_width_downloaded": str(width),
                    "image_height_downloaded": str(height),
                    "image_format_downloaded": fmt,
                }
            )
            return out
        cache_file.unlink(missing_ok=True)

    url = str(row.get("image_url") or "").strip()
    if not url.startswith(("http://", "https://")):
        out["download_status"] = "failed"
        out["download_error"] = "invalid_url"
        return out

    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        if response.status_code >= 400:
            out["download_status"] = "failed"
            out["download_error"] = f"http_{response.status_code}"
            return out
        content_type = response.headers.get("content-type", "")
        if "image" not in content_type.lower() and len(response.content) < 1024:
            out["download_status"] = "failed"
            out["download_error"] = f"non_image_content_type:{content_type}"
            return out
        cache_file.write_bytes(response.content)
        ok, width, height, fmt = validate_image(cache_file)
        if not ok:
            cache_file.unlink(missing_ok=True)
            out["download_status"] = "failed"
            out["download_error"] = "invalid_image_bytes"
            return out
        out.update(
            {
                "download_status": "downloaded",
                "image_width_downloaded": str(width),
                "image_height_downloaded": str(height),
                "image_format_downloaded": fmt,
            }
        )
        return out
    except Exception as exc:
        out["download_status"] = "failed"
        out["download_error"] = f"{type(exc).__name__}:{str(exc)[:180]}"
        return out


def main() -> None:
    args = parse_args()
    rows = read_rows(args.input)
    if args.limit:
        rows = rows[: args.limit]
    args.image_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()
    output_rows: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(download_one, row, args.image_dir, args.timeout) for row in rows]
        for index, future in enumerate(as_completed(futures), start=1):
            output_rows.append(future.result())
            if index % 100 == 0:
                print(f"processed {index}/{len(futures)}")

    fieldnames = list(output_rows[0].keys()) if output_rows else []
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    status_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    for row in output_rows:
        status_counts[row["download_status"]] = status_counts.get(row["download_status"], 0) + 1
        if row["download_error"]:
            error_key = row["download_error"].split(":", 1)[0]
            error_counts[error_key] = error_counts.get(error_key, 0) + 1
    report = {
        "rows": len(output_rows),
        "status_counts": status_counts,
        "error_counts": error_counts,
        "elapsed_seconds": round(time.time() - start, 2),
        "output": str(args.output),
        "image_dir": str(args.image_dir),
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
