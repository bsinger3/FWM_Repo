#!/usr/bin/env python3
"""Scrape customer review photos from a MeetCurve product page.

Usage:
    python scrape_meetcurve_reviews.py [PRODUCT_URL]

If PRODUCT_URL is omitted the default product URL is used.
Output is written to:
    data-pipelines/non-amazon/data/step_1_raw_scraping_data/meetcurve/
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = (
    ROOT
    / "data-pipelines"
    / "non-amazon"
    / "data"
    / "step_1_raw_scraping_data"
    / "meetcurve"
)
OUTPUT_CSV = OUTPUT_DIR / "meetcurve_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "meetcurve_reviews_matching_amazon_schema_summary.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SITE_ROOT = "https://www.meetcurve.com"
BRAND = "MeetCurve"
SOURCE_SITE = f"{SITE_ROOT}/"

DEFAULT_PRODUCT_URL = (
    "https://www.meetcurve.com"
    "/black-v-neck-streak-modern-one-piece-swimsuit-b-sfop1911012.html"
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# CSV schema (matches images_intake_sample)
# ---------------------------------------------------------------------------
HEADERS = [
    "created_at_display",
    "id",
    "original_url_display",
    "product_page_url_display",
    "monetized_product_url_display",
    "height_raw",
    "weight_raw",
    "user_comment",
    "date_review_submitted_raw",
    "height_in_display",
    "review_date",
    "source_site_display",
    "status_code",
    "fetched_at",
    "updated_at",
    "brand",
    "waist_raw_display",
    "hips_raw",
    "age_raw",
    "waist_in",
    "hips_in_display",
    "age_years_display",
    "search_fts",
    "weight_display_display",
    "weight_raw_needs_correction",
    "clothing_type_id",
    "reviewer_profile_url",
    "reviewer_name_raw",
    "inseam_inches_display",
    "color_display",
    "size_display",
    "bust_in_number_display",
    "cupsize_display",
    "weight_lbs_display",
]

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")

BRA_SIZE_RE = re.compile(
    r"\b(28|30|32|34|36|38|40|42|44|46|48|50|52|54)\s*"
    r"(AAA|AA|A|B|C|D|DD|DD/?E|DDD|DDD/?F|F|G|H|I|J|K)\b",
    re.I,
)
HEIGHT_RE = re.compile(
    r"(\d)\s*(?:ft|feet|foot|[''`])\s*(\d{1,2})?\s*(?:in|inches|[\"""])?",
    re.I,
)
WEIGHT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?)\b", re.I)
WAIST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b", re.I)
HIPS_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)\s*inseam\b", re.I)

# Matches explicit size mentions: "size XL", "a 3XL", "ordered a medium", "in a large", etc.
# NOTE: longer numeric sizes (3XL) must come before shorter ones (3X); \b prevents partial-word
# matches like capturing "s" from "swimsuit" or "m" from "medium" mid-word.
SIZE_RE = re.compile(
    r"(?:"
    r"(?:size|got\s+(?:a\s+|the\s+)?|ordered\s+(?:a\s+|the\s+)?|wearing\s+(?:a\s+|the\s+)?|in\s+(?:a\s+|the\s+)?)\s*"
    r"(?:size\s*)?"
    r")"
    r"(XXS|XS|6XL|5XL|4XL|3XL|2XL|1XL|6X|5X|4X|3X|2X|1X|0X|XL|L|M|S|"
    r"(?:x+[-\s]?(?:small|large))|small|medium|large|plus)\b",
    re.I,
)

COLOR_PATTERNS: Sequence[Tuple[str, str]] = (
    ("off white", "off white"),
    ("off-white", "off white"),
    ("coffee", "brown"),
    ("brown", "brown"),
    ("black", "black"),
    ("blue", "blue"),
    ("green", "green"),
    ("purple", "purple"),
    ("pink", "pink"),
    ("white", "white"),
    ("red", "red"),
    ("yellow", "yellow"),
    ("orange", "orange"),
    ("navy", "navy"),
    ("grey", "grey"),
    ("gray", "gray"),
    ("beige", "beige"),
    ("khaki", "khaki"),
    ("floral", "floral"),
    ("leopard", "leopard"),
    ("animal print", "animal print"),
    ("stripe", "stripe"),
    ("plaid", "plaid"),
)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def strip_tags(text: str) -> str:
    return normalize_whitespace(unescape(TAG_RE.sub(" ", text or "")))


def maybe_number_text(value: Optional[float]) -> str:
    if value is None:
        return ""
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Measurement parsers
# ---------------------------------------------------------------------------

def parse_height_inches(text: str) -> Optional[float]:
    match = HEIGHT_RE.search(text)
    if not match:
        return None
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    return feet * 12 + inches


def parse_weight_lbs(text: str) -> Optional[float]:
    match = WEIGHT_RE.search(text)
    return float(match.group(1)) if match else None


def parse_measurement(text: str, pattern: re.Pattern) -> Optional[float]:
    match = pattern.search(text)
    if not match:
        return None
    value = float(match.group(1))
    return None if value > 60 else value


def parse_age(text: str) -> Optional[int]:
    match = AGE_RE.search(text)
    if not match:
        return None
    value = match.group(1) or match.group(2)
    return int(value) if value else None


def normalize_bra_size(value: str) -> str:
    collapsed = normalize_whitespace(value).upper().replace(" ", "")
    if collapsed == "DDE":
        return "DD/E"
    if collapsed == "DDDF":
        return "DDD/F"
    return collapsed


def parse_bust_and_cup(text: str) -> Tuple[str, str]:
    match = BRA_SIZE_RE.search(text)
    if not match:
        return "", ""
    return match.group(1), normalize_bra_size(match.group(2))


def parse_size_from_text(text: str) -> str:
    """Try to extract a garment size (XL, 3XL, medium, etc.) from review text."""
    match = SIZE_RE.search(text)
    if not match:
        return "unknown"
    raw = match.group(1).strip()
    # Normalise to uppercase for letter sizes, title-case for words
    if raw.upper() in {
        "XXS", "XS", "S", "M", "L", "XL",
        "0X", "1X", "2X", "3X", "4X", "5X", "6X",
        "1XL", "2XL", "3XL", "4XL", "5XL", "6XL",
    }:
        return raw.upper()
    return raw.lower()


def infer_color(product_name: str, product_url: str) -> str:
    haystack = f"{product_name} {product_url}".lower()
    for needle, normalized in COLOR_PATTERNS:
        if needle in haystack:
            return normalized
    return ""


def classify_clothing_type(product_name: str, product_url: str) -> str:
    value = f"{product_name} {product_url}".lower()
    if "one-piece" in value or "one piece" in value or "one_piece" in value:
        return "one_piece"
    if "swimsuit" in value or "swimwear" in value:
        return "one_piece"
    if "bikini top" in value or value.endswith(" top") or "-top" in value:
        return "top"
    if "bikini bottom" in value or value.endswith(" bottom") or "-bottom" in value:
        return "bottom"
    if "bikini" in value:
        return "bikini"
    if "tankini" in value:
        return "tankini"
    if "dress" in value:
        return "dress"
    if "skirt" in value:
        return "skirt"
    if "shorts" in value:
        return "shorts"
    if "legging" in value:
        return "leggings"
    if "top" in value:
        return "top"
    return ""


def build_search_fts(parts: Iterable[str]) -> str:
    return normalize_whitespace(" ".join(p for p in parts if p))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def fetch_text(url: str, retries: int = 6) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"{SITE_ROOT}/",
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
        except URLError as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 20))
    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def _text_between(html: str, start_pattern: str, end_pattern: str = r"</div>") -> str:
    m = re.search(start_pattern + r"(.*?)" + end_pattern, html, re.S)
    return strip_tags(m.group(1)) if m else ""


def build_image_map(html: str) -> Dict[str, List[str]]:
    """Return {review_id: [img_url, ...]} from review-thumbnail-images blocks."""
    image_map: Dict[str, List[str]] = {}
    # Each block: <div class="review-thumbnail-images" ... data-id="NNN"> ... imgs ... </div>
    for block_match in re.finditer(
        r'<div[^>]+class=["\']review-thumbnail-images["\'][^>]+data-id=["\'](\d+)["\'][^>]*>'
        r'(.*?)</div>',
        html,
        re.S,
    ):
        review_id = block_match.group(1)
        block_html = block_match.group(2)
        urls = re.findall(
            r'<img[^>]+src=["\']'
            r'(https://images\.meetcurve\.com/media/reviewimages[^"\']+)'
            r'["\']',
            block_html,
        )
        if urls:
            image_map.setdefault(review_id, []).extend(urls)
    return image_map


def parse_reviews(html: str, product_url: str, fetched_at: str) -> List[Dict[str, str]]:
    """Parse all reviews from the HTML and return a list of row dicts."""
    # Build image_id → [urls] mapping first
    image_map = build_image_map(html)

    rows: List[Dict[str, str]] = []

    # Each review occupies one <div class="review-list-cust"> ... block.
    # We split on that boundary.
    review_chunks = re.split(r'(?=<div[^>]+class="review-list-cust")', html)

    for chunk in review_chunks:
        if 'class="review-list-cust"' not in chunk:
            continue

        # --- Review ID ---
        id_match = re.search(r'id="review-(\d+)"', chunk)
        if not id_match:
            continue
        review_id = id_match.group(1)

        # Skip reviews with no customer photos
        photo_urls = image_map.get(review_id, [])
        if not photo_urls:
            continue

        # --- Reviewer name ---
        name_match = re.search(r'class="name-cust">(.*?)<span', chunk, re.S)
        reviewer_name = strip_tags(name_match.group(1)) if name_match else ""

        # --- Date ---
        date_match = re.search(r'<small class="date">(.*?)</small>', chunk, re.S)
        date_raw = strip_tags(date_match.group(1)) if date_match else ""
        # Normalise M/D/YYYY → YYYY-MM-DD
        review_date = ""
        if date_raw:
            try:
                review_date = datetime.strptime(date_raw, "%m/%d/%Y").date().isoformat()
            except ValueError:
                review_date = date_raw

        # --- Review text ---
        comment_match = re.search(
            rf'id="review-detail-content-{re.escape(review_id)}">(.*?)</div>',
            chunk,
            re.S,
        )
        user_comment = strip_tags(comment_match.group(1)) if comment_match else ""

        # --- Product name ---
        name_div_match = re.search(
            rf'id="product-detail-name-{re.escape(review_id)}">(.*?)</div>',
            chunk,
            re.S,
        )
        product_name = strip_tags(name_div_match.group(1)) if name_div_match else ""

        # --- Measurements from review text ---
        text_pool = user_comment
        height_in = parse_height_inches(text_pool)
        weight_lbs = parse_weight_lbs(text_pool)
        waist_in = parse_measurement(text_pool, WAIST_RE)
        hips_in = parse_measurement(text_pool, HIPS_RE)
        age_years = parse_age(text_pool)
        inseam_in = parse_measurement(text_pool, INSEAM_RE)
        bust_in, cup_size = parse_bust_and_cup(text_pool)

        # --- Size ---
        size_display = parse_size_from_text(user_comment)

        # --- Color / clothing type ---
        color_display = infer_color(product_name, product_url)
        clothing_type = classify_clothing_type(product_name, product_url)

        # --- FTS ---
        search_fts = build_search_fts(
            [BRAND, product_name, reviewer_name, user_comment, size_display, color_display, clothing_type]
        )

        # --- One row per photo ---
        for photo_url in photo_urls:
            rows.append(
                {
                    "created_at_display": "",
                    "id": "",
                    "original_url_display": photo_url,
                    "product_page_url_display": product_url,
                    "monetized_product_url_display": "",
                    "height_raw": "",
                    "weight_raw": "",
                    "user_comment": user_comment,
                    "date_review_submitted_raw": date_raw,
                    "height_in_display": maybe_number_text(height_in),
                    "review_date": review_date,
                    "source_site_display": SOURCE_SITE,
                    "status_code": "200",
                    "fetched_at": fetched_at,
                    "updated_at": fetched_at,
                    "brand": BRAND,
                    "waist_raw_display": "",
                    "hips_raw": "",
                    "age_raw": "",
                    "waist_in": maybe_number_text(waist_in),
                    "hips_in_display": maybe_number_text(hips_in),
                    "age_years_display": str(age_years) if age_years is not None else "",
                    "search_fts": search_fts,
                    "weight_display_display": maybe_number_text(weight_lbs),
                    "weight_raw_needs_correction": "",
                    "clothing_type_id": clothing_type,
                    "reviewer_profile_url": "",
                    "reviewer_name_raw": reviewer_name,
                    "inseam_inches_display": maybe_number_text(inseam_in),
                    "color_display": color_display,
                    "size_display": size_display,
                    "bust_in_number_display": bust_in,
                    "cupsize_display": cup_size,
                    "weight_lbs_display": maybe_number_text(weight_lbs),
                    "_review_id": review_id,
                }
            )

    return rows


# ---------------------------------------------------------------------------
# Dedup & sort
# ---------------------------------------------------------------------------

def dedupe_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen: set = set()
    for row in rows:
        key = (row.get("_review_id"), row.get("original_url_display"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def write_csv(rows: Sequence[Dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in HEADERS})


def write_summary(
    rows: Sequence[Dict[str, str]],
    product_url: str,
    started_at: str,
    finished_at: str,
) -> None:
    summary = {
        "site": SITE_ROOT,
        "product_url": product_url,
        "products_with_image_reviews": len({r.get("product_page_url_display") for r in rows}),
        "rows_written": len(rows),
        "distinct_reviews": len({r.get("_review_id") for r in rows}),
        "distinct_images": len({r.get("original_url_display") for r in rows}),
        "output_csv": str(OUTPUT_CSV),
        "started_at": started_at,
        "finished_at": finished_at,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with SUMMARY_JSON.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    product_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PRODUCT_URL

    started_at = datetime.now(timezone.utc).isoformat()
    fetched_at = datetime.now(timezone.utc).date().isoformat()

    print(f"Fetching: {product_url}")
    html = fetch_text(product_url)

    print("Parsing reviews…")
    rows = parse_reviews(html, product_url, fetched_at)
    rows = dedupe_rows(rows)
    rows.sort(
        key=lambda r: (
            r.get("review_date", ""),
            r.get("reviewer_name_raw", ""),
            r.get("original_url_display", ""),
        ),
        reverse=True,
    )

    write_csv(rows)
    finished_at = datetime.now(timezone.utc).isoformat()
    write_summary(rows, product_url, started_at, finished_at)

    print(f"Reviews with photos : {len({r.get('_review_id') for r in rows})}")
    print(f"Rows (images) written: {len(rows)}")
    print(f"CSV  : {OUTPUT_CSV}")
    print(f"JSON : {SUMMARY_JSON}")


if __name__ == "__main__":
    main()
