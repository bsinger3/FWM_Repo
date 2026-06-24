#!/usr/bin/env python3
"""Convert scrape_amazon_reviews_direct.mjs JSON batches to the standard intake CSV.

Reads JSON batch files from FWM_Data/00_raw_scraped_data/amazon/direct_amazon/
and writes one row per (review, image) to the standard intake CSV format, with
measurements extracted from the review comment text.

The image_source_detail field encodes enough to re-fetch the CDN URL if it
expires: asin={ASIN};review_id={reviewId};img_idx={n}

Usage:
    python normalize_amazon_reviews.py
    python normalize_amazon_reviews.py --input-dir path/to/direct_amazon/
    python normalize_amazon_reviews.py --input path/to/batch_001.json
    python normalize_amazon_reviews.py --dry-run --limit 20
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_SCRIPTS_DIR = SCRIPT_DIR.parents[2]
NON_AMAZON_DIR = PIPELINE_SCRIPTS_DIR / "00_raw_scrape" / "non_amazon"
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))
if str(NON_AMAZON_DIR) not in sys.path:
    sys.path.insert(0, str(NON_AMAZON_DIR))

from pipeline_paths import raw_scraped_data_root  # noqa: E402
from step1_intake_utils import (  # noqa: E402
    INTAKE_HEADERS,
    extract_measurements,
    normalize_whitespace,
    review_date_from_raw,
    validate_rows,
)

DEFAULT_INPUT_DIR = raw_scraped_data_root() / "amazon" / "direct_amazon"
DEFAULT_OUTPUT_DIR = raw_scraped_data_root() / "amazon"

AMAZON_BASE = "https://www.amazon.com"

SIZE_COLOR_RE = re.compile(
    r"(?:^|\|)\s*Size\s*:\s*([^|]+?)(?:\s*\||\s*$)",
    re.I,
)
COLOR_RE = re.compile(
    r"(?:^|\|)\s*Color(?:\s*Name)?\s*:\s*([^|]+?)(?:\s*\||\s*$)",
    re.I,
)
# Strip trailing size qualifiers we don't want in size_display
SIZE_QUALIFIER_RE = re.compile(r"\s*[-–]\s*(?:Standard|Tall|Petite|Short|Long|Regular)\s*$", re.I)

ASSOCIATES_TAG = "fwm-20"


def product_page_url(asin: str) -> str:
    return f"{AMAZON_BASE}/dp/{asin}"


def monetized_url(asin: str) -> str:
    return f"{AMAZON_BASE}/dp/{asin}?tag={ASSOCIATES_TAG}"


def image_source_detail(asin: str, review_id: str, img_idx: int) -> str:
    return f"asin={asin};review_id={review_id};img_idx={img_idx}"


def parse_size_color(size_color_raw: str) -> Tuple[str, str]:
    raw = normalize_whitespace(size_color_raw)
    size = ""
    color = ""

    size_match = SIZE_COLOR_RE.search(raw)
    if size_match:
        size = normalize_whitespace(size_match.group(1))
        size = SIZE_QUALIFIER_RE.sub("", size).strip()

    color_match = COLOR_RE.search(raw)
    if color_match:
        color = normalize_whitespace(color_match.group(1))

    return size, color


def parse_review_date(date_raw: str) -> str:
    # Amazon dates look like "Reviewed in the United States on January 15, 2024"
    match = re.search(r"on\s+(\w+ \d+, \d{4})", date_raw)
    if match:
        return review_date_from_raw(match.group(1))
    return review_date_from_raw(date_raw)


def iter_batch_files(input_dir: Path) -> Iterator[Path]:
    for path in sorted(input_dir.glob("batch_*.json")):
        yield path


def iter_rows_from_batch(batch_path: Path) -> Iterator[Dict]:
    with batch_path.open(encoding="utf-8") as f:
        records = json.load(f)
    for record in records:
        if record.get("statusMessage") != "FOUND":
            continue
        if not record.get("imageUrlList"):
            continue
        yield record


def build_intake_rows(record: Dict, fetched_at: str) -> List[Dict[str, str]]:
    asin = record.get("asin", "").strip().upper()
    review_id = record.get("reviewId", "").strip()
    title = normalize_whitespace(record.get("title", ""))
    body = normalize_whitespace(record.get("text", ""))
    comment = " ".join(part for part in [title, body] if part)

    size_display, color_display = parse_size_color(record.get("sizeColor", ""))
    measurements = extract_measurements(comment, size_display)

    date_raw = normalize_whitespace(record.get("date", ""))
    review_date = parse_review_date(date_raw)
    product_url = product_page_url(asin)

    rows = []
    for img_idx, image_url in enumerate(record.get("imageUrlList", [])):
        if not image_url:
            continue

        row = {header: "" for header in INTAKE_HEADERS}
        row.update({
            "id": f"{asin}_{review_id}_{img_idx}" if review_id else "",
            "original_url_display": image_url,
            "image_source_type": "amazon_review_image",
            "image_source_detail": image_source_detail(asin, review_id, img_idx),
            "product_page_url_display": product_url,
            "monetized_product_url_display": monetized_url(asin),
            "user_comment": comment,
            "date_review_submitted_raw": date_raw,
            "review_date": review_date,
            "source_site_display": "https://www.amazon.com/",
            "status_code": str(record.get("statusCode", "") or ""),
            "fetched_at": fetched_at,
            "updated_at": fetched_at,
            "brand": "",
            "reviewer_profile_url": normalize_whitespace(record.get("profileUrl", "")),
            "reviewer_name_raw": normalize_whitespace(record.get("userName", "")),
            "color_canonical": color_display.lower(),
            "color_display": color_display,
            "size_display": size_display,
            "product_title_raw": normalize_whitespace(record.get("productTitle", "")),
        })
        row.update(measurements)
        rows.append(row)

    return rows


def normalize_batches(
    batch_paths: Iterable[Path],
    limit: Optional[int] = None,
) -> List[Dict[str, str]]:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    all_rows: List[Dict[str, str]] = []
    seen_keys = set()

    for batch_path in batch_paths:
        for record in iter_rows_from_batch(batch_path):
            for row in build_intake_rows(record, fetched_at):
                key = row["image_source_detail"] or row["original_url_display"]
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                all_rows.append(row)
                if limit is not None and len(all_rows) >= limit:
                    return all_rows

    return all_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize Amazon review JSON batches to intake CSV.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR,
                        help=f"Directory of batch_*.json files (default: {DEFAULT_INPUT_DIR})")
    parser.add_argument("--input", type=Path, default=None,
                        help="Process a single batch JSON file")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output CSV path (default: auto-timestamped in OUTPUT_DIR)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N rows (useful for smoke tests)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print summary stats without writing the CSV")
    args = parser.parse_args()

    if args.input:
        batch_paths = [args.input]
    else:
        batch_paths = list(iter_batch_files(args.input_dir))

    if not batch_paths:
        print(f"No batch files found in {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Processing {len(batch_paths)} batch file(s)...", file=sys.stderr)
    rows = normalize_batches(batch_paths, limit=args.limit)

    summary = validate_rows(rows)
    summary["batch_files_processed"] = len(batch_paths)

    if args.dry_run:
        print(json.dumps(summary, indent=2))
        return

    if not rows:
        print("No qualifying rows produced.", file=sys.stderr)
        return

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.output or (DEFAULT_OUTPUT_DIR / f"amazon_reviews_matching_intake_schema_{ts}.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INTAKE_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({h: row.get(h, "") for h in INTAKE_HEADERS})

    summary_path = output_path.with_name(output_path.stem + "_summary.json")
    summary["output_csv"] = str(output_path)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
