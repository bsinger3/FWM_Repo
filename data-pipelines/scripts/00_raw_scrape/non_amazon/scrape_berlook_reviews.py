#!/usr/bin/env python3
from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import math
import re
import time
from html import unescape
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = ROOT / "data-pipelines" / "non-amazon" / "data" / "step_1_raw_scraping_data" / "berlook"
OUTPUT_CSV = OUTPUT_DIR / "berlook_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "berlook_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://www.berlook.com"
ALL_REVIEWS_PAGE_URL = f"{SITE_ROOT}/pages/berlook-reviews"
JUDGEME_ALL_REVIEWS_URL = "https://api.judge.me/reviews/all_reviews_js_based"
SHOP_DOMAIN = "berlookstore.myshopify.com"
PLATFORM = "shopify"
BRAND = "BERLOOK"
SOURCE_SITE = f"{SITE_ROOT}/"
PER_PAGE = 100
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)

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

REVIEW_BLOCK_RE = re.compile(
    r"(<div class='jdgm-rev jdgm-divider-top'.*?)(?=<div class='jdgm-rev jdgm-divider-top'|</div>\s*<div class='jdgm-paginate'|$)",
    re.S,
)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")

BRA_SIZE_RE = re.compile(
    r"\b(28|30|32|34|36|38|40|42|44|46|48|50|52|54)\s*"
    r"(AAA|AA|A|B|C|D|DD|DD/?E|DDD|DDD/?F|F|G|H|I|J|K)\b",
    re.I,
)
HEIGHT_RE = re.compile(
    r"(\d)\s*(?:ft|feet|foot|['’])\s*(\d{1,2})?\s*(?:in|inches|[\"”])?",
    re.I,
)
WEIGHT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?)\b", re.I)
WAIST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b", re.I)
HIPS_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)\s*inseam\b", re.I)

COLOR_PATTERNS: Sequence[Tuple[str, str]] = (
    ("off white", "off white"),
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
)


def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def strip_tags(text: str) -> str:
    return normalize_whitespace(unescape(TAG_RE.sub(" ", text or "")))


def fetch_text(url: str, accept: str = "text/html,application/xml;q=0.9,*/*;q=0.8", retries: int = 6) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": accept,
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


def fetch_json(url: str, retries: int = 6) -> Dict[str, object]:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": SITE_ROOT,
                "Referer": f"{SITE_ROOT}/",
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
        except (URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 20))
    if last_error:
        raise RuntimeError(f"Failed JSON request for {url}: {last_error}") from last_error
    raise RuntimeError(f"Failed JSON request for {url}")


def get_all_reviews_count() -> int:
    html = fetch_text(ALL_REVIEWS_PAGE_URL)
    match = re.search(r"data-number-of-product-reviews='(\d+)'", html)
    if not match:
        return 0
    return int(match.group(1))


def build_reviews_url(page: int) -> str:
    query = urlencode(
        {
            "shop_domain": SHOP_DOMAIN,
            "platform": PLATFORM,
            "sort_by": "with_media",
            "per_page": PER_PAGE,
            "page": page,
        }
    )
    return f"{JUDGEME_ALL_REVIEWS_URL}?{query}"


def extract_attr(block: str, attr_name: str) -> str:
    match = re.search(rf"{re.escape(attr_name)}='([^']*)'|{re.escape(attr_name)}=\"([^\"]*)\"", block)
    if not match:
        return ""
    return normalize_whitespace(unescape(match.group(1) or match.group(2) or ""))


def extract_between(block: str, start_pat: str, end_pat: str) -> str:
    match = re.search(start_pat + r"(.*?)" + end_pat, block, re.S)
    return match.group(1) if match else ""


def parse_custom_answers(block: str) -> Dict[str, str]:
    answers: Dict[str, str] = {}
    for title_html, value_html in re.findall(
        r"jdgm-rev__cf-ans__title'>(.*?)</b>\s*<span class='jdgm-rev__cf-ans__value'>(.*?)</span>",
        block,
        re.S,
    ):
        title = strip_tags(title_html).rstrip(":").strip().lower()
        value = strip_tags(value_html)
        if title and value:
            answers[title] = value
    return answers


def parse_review_blocks(html: str) -> List[str]:
    return [match.group(1) for match in REVIEW_BLOCK_RE.finditer(html)]


def maybe_number_text(value: Optional[float]) -> str:
    if value is None:
        return ""
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


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


def parse_measurement(text: str, pattern: re.Pattern[str]) -> Optional[float]:
    match = pattern.search(text)
    if not match:
        return None
    value = float(match.group(1))
    if value > 60:
        return None
    return value


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


def parse_bust_and_cup(value: str) -> Tuple[str, str]:
    match = BRA_SIZE_RE.search(value)
    if not match:
        return "", ""
    return match.group(1), normalize_bra_size(match.group(2))


def normalize_size(value: str) -> str:
    cleaned = normalize_whitespace(value)
    return cleaned if cleaned else "unknown"


def infer_color(title: str, url: str) -> str:
    haystack = f"{title} {url}".lower()
    for needle, normalized in COLOR_PATTERNS:
        if needle in haystack:
            return normalized
    return ""


def classify_clothing_type(title: str, url: str) -> str:
    value = f"{title} {url}".lower()
    if "one-piece" in value or "one piece" in value or "swimsuit" in value:
        return "dress" if "dress" in value else "one_piece"
    if "bikini top" in value or value.endswith(" top") or "-top" in value:
        return "top"
    if "bikini bottom" in value or value.endswith(" bottom") or "-bottom" in value:
        return "bottom"
    if "dress" in value:
        return "dress"
    if "skirt" in value:
        return "skirt"
    if "shorts" in value or "short" in value:
        return "shorts"
    if "legging" in value:
        return "leggings"
    return ""


def build_search_fts(parts: Iterable[str]) -> str:
    return normalize_whitespace(" ".join(part for part in parts if part))


def parse_review_rows(review_html: str, fetched_at: str) -> List[Dict[str, str]]:
    review_id = extract_attr(review_html, "data-review-id")
    review_title = extract_attr(review_html, "data-product-title")
    review_url = extract_attr(review_html, "data-product-url")
    if not review_url:
        link_match = re.search(r"<a href='(/products/[^'#?]+)#judgeme_product_reviews'[^>]*class='jdgm-rev__prod-link'>(.*?)</a>", review_html, re.S)
        if link_match:
            review_url = normalize_whitespace(unescape(link_match.group(1)))
            review_title = review_title or strip_tags(link_match.group(2))
    if not review_url.startswith("/products/"):
        return []
    product_page_url = f"{SITE_ROOT}{review_url}"
    reviewer_name = strip_tags(extract_between(review_html, r"jdgm-rev__author'>", r"</span>"))
    review_timestamp = extract_attr(review_html, "data-content")
    review_date = review_timestamp.split(" ")[0] if review_timestamp else ""
    body_html = extract_between(review_html, r"<div class='jdgm-rev__body'>", r"</div>")
    user_comment = strip_tags(body_html)
    answers = parse_custom_answers(review_html)

    pic_urls = re.findall(
        r"<a class='jdgm-rev__pic-link(?![^']*jdgm-rev__product-picture)[^']*'.*?href='([^']+)'",
        review_html,
        re.S,
    )
    picture_urls = [normalize_whitespace(unescape(url)) for url in pic_urls]
    if not picture_urls:
        return []

    size_value = normalize_size(answers.get("size purchased", "unknown"))
    bust_value = answers.get("bust", "") or answers.get("bra size", "")
    bust_in, cup_size = parse_bust_and_cup(bust_value)

    text_pool = " ".join(
        [
            user_comment,
            " ".join(f"{key}: {value}" for key, value in answers.items()),
        ]
    )
    height_raw = answers.get("height", "")
    weight_raw = answers.get("weight", "")
    waist_raw = answers.get("waist", "")
    hips_raw = answers.get("hips", "")
    age_raw = answers.get("age", "")
    inseam_raw = answers.get("inseam", "")

    height_in = parse_height_inches(height_raw or text_pool)
    weight_lbs = parse_weight_lbs(weight_raw or text_pool)
    waist_in = parse_measurement(waist_raw or text_pool, WAIST_RE)
    hips_in = parse_measurement(hips_raw or text_pool, HIPS_RE)
    age_years = parse_age(age_raw or text_pool)
    inseam_in = parse_measurement(inseam_raw or text_pool, INSEAM_RE)

    color_display = infer_color(review_title, product_page_url)
    clothing_type = classify_clothing_type(review_title, product_page_url)
    search_fts = build_search_fts(
        [
            BRAND,
            review_title,
            reviewer_name,
            user_comment,
            size_value,
            color_display,
            clothing_type,
        ]
    )

    rows: List[Dict[str, str]] = []
    for picture_url in picture_urls:
        rows.append(
            {
                "created_at_display": "",
                "id": "",
                "original_url_display": picture_url,
                "product_page_url_display": product_page_url,
                "monetized_product_url_display": "",
                "height_raw": height_raw,
                "weight_raw": weight_raw,
                "user_comment": user_comment,
                "date_review_submitted_raw": review_timestamp,
                "height_in_display": maybe_number_text(height_in),
                "review_date": review_date,
                "source_site_display": SOURCE_SITE,
                "status_code": "200",
                "fetched_at": fetched_at,
                "updated_at": fetched_at,
                "brand": BRAND,
                "waist_raw_display": waist_raw,
                "hips_raw": hips_raw,
                "age_raw": age_raw,
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
                "size_display": size_value,
                "bust_in_number_display": bust_in,
                "cupsize_display": cup_size,
                "weight_lbs_display": maybe_number_text(weight_lbs),
                "_review_id": review_id,
            }
        )
    return rows


def scrape_all_reviews(fetched_at: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    page = 1
    seen_page_signatures = set()
    while True:
        payload = fetch_json(build_reviews_url(page))
        html = str(payload.get("html") or "")
        review_blocks = parse_review_blocks(html)
        if not review_blocks:
            break
        page_signature = tuple(extract_attr(block, "data-review-id") for block in review_blocks[:3])
        if page_signature in seen_page_signatures:
            break
        seen_page_signatures.add(page_signature)
        for review_block in review_blocks:
            rows.extend(parse_review_rows(review_block, fetched_at))
        page += 1
    return rows


def write_csv(rows: Sequence[Dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            clean_row = {key: row.get(key, "") for key in HEADERS}
            writer.writerow(clean_row)


def write_summary(rows: Sequence[Dict[str, str]], started_at: str, finished_at: str, total_reviews_hint: int) -> None:
    summary = {
        "site": SITE_ROOT,
        "products_with_image_reviews": len({row.get("product_page_url_display") for row in rows}),
        "rows_written": len(rows),
        "distinct_reviews": len({row.get("_review_id") for row in rows}),
        "distinct_images": len({row.get("original_url_display") for row in rows}),
        "product_reviews_count_hint_from_store_page": total_reviews_hint,
        "output_csv": str(OUTPUT_CSV),
        "started_at": started_at,
        "finished_at": finished_at,
    }
    with SUMMARY_JSON.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)


def dedupe_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        key = (row.get("_review_id"), row.get("original_url_display"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def main() -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    fetched_at = datetime.now(timezone.utc).date().isoformat()
    total_reviews_hint = get_all_reviews_count()
    rows = scrape_all_reviews(fetched_at)
    rows = dedupe_rows(rows)
    rows.sort(
        key=lambda row: (
            row.get("review_date", ""),
            row.get("product_page_url_display", ""),
            row.get("reviewer_name_raw", ""),
            row.get("original_url_display", ""),
        ),
        reverse=True,
    )

    write_csv(rows)
    finished_at = datetime.now(timezone.utc).isoformat()
    write_summary(rows, started_at, finished_at, total_reviews_hint)

    print(f"Products with image reviews: {len({row.get('product_page_url_display') for row in rows})}")
    print(f"Rows written: {len(rows)}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Summary: {SUMMARY_JSON}")


if __name__ == "__main__":
    main()
