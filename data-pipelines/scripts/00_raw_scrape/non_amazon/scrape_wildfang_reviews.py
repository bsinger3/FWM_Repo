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
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = legacy_raw_run_dir("wildfang_com")
OUTPUT_CSV = OUTPUT_DIR / "wildfang_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "wildfang_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://www.wildfang.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
OKENDO_STORE_ID = "5c043363-b18d-4bda-8184-c69c4fc0968e"
OKENDO_API_ROOT = f"https://api.okendo.io/v1/stores/{OKENDO_STORE_ID}"
BRAND = "Wildfang"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

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
BUST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*(?:bust|chest)\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*inseam\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
BRA_SIZE_RE = re.compile(r"\b((?:2[8-9]|3[0-9]|4[0-8])\s*(?:aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k))\b", re.I)
SIZE_RE = re.compile(
    r"\b(?:ordered|bought|purchased|got|wearing|wore|in a|size)\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:size\s*)?(xxs|xs|small|s|medium|m|large|l|xl|xlarge|x-large|1x|2x|3x|4x|5x|6x|"
    r"xsmall|x-small|xxl|xxxl|\d{1,2})\b",
    re.I,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(value: object) -> str:
    return WS_RE.sub(" ", str(value or "").replace("\xa0", " ")).strip()


def strip_tags(value: object) -> str:
    text = re.sub(r"</p\s*>|<br\s*/?>|</li\s*>", " ", str(value or ""), flags=re.I)
    return norm(html.unescape(TAG_RE.sub(" ", text)))


def fetch_text(url: str, retries: int = 5, referer: str = SOURCE_SITE) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/json,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": referer,
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", "replace")
        except (HTTPError, URLError) as exc:
            last_error = exc
            if isinstance(exc, HTTPError) and exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
        time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"Failed text request for {url}: {last_error}")


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, referer: str = SOURCE_SITE) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    return json.loads(fetch_text(query_url, referer=referer))


def product_url_for(product: Dict[str, object]) -> str:
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else norm(product.get("_url"))


def canonical_product_url(url: object, fallback: str = "") -> str:
    text = norm(url)
    if text.startswith("//"):
        text = "https:" + text
    if text.startswith("/"):
        text = urljoin(SITE_ROOT, text)
    if not text:
        text = fallback
    return text.split("?", 1)[0].rstrip("/")


def fetch_products(limit_products: Optional[int] = None) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    sources: List[Dict[str, object]] = []
    page = 1
    try:
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
    except Exception as exc:  # noqa: BLE001
        cached = cached_products_from_summary(limit_products)
        if cached:
            return cached, [{"source": "cached_previous_summary_product_list", "count": len(cached), "error": str(exc)}]
        raise

    sitemap_index = fetch_text(SITEMAP_URL)
    sitemap_urls = [
        html.unescape(url)
        for url in re.findall(r"<loc>(https://www\.wildfang\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index)
        if "/en-ca/" not in html.unescape(url)
    ]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url)
        urls = sorted(set(re.findall(r"https://www\.wildfang\.com/products/[^<\s\"']+", text)))
        urls = [canonical_product_url(html.unescape(url)) for url in urls]
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        sitemap_product_urls.extend(urls)

    by_url: Dict[str, Dict[str, object]] = {product_url_for(product): product for product in products if product_url_for(product)}
    missing = [url for url in sorted(set(sitemap_product_urls)) if url not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {"id": "", "handle": handle, "title": handle.replace("-", " ").title(), "product_type": "", "body_html": "", "variants": [], "_url": url}
    sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)})
    out = list(by_url.values())
    if limit_products:
        out = out[:limit_products]
    return out, sources


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
        product_id = norm(item.get("product_id"))
        product_url = canonical_product_url(item.get("product_url"))
        handle = product_url.rstrip("/").rsplit("/", 1)[-1] if "/products/" in product_url else ""
        if not product_id or not handle:
            continue
        products.append(
            {
                "id": product_id,
                "handle": handle,
                "title": norm(item.get("product_title")),
                "product_type": norm(item.get("product_type")),
                "body_html": "",
                "variants": [],
                "_url": product_url,
                "_cached_from_previous_summary": True,
            }
        )
        if limit_products and len(products) >= limit_products:
            break
    return products


def okendo_reviews_url(product_id: object) -> str:
    return f"{OKENDO_API_ROOT}/products/shopify-{product_id}/reviews"


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
        url = norm(item.get("fullSizeUrl") or item.get("largeUrl") or item.get("thumbnailUrl"))
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


def reviewer_attribute_text(review: Dict[str, object]) -> str:
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    attrs = reviewer.get("attributes") if isinstance(reviewer, dict) else []
    pieces: List[str] = []
    if isinstance(attrs, list):
        for attr in attrs:
            if isinstance(attr, dict):
                title = norm(attr.get("title"))
                value = norm(attr.get("value"))
                if title and value:
                    pieces.append(f"{title}: {value}")
    return norm(" ".join(pieces))


def normalize_size(value: object) -> str:
    text = norm(value).upper().replace(" ", "")
    aliases = {
        "XSMALL": "XS",
        "X-SMALL": "XS",
        "SMALL": "S",
        "MEDIUM": "M",
        "LARGE": "L",
        "XLARGE": "XL",
        "X-LARGE": "XL",
        "XXL": "2X",
        "XXXL": "3X",
    }
    return aliases.get(text, text)


def extract_size(review: Dict[str, object], text: str) -> str:
    variant = norm(review.get("productVariantName"))
    if variant and variant.lower() != "default title":
        return normalize_size(variant)
    match = SIZE_RE.search(text)
    return normalize_size(match.group(1)) if match else ""


def extract_bra_size(text: str) -> Tuple[str, str]:
    match = BRA_SIZE_RE.search(text)
    if not match:
        return "", ""
    raw = norm(match.group(1)).upper().replace(" ", "")
    band = re.match(r"\d+", raw)
    cup = re.search(r"[A-Z]+$", raw)
    return (band.group(0) if band else "", cup.group(0) if cup else "")


def variant_detail(product: Dict[str, object]) -> str:
    vals: List[str] = []
    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants[:250]:
            if isinstance(variant, dict):
                title = norm(variant.get("title"))
                if title and title.lower() != "default title" and title not in vals:
                    vals.append(title)
    return " | ".join(vals)


def classify(product: Dict[str, object], review: Optional[Dict[str, object]] = None) -> str:
    review = review or {}
    value = f"{product.get('title') or ''} {product.get('product_type') or ''} {review.get('productName') or ''}".lower()
    if "gift" in value or "sticker" in value:
        return ""
    if any(term in value for term in ["pant", "trouser", "bottom", "short"]):
        return "pants"
    if any(term in value for term in ["blazer", "jacket", "vest"]):
        return "jacket"
    if any(term in value for term in ["button up", "shirt", "tank", "tee", "top", "sweater"]):
        return "top"
    if "dress" in value:
        return "dress"
    if "coverall" in value or "jumpsuit" in value:
        return "jumpsuit"
    return norm(product.get("product_type")).lower()


def output_skip_reason(product: Dict[str, object]) -> str:
    value = f"{product.get('title') or ''} {product.get('product_type') or ''} {' '.join(product.get('tags') or []) if isinstance(product.get('tags'), list) else ''}".lower()
    if "gift card" in value:
        return "out_of_scope_gift_card"
    if "shipping protection" in value or "insurance" in value:
        return "out_of_scope_shipping_protection"
    if "dog" in value or "pets" in value:
        return "out_of_scope_pet_item"
    accessory_re = re.compile(r"\b(sticker|pin|beanie|hat|cap|bag|tote|tie|bolo|suspenders|belt|scarf|collar clip|tie bar)\b")
    if accessory_re.search(value):
        return "out_of_scope_accessory"
    return ""


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
    total = payload.get("total") if "payload" in locals() and isinstance(payload.get("total"), dict) else {}
    meta["review_count_hint"] = int(total.get("count") or len(reviews))
    meta["matching_review_images"] = sum(len(media_urls(review)) for review in reviews)
    return reviews, meta


def row_for(product: Dict[str, object], review: Dict[str, object], image_url: str, image_index: int, fetched: str) -> Dict[str, str]:
    title = strip_tags(review.get("title"))
    body = strip_tags(review.get("body"))
    attr_text = reviewer_attribute_text(review)
    variant_name = norm(review.get("productVariantName"))
    text = norm(" ".join(part for part in [title, body, attr_text, f"Variant: {variant_name}" if variant_name else ""] if part))
    height_raw, height_in = parse_height(text)
    weight_raw, weight = parse_num(WEIGHT_RE, text, 700)
    waist_raw, waist = parse_num(WAIST_RE, text, 90)
    hips_raw, hips = parse_num(HIPS_RE, text, 90)
    bust_raw, bust = parse_num(BUST_RE, text, 70)
    inseam_raw, inseam = parse_num(INSEAM_RE, text, 45)
    age_raw, age = parse_age(text)
    bra_band, cupsize = extract_bra_size(text)
    size_display = extract_size(review, text)
    product_url = canonical_product_url(review.get("productUrl"), product_url_for(product))
    product_title = norm(review.get("productName") or product.get("title"))
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    review_id = norm(review.get("reviewId")) or f"{product.get('id')}-{image_index}"
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
        "search_fts": norm(" ".join([BRAND, product_title, strip_tags(product.get("body_html")), text])),
        "weight_display_display": maybe_num(weight),
        "weight_raw_needs_correction": "",
        "clothing_type_id": classify(product, review),
        "reviewer_profile_url": "",
        "reviewer_name_raw": norm(reviewer.get("displayName")),
        "inseam_inches_display": maybe_num(inseam),
        "color_canonical": "",
        "color_display": "",
        "size_display": size_display,
        "bust_in_number_display": bra_band or maybe_num(bust),
        "cupsize_display": cupsize,
        "weight_lbs_display": maybe_num(weight),
        "weight_lbs_raw_issue": "",
        "product_title_raw": product_title,
        "product_subtitle_raw": title,
        "product_description_raw": strip_tags(product.get("body_html")),
        "product_detail_raw": variant_detail(product),
        "product_category_raw": norm(product.get("product_type")),
        "product_variant_raw": variant_name,
    }


def has_measurement(row: Dict[str, str]) -> bool:
    fields = ["height_in_display", "weight_lbs_display", "bust_in_number_display", "hips_in_display", "waist_in", "inseam_inches_display"]
    return any(norm(row.get(field)) for field in fields)


def has_product_url(row: Dict[str, str]) -> bool:
    return bool(norm(row.get("product_page_url_display") or row.get("monetized_product_url_display")))


def is_supabase_qualified(row: Dict[str, str]) -> bool:
    return bool(norm(row.get("original_url_display")) and has_product_url(row) and has_measurement(row) and norm(row.get("size_display")))


def dedupe_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
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
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    total_pages = 0
    total_hint = 0
    products_excluded = 0
    fetched = now_iso()

    for idx, product in enumerate(products, start=1):
        reviews, meta = fetch_product_reviews(product, limit_pages=limit_pages)
        skip_reason = output_skip_reason(product)
        if skip_reason:
            products_excluded += 1
        total_pages += int(meta.get("review_pages_scanned") or 0)
        total_hint += int(meta.get("review_count_hint") or 0)
        product_rows = 0
        if not skip_reason:
            for review in reviews:
                for image_index, image_url in enumerate(media_urls(review), start=1):
                    rows.append(row_for(product, review, image_url, image_index, fetched))
                    product_rows += 1
        product_summaries.append(
            {
                "product_index": idx,
                "product_id": product.get("id"),
                "product_title": product.get("title"),
                "product_type": product.get("product_type"),
                "product_url": product_url_for(product),
                "review_count_hint": meta.get("review_count_hint"),
                "review_pages_scanned": meta.get("review_pages_scanned"),
                "matching_review_images": meta.get("matching_review_images"),
                "rows": product_rows,
                "errors": meta.get("errors"),
                "adapter_used": meta.get("adapter_used"),
                "skipped_from_output": bool(skip_reason),
                "skip_reason": skip_reason,
            }
        )
        status = f" skipped={skip_reason}" if skip_reason else ""
        print(f"[{idx}/{len(products)}] {product.get('title')} reviews={meta.get('review_count_hint')} pages={meta.get('review_pages_scanned')} rows={product_rows}{status}", flush=True)

    deduped = dedupe_rows(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(deduped)

    product_urls = {row.get("product_page_url_display") or row.get("monetized_product_url_display") for row in deduped if has_product_url(row)}
    summary = {
        "site": SITE_ROOT,
        "retailer": "wildfang_com",
        "adapter": "okendo_product_level",
        "okendo_store_id": OKENDO_STORE_ID,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "products_excluded_from_output": products_excluded,
        "products_with_review_rows": sum(1 for item in product_summaries if item.get("rows")),
        "exhaustive_review_paging": limit_pages is None,
        "review_pages_scanned": total_pages,
        "product_review_count_hint": total_hint,
        "rows_written": len(deduped),
        "distinct_reviews": len({row["id"].rsplit("-", 1)[0] for row in deduped}),
        "distinct_images": len({re.sub(r"\?.*$", "", row["original_url_display"]) for row in deduped}),
        "distinct_product_urls": len(product_urls),
        "distinct_products": len(product_urls),
        "rows_with_distinct_product_url": sum(1 for row in deduped if has_product_url(row)),
        "rows_with_product_url": sum(1 for row in deduped if has_product_url(row)),
        "rows_missing_product_url": sum(1 for row in deduped if not has_product_url(row)),
        "rows_with_any_measurement": sum(1 for row in deduped if has_measurement(row)),
        "rows_with_customer_image": sum(1 for row in deduped if norm(row.get("original_url_display"))),
        "rows_with_customer_ordered_size": sum(1 for row in deduped if norm(row.get("size_display"))),
        "rows_with_size": sum(1 for row in deduped if norm(row.get("size_display"))),
        "rows_supabase_qualified": sum(1 for row in deduped if is_supabase_qualified(row)),
        "rows_with_image_product_and_measurement": sum(1 for row in deduped if norm(row.get("original_url_display")) and has_product_url(row) and has_measurement(row)),
        "rows_with_image_product_size_and_measurement": sum(1 for row in deduped if is_supabase_qualified(row)),
        "output_csv": str(OUTPUT_CSV),
        "summary_json": str(SUMMARY_JSON),
        "started_at": started,
        "finished_at": now_iso(),
        "product_summaries": product_summaries,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
