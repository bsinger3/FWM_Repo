#!/usr/bin/env python3
"""Build a broader LLM-seeded reason-labeling queue from Amazon + non-Amazon rows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from experiment_image_quality_baseline import larger_image_url_candidates, quality_metrics  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[4]
PIPELINE_SCRIPTS_DIR = REPO_ROOT / "data-pipelines" / "scripts"
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, cv_annotated_pending_human_review_root, raw_scraped_data_root  # noqa: E402

LEGACY_OUTPUTS_ARCHIVE = archive_root() / "old_outputs" / "repo_outputs_archive" / "supabase_output_cleanup_2026_05_29"
CV_EXPERIMENTS_DIR = LEGACY_OUTPUTS_ARCHIVE / "cv_experiments"

PROJECT_ROOT = REPO_ROOT.parent
DATA_ROOT = PROJECT_ROOT / "FWM_Data"
NON_AMAZON_ROOT = raw_scraped_data_root()
AMAZON_STEP4 = cv_annotated_pending_human_review_root() / "amazon_legacy_step_4_human_review_and_visibility_decisions"
PREVIOUS_LABELS = CV_EXPERIMENTS_DIR / "ground_truth_labeling/labeled_image_rejection_reason_queue.csv"
PREVIOUS_LABELS_NEXT = CV_EXPERIMENTS_DIR / "ground_truth_labeling_next/llm_seeded_ground_truth_queue.csv"
OUT_DIR = CV_EXPERIMENTS_DIR / "ground_truth_labeling_broad"
DEFAULT_ENV_PATH = REPO_ROOT / ".env"

TARGET_LABELS = [
    "LOW_RESOLUTION",
    "TOO_BRIGHT_OR_WASHED_OUT",
    "BLURRY_OR_MOTION_BLUR",
    "GRAINY_OR_NOISY",
    "GARMENT_CUT_OFF",
    "TARGET_WEARER_AMBIGUOUS",
    "PERSON_TOO_FAR",
]

SYSTEM_PROMPT = """You are helping seed a ground-truth labeling queue for a clothing fit-photo quality system.

You are not making the final label. You are identifying whether an image is a promising candidate for sparse rejection-reason labels that need more human-labeled examples.

Only use the visual image. Do not reject or label based on product category mismatch.

Candidate labels:
- LOW_RESOLUTION: visibly tiny, pixelated, or heavily compressed.
- TOO_BRIGHT_OR_WASHED_OUT: overexposed or washed out enough to hurt fit evaluation.
- BLURRY_OR_MOTION_BLUR: blurred enough to hurt fit evaluation.
- GRAINY_OR_NOISY: heavy image noise/grain enough to hurt fit evaluation.
- GARMENT_CUT_OFF: the relevant worn clothing/fit view is materially cut off by the image boundary.
- TARGET_WEARER_AMBIGUOUS: multiple people are visible and it is unclear whose garment/fit should be evaluated.
- PERSON_TOO_FAR: the person/garment is too small or distant for fit evaluation.

Return JSON only. Be generous about candidates: if the image might be useful for human labeling as a positive example, include the label. If none apply, return an empty labels array.
"""


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def read_rows(path: Path) -> List[Dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))
    except UnicodeDecodeError:
        with path.open(newline="", encoding="latin-1") as handle:
            return list(csv.DictReader(handle))


def known_keys() -> set[str]:
    keys: set[str] = set()
    for path in [PREVIOUS_LABELS, PREVIOUS_LABELS_NEXT]:
        if not path.exists():
            continue
        for row in read_rows(path):
            if row.get("review_row_key"):
                keys.add(row["review_row_key"])
            if row.get("original_url_display"):
                keys.add("url::" + row["original_url_display"])
    return keys


def nonempty(row: Dict[str, str], columns: Iterable[str]) -> bool:
    return any(str(row.get(column, "") or "").strip() for column in columns)


def is_supabase_qualified(row: Dict[str, str]) -> bool:
    if not str(row.get("original_url_display", "") or "").strip():
        return False
    if not str(row.get("product_page_url_display", "") or "").strip():
        return False
    size_cols = ["size_display", "size_ordered_raw_display", "size_ordered_norm", "product_variant_raw"]
    measurement_cols = [
        "height_raw",
        "height_in_display",
        "weight_raw",
        "weight_display_display",
        "weight_lbs_display",
        "weight_lb",
        "waist_raw_display",
        "waist_in",
        "hips_raw",
        "hips_in_display",
        "bust_in_display",
        "bust_in_number_display",
        "bra_band_in_display",
        "inseam_inches_display",
        "age_raw",
        "age_years_display",
    ]
    return nonempty(row, size_cols) or nonempty(row, measurement_cols)


def normalize_non_amazon_row(path: Path, row_number: int, row: Dict[str, str]) -> Optional[Dict[str, str]]:
    if not is_supabase_qualified(row):
        return None
    image_source_type = str(row.get("image_source_type", "") or "").lower()
    image_source_detail = str(row.get("image_source_detail", "") or "").lower()
    if "catalog" in image_source_type or "catalog" in image_source_detail:
        return None
    source_site = row.get("source_site_display", "") or path.parent.name
    row_id = row.get("id", "") or f"{path.stem}::{row_number}"
    return {
        "source_pool": "non_amazon_supabase_qualified",
        "source_file": str(path),
        "source_site_display": source_site,
        "review_row_key": f"nonamazon::{path.parent.name}::{row_id}",
        "original_url_display": row.get("original_url_display", ""),
        "product_page_url_display": row.get("product_page_url_display", ""),
        "existing_manual_label": "",
        "existing_manual_reason": "",
        "user_comment": row.get("user_comment", ""),
        "height_raw": row.get("height_raw", ""),
        "weight_raw": row.get("weight_raw", ""),
        "size_display": row.get("size_display", "") or row.get("size_ordered_raw_display", "") or row.get("product_variant_raw", ""),
        "clothing_type_id": row.get("clothing_type_id", ""),
        "product_title_raw": row.get("product_title_raw", ""),
        "image_source_type": row.get("image_source_type", ""),
        "is_supabase_qualified": "TRUE",
    }


def normalize_amazon_step4_row(path: Path, row_number: int, row: Dict[str, str]) -> Optional[Dict[str, str]]:
    image_url = row.get("original_url_display", "")
    product_url = row.get("product_page_url_display", "")
    if not image_url or not product_url:
        return None
    manual_label = row.get("Manual_approval(1=approved,2=reject, 3=ApprovedANDLabel'Pretty\")", "")
    if manual_label not in {"", "2"}:
        return None
    key = row.get("review_row_key") or f"{path.name}::{row_number}"
    return {
        "source_pool": "amazon_step4_remaining",
        "source_file": str(path),
        "source_site_display": "amazon.com",
        "review_row_key": f"amazon::{key}",
        "original_url_display": image_url,
        "product_page_url_display": product_url,
        "existing_manual_label": manual_label,
        "existing_manual_reason": row.get("Rejection Reason_Manual", ""),
        "user_comment": row.get("user_comment", ""),
        "height_raw": row.get("height_raw", ""),
        "weight_raw": row.get("weight_raw", ""),
        "size_display": row.get("size_display", ""),
        "clothing_type_id": row.get("clothing_type_id", ""),
        "product_title_raw": "",
        "image_source_type": "customer_review_image",
        "is_supabase_qualified": "",
        "person_count_yolo_detect": row.get("person_count_yolo_detect", ""),
        "main_person_height_pct_yolo_detect": row.get("main_person_height_pct_yolo_detect", ""),
        "main_person_bbox_area_pct_yolo_detect": row.get("main_person_bbox_area_pct_yolo_detect", ""),
        "body_coverage_score_yolo_pose": row.get("body_coverage_score_yolo_pose", ""),
        "cv_reason_code": row.get("cv_reason_code", ""),
    }


def collect_pool(max_non_amazon_per_file: int, max_amazon: int, seed: int) -> List[Dict[str, str]]:
    rng = random.Random(seed)
    seen = known_keys()
    candidates: List[Dict[str, str]] = []

    for path in sorted(NON_AMAZON_ROOT.glob("**/*reviews_matching_*schema.csv")):
        rows = read_rows(path)
        normalized = [
            item
            for idx, row in enumerate(rows, start=2)
            if (item := normalize_non_amazon_row(path, idx, row)) is not None
        ]
        rng.shuffle(normalized)
        for row in normalized[:max_non_amazon_per_file]:
            if row["review_row_key"] in seen or "url::" + row["original_url_display"] in seen:
                continue
            seen.add(row["review_row_key"])
            seen.add("url::" + row["original_url_display"])
            candidates.append(row)

    amazon_paths = [
        AMAZON_STEP4 / "part_002_REVIEWED.csv",
        *sorted((AMAZON_STEP4 / "manual_chunks").glob("images_to_approve_part_*.csv")),
    ]
    amazon_rows: List[Dict[str, str]] = []
    for path in amazon_paths:
        if not path.exists():
            continue
        for idx, row in enumerate(read_rows(path), start=2):
            normalized = normalize_amazon_step4_row(path, idx, row)
            if normalized:
                amazon_rows.append(normalized)
    rng.shuffle(amazon_rows)
    for row in amazon_rows[:max_amazon]:
        if row["review_row_key"] in seen or "url::" + row["original_url_display"] in seen:
            continue
        seen.add(row["review_row_key"])
        seen.add("url::" + row["original_url_display"])
        candidates.append(row)
    return candidates


def fetch_image(url: str, timeout: float) -> tuple[Optional[object], Dict[str, object]]:
    from PIL import Image

    last_error = ""
    for candidate in larger_image_url_candidates(url):
        try:
            request = Request(candidate, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=timeout) as response:
                data = response.read()
            image = Image.open(BytesIO(data)).convert("RGB")
            return image, {
                "fetch_ok": True,
                "selected_url": candidate,
                "url_was_upgraded": candidate != url,
                "bytes_loaded": len(data),
            }
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = repr(exc)
    return None, {"fetch_ok": False, "fetch_error": last_error}


def add_quality_fields(rows: List[Dict[str, object]], max_fetch: int, timeout: float) -> None:
    for index, row in enumerate(rows[:max_fetch], start=1):
        image, fetch = fetch_image(str(row.get("original_url_display", "")), timeout)
        row.update(fetch)
        if image is not None:
            row.update(quality_metrics(image))
        row["quality_candidate_tags"] = ";".join(quality_tags(row))
        if index % 100 == 0:
            print(f"quality checked {index}/{min(len(rows), max_fetch)}", flush=True)


def as_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except ValueError:
        return default


def quality_tags(row: Dict[str, object]) -> List[str]:
    tags: List[str] = []
    if row.get("fetch_ok") is False:
        return ["INVALID_OR_DEAD_IMAGE_URL"]
    if row.get("fetch_ok") is not True:
        return []
    width = as_float(row.get("width"))
    height = as_float(row.get("height"))
    pixels = as_float(row.get("pixels"))
    lum = as_float(row.get("luminance_mean"), 999)
    bright = as_float(row.get("bright_pixel_pct"))
    blur = as_float(row.get("laplacian_variance"), 999999)
    contrast = as_float(row.get("contrast_std"), 999)
    if width and height and (min(width, height) < 360 or pixels < 250_000):
        tags.append("LOW_RESOLUTION")
    if bright > 0.12 or lum > 220:
        tags.append("TOO_BRIGHT_OR_WASHED_OUT")
    if blur < 70:
        tags.append("BLURRY_OR_MOTION_BLUR")
    if blur < 120 and contrast < 35:
        tags.append("GRAINY_OR_NOISY")
    return tags


def heuristic_tags(row: Dict[str, object]) -> List[str]:
    tags = list(quality_tags(row))
    height = as_float(row.get("main_person_height_pct_yolo_detect"))
    area = as_float(row.get("main_person_bbox_area_pct_yolo_detect"))
    coverage = as_float(row.get("body_coverage_score_yolo_pose"))
    if height and height < 0.70:
        tags.append("PERSON_TOO_FAR")
    if area and area < 0.30:
        tags.append("PERSON_TOO_FAR")
    if coverage and coverage <= 66.7:
        tags.append("GARMENT_CUT_OFF")
    return list(dict.fromkeys(tag for tag in tags if tag in TARGET_LABELS))


def score_row(row: Dict[str, object]) -> float:
    tags = heuristic_tags(row)
    score = 10.0 * len(tags)
    if row.get("source_pool") == "non_amazon_supabase_qualified":
        score += 8
    if row.get("existing_manual_label") == "2":
        score += 12
    if not row.get("existing_manual_reason"):
        score += 3
    if row.get("fetch_ok") is False:
        score -= 20
    return round(score, 3)


def select_for_llm(rows: List[Dict[str, object]], limit: int) -> List[Dict[str, object]]:
    for row in rows:
        row["candidate_heuristic_tags"] = ";".join(heuristic_tags(row))
        row["candidate_score"] = score_row(row)
    buckets: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        tags = heuristic_tags(row)
        if not tags:
            buckets["NO_HEURISTIC_TAG"].append(row)
        for tag in tags:
            buckets[tag].append(row)
    selected: List[Dict[str, object]] = []
    seen = set()
    per_label = max(10, limit // len(TARGET_LABELS))
    for label in TARGET_LABELS:
        for row in sorted(buckets.get(label, []), key=lambda r: float(r["candidate_score"]), reverse=True)[:per_label]:
            key = row["review_row_key"]
            if key not in seen:
                selected.append(row)
                seen.add(key)
    remaining = [row for row in sorted(rows, key=lambda r: float(r["candidate_score"]), reverse=True) if row["review_row_key"] not in seen]
    selected.extend(remaining[: max(0, limit - len(selected))])
    return selected[:limit]


def build_payload(model: str, row: Dict[str, object]) -> Dict[str, object]:
    metadata = {
        "source_pool": row.get("source_pool", ""),
        "source_site_display": row.get("source_site_display", ""),
        "candidate_heuristic_tags": row.get("candidate_heuristic_tags", ""),
        "quality_metrics": {
            "width": row.get("width", ""),
            "height": row.get("height", ""),
            "luminance_mean": row.get("luminance_mean", ""),
            "bright_pixel_pct": row.get("bright_pixel_pct", ""),
            "laplacian_variance": row.get("laplacian_variance", ""),
        },
        "product_title_raw": row.get("product_title_raw", ""),
        "user_comment": str(row.get("user_comment", ""))[:1000],
    }
    return {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": json.dumps(metadata, ensure_ascii=False)},
                    {"type": "input_image", "image_url": row.get("original_url_display", ""), "detail": "low"},
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "candidate_labels",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "labels": {"type": "array", "items": {"type": "string", "enum": TARGET_LABELS}},
                        "summary": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["labels", "summary", "confidence"],
                },
                "strict": True,
            }
        },
        "max_output_tokens": 250,
    }


def extract_response_text(response_json: Dict[str, object]) -> str:
    output_text = response_json.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    text_parts: List[str] = []
    for output in response_json.get("output", []) or []:
        if isinstance(output, dict):
            for part in output.get("content", []) or []:
                if isinstance(part, dict) and part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
    if text_parts:
        return "\n".join(text_parts).strip()
    raise ValueError("Could not extract response text")


def classify_candidate(api_key: str, model: str, row: Dict[str, object], timeout_seconds: int) -> Dict[str, object]:
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(build_payload(model, row)).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        response_json = json.loads(response.read().decode("utf-8"))
    parsed = json.loads(extract_response_text(response_json))
    usage = response_json.get("usage") if isinstance(response_json.get("usage"), dict) else {}
    return {
        "llm_candidate_labels": ";".join(parsed.get("labels") or []),
        "llm_candidate_summary": parsed.get("summary", ""),
        "llm_candidate_confidence": parsed.get("confidence", ""),
        "llm_request_status": "OK",
        "llm_input_tokens": usage.get("input_tokens", 0),
        "llm_output_tokens": usage.get("output_tokens", 0),
        "llm_error_message": "",
    }


def output_rows(rows: Sequence[Dict[str, object]], llm_results: Dict[str, Dict[str, object]]) -> List[Dict[str, object]]:
    output: List[Dict[str, object]] = []
    for row in rows:
        key = str(row["review_row_key"])
        llm = llm_results.get(key, {})
        llm_labels = str(llm.get("llm_candidate_labels", "") or "")
        likely = llm_labels or str(row.get("candidate_heuristic_tags", "") or "")
        out: Dict[str, object] = {
            "queue_priority": "BROAD_LLM_SEEDED_CANDIDATE",
            "source_pool": row.get("source_pool", ""),
            "source_site_display": row.get("source_site_display", ""),
            "is_supabase_qualified": row.get("is_supabase_qualified", ""),
            "review_row_key": key,
            "original_url_display": row.get("original_url_display", ""),
            "image_preview": f'=IMAGE("{row.get("original_url_display", "")}")',
            "product_page_url_display": row.get("product_page_url_display", ""),
            "existing_manual_label": row.get("existing_manual_label", ""),
            "existing_manual_reason": row.get("existing_manual_reason", ""),
            "candidate_heuristic_tags": row.get("candidate_heuristic_tags", ""),
            "candidate_score": row.get("candidate_score", ""),
            "llm_suggested_labels": llm_labels,
            "llm_summary": llm.get("llm_candidate_summary", ""),
            "llm_confidence": llm.get("llm_candidate_confidence", ""),
            "likely_label_to_check": likely,
            "width": row.get("width", ""),
            "height": row.get("height", ""),
            "luminance_mean": row.get("luminance_mean", ""),
            "bright_pixel_pct": row.get("bright_pixel_pct", ""),
            "laplacian_variance": row.get("laplacian_variance", ""),
            "user_comment": row.get("user_comment", ""),
            "product_title_raw": row.get("product_title_raw", ""),
            "final_human_decision": "",
            "primary_reason_code": "",
            "secondary_reason_code": "",
            "labeler_notes": "",
        }
        for label in TARGET_LABELS:
            out[label] = ""
        output.append(out)
    return output


def write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, rows: Sequence[Dict[str, object]], pool_rows: Sequence[Dict[str, object]], elapsed: float) -> None:
    llm_counts = Counter()
    heuristic_counts = Counter()
    source_counts = Counter(row.get("source_pool", "") for row in rows)
    pool_counts = Counter(row.get("source_pool", "") for row in pool_rows)
    for row in rows:
        for label in str(row.get("llm_suggested_labels", "") or "").split(";"):
            if label:
                llm_counts[label] += 1
        for label in str(row.get("candidate_heuristic_tags", "") or "").split(";"):
            if label:
                heuristic_counts[label] += 1
    lines = [
        "# Broad LLM-Seeded Ground Truth Queue",
        "",
        f"- elapsed seconds: `{elapsed:.1f}`",
        f"- broad pool rows scanned: `{len(pool_rows)}`",
        f"- queue rows: `{len(rows)}`",
        f"- pool source counts: `{dict(pool_counts)}`",
        f"- queue source counts: `{dict(source_counts)}`",
        "",
        "## LLM Suggested Label Counts",
        "",
        "| label | count |",
        "| --- | ---: |",
    ]
    for label in TARGET_LABELS:
        lines.append(f"| `{label}` | {llm_counts.get(label, 0)} |")
    lines.extend(["", "## Heuristic Seed Counts", "", "| label | count |", "| --- | ---: |"])
    for label in TARGET_LABELS:
        lines.append(f"| `{label}` | {heuristic_counts.get(label, 0)} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool-limit", type=int, default=900)
    parser.add_argument("--quality-fetch-limit", type=int, default=900)
    parser.add_argument("--llm-limit", type=int, default=180)
    parser.add_argument("--max-non-amazon-per-file", type=int, default=10)
    parser.add_argument("--max-amazon", type=int, default=250)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--image-timeout", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=20260520)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    load_env_file(DEFAULT_ENV_PATH)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        raise SystemExit("OPENAI_API_KEY is not set")

    start = time.perf_counter()
    pool = collect_pool(args.max_non_amazon_per_file, args.max_amazon, args.seed)[: args.pool_limit]
    add_quality_fields(pool, args.quality_fetch_limit, args.image_timeout)
    selected = select_for_llm(pool, args.llm_limit)

    llm_results: Dict[str, Dict[str, object]] = {}
    if args.dry_run:
        llm_results = {str(row["review_row_key"]): {"llm_candidate_labels": "", "llm_candidate_summary": "", "llm_candidate_confidence": ""} for row in selected}
    else:
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            future_to_row = {executor.submit(classify_candidate, api_key, args.model, row, args.timeout_seconds): row for row in selected}
            completed = 0
            for future in as_completed(future_to_row):
                row = future_to_row[future]
                key = str(row["review_row_key"])
                try:
                    llm_results[key] = future.result()
                except Exception as exc:  # noqa: BLE001
                    llm_results[key] = {
                        "llm_candidate_labels": "",
                        "llm_candidate_summary": "",
                        "llm_candidate_confidence": "",
                        "llm_request_status": "ERROR",
                        "llm_error_message": repr(exc),
                    }
                completed += 1
                if completed % 25 == 0:
                    print(f"llm classified {completed}/{len(selected)}", flush=True)

    rows = output_rows(selected, llm_results)
    write_csv(OUT_DIR / "broad_llm_seeded_ground_truth_queue.csv", rows)
    write_report(OUT_DIR / "broad_llm_seeded_ground_truth_queue_report.md", rows, pool, time.perf_counter() - start)
    print(f"Wrote {OUT_DIR}")


if __name__ == "__main__":
    main()
