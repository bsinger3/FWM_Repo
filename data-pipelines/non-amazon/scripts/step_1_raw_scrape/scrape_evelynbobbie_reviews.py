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
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "evelynbobbie_com"
OUTPUT_CSV = OUTPUT_DIR / "evelynbobbie_com_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "evelynbobbie_com_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://evelynbobbie.com"
SOURCE_SITE = f"{SITE_ROOT}/"
SHOP_DOMAIN = "evelyn-bobbie.myshopify.com"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
YOTPO_APP_KEY = "vgU7jBMr0iIRREtgyPw6Z6gWm1B8bpSRpdLfGg4h"
YOTPO_API_ROOT = f"https://api-cdn.yotpo.com/v1/widget/{YOTPO_APP_KEY}"
YOTPO_V3_API_ROOT = f"https://api-cdn.yotpo.com/v3/storefront/store/{YOTPO_APP_KEY}"
BRAND = "Evelyn & Bobbie"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
LEAD_URLS = [
    "https://evelynbobbie.com/products/evelyn-wireless-bra",
]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

HEADERS = [
    "created_at_display",
    "id",
    "original_url_display",
    "image_source_type",
    "image_source_detail",
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
BRA_SIZE_RE = re.compile(r"\b((?:2[6-9]|3[0-9]|4[0-9]|5[0-4])\s*(?:aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k))\b", re.I)
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


class StopScrape(RuntimeError):
    pass


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


def check_block_body(text: str, url: str) -> None:
    lowered = text[:5000].lower()
    block_markers = [
        "captcha",
        "cf-challenge",
        "cloudflare",
        "datadome",
        "access denied",
        "temporarily blocked",
        "security check",
        "suspicious",
    ]
    if any(marker in lowered for marker in block_markers):
        raise StopScrape(f"WAF/captcha-like response detected for {url}")


def fetch_text(url: str, params: Optional[Dict[str, object]] = None, referer: Optional[str] = None) -> str:
    query_url = f"{url}?{urlencode(params)}" if params else url
    req = Request(
        query_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html,application/xml,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": SITE_ROOT,
            "Referer": referer or SOURCE_SITE,
        },
    )
    try:
        with urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code in {403, 409, 418, 429}:
            raise StopScrape(f"Stop status {exc.code} for {query_url}") from exc
        raise
    check_block_body(body, query_url)
    return body


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, referer: Optional[str] = None) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    try:
        return json.loads(fetch_text(url, params=params, referer=referer))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed JSON decode for {query_url}: {exc}") from exc


def product_url_for(product: Dict[str, object]) -> str:
    handle = normalize_whitespace(str(product.get("handle") or ""))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def skip_reason(product: Dict[str, object]) -> str:
    haystack = " ".join(
        normalize_whitespace(str(part or ""))
        for part in [
            product.get("title"),
            product.get("handle"),
            product.get("product_type"),
            " ".join(str(tag) for tag in product.get("tags", []) if isinstance(tag, str))
            if isinstance(product.get("tags"), list)
            else product.get("tags"),
        ]
    ).lower()
    if "gift card" in haystack:
        return "out_of_scope_gift_card"
    if re.search(r"\b(travel bag|wash bag|laundry bag|bag)\b", haystack):
        return "out_of_scope_accessory"
    return ""


def product_handle_from_url(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) >= 2 and parts[-2] == "products":
        return parts[-1]
    return ""


def fetch_products_json(limit_products: Optional[int] = None) -> List[Dict[str, object]]:
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


def discover_sitemap_product_urls() -> List[str]:
    product_urls: List[str] = []
    root = fetch_text(urljoin(SITE_ROOT, "/sitemap.xml"))
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    try:
        tree = ET.fromstring(root)
    except ET.ParseError:
        return []
    sitemap_urls = [html.unescape((node.text or "").strip()) for node in tree.findall(".//sm:loc", ns)]
    for sitemap_url in sitemap_urls:
        if "sitemap_products_" not in sitemap_url:
            continue
        body = fetch_text(sitemap_url)
        try:
            sitemap_tree = ET.fromstring(body)
        except ET.ParseError:
            continue
        for loc in sitemap_tree.findall(".//sm:loc", ns):
            url = html.unescape((loc.text or "").strip())
            if "/products/" in url and product_handle_from_url(url) and url not in product_urls:
                product_urls.append(url)
    return product_urls


def discover_products(limit_products: Optional[int] = None) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    products = fetch_products_json(limit_products=None)
    products_by_handle = {normalize_whitespace(str(product.get("handle") or "")): product for product in products}
    product_sources: Dict[str, object] = {
        "shopify_products_json": len(products),
        "sitemap_products": 0,
        "lead_urls": len(LEAD_URLS),
        "duplicates_removed": 0,
    }
    for url in discover_sitemap_product_urls():
        handle = product_handle_from_url(url)
        if not handle:
            continue
        product_sources["sitemap_products"] = int(product_sources["sitemap_products"]) + 1
        if handle in products_by_handle:
            product_sources["duplicates_removed"] = int(product_sources["duplicates_removed"]) + 1
            continue
        products_by_handle[handle] = {
            "id": "",
            "title": handle.replace("-", " ").title(),
            "handle": handle,
            "body_html": "",
            "product_type": "",
            "tags": [],
            "variants": [],
            "_discovered_from_sitemap_only": True,
        }
    for url in LEAD_URLS:
        handle = product_handle_from_url(url)
        if not handle:
            continue
        if handle in products_by_handle:
            product_sources["duplicates_removed"] = int(product_sources["duplicates_removed"]) + 1
            continue
        products_by_handle[handle] = {
            "id": "",
            "title": handle.replace("-", " ").title(),
            "handle": handle,
            "body_html": "",
            "product_type": "",
            "tags": [],
            "variants": [],
            "_discovered_from_lead_only": True,
        }
    ordered: List[Dict[str, object]] = []
    seen_handles = set()
    for product in products:
        handle = normalize_whitespace(str(product.get("handle") or ""))
        if handle and handle in products_by_handle and handle not in seen_handles:
            ordered.append(products_by_handle[handle])
            seen_handles.add(handle)
    for handle, product in products_by_handle.items():
        if handle and handle not in seen_handles:
            ordered.append(product)
            seen_handles.add(handle)
    product_sources["final_products_to_scan"] = len(ordered)
    if limit_products is not None:
        product_sources["limited_products_to_scan"] = limit_products
        ordered = ordered[:limit_products]
    return ordered, product_sources


def cached_products_from_summary(limit_products: Optional[int] = None) -> List[Dict[str, object]]:
    if not SUMMARY_JSON.exists():
        return []
    try:
        summary = json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    products: List[Dict[str, object]] = []
    for item in summary.get("product_summaries") or []:
        if not isinstance(item, dict):
            continue
        product_url = normalize_whitespace(str(item.get("product_url") or ""))
        handle = Path(urlparse(product_url).path).name
        product = {
            "id": item.get("shopify_product_id"),
            "title": item.get("product_title"),
            "handle": handle,
            "body_html": "",
            "product_type": classify_title_product_type(normalize_whitespace(str(item.get("product_title") or ""))),
            "tags": [],
            "variants": [],
            "_cached_from_previous_summary": True,
        }
        products.append(product)
        if limit_products is not None and len(products) >= limit_products:
            return products[:limit_products]
    return products


def yotpo_reviews_url(product_id: object) -> str:
    return f"{YOTPO_API_ROOT}/products/{product_id}/reviews.json"


def yotpo_store_reviews_url() -> str:
    return f"{YOTPO_V3_API_ROOT}/reviews"


def yotpo_response(payload: Dict[str, object]) -> Dict[str, object]:
    response = payload.get("response")
    return response if isinstance(response, dict) else {}


def fetch_product_reviews(
    product: Dict[str, object],
    limit_pages: Optional[int],
    request_delay_seconds: float,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    product_url = product_url_for(product)
    product_id = product.get("id")
    meta: Dict[str, object] = {
        "product_url": product_url,
        "product_title": product.get("title"),
        "shopify_product_id": product_id,
        "adapter_used": "yotpo_v1_product_level_full_pages" if product_id else "missing-shopify-product-id",
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "matching_review_images": 0,
        "errors": [],
    }
    reviews: List[Dict[str, object]] = []
    seen_review_ids = set()
    if not product_id:
        meta["errors"].append("missing_shopify_product_id_for_yotpo")
        return reviews, meta
    page = 1
    total_pages = 1
    while page <= total_pages:
        if limit_pages is not None and page > limit_pages:
            meta["limited_after_pages"] = limit_pages
            break
        try:
            payload = fetch_json(yotpo_reviews_url(product_id), {"per_page": REVIEWS_PER_PAGE, "page": page}, referer=product_url)
        except StopScrape:
            raise
        except (HTTPError, URLError, RuntimeError) as exc:
            meta["errors"].append(str(exc))
            break
        response = yotpo_response(payload)
        pagination = response.get("pagination") if isinstance(response.get("pagination"), dict) else {}
        total = int(pagination.get("total") or 0)
        per_page = int(pagination.get("per_page") or REVIEWS_PER_PAGE)
        total_pages = max(1, (total + per_page - 1) // per_page)
        if page == 1:
            meta["review_count_hint"] = total
            meta["review_pages_available"] = total_pages
        page_reviews = [item for item in response.get("reviews", []) if isinstance(item, dict)]
        if not page_reviews:
            break
        for review in page_reviews:
            review_id = str(review.get("id") or "")
            if review_id and review_id in seen_review_ids:
                continue
            seen_review_ids.add(review_id)
            if review_image_urls(review):
                reviews.append(review)
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"]) + 1
        page += 1
        if request_delay_seconds > 0 and page <= total_pages:
            time.sleep(request_delay_seconds)
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
    images = review.get("images_data") or review.get("imagesData")
    if not isinstance(images, list):
        return urls
    for image in images:
        if not isinstance(image, dict):
            continue
        url = normalize_whitespace(
            str(image.get("original_url") or image.get("originalUrl") or image.get("thumb_url") or image.get("thumbUrl") or "")
        )
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


def yotpo_review_value(review: Dict[str, object], snake_key: str, camel_key: str) -> object:
    return review.get(snake_key) if snake_key in review else review.get(camel_key)


def product_variants_text(review: Dict[str, object]) -> Tuple[str, str, str]:
    variants = review.get("productVariants")
    if not isinstance(variants, dict):
        return "", "", ""
    size = normalize_whitespace(str(variants.get("Size") or variants.get("size") or ""))
    color = normalize_whitespace(str(variants.get("Color") or variants.get("color") or ""))
    raw = " / ".join(part for part in [color, size] if part)
    return color, size, raw


def classify_title_product_type(title: str) -> str:
    value = title.lower()
    if "short" in value:
        return "shorts"
    if "bikini" in value or "thong" in value or "underwear" in value or "brief" in value:
        return "underwear"
    if "tank" in value or "camisole" in value:
        return "top"
    if "bra" in value:
        return "bra"
    return ""


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
    date_created = normalize_whitespace(str(yotpo_review_value(review, "created_at", "createdAt") or ""))
    review_date = date_created.split("T", 1)[0] if "T" in date_created else date_created
    user = review.get("user") if isinstance(review.get("user"), dict) else {}
    reviewer_name = strip_tags(str(user.get("display_name") or user.get("displayName") or user.get("name") or ""))
    color_display = ""
    size_display = extract_size_from_text(text_pool)
    variant_color, variant_size, variant_raw = product_variants_text(review)
    if variant_color:
        color_display = variant_color
    if variant_size:
        size_display = variant_size
    custom_fields = review.get("custom_fields") if isinstance(review.get("custom_fields"), dict) else {}
    if not custom_fields and isinstance(review.get("customFields"), dict):
        custom_fields = review.get("customFields")
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
    if not size_display and bust_in and cupsize:
        size_display = f"{bust_in}{cupsize}"
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
                "image_source_type": "customer_review_image",
                "image_source_detail": "yotpo_review_images_data",
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
                "product_variant_raw": variant_raw,
            }
        )
    return rows


def product_from_yotpo_store_item(item: Dict[str, object]) -> Dict[str, object]:
    domain_key = normalize_whitespace(str(item.get("domainKey") or item.get("domain_key") or ""))
    name = normalize_whitespace(str(item.get("name") or ""))
    handle = ""
    tags = item.get("productTags") or item.get("product_tags") or []
    if isinstance(tags, list):
        tags = [tag.get("tag") for tag in tags if isinstance(tag, dict) and tag.get("tag")]
    return {
        "id": domain_key,
        "title": name,
        "handle": handle,
        "body_html": "",
        "product_type": classify_title_product_type(name),
        "tags": tags,
        "variants": [],
        "_discovered_from_yotpo_store_feed": True,
    }


def fetch_store_reviews_v3(
    products: List[Dict[str, object]],
    limit_pages: Optional[int],
    request_delay_seconds: float,
    fetched_at: str,
) -> Tuple[List[Dict[str, str]], Dict[str, object], Dict[str, Dict[str, object]]]:
    products_by_shopify_id = {
        normalize_whitespace(str(product.get("id") or "")): product
        for product in products
        if normalize_whitespace(str(product.get("id") or ""))
    }
    yotpo_products: Dict[str, Dict[str, object]] = {}
    rows: List[Dict[str, str]] = []
    errors: List[str] = []
    page = 1
    total_pages = 1
    reviews_seen = 0
    media_reviews_seen = 0
    product_stats: Dict[str, Dict[str, object]] = {}
    while page <= total_pages:
        if limit_pages is not None and page > limit_pages:
            break
        try:
            payload = fetch_json(yotpo_store_reviews_url(), {"perPage": REVIEWS_PER_PAGE, "page": page}, referer=SOURCE_SITE)
        except StopScrape:
            raise
        except (HTTPError, URLError, RuntimeError) as exc:
            errors.append(str(exc))
            break
        pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
        total = int(pagination.get("total") or 0)
        per_page = int(pagination.get("perPage") or REVIEWS_PER_PAGE)
        total_pages = max(1, (total + per_page - 1) // per_page)
        for item in payload.get("products") or []:
            if not isinstance(item, dict):
                continue
            internal_id = normalize_whitespace(str(item.get("id") or ""))
            if internal_id:
                yotpo_products[internal_id] = item
        page_reviews = [review for review in payload.get("reviews") or [] if isinstance(review, dict)]
        reviews_seen += len(page_reviews)
        for review in page_reviews:
            if not review_image_urls(review):
                continue
            media_reviews_seen += 1
            internal_product_id = normalize_whitespace(str(review.get("product_id") or review.get("productId") or ""))
            yotpo_product = yotpo_products.get(internal_product_id, {})
            domain_key = normalize_whitespace(str(yotpo_product.get("domainKey") or yotpo_product.get("domain_key") or ""))
            product = products_by_shopify_id.get(domain_key)
            if not product and yotpo_product:
                product = product_from_yotpo_store_item(yotpo_product)
            if not product:
                continue
            if skip_reason(product):
                continue
            review_rows = parse_review_rows(review, product, fetched_at)
            rows.extend(review_rows)
            product_url = product_url_for(product) or domain_key
            stat = product_stats.setdefault(
                product_url,
                {
                    "product_url": product_url,
                    "product_title": product.get("title"),
                    "shopify_product_id": domain_key,
                    "adapter_used": "yotpo_v3_store_feed",
                    "store_reviews_seen": 0,
                    "store_media_reviews": 0,
                    "matching_review_images": 0,
                    "rows": 0,
                },
            )
            stat["store_reviews_seen"] = int(stat["store_reviews_seen"]) + 1
            stat["store_media_reviews"] = int(stat["store_media_reviews"]) + 1
            stat["matching_review_images"] = int(stat["matching_review_images"]) + len(review_rows)
            stat["rows"] = int(stat["rows"]) + len(review_rows)
        print(f"[store review page {page}/{total_pages}] reviews={len(page_reviews)} rows={len(rows)}", flush=True)
        page += 1
        if request_delay_seconds > 0 and page <= total_pages:
            time.sleep(request_delay_seconds)
    return rows, {
        "store_review_pages_scanned": page - 1,
        "store_review_pages_available": total_pages,
        "store_reviews_seen": reviews_seen,
        "store_media_reviews_seen": media_reviews_seen,
        "store_errors": errors,
        "store_exhaustive_review_paging": page > total_pages and not errors and limit_pages is None,
    }, product_stats


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


def scrape_reviews(
    limit_products: Optional[int] = None,
    limit_pages_per_product: Optional[int] = None,
    request_delay_seconds: float = 0.0,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    discovery_method = "shopify_products_json"
    discovery_errors: List[str] = []
    try:
        products, product_sources = discover_products(limit_products=limit_products)
        discovery_method = "shopify_products_json_sitemap_and_lead_urls"
    except Exception as exc:  # noqa: BLE001
        discovery_errors.append(str(exc))
        products = cached_products_from_summary(limit_products=limit_products)
        product_sources = {"cached_previous_summary_product_list": len(products)}
        discovery_method = "cached_previous_summary_product_list"
    if not products:
        raise RuntimeError("No Evelyn Bobbie products discovered from Shopify or cached summary.")
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": "evelynbobbie_com",
        "adapter": "yotpo_product_level_plus_v3_store_feed",
        "yotpo_app_key": YOTPO_APP_KEY,
        "shop_domain": SHOP_DOMAIN,
        "started_at": fetched_at,
        "products_discovered": len(products),
        "product_sources": product_sources,
        "discovery_method": discovery_method,
        "catalog_discovery_errors": discovery_errors,
        "products_scanned": 0,
        "products_excluded_from_output": 0,
        "exhaustive_review_paging": limit_pages_per_product is None,
        "limit_pages_per_product": limit_pages_per_product,
        "request_delay_seconds": request_delay_seconds,
        "products_with_review_rows": 0,
        "review_pages_scanned": 0,
        "product_review_count_hint": 0,
        "access_policy": "public_product_and_review_pages_only; stop_immediately_on_429_captcha_or_waf_like_response",
        "measurement_extraction": "deterministic_regex_and_provider_fields_only",
        "errors": [],
    }
    for index, product in enumerate(products, start=1):
        reason = skip_reason(product)
        reviews, product_meta = fetch_product_reviews(
            product,
            limit_pages=limit_pages_per_product,
            request_delay_seconds=request_delay_seconds,
        )
        product_rows: List[Dict[str, str]] = []
        if not reason:
            for review in reviews:
                product_rows.extend(parse_review_rows(review, product, fetched_at))
        product_summaries.append({**product_meta, "product_index": index, "rows": len(product_rows), "skipped_from_output": bool(reason), "skip_reason": reason})
        summary["products_scanned"] = int(summary["products_scanned"]) + 1
        summary["products_excluded_from_output"] = int(summary["products_excluded_from_output"]) + (1 if reason else 0)
        summary["review_pages_scanned"] = int(summary["review_pages_scanned"]) + int(product_meta.get("review_pages_scanned") or 0)
        summary["product_review_count_hint"] = int(summary["product_review_count_hint"]) + int(product_meta.get("review_count_hint") or 0)
        if product_rows:
            summary["products_with_review_rows"] = int(summary["products_with_review_rows"]) + 1
        if product_meta.get("errors"):
            summary["errors"].append(product_meta)
        rows.extend(product_rows)
        print(
            f"[product {index}/{len(products)}] pages={product_meta.get('review_pages_scanned')} "
            f"image_reviews={len(reviews)} rows={len(product_rows)} url={product_meta.get('product_url')}",
            flush=True,
        )
    store_rows, store_meta, store_product_stats = fetch_store_reviews_v3(
        products,
        limit_pages=limit_pages_per_product,
        request_delay_seconds=request_delay_seconds,
        fetched_at=fetched_at,
    )
    rows.extend(store_rows)
    for product_summary in product_summaries:
        product_url = normalize_whitespace(str(product_summary.get("product_url") or ""))
        store_stat = store_product_stats.get(product_url)
        if not store_stat:
            continue
        product_summary["store_reviews_seen"] = store_stat.get("store_reviews_seen", 0)
        product_summary["store_media_reviews"] = store_stat.get("store_media_reviews", 0)
        product_summary["store_matching_review_images"] = store_stat.get("matching_review_images", 0)
        product_summary["store_rows"] = store_stat.get("rows", 0)
        product_summary["matching_review_images"] = int(product_summary.get("matching_review_images") or 0) + int(store_stat.get("matching_review_images") or 0)
        product_summary["rows"] = int(product_summary.get("rows") or 0) + int(store_stat.get("rows") or 0)
    for product_url, store_stat in store_product_stats.items():
        if any(product_url == normalize_whitespace(str(item.get("product_url") or "")) for item in product_summaries):
            continue
        product_summaries.append({**store_stat, "product_index": None, "review_pages_scanned": 0, "review_count_hint": 0, "errors": []})
    summary["review_pages_scanned"] = int(summary["review_pages_scanned"]) + int(store_meta.get("store_review_pages_scanned") or 0)
    summary.update(store_meta)
    if store_meta.get("store_errors"):
        summary["errors"].append({"scope": "yotpo_v3_store_feed", "errors": store_meta.get("store_errors")})
    summary["product_summaries"] = product_summaries
    summary["finished_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    deduped = dedupe_rows(rows)
    summary["products_with_review_rows"] = len({row.get("product_page_url_display") for row in deduped if row.get("product_page_url_display")})
    return deduped, summary


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
    limit_pages_per_product: Optional[int] = None
    if "--limit-pages-per-product" in argv:
        index = argv.index("--limit-pages-per-product")
        limit_pages_per_product = int(argv[index + 1])
    request_delay_seconds = 0.0
    if "--request-delay-seconds" in argv:
        index = argv.index("--request-delay-seconds")
        request_delay_seconds = float(argv[index + 1])
    rows, summary = scrape_reviews(
        limit_products=limit_products,
        limit_pages_per_product=limit_pages_per_product,
        request_delay_seconds=request_delay_seconds,
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
