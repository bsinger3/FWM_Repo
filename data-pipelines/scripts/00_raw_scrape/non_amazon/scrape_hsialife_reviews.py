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

PIPELINE_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, legacy_raw_run_dir, raw_scraped_data_root, reports_root  # noqa: E402
from typing import Dict, List, Optional, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = legacy_raw_run_dir("hsialife_com")
OUTPUT_CSV = OUTPUT_DIR / "hsialife_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "hsialife_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://www.hsialife.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
OKENDO_STORE_ID = "0cc616d6-d35d-46a6-af6c-6a54931b1b18"
OKENDO_API_ROOT = f"https://api.okendo.io/v1/stores/{OKENDO_STORE_ID}"
BRAND = "HSIA"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36"
CHALLENGE_RE = re.compile(r"\b(?:captcha|cloudflare|datadome|perimeterx|challenge|access denied|blocked)\b", re.I)

HEADERS = [
    "created_at_display", "id", "original_url_display", "product_page_url_display", "monetized_product_url_display",
    "height_raw", "weight_raw", "user_comment", "date_review_submitted_raw", "height_in_display", "review_date",
    "source_site_display", "status_code", "content_type", "bytes", "width", "height", "hash_md5", "fetched_at",
    "updated_at", "brand", "waist_raw_display", "hips_raw", "age_raw", "waist_in", "hips_in_display",
    "age_years_display", "search_fts", "weight_display_display", "weight_raw_needs_correction", "clothing_type_id",
    "reviewer_profile_url", "reviewer_name_raw", "inseam_inches_display", "color_canonical", "color_display",
    "size_display", "bust_in_number_display", "cupsize_display", "weight_lbs_display", "weight_lbs_raw_issue",
    "product_title_raw", "product_subtitle_raw", "product_description_raw", "product_detail_raw",
    "product_category_raw", "product_variant_raw",
]

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
HEIGHT_RE = re.compile(r"\b([4-6])\s*(?:ft|feet|foot|['\u2019])\s*(\d{1,2})?\s*(?:in|inches|[\"\u201d])?", re.I)
WEIGHT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?|#)\b", re.I)
WAIST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b", re.I)
HIPS_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*inseam\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
BRA_RE = re.compile(r"\b((?:2[8-9]|3[0-9]|4[0-8])\s*(?:aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k)(?:/[a-z]+)?)\b", re.I)
SIZE_ORDERED_RE = re.compile(r"\b(?:size|ordered|wear(?:ing)?|bought)\s*(?:a|an|the|is|:)?\s*((?:2[8-9]|3[0-9]|4[0-8])\s*(?:aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k)(?:/[a-z]+)?|xxs|xs|s|m|l|xl|xxl|2xl|3xl|4xl|\d{1,2})\b", re.I)
APPAREL_SIZE_RE = re.compile(r"^(?:xxs|xs|s|m|l|xl|xxl|xxxl|2xl|3xl|4xl|\d{1,2})$", re.I)


class StopScrape(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm(text: object) -> str:
    return WS_RE.sub(" ", str(text or "")).strip()


def strip_tags(value: object) -> str:
    text = re.sub(r"</p\s*>|<br\s*/?>", " ", str(value or ""), flags=re.I)
    return norm(html.unescape(TAG_RE.sub(" ", text)))


def fetch_text(url: str, retries: int = 5) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        try:
            with urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8", "replace")
                if CHALLENGE_RE.search(text[:4000]):
                    raise StopScrape(f"Challenge-like response while fetching {url}")
                return text
        except (HTTPError, URLError) as exc:
            last_error = exc
            if isinstance(exc, HTTPError) and exc.code == 429:
                raise StopScrape(f"HTTP 429 rate limit while fetching {url}") from exc
            if isinstance(exc, HTTPError) and exc.code not in {500, 502, 503, 504}:
                raise
        time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"Failed text request for {url}: {last_error}")


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, referer: Optional[str] = None, retries: int = 5) -> Dict[str, object]:
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
                raw = resp.read().decode("utf-8", "replace")
                if CHALLENGE_RE.search(raw[:4000]):
                    raise StopScrape(f"Challenge-like response while fetching {query_url}")
                return json.loads(raw)
        except HTTPError as exc:
            last_error = exc
            if exc.code == 429:
                raise StopScrape(f"HTTP 429 rate limit while fetching {query_url}") from exc
            if exc.code not in {500, 502, 503, 504}:
                raise
        except (URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"Failed JSON request for {query_url}: {last_error}")


def product_url_for(product: Dict[str, object]) -> str:
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def fetch_products(limit_products: Optional[int] = None) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    sources: List[Dict[str, object]] = []
    page = 1
    while True:
        payload = fetch_json(PRODUCTS_JSON_URL, {"limit": PRODUCTS_PER_PAGE, "page": page})
        page_products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        sources.append({"source": "products.json", "page": page, "count": len(page_products)})
        if not page_products:
            break
        products.extend(page_products)
        if len(page_products) < PRODUCTS_PER_PAGE or (limit_products and len(products) >= limit_products):
            break
        page += 1

    sitemap_index = fetch_text(SITEMAP_URL)
    sitemap_urls = [html.unescape(url) for url in re.findall(r"<loc>(https://www\.hsialife\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index)]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        if "/en-" in sitemap_url:
            continue
        text = fetch_text(sitemap_url)
        urls = sorted(set(re.findall(r"https://www\.hsialife\.com/products/[^<\s\"']+", text)))
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        sitemap_product_urls.extend(urls)

    by_url: Dict[str, Dict[str, object]] = {product_url_for(product): product for product in products if product_url_for(product)}
    missing = [url for url in sorted(set(sitemap_product_urls)) if url not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {"id": "", "handle": handle, "title": handle.replace("-", " ").title(), "product_type": "", "body_html": "", "variants": []}
    sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)})
    products_out = list(by_url.values())
    if limit_products:
        products_out = products_out[:limit_products]
    return products_out, sources


def okendo_reviews_url(product_id: object) -> str:
    return f"{OKENDO_API_ROOT}/products/shopify-{product_id}/reviews"


def okendo_store_reviews_url() -> str:
    return f"{OKENDO_API_ROOT}/reviews"


def normalize_product_url(value: object, fallback: str) -> str:
    text = norm(value)
    if text.startswith("//"):
        return "https:" + text
    if text.startswith("/"):
        return urljoin(SITE_ROOT, text)
    return text or fallback


def media_urls(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    media = review.get("media")
    if not isinstance(media, list):
        return urls
    for item in media:
        if not isinstance(item, dict):
            continue
        if norm(item.get("type")).lower() not in {"", "image", "photo"}:
            continue
        image_urls = item.get("imageUrls") if isinstance(item.get("imageUrls"), dict) else {}
        url = norm(
            item.get("fullSizeUrl")
            or item.get("largeUrl")
            or item.get("url")
            or item.get("thumbnailUrl")
            or image_urls.get("fullSizeUrl")
            or image_urls.get("largeUrl")
            or image_urls.get("originalUrl")
            or image_urls.get("thumbnailUrl")
        )
        if url and url not in urls:
            urls.append(url)
    return urls


def maybe_num(value: Optional[float]) -> str:
    if value is None:
        return ""
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def parse_num(pattern: re.Pattern[str], text: str, max_value: Optional[float] = None) -> Tuple[str, Optional[float]]:
    match = pattern.search(text)
    if not match:
        return "", None
    value = float(match.group(1))
    if max_value is not None and value > max_value:
        return "", None
    return norm(match.group(0)), value


def parse_height(text: str) -> Tuple[str, Optional[float]]:
    match = HEIGHT_RE.search(text)
    if not match:
        return "", None
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    if 4 <= feet <= 7 and 0 <= inches <= 11:
        return norm(match.group(0)), feet * 12 + inches
    return "", None


def parse_age(text: str) -> Tuple[str, str]:
    match = AGE_RE.search(text)
    return (norm(match.group(0)), match.group(1) or match.group(2) or "") if match else ("", "")


def parse_bra(text: str) -> Tuple[str, str]:
    match = BRA_RE.search(text)
    if not match:
        return "", ""
    compact = re.sub(r"\s+", "", match.group(1)).upper()
    band = re.match(r"(\d{2})", compact)
    cup = re.search(r"[A-Z]+(?:/[A-Z]+)?$", compact)
    return (band.group(1) if band else "", cup.group(0) if cup else "")


def parse_variant(variant: object) -> Tuple[str, str, str, str, str]:
    text = norm(variant)
    if not text:
        return "", "", "", "", ""
    parts = [part.strip() for part in text.split("/") if part.strip()]
    color = parts[0] if parts else ""
    size = ""
    bust = ""
    cup = ""
    first_bust, first_cup = parse_bra(parts[0] if parts else "")
    if len(parts) >= 2 and first_bust and first_cup:
        size = re.sub(r"\s+", "", parts[0]).upper()
        bust = first_bust
        cup = first_cup
        color = parts[-1]
    elif len(parts) >= 3 and re.fullmatch(r"\d{2}", parts[-2]) and re.fullmatch(r"[A-Za-z]+(?:/[A-Za-z]+)?", parts[-1]):
        bust = parts[-2]
        cup = parts[-1].upper()
        size = f"{bust}{cup}"
    elif len(parts) >= 2 and APPAREL_SIZE_RE.fullmatch(parts[0]) and not APPAREL_SIZE_RE.fullmatch(parts[-1]):
        size = parts[0].upper()
        color = parts[-1]
    elif len(parts) >= 2:
        size = parts[-1]
        bust, cup = parse_bra(size)
    return color, color.lower(), size, bust or "", cup


def attr_text(attrs: object) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not isinstance(attrs, list):
        return out
    for item in attrs:
        if not isinstance(item, dict):
            continue
        title = norm(item.get("title")).strip().rstrip(":").lower()
        value = item.get("value")
        if isinstance(value, list):
            text = " | ".join(norm(v) for v in value if norm(v))
        else:
            text = norm(value)
        if title and text:
            out[title] = text
    return out


def attribute_text(review: Dict[str, object]) -> str:
    parts: List[str] = []
    for source in (review.get("productAttributes"), review.get("attributesWithRating")):
        for title, value in attr_text(source).items():
            parts.append(f"{title}: {value}")
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    for title, value in attr_text(reviewer.get("attributes") if isinstance(reviewer, dict) else None).items():
        parts.append(f"{title}: {value}")
    return " ".join(parts)


def parse_size(review: Dict[str, object], text: str, variant_size: str) -> str:
    product_attrs = attr_text(review.get("productAttributes"))
    for key in ("size ordered", "size purchased", "purchased size", "size"):
        if product_attrs.get(key):
            return product_attrs[key]
    if variant_size:
        return variant_size
    match = SIZE_ORDERED_RE.search(text)
    if not match:
        return ""
    return re.sub(r"\s+", "", match.group(1)).upper()


def skip_reason(product: Dict[str, object]) -> str:
    title_type = " ".join([
        norm(product.get("title")),
        norm(product.get("product_type")),
    ]).lower()
    hay = " ".join([
        norm(product.get("title")),
        norm(product.get("product_type")),
        " ".join(norm(tag) for tag in product.get("tags", []) if isinstance(tag, str)),
    ]).lower()
    product_type = norm(product.get("product_type")).lower()
    if "gift card" in hay or "e-gift" in hay:
        return "out_of_scope_gift_card"
    if product_type in {"bra accessories", "accessories"} or re.search(r"\b(accessor(?:y|ies)|extenders?|breast petals?|nipple covers?|concealers?|adhesive|tape|laundry bag)\b", title_type):
        return "out_of_scope_accessory"
    if re.search(r"\b(kids|girls|toddler|infant|baby)\b", hay):
        return "out_of_scope_kids"
    if re.search(r"\b(mens|men's)\b", hay):
        return "out_of_scope_mens"
    return ""


def variant_detail(product: Dict[str, object]) -> str:
    vals: List[str] = []
    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants[:200]:
            if isinstance(variant, dict):
                title = norm(variant.get("title"))
                if title and title.lower() != "default title" and title not in vals:
                    vals.append(title)
    return " | ".join(vals)


def classify(product: Dict[str, object]) -> str:
    value = f"{product.get('title') or ''} {product.get('product_type') or ''}".lower()
    if "panty" in value or "underwear" in value or "brief" in value:
        return "underwear"
    if "swim" in value or "bikini" in value:
        return "swimwear"
    if "bra" in value or "bralette" in value:
        return "bra"
    return "womens_clothing"


def fetch_product_reviews(product: Dict[str, object], limit_pages: Optional[int] = None) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    product_url = product_url_for(product)
    meta: Dict[str, object] = {
        "product_url": product_url,
        "product_title": product.get("title"),
        "adapter_used": "okendo_product_level",
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "matching_review_images": 0,
        "errors": [],
    }
    product_id = product.get("id")
    if not product_id:
        meta["errors"].append("missing_shopify_product_id")
        return [], meta

    reviews: List[Dict[str, object]] = []
    seen = set()
    url = okendo_reviews_url(product_id)
    params: Optional[Dict[str, object]] = {"limit": REVIEWS_PER_PAGE, "orderBy": "date desc"}
    while url:
        if limit_pages is not None and int(meta["review_pages_scanned"]) >= limit_pages:
            break
        try:
            payload = fetch_json(url, params=params, referer=product_url)
        except Exception as exc:  # noqa: BLE001
            meta["errors"].append(str(exc))
            break
        params = None
        page_reviews = [item for item in payload.get("reviews", []) if isinstance(item, dict)]
        if not page_reviews:
            break
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"]) + 1
        for review in page_reviews:
            review_id = norm(review.get("reviewId"))
            if review_id and review_id in seen:
                continue
            seen.add(review_id)
            reviews.append(review)
        next_url = norm(payload.get("nextUrl"))
        url = "https://api.okendo.io/v1" + next_url if next_url.startswith("/stores/") else ""
    meta["review_count_hint"] = len(reviews)
    meta["matching_review_images"] = sum(len(media_urls(review)) for review in reviews)
    return reviews, meta


def row_for(product: Dict[str, object], review: Dict[str, object], image_url: str, image_index: int) -> Dict[str, str]:
    text_parts = [norm(review.get("title")), strip_tags(review.get("body")), attribute_text(review)]
    variant_name = norm(review.get("productVariantName"))
    if variant_name:
        text_parts.append(f"Variant: {variant_name}")
    text = norm(" ".join(part for part in text_parts if part))

    height_raw, height_in = parse_height(text)
    weight_raw, weight = parse_num(WEIGHT_RE, text, 500)
    waist_raw, waist = parse_num(WAIST_RE, text, 80)
    hips_raw, hips = parse_num(HIPS_RE, text, 90)
    inseam_raw, inseam = parse_num(INSEAM_RE, text, 50)
    age_raw, age = parse_age(text)
    color_display, color_canonical, variant_size, bust, cup_from_variant = parse_variant(variant_name)
    size_display = parse_size(review, text, variant_size)
    bust_from_text, cup = parse_bra(text)
    if not bust:
        bust = bust_from_text
    if not cup:
        cup = cup_from_variant
    if not size_display and bust and cup:
        size_display = f"{bust}{cup}"

    product_url = normalize_product_url(review.get("productUrl"), product_url_for(product))
    if not product_url and norm(review.get("productHandle")):
        product_url = f"{SITE_ROOT}/products/{quote(norm(review.get('productHandle')), safe='/-._~')}"
    product_title = norm(review.get("productName") or product.get("title"))
    detail = variant_detail(product)
    review_id = norm(review.get("reviewId")) or f"{product.get('id')}-{image_index}"
    fetched = now_iso()
    return {
        "created_at_display": fetched,
        "id": f"{review_id}-{image_index}",
        "original_url_display": image_url,
        "product_page_url_display": product_url,
        "monetized_product_url_display": product_url,
        "height_raw": height_raw,
        "weight_raw": weight_raw,
        "user_comment": text,
        "date_review_submitted_raw": norm(review.get("dateCreated")),
        "height_in_display": maybe_num(height_in),
        "review_date": norm(review.get("dateCreated"))[:10],
        "source_site_display": SOURCE_SITE,
        "status_code": "",
        "content_type": "",
        "bytes": "",
        "width": "",
        "height": "",
        "hash_md5": "",
        "fetched_at": fetched,
        "updated_at": fetched,
        "brand": BRAND,
        "waist_raw_display": waist_raw,
        "hips_raw": hips_raw,
        "age_raw": age_raw,
        "waist_in": maybe_num(waist),
        "hips_in_display": maybe_num(hips),
        "age_years_display": age,
        "search_fts": text,
        "weight_display_display": maybe_num(weight),
        "weight_raw_needs_correction": "",
        "clothing_type_id": classify(product),
        "reviewer_profile_url": "",
        "reviewer_name_raw": norm((review.get("reviewer") or {}).get("displayName") if isinstance(review.get("reviewer"), dict) else ""),
        "inseam_inches_display": maybe_num(inseam),
        "color_canonical": color_canonical,
        "color_display": color_display,
        "size_display": size_display,
        "bust_in_number_display": bust,
        "cupsize_display": cup,
        "weight_lbs_display": maybe_num(weight),
        "weight_lbs_raw_issue": "",
        "product_title_raw": product_title,
        "product_subtitle_raw": norm(review.get("title")),
        "product_description_raw": strip_tags(product.get("body_html")),
        "product_detail_raw": detail,
        "product_category_raw": norm(product.get("product_type")),
        "product_variant_raw": variant_name,
    }


def product_key(product: Dict[str, object]) -> str:
    return norm(product.get("id")) or norm(product.get("handle")) or product_url_for(product)


def context_product_from_review(
    review: Dict[str, object],
    products_by_id: Dict[str, Dict[str, object]],
    products_by_handle: Dict[str, Dict[str, object]],
) -> Dict[str, object]:
    product_id = norm(review.get("productId")).removeprefix("shopify-")
    handle = norm(review.get("productHandle"))
    product = products_by_id.get(product_id) or products_by_handle.get(handle)
    if product:
        return product
    product_url = normalize_product_url(review.get("productUrl"), "")
    fallback_handle = handle or product_url.rstrip("/").rsplit("/", 1)[-1]
    return {
        "id": product_id,
        "handle": fallback_handle,
        "title": norm(review.get("productName")),
        "product_type": "",
        "body_html": "",
        "variants": [],
        "_from_store_review_only": True,
    }


def fetch_store_reviews(
    products: List[Dict[str, object]],
    limit_pages: Optional[int] = None,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    products_by_id = {norm(product.get("id")): product for product in products if norm(product.get("id"))}
    products_by_handle = {norm(product.get("handle")): product for product in products if norm(product.get("handle"))}
    rows: List[Dict[str, str]] = []
    errors: List[str] = []
    product_stats: Dict[str, Dict[str, object]] = {}
    skipped_media_rows = 0
    skipped_media_reviews = 0
    reviews_seen = 0
    media_reviews_seen = 0
    pages = 0
    url = okendo_store_reviews_url()
    params: Optional[Dict[str, object]] = {"limit": REVIEWS_PER_PAGE}
    seen_review_ids: Set[str] = set()

    while url:
        if limit_pages is not None and pages >= limit_pages:
            break
        try:
            payload = fetch_json(url, params=params, referer=SOURCE_SITE)
        except StopScrape:
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            break
        params = None
        page_reviews = [item for item in payload.get("reviews", []) if isinstance(item, dict)]
        if not page_reviews:
            break
        pages += 1
        reviews_seen += len(page_reviews)
        for review in page_reviews:
            review_id = norm(review.get("reviewId"))
            if review_id and review_id in seen_review_ids:
                continue
            if review_id:
                seen_review_ids.add(review_id)
            product = context_product_from_review(review, products_by_id, products_by_handle)
            key = product_key(product)
            urls = media_urls(review)
            reason = skip_reason(product)
            stats = product_stats.setdefault(
                key,
                {
                    "product_id": norm(product.get("id")),
                    "product_title": norm(product.get("title") or review.get("productName")),
                    "product_url": product_url_for(product) or normalize_product_url(review.get("productUrl"), ""),
                    "product_type": norm(product.get("product_type")),
                    "adapter_used": "okendo_store_level",
                    "review_count_hint": 0,
                    "review_pages_scanned": 0,
                    "matching_review_images": 0,
                    "rows": 0,
                    "skipped_from_output": bool(reason),
                    "skip_reason": reason,
                    "errors": [],
                },
            )
            stats["review_count_hint"] = int(stats["review_count_hint"]) + 1
            stats["matching_review_images"] = int(stats["matching_review_images"]) + len(urls)
            if urls:
                media_reviews_seen += 1
            if reason:
                skipped_media_rows += len(urls)
                skipped_media_reviews += 1 if urls else 0
                continue
            for image_index, image_url in enumerate(urls, start=1):
                rows.append(row_for(product, review, image_url, image_index))
                stats["rows"] = int(stats["rows"]) + 1
        print(f"[review page {pages}] reviews={len(page_reviews)} total_reviews={reviews_seen} rows={len(rows)}", flush=True)
        next_url = norm(payload.get("nextUrl"))
        url = urljoin("https://api.okendo.io/v1/", next_url.lstrip("/")) if next_url else ""

    return rows, {
        "review_pages_scanned": pages,
        "reviews_seen": reviews_seen,
        "media_reviews_seen": media_reviews_seen,
        "skipped_out_of_scope_media_reviews": skipped_media_reviews,
        "skipped_out_of_scope_media_rows": skipped_media_rows,
        "product_summaries": product_stats,
        "errors": errors,
        "store_feed_complete": not bool(url),
    }


def is_measurement_row(row: Dict[str, str]) -> bool:
    fields = ["height_in_display", "weight_lbs_display", "bust_in_number_display", "hips_in_display", "waist_in", "inseam_inches_display"]
    return any(norm(row.get(field)) for field in fields)


def main(argv: List[str]) -> int:
    limit_products: Optional[int] = None
    limit_pages: Optional[int] = None
    if "--limit-products" in argv:
        limit_products = int(argv[argv.index("--limit-products") + 1])
    if "--limit-pages-per-product" in argv:
        limit_pages = int(argv[argv.index("--limit-pages-per-product") + 1])

    started = now_iso()
    products, product_sources = fetch_products(limit_products=limit_products)
    print(f"Discovered {len(products)} products")
    try:
        store_rows, store_meta = fetch_store_reviews(products, limit_pages=limit_pages)
    except StopScrape as exc:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        SUMMARY_JSON.write_text(
            json.dumps(
                {
                    "site": "hsialife.com",
                    "adapter": "okendo_store_level",
                    "okendo_store_id": OKENDO_STORE_ID,
                    "product_sources": product_sources,
                    "products_discovered": len(products),
                    "products_scanned": 0,
                    "rows_written": 0,
                    "scrape_stopped": True,
                    "stop_reason": str(exc),
                    "started_at": started,
                    "finished_at": now_iso(),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"Stopped scrape: {exc}")
        return 2

    rows: List[Dict[str, str]] = list(store_rows)
    store_product_stats = store_meta.get("product_summaries") if isinstance(store_meta.get("product_summaries"), dict) else {}
    products_by_title = {norm(product.get("title")).lower(): product for product in products if norm(product.get("title"))}
    product_level_stats: Dict[str, Dict[str, object]] = {}
    product_level_pages = 0
    product_level_reviews = 0
    product_level_media = 0
    for idx, product in enumerate(products, start=1):
        reason = skip_reason(product)
        try:
            reviews, meta = fetch_product_reviews(product, limit_pages=limit_pages)
        except StopScrape as exc:
            store_meta.setdefault("errors", [])
            if isinstance(store_meta["errors"], list):
                store_meta["errors"].append(str(exc))
            break
        product_rows = 0
        image_count = 0
        for review in reviews:
            urls = media_urls(review)
            image_count += len(urls)
            if reason:
                continue
            row_product = products_by_title.get(norm(review.get("productName")).lower(), product)
            for image_index, image_url in enumerate(urls, start=1):
                rows.append(row_for(row_product, review, image_url, image_index))
                product_rows += 1
        product_level_pages += int(meta.get("review_pages_scanned") or 0)
        product_level_reviews += int(meta.get("review_count_hint") or 0)
        product_level_media += image_count
        product_level_stats[product_key(product)] = {
            "product_level_review_count_hint": int(meta.get("review_count_hint") or 0),
            "product_level_review_pages_scanned": int(meta.get("review_pages_scanned") or 0),
            "product_level_matching_review_images": image_count,
            "product_level_rows": product_rows,
            "product_level_errors": meta.get("errors") or [],
        }
        if idx % 50 == 0 or idx == len(products):
            print(f"[product feeds] scanned={idx}/{len(products)} product_rows={sum(int(item.get('product_level_rows') or 0) for item in product_level_stats.values())}", flush=True)

    product_summaries: List[Dict[str, object]] = []
    for idx, product in enumerate(products, start=1):
        key = product_key(product)
        reason = skip_reason(product)
        stats = dict(store_product_stats.get(key, {}))
        product_stats = product_level_stats.get(key, {})
        summary = {
            "product_index": idx,
            "product_id": product.get("id"),
            "product_title": product.get("title"),
            "product_url": product_url_for(product),
            "product_type": norm(product.get("product_type")),
            "adapter_used": "okendo_store_level_and_product_level",
            "review_count_hint": int(product_stats.get("product_level_review_count_hint") or stats.get("review_count_hint") or 0),
            "store_review_count_hint": int(stats.get("review_count_hint") or 0),
            "product_level_review_count_hint": int(product_stats.get("product_level_review_count_hint") or 0),
            "review_pages_scanned": int(product_stats.get("product_level_review_pages_scanned") or 0),
            "matching_review_images": int(product_stats.get("product_level_matching_review_images") or stats.get("matching_review_images") or 0),
            "store_matching_review_images": int(stats.get("matching_review_images") or 0),
            "product_level_matching_review_images": int(product_stats.get("product_level_matching_review_images") or 0),
            "rows": int(product_stats.get("product_level_rows") or 0) + int(stats.get("rows") or 0),
            "store_rows": int(stats.get("rows") or 0),
            "product_level_rows": int(product_stats.get("product_level_rows") or 0),
            "errors": list(stats.get("errors") or []) + list(product_stats.get("product_level_errors") or []),
            "skipped_from_output": bool(reason),
            "skip_reason": reason,
        }
        product_summaries.append(summary)
    catalog_keys = {product_key(product) for product in products}
    for stats in store_product_stats.values():
        if not isinstance(stats, dict) or norm(stats.get("product_id")) in catalog_keys:
            continue
        if norm(stats.get("product_id")) and norm(stats.get("product_id")) not in catalog_keys:
            product_summaries.append({
                "product_index": None,
                **stats,
                "review_pages_scanned": 0,
                "store_review_only": True,
            })

    seen_images = set()
    deduped: List[Dict[str, str]] = []
    for row in rows:
        key = (row["id"], row["original_url_display"])
        if key in seen_images:
            continue
        seen_images.add(key)
        deduped.append(row)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(deduped)

    rows_with_product_url = sum(1 for row in deduped if norm(row.get("product_page_url_display") or row.get("monetized_product_url_display")))
    rows_with_measurement = sum(1 for row in deduped if is_measurement_row(row))
    rows_with_image = sum(1 for row in deduped if norm(row.get("original_url_display")))
    rows_with_size = sum(1 for row in deduped if norm(row.get("size_display")) and norm(row.get("size_display")).lower() != "unknown")
    rows_supabase = sum(
        1
        for row in deduped
        if norm(row.get("original_url_display"))
        and norm(row.get("product_page_url_display") or row.get("monetized_product_url_display"))
        and is_measurement_row(row)
        and norm(row.get("size_display"))
    )
    summary = {
        "site": "hsialife.com",
        "adapter": "okendo_store_level_and_product_level",
        "okendo_store_id": OKENDO_STORE_ID,
        "product_sources": product_sources + [
            {
                "source": "okendo_store_reviews",
                "count": int(store_meta.get("reviews_seen") or 0),
                "media_reviews": int(store_meta.get("media_reviews_seen") or 0),
                "complete": bool(store_meta.get("store_feed_complete")),
            }
        ],
        "products_discovered": len(products),
        "products_scanned": len(products),
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "exhaustive_review_paging": limit_pages is None,
        "review_pages_scanned": int(store_meta.get("review_pages_scanned") or 0) + product_level_pages,
        "store_review_pages_scanned": int(store_meta.get("review_pages_scanned") or 0),
        "product_level_review_pages_scanned": product_level_pages,
        "product_review_count_hint": product_level_reviews,
        "store_reviews_seen": int(store_meta.get("reviews_seen") or 0),
        "store_media_reviews_seen": int(store_meta.get("media_reviews_seen") or 0),
        "product_level_reviews_seen": product_level_reviews,
        "product_level_media_images_seen": product_level_media,
        "raw_review_image_occurrences_before_dedupe": len(rows),
        "skipped_out_of_scope_media_reviews": int(store_meta.get("skipped_out_of_scope_media_reviews") or 0),
        "skipped_out_of_scope_media_rows": int(store_meta.get("skipped_out_of_scope_media_rows") or 0),
        "errors": store_meta.get("errors") or [],
        "rows_written": len(deduped),
        "distinct_reviews": len({row["id"].rsplit("-", 1)[0] for row in deduped}),
        "distinct_images": len({row["original_url_display"] for row in deduped}),
        "distinct_products": len({row["product_page_url_display"] for row in deduped}),
        "rows_with_distinct_product_url": len({row["product_page_url_display"] or row["monetized_product_url_display"] for row in deduped if row["product_page_url_display"] or row["monetized_product_url_display"]}),
        "rows_with_product_url": rows_with_product_url,
        "rows_with_any_measurement": rows_with_measurement,
        "rows_with_customer_image": rows_with_image,
        "rows_with_customer_ordered_size": rows_with_size,
        "rows_with_size": rows_with_size,
        "rows_supabase_qualified": rows_supabase,
        "output_csv": str(OUTPUT_CSV),
        "summary_json": str(SUMMARY_JSON),
        "started_at": started,
        "finished_at": now_iso(),
        "product_summaries": product_summaries,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(deduped)} rows to {OUTPUT_CSV}")
    print(f"Supabase-qualified rows: {rows_supabase}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
