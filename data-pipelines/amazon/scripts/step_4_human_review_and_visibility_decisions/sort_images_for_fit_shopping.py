#!/usr/bin/env python3
"""First staged image sorter for fit-shopping usefulness.

This script turns the CV experiments into an end-to-end sorting pass. It is
intentionally conservative: objective URL/quality/geometry checks produce
actions directly, while semantic labels are routed to LLM or human review.
"""

from __future__ import annotations

import argparse
import csv
import time
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image, ImageStat


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_INPUT = REPO_ROOT / "outputs/cv_experiments/yolo_segmentation_crop_reasons_broad_2026_05_25/yolo_segmentation_crop_reason_rows.csv"
DEFAULT_OUT_DIR = REPO_ROOT / "outputs/cv_experiments/fit_image_sorter_2026_05_27"

OUTPUT_COLUMNS = [
    "review_row_key",
    "source_pool",
    "source_site_display",
    "is_supabase_qualified",
    "original_url_display",
    "sort_image_url",
    "raw_scraped_image_url",
    "url_repaired",
    "url_repair_attempted",
    "url_repair_candidate_count",
    "loaded_width",
    "loaded_height",
    "loaded_pixels",
    "sort_decision",
    "primary_action",
    "reason_codes",
    "confidence",
    "needs_human_review",
    "needs_llm_review",
    "needs_url_update",
    "crop_priority",
    "debug_summary",
    "product_page_url_display",
]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: Path, rows: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in OUTPUT_COLUMNS})


def unique(items: Iterable[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def replace_query_params(url: str, replacements: dict[str, str | None]) -> str:
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key in replacements:
            replacement = replacements[key]
            if replacement is None:
                continue
            query.append((key, replacement))
        else:
            query.append((key, value))
    existing = {key for key, _ in query}
    for key, value in replacements.items():
        if value is not None and key not in existing:
            query.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def larger_image_url_candidates(url: str) -> list[str]:
    candidates = [url]
    try:
        parts = urlsplit(url)
    except Exception:
        return candidates

    host = parts.netloc.lower()
    filename = parts.path.rsplit("/", 1)[-1]

    if ("media-amazon.com" in host or "images-amazon.com" in host) and "._" in filename:
        stem, _transform = filename.split("._", 1)
        extension = ""
        for candidate_extension in (".jpg", ".jpeg", ".png", ".webp"):
            if filename.lower().endswith(candidate_extension):
                extension = filename[-len(candidate_extension) :]
                break
        if extension:
            canonical_path = parts.path.rsplit("/", 1)[0] + "/" + stem + extension
            candidates.insert(0, urlunsplit((parts.scheme, parts.netloc, canonical_path, parts.query, parts.fragment)))

    if "imgix.net" in host:
        candidates.insert(0, replace_query_params(url, {"w": "1200", "h": None, "fit": None, "crop": None}))
        candidates.insert(0, replace_query_params(url, {"w": None, "h": None, "fit": None, "crop": None}))

    if "media-dynamic.okendo.io" in host:
        candidates.insert(0, replace_query_params(url, {"d": "1200x1200", "crop": None}))
        candidates.insert(0, replace_query_params(url, {"d": None, "crop": None}))

    if "judgeme" in host and "w=" in parts.query:
        candidates.insert(0, replace_query_params(url, {"w": "1200"}))
        candidates.insert(0, replace_query_params(url, {"w": None}))

    return unique(candidates)


def fetch_image(url: str, timeout: float, retries: int) -> tuple[Image.Image | None, dict[str, object]]:
    candidates = larger_image_url_candidates(url)
    best: tuple[Image.Image, str, int, int] | None = None
    attempts = []
    last_error = ""
    for candidate in candidates:
        for attempt in range(max(1, retries)):
            try:
                request = Request(
                    candidate,
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123 Safari/537.36"},
                )
                with urlopen(request, timeout=timeout) as response:
                    data = response.read()
                image = Image.open(BytesIO(data)).convert("RGB")
                pixels = image.size[0] * image.size[1]
                attempts.append(f"{candidate}=>{image.size[0]}x{image.size[1]}")
                if best is None or pixels > best[2]:
                    best = (image, candidate, pixels, len(data))
                break
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                last_error = repr(exc)
                if attempt + 1 >= max(1, retries):
                    attempts.append(f"{candidate}=>ERROR")
                else:
                    time.sleep(0.25 * (attempt + 1))
    if best is None:
        return None, {
            "fetch_ok": False,
            "selected_url": url,
            "url_repaired": False,
            "candidate_count": len(candidates),
            "fetch_error": last_error,
            "attempts": " | ".join(attempts),
        }
    image, selected_url, pixels, byte_count = best
    original_image, original_meta = fetch_single_image(url, timeout)
    original_pixels = original_image.size[0] * original_image.size[1] if original_image is not None else 0
    materially_bigger = selected_url != url and pixels > max(original_pixels * 1.25, original_pixels + 20_000)
    return image, {
        "fetch_ok": True,
        "selected_url": selected_url,
        "url_repaired": materially_bigger,
        "candidate_count": len(candidates),
        "loaded_width": image.size[0],
        "loaded_height": image.size[1],
        "loaded_pixels": pixels,
        "loaded_bytes": byte_count,
        "original_width": original_meta.get("width", ""),
        "original_height": original_meta.get("height", ""),
        "attempts": " | ".join(attempts),
    }


def fetch_single_image(url: str, timeout: float) -> tuple[Image.Image | None, dict[str, object]]:
    try:
        request = Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123 Safari/537.36"},
        )
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
        image = Image.open(BytesIO(data)).convert("RGB")
        return image, {"width": image.size[0], "height": image.size[1], "bytes": len(data)}
    except (HTTPError, URLError, TimeoutError, OSError):
        return None, {}


def laplacian_variance(gray: np.ndarray) -> float:
    gray = gray.astype(np.float32)
    center = -4 * gray[1:-1, 1:-1]
    lap = center + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    return float(np.var(lap))


def image_quality_metrics(image: Image.Image) -> dict[str, object]:
    thumb = image.copy()
    thumb.thumbnail((768, 768))
    gray_img = thumb.convert("L")
    gray = np.asarray(gray_img)
    stat = ImageStat.Stat(gray_img)
    lum = gray.astype(np.float32)
    return {
        "luminance_mean": round(float(stat.mean[0]), 2),
        "dark_pixel_pct": round(float(np.mean(lum < 35)), 4),
        "bright_pixel_pct": round(float(np.mean(lum > 245)), 4),
        "laplacian_variance": round(laplacian_variance(gray), 2),
    }


def to_float(value: object, default: float | None = None) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except ValueError:
        return default


def boolish(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "yes", "1"}


def is_supabase_qualified_row(row: dict[str, str]) -> bool:
    if boolish(row.get("is_supabase_qualified")):
        return True
    return str(row.get("source_pool") or "").strip() == "non_amazon_supabase_qualified"


def add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def choose_sort_decision(row: dict[str, str], fetch: dict[str, object], metrics: dict[str, object]) -> dict[str, object]:
    reasons: list[str] = []
    debug: list[str] = []
    needs_llm = False
    needs_human = False
    crop_priority = ""
    confidence = 0.5

    if not fetch.get("fetch_ok"):
        return {
            "sort_decision": "REJECT",
            "primary_action": "IMAGE_FETCH_FAILED",
            "reason_codes": "IMAGE_FETCH_FAILED",
            "confidence": 0.99,
            "needs_human_review": False,
            "needs_llm_review": False,
            "crop_priority": "",
            "debug_summary": f"fetch failed: {fetch.get('fetch_error', '')}",
        }

    width = int(fetch.get("loaded_width") or 0)
    height = int(fetch.get("loaded_height") or 0)
    pixels = int(fetch.get("loaded_pixels") or 0)
    luminance = float(metrics.get("luminance_mean") or 0)
    dark_pct = float(metrics.get("dark_pixel_pct") or 0)
    bright_pct = float(metrics.get("bright_pixel_pct") or 0)
    blur = float(metrics.get("laplacian_variance") or 0)

    low_resolution = min(width, height) < 300 or pixels < 180_000
    too_dark_review = luminance < 65 or dark_pct > 0.40
    too_bright_review = bright_pct > 0.18
    blurry_review = blur < 55

    if fetch.get("url_repaired"):
        debug.append("larger_url_found")
    if low_resolution:
        add_reason(reasons, "LOW_RESOLUTION_AFTER_URL_REPAIR")
        needs_human = True
        debug.append(f"low_res={width}x{height}")
    if too_dark_review:
        add_reason(reasons, "TOO_DARK")
        needs_human = True
        debug.append(f"luminance={luminance};dark_pct={dark_pct}")
    if too_bright_review:
        add_reason(reasons, "TOO_BRIGHT_OR_WASHED_OUT")
        needs_human = True
        debug.append(f"bright_pct={bright_pct}")
    if blurry_review:
        add_reason(reasons, "BLURRY_OR_LOW_DETAIL")
        needs_human = True
        debug.append(f"laplacian={blur}")

    seg_person_count = to_float(row.get("seg_person_count"))
    seg_mask_area = to_float(row.get("seg_mask_area_pct"))
    if seg_person_count == 0:
        add_reason(reasons, "NOT_WORN_OR_NO_PERSON_CANDIDATE")
        needs_llm = True
        debug.append("seg_person_count=0")
    if seg_mask_area is not None:
        if seg_mask_area < 0.20:
            add_reason(reasons, "NEEDS_CROP_HIGH_CONFIDENCE")
            crop_priority = "HIGH"
            debug.append(f"seg_mask_area_pct={seg_mask_area}")
        elif seg_mask_area < 0.25:
            add_reason(reasons, "NEEDS_CROP_BORDERLINE")
            crop_priority = "BORDERLINE"
            needs_llm = True
            debug.append(f"seg_mask_area_pct={seg_mask_area}")

    semantic_hints = set()
    for column in ["llm_suggested_labels", "primary_reason_code", "secondary_reason_code", "candidate_heuristic_tags"]:
        for part in str(row.get(column) or "").replace(",", ";").split(";"):
            part = part.strip().upper()
            if part:
                semantic_hints.add(part)
    llm_semantic_reasons = {
        "GARMENT_OBSCURED",
        "GARMENT_TOP_COVERED",
        "GARMENT_BOTTOM_CUT_OFF",
        "BACKGROUND_TOO_CLUTTERED",
        "DISTRACTING_OBJECTS",
        "BAD_ANGLE_TOP_DOWN",
        "BAD_ANGLE_SIDE_OR_TWISTED",
        "NO_PERSON_VISIBLE",
        "NOT_WORN_BY_PERSON",
    }
    hinted = sorted(semantic_hints & llm_semantic_reasons)
    if hinted:
        for reason in hinted:
            add_reason(reasons, reason + "_LLM_REVIEW")
        needs_llm = True
        debug.append("semantic_hints=" + ",".join(hinted))

    if low_resolution or too_dark_review or too_bright_review or blurry_review:
        sort_decision = "REVIEW"
        primary_action = "QUALITY_REVIEW"
        confidence = 0.75
    elif "NOT_WORN_OR_NO_PERSON_CANDIDATE" in reasons:
        sort_decision = "REVIEW"
        primary_action = "LLM_NOT_WORN_REVIEW"
        confidence = 0.85
    elif crop_priority == "HIGH":
        sort_decision = "REVIEW"
        primary_action = "CROP_REVIEW_PRIORITY"
        confidence = 0.86
    elif needs_llm:
        sort_decision = "REVIEW"
        primary_action = "LLM_SEMANTIC_REVIEW"
        confidence = 0.7
    else:
        sort_decision = "REVIEW"
        primary_action = "LLM_APPROVAL_CONFIRMATION"
        needs_llm = True
        confidence = 0.65

    return {
        "sort_decision": sort_decision,
        "primary_action": primary_action,
        "reason_codes": ";".join(reasons),
        "confidence": confidence,
        "needs_human_review": needs_human,
        "needs_llm_review": needs_llm,
        "crop_priority": crop_priority,
        "debug_summary": " | ".join(debug),
    }


def sort_rows(rows: Sequence[dict[str, str]], timeout: float, retries: int, limit: int) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    process_rows = rows[:limit] if limit else rows
    for index, row in enumerate(process_rows, start=1):
        raw_url = str(row.get("original_url_display") or "").strip()
        image, fetch = fetch_image(raw_url, timeout, retries)
        metrics = image_quality_metrics(image) if image is not None else {}
        decision = choose_sort_decision(row, fetch, metrics)
        selected_url = str(fetch.get("selected_url") or raw_url)
        output.append(
            {
                "review_row_key": row.get("review_row_key", ""),
                "source_pool": row.get("source_pool", ""),
                "source_site_display": row.get("source_site_display", ""),
                "is_supabase_qualified": row.get("is_supabase_qualified", ""),
                "original_url_display": raw_url,
                "sort_image_url": selected_url,
                "raw_scraped_image_url": raw_url,
                "url_repaired": bool(fetch.get("url_repaired")),
                "url_repair_attempted": True,
                "url_repair_candidate_count": fetch.get("candidate_count", ""),
                "loaded_width": fetch.get("loaded_width", ""),
                "loaded_height": fetch.get("loaded_height", ""),
                "loaded_pixels": fetch.get("loaded_pixels", ""),
                "needs_url_update": bool(fetch.get("url_repaired")),
                "product_page_url_display": row.get("product_page_url_display", ""),
                **decision,
            }
        )
        if index % 25 == 0:
            print(f"processed {index}/{len(process_rows)}", flush=True)
    return output


def write_report(path: Path, rows: Sequence[dict[str, object]], input_path: Path) -> None:
    decisions = Counter(str(row.get("sort_decision") or "") for row in rows)
    actions = Counter(str(row.get("primary_action") or "") for row in rows)
    reasons = Counter()
    for row in rows:
        for reason in str(row.get("reason_codes") or "").split(";"):
            if reason:
                reasons[reason] += 1
    lines = [
        "# Fit Image Sorter Run",
        "",
        f"- input: `{input_path}`",
        f"- rows sorted: `{len(rows)}`",
        f"- URL repairs found: `{sum(1 for row in rows if row.get('url_repaired'))}`",
        "",
        "## Decisions",
        "",
        "| decision | rows |",
        "| --- | ---: |",
    ]
    for key, value in decisions.most_common():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Primary Actions", "", "| action | rows |", "| --- | ---: |"])
    for key, value in actions.most_common():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Reason Codes", "", "| reason | rows |", "| --- | ---: |"])
    for key, value in reasons.most_common():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `sort_image_url` is the URL downstream steps should use.",
            "- `raw_scraped_image_url` preserves original provenance.",
            "- `LOW_RESOLUTION_AFTER_URL_REPAIR` is only emitted after larger URL candidates were tried.",
            "- Semantic reasons are intentionally routed to LLM review in this first sorter.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only-supabase-qualified", action="store_true", help="Sort only rows marked as Supabase-qualified.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = [row for row in read_csv_rows(args.input_csv) if row.get("original_url_display")]
    if args.only_supabase_qualified:
        rows = [row for row in rows if is_supabase_qualified_row(row)]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    sorted_rows = sort_rows(rows, args.timeout, args.retries, args.limit)
    output_csv = args.out_dir / "fit_image_sorter_results.csv"
    report = args.out_dir / "fit_image_sorter_report.md"
    write_csv_rows(output_csv, sorted_rows)
    write_report(report, sorted_rows, args.input_csv)
    print(output_csv)
    print(report)


if __name__ == "__main__":
    main()
