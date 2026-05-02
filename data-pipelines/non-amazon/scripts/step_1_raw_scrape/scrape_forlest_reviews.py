#!/usr/bin/env python3
from __future__ import annotations

import csv
from datetime import datetime, timezone
import html
import json
import math
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
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "forlest_com"
OUTPUT_CSV = OUTPUT_DIR / "forlest_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "forlest_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://forlest.com"
SOURCE_SITE = f"{SITE_ROOT}/"
SHOP_DOMAIN = "forlest.myshopify.com"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
RYVIU_CLIENT_URL = "https://app.ryviu.io/frontend/client"
BRAND = "FORLEST"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 8
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
HEIGHT_RE = re.compile(
    r"(\d)\s*(?:ft|feet|foot|['\u2019])\s*(\d{1,2})?\s*(?:in|inches|[\"\u201d])?",
    re.I,
)
WEIGHT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?|#)\b", re.I)
WAIST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b", re.I)
HIPS_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*inseam\b", re.I)
BRA_SIZE_RE = re.compile(
    r"\b(?:ordered|bought|got|wear(?:ing)?|in|size|sz)\s+(?:a|an|the|my)?\s*"
    r"((?:2[8-9]|3[0-9]|4[0-8])\s*(?:aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k))\b",
    re.I,
)
SIZE_PATTERNS = [
    BRA_SIZE_RE,
    re.compile(
        r"\b(?:size|sz)\s*(?:up|down|is|was|ordered|bought|got|:)?\s*"
        r"(xxs|xs|s\+?|m\+?|l\+?|xl\+?|2xl\+?|3xl\+?|4xl\+?|5xl\+?|small|medium|large)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:ordered|bought|got|purchased|wear(?:ing)?)\s+(?:a|an|the)?\s*"
        r"(?:size\s*)?(xxs|xs|s\+?|m\+?|l\+?|xl\+?|2xl\+?|3xl\+?|4xl\+?|5xl\+?|small|medium|large)\b",
        re.I,
    ),
]

COLOR_WORDS = (
    "almond",
    "americano",
    "black",
    "cafe latte",
    "chili",
    "cloud",
    "lace pink",
    "mocha",
    "pistachio",
    "tea latte",
    "vanilla",
    "white",
)


def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def strip_tags(value: str) -> str:
    cleaned = re.sub(r"</p\s*>|<br\s*/?>", " ", value or "", flags=re.I)
    return normalize_whitespace(html.unescape(TAG_RE.sub(" ", cleaned)))


def fetch_json(
    url: str,
    params: Optional[Dict[str, object]] = None,
    body: Optional[Dict[str, object]] = None,
    retries: int = 5,
    referer: Optional[str] = None,
) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    payload = json.dumps(body or {}).encode("utf-8") if body is not None else None
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": SITE_ROOT,
            "Referer": referer or SOURCE_SITE,
        }
        if payload is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = Request(query_url, data=payload, headers=headers, method="POST" if payload is not None else "GET")
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
            product_type = normalize_whitespace(str(product.get("product_type") or "")).lower()
            title = normalize_whitespace(str(product.get("title") or "")).lower()
            if "bag" in title or "gift card" in title:
                continue
            if product_type and product_type not in {"bras", "bra", "tops", "tanks"}:
                continue
            products.append(product)
            if limit_products is not None and len(products) >= limit_products:
                return products[:limit_products]
        if len(page_products) < PRODUCTS_PER_PAGE:
            break
        page += 1
    return products


def ryviu_url(action: str) -> str:
    return f"{RYVIU_CLIENT_URL}/{action}"


def ryviu_body(product: Dict[str, object], page: int, first_load: bool = False) -> Dict[str, object]:
    return {
        "handle": product.get("handle"),
        "product_id": product.get("id"),
        "domain": SHOP_DOMAIN,
        "platform": "shopify",
        "page": page,
        "type": "load-more",
        "order": "featured",
        "filter": "all",
        "filter_review": {"stars": [], "image": False, "replies": False},
        "feature": False,
        "feature_extend": True,
        "first_load": first_load,
        "type_review": "all",
        "snippet": False,
        "limit_number": 10,
    }


def fetch_product_reviews(
    product: Dict[str, object],
    limit_pages_per_product: Optional[int] = None,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    product_url = product_url_for(product)
    reviews: List[Dict[str, object]] = []
    meta: Dict[str, object] = {
        "product_url": product_url,
        "product_title": product.get("title"),
        "adapter_used": "ryviu_product_level",
        "matching_review_images": 0,
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "errors": [],
    }
    try:
        first = fetch_json(
            ryviu_url("get-reviews-data"),
            {"domain": SHOP_DOMAIN},
            ryviu_body(product, 1, first_load=True),
            referer=product_url,
        )
    except Exception as exc:  # noqa: BLE001
        meta["errors"].append(str(exc))
        return reviews, meta

    ratings = first.get("ratings")
    total = int(ratings.get("total_limit") or ratings.get("total") or ratings.get("count") or 0) if isinstance(ratings, dict) else 0
    meta["review_count_hint"] = total
    first_reviews = [item for item in first.get("reviews", []) if isinstance(item, dict)]
    reviews.extend(first_reviews)
    meta["review_pages_scanned"] = 1 if first_reviews else 0

    total_pages = max(1, math.ceil(total / REVIEWS_PER_PAGE)) if total else 1
    page = 2
    while page <= total_pages:
        if limit_pages_per_product is not None and page > limit_pages_per_product:
            break
        payload = fetch_json(
            ryviu_url("get-more-reviews"),
            {"domain": SHOP_DOMAIN},
            ryviu_body(product, page),
            referer=product_url,
        )
        more_reviews = [item for item in payload.get("more_reviews", []) if isinstance(item, dict)]
        if not more_reviews:
            break
        reviews.extend(more_reviews)
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"]) + 1
        page += 1
    meta["matching_review_images"] = sum(len(review_image_urls(review)) for review in reviews)
    return reviews, meta


def maybe_number_text(value: Optional[float]) -> str:
    if value is None:
        return ""
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def parse_height_inches(text: str) -> Tuple[str, Optional[float]]:
    match = HEIGHT_RE.search(text)
    if not match:
        return "", None
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    if feet < 4 or feet > 7 or inches > 11:
        return "", None
    return normalize_whitespace(match.group(0)), feet * 12 + inches


def parse_numeric(pattern: re.Pattern[str], text: str, max_value: Optional[float] = None) -> Tuple[str, Optional[float]]:
    match = pattern.search(text)
    if not match:
        return "", None
    value = float(match.group(1))
    if max_value is not None and value > max_value:
        return "", None
    return normalize_whitespace(match.group(0)), value


def parse_age(text: str) -> Tuple[str, str]:
    match = AGE_RE.search(text)
    if not match:
        return "", ""
    value = match.group(1) or match.group(2) or ""
    return normalize_whitespace(match.group(0)), value


def normalize_size(value: str) -> str:
    cleaned = normalize_whitespace(value).upper().replace(" ", "")
    mapping = {
        "S": "small",
        "M": "medium",
        "L": "large",
        "XL": "x-large",
        "2XL": "xx-large",
        "3XL": "xxx-large",
    }
    return mapping.get(cleaned, cleaned)


def extract_size(text: str) -> Tuple[str, str, str]:
    for pattern in SIZE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        raw = normalize_whitespace(match.group(1))
        if re.match(r"^(?:2[8-9]|3[0-9]|4[0-8])\s*(?:aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k)$", raw, re.I):
            size = normalize_size(raw)
            bust_match = re.match(r"^(\d{2})", size)
            cup_match = re.search(r"([A-Z]+)$", size)
            return size, bust_match.group(1) if bust_match else "", cup_match.group(1) if cup_match else ""
        return normalize_size(raw), "", ""
    return "", "", ""


def infer_color(product: Dict[str, object], review: Dict[str, object]) -> Tuple[str, str]:
    haystack = " ".join(
        [
            str(product.get("title") or ""),
            str(product.get("handle") or ""),
            str(review.get("body_text") or ""),
        ]
    ).lower().replace("-", " ")
    for color in sorted(COLOR_WORDS, key=len, reverse=True):
        if color in haystack:
            return color, color.title()
    return "", ""


def classify_clothing_type(product: Dict[str, object]) -> str:
    value = f"{product.get('title') or ''} {product.get('product_type') or ''}".lower()
    if "bra" in value or "bralette" in value:
        return "bra"
    if "tank" in value or "top" in value:
        return "top"
    return ""


def build_search_fts(parts: Iterable[str]) -> str:
    return normalize_whitespace(" ".join(part for part in parts if part))


def review_image_urls(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    body_urls = review.get("body_urls")
    if not isinstance(body_urls, list):
        return urls
    for value in body_urls:
        url = normalize_whitespace(str(value or ""))
        if url and url not in urls:
            urls.append(url)
    return urls


def product_detail(product: Dict[str, object]) -> str:
    variants = product.get("variants")
    titles: List[str] = []
    if isinstance(variants, list):
        for variant in variants[:80]:
            if isinstance(variant, dict):
                title = normalize_whitespace(str(variant.get("title") or ""))
                if title and title not in titles:
                    titles.append(title)
    tags = product.get("tags")
    tag_text = " | ".join(str(tag) for tag in tags) if isinstance(tags, list) else str(tags or "")
    return normalize_whitespace(" | ".join([tag_text] + titles))


def parse_review_rows(
    review: Dict[str, object],
    product: Dict[str, object],
    fetched_at: str,
) -> List[Dict[str, str]]:
    picture_urls = review_image_urls(review)
    if not picture_urls:
        return []

    product_url = product_url_for(product)
    product_title = strip_tags(str(product.get("title") or ""))
    review_id = f"ryviu-{review.get('key')}"
    title = strip_tags(str(review.get("title") or ""))
    body = strip_tags(str(review.get("body_text") or ""))
    timestamp = normalize_whitespace(str(review.get("created_at") or ""))
    review_date = normalize_whitespace(str(review.get("created_at_format") or timestamp.split("T", 1)[0]))
    reviewer_name = strip_tags(str(review.get("author") or ""))
    text_pool = normalize_whitespace(" ".join([title, body]))

    height_raw, height_in = parse_height_inches(text_pool)
    weight_raw, weight_lbs = parse_numeric(WEIGHT_RE, text_pool)
    waist_raw, waist_in = parse_numeric(WAIST_RE, text_pool, max_value=60)
    hips_raw, hips_in = parse_numeric(HIPS_RE, text_pool, max_value=80)
    age_raw, age_years = parse_age(text_pool)
    _inseam_raw, inseam_in = parse_numeric(INSEAM_RE, text_pool, max_value=40)
    size_display, bust_in, cupsize = extract_size(text_pool)
    color_canonical, color_display = infer_color(product, review)
    clothing_type = classify_clothing_type(product)
    product_variant = normalize_whitespace(" / ".join(part for part in [color_display, size_display] if part))

    rows: List[Dict[str, str]] = []
    for index, picture_url in enumerate(picture_urls, start=1):
        rows.append(
            {
                "created_at_display": "",
                "id": f"{review_id}-{index}",
                "original_url_display": picture_url,
                "product_page_url_display": product_url,
                "monetized_product_url_display": "",
                "height_raw": height_raw,
                "weight_raw": weight_raw,
                "user_comment": text_pool,
                "date_review_submitted_raw": timestamp,
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
                "waist_in": maybe_number_text(waist_in),
                "hips_in_display": maybe_number_text(hips_in),
                "age_years_display": age_years,
                "search_fts": build_search_fts([BRAND, product_title, title, body, color_display, size_display]),
                "weight_display_display": maybe_number_text(weight_lbs),
                "weight_raw_needs_correction": "",
                "clothing_type_id": clothing_type,
                "reviewer_profile_url": "",
                "reviewer_name_raw": reviewer_name,
                "inseam_inches_display": maybe_number_text(inseam_in),
                "color_canonical": color_canonical,
                "color_display": color_display,
                "size_display": size_display,
                "bust_in_number_display": bust_in,
                "cupsize_display": cupsize,
                "weight_lbs_display": maybe_number_text(weight_lbs),
                "weight_lbs_raw_issue": "",
                "product_title_raw": product_title,
                "product_subtitle_raw": "",
                "product_description_raw": strip_tags(str(product.get("body_html") or "")),
                "product_detail_raw": product_detail(product),
                "product_category_raw": normalize_whitespace(str(product.get("product_type") or "")),
                "product_variant_raw": product_variant,
            }
        )
    return rows


def dedupe_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        key = (row.get("id"), row.get("original_url_display"), row.get("product_page_url_display"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def scrape_reviews(
    limit_products: Optional[int] = None,
    limit_pages_per_product: Optional[int] = None,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    products = fetch_products(limit_products=limit_products)
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": "forlest_com",
        "adapter": "ryviu_product_level",
        "shop_domain": SHOP_DOMAIN,
        "started_at": fetched_at,
        "products_discovered": len(products),
        "products_scanned": 0,
        "products_with_review_rows": 0,
        "review_pages_scanned": 0,
        "product_review_count_hint": 0,
        "product_level_required": True,
        "aggregate_only": False,
        "measurement_extraction": "deterministic_regex_and_provider_fields_only",
        "errors": [],
    }
    for index, product in enumerate(products, start=1):
        reviews, product_meta = fetch_product_reviews(product, limit_pages_per_product=limit_pages_per_product)
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


def has_product_url(row: Dict[str, str]) -> bool:
    return bool(row.get("product_page_url_display") or row.get("monetized_product_url_display"))


def is_supabase_qualified(row: Dict[str, str]) -> bool:
    return bool(
        has_product_url(row)
        and has_measurement(row)
        and row.get("original_url_display")
        and row.get("size_display")
        and row.get("size_display") != "unknown"
    )


def enrich_summary(summary: Dict[str, object], rows: Sequence[Dict[str, str]], output_csv: Path) -> Dict[str, object]:
    product_urls = {
        row.get("product_page_url_display") or row.get("monetized_product_url_display")
        for row in rows
        if has_product_url(row)
    }
    summary.update(
        {
            "output_csv": str(output_csv),
            "rows_written": len(rows),
            "distinct_reviews": len({row.get("id", "").rsplit("-", 1)[0] for row in rows if row.get("id")}),
            "distinct_images": len({row.get("original_url_display") for row in rows if row.get("original_url_display")}),
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
            "distinct_qualified_reviews": len({row.get("id", "").rsplit("-", 1)[0] for row in rows if row.get("id") and is_supabase_qualified(row)}),
            "rows_with_image_and_product_url": sum(
                1 for row in rows if row.get("original_url_display") and has_product_url(row)
            ),
            "rows_with_image_product_and_measurement": sum(
                1 for row in rows if row.get("original_url_display") and has_product_url(row) and has_measurement(row)
            ),
            "rows_with_image_product_size_and_measurement": sum(1 for row in rows if is_supabase_qualified(row)),
            "rows_with_image_product_and_user_comment": sum(
                1
                for row in rows
                if row.get("original_url_display") and has_product_url(row) and row.get("user_comment")
            ),
            "rows_with_product_context": sum(1 for row in rows if row.get("product_title_raw")),
            "rows_for_bra_products": sum(1 for row in rows if row.get("clothing_type_id") == "bra"),
            "rows_for_bra_products_with_customer_bra_size": sum(
                1 for row in rows if row.get("clothing_type_id") == "bra" and row.get("bust_in_number_display") and row.get("cupsize_display")
            ),
        }
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    limit_products: Optional[int] = None
    limit_pages_per_product: Optional[int] = None
    if "--limit-products" in argv:
        index = argv.index("--limit-products")
        limit_products = int(argv[index + 1])
    if "--limit-pages-per-product" in argv:
        index = argv.index("--limit-pages-per-product")
        limit_pages_per_product = int(argv[index + 1])

    rows, summary = scrape_reviews(
        limit_products=limit_products,
        limit_pages_per_product=limit_pages_per_product,
    )
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
