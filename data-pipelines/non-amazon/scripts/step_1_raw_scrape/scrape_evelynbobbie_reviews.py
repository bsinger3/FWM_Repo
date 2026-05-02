#!/usr/bin/env python3
from __future__ import annotations

import csv
from datetime import datetime, timezone
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "evelynbobbie_com"
OUTPUT_CSV = OUTPUT_DIR / "evelynbobbie_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "evelynbobbie_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://evelynbobbie.com"
SOURCE_SITE = f"{SITE_ROOT}/"
SHOP_DOMAIN = "evelyn-bobbie.myshopify.com"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
YOTPO_APP_KEY = "vgU7jBMr0iIRREtgyPw6Z6gWm1B8bpSRpdLfGg4h"
YOTPO_API_ROOT = f"https://api-cdn.yotpo.com/v1/widget/{YOTPO_APP_KEY}"
BRAND = "Evelyn & Bobbie"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
MAX_CONSECUTIVE_NO_IMAGE_PAGES = 5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
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
    "content_type",
    "bytes",
    "width",
    "height",
    "hash_md5",
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
    "color_canonical",
    "color_display",
    "size_display",
    "bust_in_number_display",
    "cupsize_display",
    "weight_lbs_display",
    "weight_lbs_raw_issue",
    "product_title_raw",
    "product_subtitle_raw",
    "product_description_raw",
    "product_detail_raw",
    "product_category_raw",
    "product_variant_raw",
]

TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
HEIGHT_NUMERIC_RE = re.compile(
    r"\b([4-6])\s*(?:ft|feet|foot|['\u2019])\s*(?:(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven)\s*)?(?:in|inches|[\"\u201d])?",
    re.I,
)
HEIGHT_COMPACT_RE = re.compile(r"\b([4-6])\s*[\u2019']\s*(\d{1,2})\b")
WEIGHT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?|#)\b", re.I)
WAIST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b", re.I)
HIPS_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?(?:\s*old)?)\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*inseam\b", re.I)
BRA_SIZE_RE = re.compile(r"\b((?:2[8-9]|3[0-9]|4[0-8])\s*(?:aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k))\b", re.I)
SIZE_RE = re.compile(
    r"\b(?:size|sz|ordered|bought|got|wear(?:ing)?|usual size)\s*(?:is|was|a|an|the|:)?\s*"
    r"(xxs|xs|s|m|l|xl|2xl|3xl|4xl|small|medium|large|x-large|xx-large|xxx-large)\b",
    re.I,
)
WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
}


def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def strip_tags(value: str) -> str:
    cleaned = re.sub(r"</p\s*>|<br\s*/?>", " ", value or "", flags=re.I)
    return repair_mojibake(normalize_whitespace(html.unescape(TAG_RE.sub(" ", cleaned))))


def repair_mojibake(text: str) -> str:
    if not text or "â" not in text:
        return text
    try:
        return text.encode("latin1").decode("utf-8")
    except UnicodeError:
        return text


def fetch_json(
    url: str,
    params: Optional[Dict[str, object]] = None,
    retries: int = 6,
    referer: Optional[str] = None,
) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            query_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": SITE_ROOT,
                "Referer": referer or SOURCE_SITE,
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
        time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"Failed JSON request for {query_url}: {last_error}")


def product_url_for(product: Dict[str, object]) -> str:
    handle = normalize_whitespace(str(product.get("handle") or ""))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def fetch_products(limit_products: Optional[int] = None) -> List[Dict[str, object]]:
    products: List[Dict[str, object]] = []
    page = 1
    while True:
        payload = fetch_json(PRODUCTS_JSON_URL, {"limit": PRODUCTS_PER_PAGE, "page": page})
        page_products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        if not page_products:
            break
        for product in page_products:
            products.append(product)
            if limit_products is not None and len(products) >= limit_products:
                return products[:limit_products]
        if len(page_products) < PRODUCTS_PER_PAGE:
            break
        page += 1
    return products


def yotpo_reviews_url(product_id: object) -> str:
    return f"{YOTPO_API_ROOT}/products/{product_id}/reviews.json"


def yotpo_response(payload: Dict[str, object]) -> Dict[str, object]:
    response = payload.get("response")
    return response if isinstance(response, dict) else {}


def fetch_product_reviews(product: Dict[str, object], exhaustive: bool) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    product_url = product_url_for(product)
    product_id = product.get("id")
    meta: Dict[str, object] = {
        "product_url": product_url,
        "product_title": product.get("title"),
        "shopify_product_id": product_id,
        "adapter_used": "yotpo_product_level",
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "matching_review_images": 0,
        "errors": [],
    }
    reviews: List[Dict[str, object]] = []
    seen_review_ids = set()
    page = 1
    total_pages = 1
    consecutive_no_image_pages = 0
    while page <= total_pages:
        try:
            payload = fetch_json(
                yotpo_reviews_url(product_id),
                {"per_page": REVIEWS_PER_PAGE, "page": page, "sort": "with_pictures"},
                referer=product_url,
            )
        except Exception as exc:  # noqa: BLE001
            meta["errors"].append(str(exc))
            break
        response = yotpo_response(payload)
        pagination = response.get("pagination") if isinstance(response.get("pagination"), dict) else {}
        total = int(pagination.get("total") or 0)
        per_page = int(pagination.get("per_page") or REVIEWS_PER_PAGE)
        total_pages = max(1, (total + per_page - 1) // per_page)
        if page == 1:
            meta["review_count_hint"] = total
        page_reviews = [item for item in response.get("reviews", []) if isinstance(item, dict)]
        if not page_reviews:
            break
        page_image_count = 0
        for review in page_reviews:
            review_id = str(review.get("id") or "")
            if review_id and review_id in seen_review_ids:
                continue
            seen_review_ids.add(review_id)
            reviews.append(review)
            page_image_count += len(review_image_urls(review))
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"]) + 1
        if page_image_count:
            consecutive_no_image_pages = 0
        else:
            consecutive_no_image_pages += 1
        if not exhaustive and consecutive_no_image_pages >= MAX_CONSECUTIVE_NO_IMAGE_PAGES:
            break
        page += 1
    meta["matching_review_images"] = sum(len(review_image_urls(review)) for review in reviews)
    return reviews, meta


def parse_height_inches(text: str) -> Tuple[str, Optional[int]]:
    match = HEIGHT_COMPACT_RE.search(text)
    if not match:
        match = HEIGHT_NUMERIC_RE.search(text)
    if not match:
        return "", None
    feet = int(match.group(1))
    inches_text = (match.group(2) or "").lower()
    inches = WORD_NUMBERS.get(inches_text, int(inches_text) if inches_text.isdigit() else 0)
    if 4 <= feet <= 6 and 0 <= inches < 12:
        return match.group(0), feet * 12 + inches
    return "", None


def parse_numeric(pattern: re.Pattern[str], text: str, max_value: Optional[float] = None) -> Tuple[str, str]:
    match = pattern.search(text)
    if not match:
        return "", ""
    value = float(match.group(1))
    if max_value is not None and value > max_value:
        return "", ""
    return match.group(0), f"{value:g}"


def parse_age(text: str) -> Tuple[str, str]:
    match = AGE_RE.search(text)
    if not match:
        return "", ""
    value = match.group(1) or match.group(2)
    if not value:
        return "", ""
    age = int(value)
    if 13 <= age <= 99:
        return match.group(0), str(age)
    return "", ""


def maybe_number_text(value: Optional[int]) -> str:
    return "" if value is None else str(value)


def extract_bra_size(text: str) -> Tuple[str, str]:
    match = BRA_SIZE_RE.search(text)
    if not match:
        return "", ""
    compact = re.sub(r"\s+", "", match.group(1)).upper()
    band = re.match(r"(\d{2})", compact)
    cup = re.search(r"[A-Z]+$", compact)
    return (band.group(1) if band else "", cup.group(0) if cup else "")


def review_image_urls(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    images = review.get("images_data")
    if not isinstance(images, list):
        return urls
    for image in images:
        if not isinstance(image, dict):
            continue
        url = normalize_whitespace(str(image.get("original_url") or image.get("thumb_url") or ""))
        if url and url not in urls:
            urls.append(url)
    return urls


def product_detail(product: Dict[str, object]) -> str:
    tags = product.get("tags")
    tag_text = " | ".join(str(tag) for tag in tags) if isinstance(tags, list) else str(tags or "")
    variants = product.get("variants")
    variant_titles: List[str] = []
    if isinstance(variants, list):
        for variant in variants[:150]:
            if isinstance(variant, dict):
                title = normalize_whitespace(str(variant.get("title") or ""))
                if title and title.lower() != "default title" and title not in variant_titles:
                    variant_titles.append(title)
    return normalize_whitespace(" | ".join([tag_text] + variant_titles))


def variant_lookup(product: Dict[str, object]) -> Dict[str, Tuple[str, str]]:
    lookup: Dict[str, Tuple[str, str]] = {}
    variants = product.get("variants")
    if not isinstance(variants, list):
        return lookup
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        title = normalize_whitespace(str(variant.get("title") or ""))
        if not title or title.lower() == "default title":
            continue
        parts = [normalize_whitespace(part) for part in title.split("/") if normalize_whitespace(part)]
        if len(parts) >= 2:
            color, size = parts[0], parts[-1]
        elif re.fullmatch(r"(?:xxs|xs|s|m|l|xl|2xl|3xl|4xl|small|medium|large)", title, re.I):
            color, size = "", title
        else:
            color, size = title, ""
        lookup[title.lower()] = (color, size)
    return lookup


def extract_size_from_text(text: str) -> str:
    match = SIZE_RE.search(text)
    return match.group(1).upper() if match else ""


def classify_clothing_type(product: Dict[str, object]) -> str:
    value = f"{product.get('title') or ''} {product.get('product_type') or ''}".lower()
    if "short" in value:
        return "shorts"
    if "bikini" in value or "thong" in value or "underwear" in value:
        return "underwear"
    if "tank" in value or "camisole" in value:
        return "top"
    if "bra" in value:
        return "bra"
    return normalize_whitespace(str(product.get("product_type") or "")).lower()


def build_search_fts(parts: Iterable[str]) -> str:
    return normalize_whitespace(" ".join(part for part in parts if part))


def parse_review_rows(review: Dict[str, object], product: Dict[str, object], fetched_at: str) -> List[Dict[str, str]]:
    image_urls = review_image_urls(review)
    if not image_urls:
        return []
    product_url = product_url_for(product)
    product_title = strip_tags(str(product.get("title") or ""))
    title = strip_tags(str(review.get("title") or ""))
    body = strip_tags(str(review.get("content") or ""))
    text_pool = normalize_whitespace(" ".join([title, body]))
    date_created = normalize_whitespace(str(review.get("created_at") or ""))
    review_date = date_created.split("T", 1)[0] if "T" in date_created else date_created
    user = review.get("user") if isinstance(review.get("user"), dict) else {}
    reviewer_name = strip_tags(str(user.get("display_name") or user.get("name") or ""))
    color_display = ""
    size_display = extract_size_from_text(text_pool)
    custom_fields = review.get("custom_fields") if isinstance(review.get("custom_fields"), dict) else {}
    if custom_fields:
        fields_blob = json.dumps(custom_fields, ensure_ascii=False)
        size_display = size_display or extract_size_from_text(fields_blob)
    lookup = variant_lookup(product)
    if lookup:
        for _variant_title, (variant_color, variant_size) in lookup.items():
            if variant_color and re.search(rf"\b{re.escape(variant_color)}\b", text_pool, re.I):
                color_display = variant_color
                size_display = size_display or variant_size
                break
    height_raw, height_in = parse_height_inches(text_pool)
    weight_raw, weight_lbs = parse_numeric(WEIGHT_RE, text_pool)
    waist_raw, waist_in = parse_numeric(WAIST_RE, text_pool, max_value=60)
    hips_raw, hips_in = parse_numeric(HIPS_RE, text_pool, max_value=80)
    age_raw, age_years = parse_age(text_pool)
    _inseam_raw, inseam_in = parse_numeric(INSEAM_RE, text_pool, max_value=40)
    bust_in, cupsize = extract_bra_size(text_pool)
    product_description = strip_tags(str(product.get("body_html") or ""))
    product_category = normalize_whitespace(str(product.get("product_type") or ""))
    review_id = normalize_whitespace(str(review.get("id") or ""))

    rows: List[Dict[str, str]] = []
    for index, image_url in enumerate(image_urls, start=1):
        rows.append(
            {
                "created_at_display": "",
                "id": f"{review_id}-{index}" if review_id else f"{hash(image_url)}-{index}",
                "original_url_display": image_url,
                "product_page_url_display": product_url,
                "monetized_product_url_display": "",
                "height_raw": height_raw,
                "weight_raw": weight_raw,
                "user_comment": text_pool,
                "date_review_submitted_raw": date_created,
                "height_in_display": maybe_number_text(height_in),
                "review_date": review_date,
                "source_site_display": SOURCE_SITE,
                "status_code": "200",
                "content_type": "",
                "bytes": "",
                "width": "",
                "height": "",
                "hash_md5": "",
                "fetched_at": fetched_at,
                "updated_at": fetched_at,
                "brand": BRAND,
                "waist_raw_display": waist_raw,
                "hips_raw": hips_raw,
                "age_raw": age_raw,
                "waist_in": waist_in,
                "hips_in_display": hips_in,
                "age_years_display": age_years,
                "search_fts": build_search_fts([BRAND, product_title, product_description, title, body]),
                "weight_display_display": weight_lbs,
                "weight_raw_needs_correction": "",
                "clothing_type_id": classify_clothing_type(product),
                "reviewer_profile_url": "",
                "reviewer_name_raw": reviewer_name,
                "inseam_inches_display": inseam_in,
                "color_canonical": color_display.lower(),
                "color_display": color_display,
                "size_display": size_display,
                "bust_in_number_display": bust_in,
                "cupsize_display": cupsize,
                "weight_lbs_display": weight_lbs,
                "weight_lbs_raw_issue": "",
                "product_title_raw": product_title,
                "product_subtitle_raw": "",
                "product_description_raw": product_description,
                "product_detail_raw": product_detail(product),
                "product_category_raw": product_category,
                "product_variant_raw": "",
            }
        )
    return rows


def dedupe_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        image_key = re.sub(r"\?.*$", "", row.get("original_url_display", ""))
        key = (row.get("id", "").rsplit("-", 1)[0], image_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def has_product_url(row: Dict[str, str]) -> bool:
    return bool(row.get("product_page_url_display") or row.get("monetized_product_url_display"))


def has_measurement(row: Dict[str, str]) -> bool:
    return any(
        row.get(key)
        for key in [
            "height_in_display",
            "weight_display_display",
            "weight_lbs_display",
            "bust_in_number_display",
            "hips_in_display",
            "waist_in",
            "inseam_inches_display",
        ]
    )


def is_supabase_qualified(row: Dict[str, str]) -> bool:
    return bool(has_product_url(row) and has_measurement(row) and row.get("original_url_display") and row.get("size_display"))


def scrape_reviews(limit_products: Optional[int] = None, exhaustive: bool = True) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    products = fetch_products(limit_products=limit_products)
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": "evelynbobbie_com",
        "adapter": "yotpo_product_level",
        "yotpo_app_key": YOTPO_APP_KEY,
        "shop_domain": SHOP_DOMAIN,
        "started_at": fetched_at,
        "products_discovered": len(products),
        "products_scanned": 0,
        "exhaustive_review_paging": exhaustive,
        "products_with_review_rows": 0,
        "review_pages_scanned": 0,
        "product_review_count_hint": 0,
        "access_policy": "public_pages_only; no_auth_bypass; no_captcha_bypass; polite_retries",
        "measurement_extraction": "deterministic_regex_and_provider_fields_only",
        "errors": [],
    }
    for index, product in enumerate(products, start=1):
        reviews, product_meta = fetch_product_reviews(product, exhaustive=exhaustive)
        product_rows: List[Dict[str, str]] = []
        for review in reviews:
            product_rows.extend(parse_review_rows(review, product, fetched_at))
        product_summaries.append({**product_meta, "product_index": index, "rows": len(product_rows)})
        summary["products_scanned"] = int(summary["products_scanned"]) + 1
        summary["review_pages_scanned"] = int(summary["review_pages_scanned"]) + int(product_meta.get("review_pages_scanned") or 0)
        summary["product_review_count_hint"] = int(summary["product_review_count_hint"]) + int(product_meta.get("review_count_hint") or 0)
        if product_rows:
            summary["products_with_review_rows"] = int(summary["products_with_review_rows"]) + 1
        if product_meta.get("errors"):
            summary["errors"].append(product_meta)
        rows.extend(product_rows)
        print(
            f"[product {index}/{len(products)}] reviews={len(reviews)} rows={len(product_rows)} url={product_meta.get('product_url')}",
            flush=True,
        )
    summary["product_summaries"] = product_summaries
    summary["finished_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return dedupe_rows(rows), summary


def write_csv(rows: Sequence[Dict[str, str]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in HEADERS})


def enrich_summary(summary: Dict[str, object], rows: Sequence[Dict[str, str]], output_csv: Path) -> Dict[str, object]:
    product_urls = {
        row.get("product_page_url_display") or row.get("monetized_product_url_display")
        for row in rows
        if has_product_url(row)
    }
    qualified_reviews = {row.get("id", "").rsplit("-", 1)[0] for row in rows if row.get("id") and is_supabase_qualified(row)}
    summary.update(
        {
            "output_csv": str(output_csv),
            "rows_written": len(rows),
            "distinct_reviews": len({row.get("id", "").rsplit("-", 1)[0] for row in rows if row.get("id")}),
            "distinct_images": len({re.sub(r"\?.*$", "", row.get("original_url_display", "")) for row in rows if row.get("original_url_display")}),
            "distinct_product_urls": len(product_urls),
            "distinct_products": len(product_urls),
            "rows_with_distinct_product_url": sum(1 for row in rows if has_product_url(row)),
            "rows_with_product_url": sum(1 for row in rows if has_product_url(row)),
            "rows_missing_product_url": sum(1 for row in rows if not has_product_url(row)),
            "rows_with_customer_image": sum(1 for row in rows if row.get("original_url_display")),
            "rows_with_image_url": sum(1 for row in rows if row.get("original_url_display")),
            "rows_missing_image_url": sum(1 for row in rows if not row.get("original_url_display")),
            "rows_with_user_comment": sum(1 for row in rows if row.get("user_comment")),
            "rows_with_size": sum(1 for row in rows if row.get("size_display")),
            "rows_with_customer_ordered_size": sum(1 for row in rows if row.get("size_display")),
            "rows_with_any_measurement": sum(1 for row in rows if has_measurement(row)),
            "rows_supabase_qualified": sum(1 for row in rows if is_supabase_qualified(row)),
            "distinct_qualified_reviews": len(qualified_reviews),
            "rows_with_image_and_product_url": sum(1 for row in rows if row.get("original_url_display") and has_product_url(row)),
            "rows_with_image_product_and_measurement": sum(
                1 for row in rows if row.get("original_url_display") and has_product_url(row) and has_measurement(row)
            ),
            "rows_with_image_product_size_and_measurement": sum(1 for row in rows if is_supabase_qualified(row)),
            "rows_with_image_product_and_user_comment": sum(
                1 for row in rows if row.get("original_url_display") and has_product_url(row) and row.get("user_comment")
            ),
            "rows_with_product_context": sum(1 for row in rows if row.get("product_title_raw")),
            "rows_for_bra_products": sum(1 for row in rows if row.get("clothing_type_id") == "bra"),
        }
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    limit_products: Optional[int] = None
    if "--limit-products" in argv:
        index = argv.index("--limit-products")
        limit_products = int(argv[index + 1])
    exhaustive = "--quick-photo-scan" not in argv
    rows, summary = scrape_reviews(limit_products=limit_products, exhaustive=exhaustive)
    rows.sort(
        key=lambda row: (
            row.get("review_date", ""),
            row.get("product_page_url_display", ""),
            row.get("reviewer_name_raw", ""),
            row.get("original_url_display", ""),
        ),
        reverse=True,
    )
    write_csv(rows, OUTPUT_CSV)
    summary = enrich_summary(summary, rows, OUTPUT_CSV)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Rows written: {len(rows)}")
    print(f"Supabase-qualified rows: {summary['rows_supabase_qualified']}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
