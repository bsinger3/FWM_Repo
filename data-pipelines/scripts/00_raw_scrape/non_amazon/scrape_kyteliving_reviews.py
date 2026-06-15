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
OUTPUT_DIR = legacy_raw_run_dir("kyteliving_com")
OUTPUT_CSV = OUTPUT_DIR / "kyteliving_com_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "kyteliving_com_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://kyteliving.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
OKENDO_STORE_ID = "2891f42d-2971-48d7-a4fc-2d2265d8bb7f"
OKENDO_API_ROOT = f"https://api.okendo.io/v1/stores/{OKENDO_STORE_ID}"
BRAND = "Kyte Living"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36"
BLOCK_STATUS_CODES = {403, 429}
BLOCK_TEXT_RE = re.compile(r"\b(?:access denied|blocked|forbidden|unusual traffic|verify you are human)\b", re.I)

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
SIZE_RE = re.compile(r"\b(?:size(?:\s+purchased)?|ordered|bought|wearing|wore)\s*:?\s*(xxs|xs|s|m|l|xl|xxl|[0-9]x|[0-9]{1,2})\b", re.I)


class BlockedScrapeError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(value: object) -> str:
    return WS_RE.sub(" ", str(value or "").replace("\xa0", " ")).strip()


def strip_tags(value: object) -> str:
    text = re.sub(r"</p\s*>|<br\s*/?>|</li\s*>", " ", str(value or ""), flags=re.I)
    return norm(html.unescape(TAG_RE.sub(" ", text)))


def detect_blocked_response(status: int, body: str, url: str) -> None:
    if status in BLOCK_STATUS_CODES or BLOCK_TEXT_RE.search(body[:5000]):
        raise BlockedScrapeError(f"Blocked response while fetching {url}: status={status}")


def fetch_text(url: str, referer: str = SOURCE_SITE, retries: int = 4) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": referer})
        try:
            with urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8", "replace")
                detect_blocked_response(resp.status, text, url)
                return text
        except (HTTPError, URLError) as exc:
            last_error = exc
            if isinstance(exc, HTTPError) and exc.code in BLOCK_STATUS_CODES:
                raise BlockedScrapeError(f"Blocked response while fetching {url}: status={exc.code}") from exc
            if isinstance(exc, HTTPError) and exc.code not in {408, 500, 502, 503, 504}:
                raise
        time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"Failed request for {url}: {last_error}")


def fetch_json(url: str, referer: str = SOURCE_SITE) -> Dict[str, object]:
    return json.loads(fetch_text(url, referer=referer))


def product_url_for(product: Dict[str, object]) -> str:
    url = normalize_product_url(product.get("url"))
    if url:
        return url
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def normalize_product_url(url: object) -> str:
    value = norm(url)
    if value.startswith("//"):
        value = "https:" + value
    if value.startswith("kyteliving.com/"):
        value = "https://" + value
    if value.startswith("/"):
        value = urljoin(SITE_ROOT, value)
    return value.split("?", 1)[0].rstrip("/")


def fetch_products() -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    sources: List[Dict[str, object]] = []
    page = 1
    while True:
        url = f"{PRODUCTS_JSON_URL}?{urlencode({'limit': PRODUCTS_PER_PAGE, 'page': page})}"
        payload = fetch_json(url)
        page_products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        sources.append({"source": "products.json", "page": page, "count": len(page_products)})
        if not page_products:
            break
        products.extend(page_products)
        if len(page_products) < PRODUCTS_PER_PAGE:
            break
        page += 1
    sources.append({"source": "products_json_full_catalog", "count": len(products)})
    return products, sources


def fetch_okendo_product(product_id: str) -> Dict[str, object]:
    if not product_id:
        return {}
    url = f"{OKENDO_API_ROOT}/products/{quote(product_id, safe='')}"
    try:
        payload = fetch_json(url)
    except HTTPError as exc:
        if exc.code == 404:
            return {}
        raise
    product = payload.get("product")
    if not isinstance(product, dict):
        return {}
    return {
        "id": product_id.replace("shopify-", ""),
        "handle": "",
        "title": norm(product.get("name")),
        "product_type": "",
        "body_html": "",
        "tags": [],
        "url": normalize_product_url(product.get("url")),
        "imageUrl": norm(product.get("imageUrl")),
    }


def classify_product(product: Dict[str, object], title: str = "") -> str:
    hay = " ".join([title, norm(product.get("title")), norm(product.get("product_type")), " ".join(norm(t) for t in product.get("tags", []) if isinstance(t, str))]).lower()
    if not re.search(r"\bwomen'?s?\b", hay):
        return ""
    if any(word in hay for word in ["dress", "gown"]):
        return "dress"
    if any(word in hay for word in ["pajama", "sleep"]):
        return "sleepwear"
    if any(word in hay for word in ["pant", "legging", "jogger"]):
        return "pants"
    if any(word in hay for word in ["short"]):
        return "shorts"
    if any(word in hay for word in ["tee", "shirt", "tank", "cami", "top", "v-neck", "sleeve"]):
        return "top"
    return "clothing"


def skip_reason(product: Dict[str, object]) -> str:
    hay = " ".join([norm(product.get("title")), norm(product.get("product_type")), " ".join(norm(t) for t in product.get("tags", []) if isinstance(t, str))]).lower()
    if any(word in hay for word in ["men's", "mens ", "baby", "toddler", "kid", "child", "blanket", "sheet", "pillow", "crib", "toy", "hat", "bow", "gift card"]):
        return "out_of_scope_non_womens_clothing"
    if not classify_product(product):
        return "out_of_scope_non_womens_clothing_or_unknown"
    return ""


def maybe_num(value: Optional[float]) -> str:
    if value is None:
        return ""
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def parse_height(text: str) -> Tuple[str, Optional[float]]:
    match = HEIGHT_RE.search(text)
    if not match:
        return "", None
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    if 4 <= feet <= 7 and 0 <= inches <= 11:
        return norm(match.group(0)), feet * 12 + inches
    return "", None


def parse_num(pattern: re.Pattern[str], text: str, max_value: float) -> Tuple[str, Optional[float]]:
    match = pattern.search(text)
    if not match:
        return "", None
    value = float(match.group(1))
    if value > max_value:
        return "", None
    return norm(match.group(0)), value


def parse_size(review: Dict[str, object], text: str) -> str:
    attrs = review.get("productAttributes")
    if isinstance(attrs, list):
        for attr in attrs:
            if isinstance(attr, dict) and "size" in norm(attr.get("title")).lower():
                value = norm(attr.get("value"))
                if value:
                    return value.split("(", 1)[0].strip().upper()
    variant = norm(review.get("productVariantName"))
    if variant and re.search(r"\b(?:xxs|xs|s|m|l|xl|xxl|[0-9]x)\b", variant, re.I):
        return variant.split("(", 1)[0].strip().upper()
    match = SIZE_RE.search(text)
    return norm(match.group(1)).upper() if match else ""


def profile_attribute_text(review: Dict[str, object]) -> str:
    parts: List[str] = []
    attrs = review.get("productAttributes")
    if isinstance(attrs, list):
        for attr in attrs:
            if not isinstance(attr, dict):
                continue
            title = norm(attr.get("title")).rstrip(":")
            value = norm(attr.get("value"))
            if title and value:
                parts.append(f"{title}: {value}")
    return " ".join(parts)


def media_urls(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    for item in review.get("media") or []:
        if not isinstance(item, dict) or norm(item.get("type")).lower() not in {"", "image"}:
            continue
        url = norm(item.get("fullSizeUrl") or item.get("largeUrl") or item.get("thumbnailUrl"))
        if url and url not in urls:
            urls.append(url)
    return urls


def okendo_store_reviews_url() -> str:
    return f"{OKENDO_API_ROOT}/reviews?{urlencode({'limit': REVIEWS_PER_PAGE, 'orderBy': 'has_media desc'})}"


def row_for(review: Dict[str, object], product: Dict[str, object], image_url: str, image_index: int, fetched_at: str) -> Dict[str, str]:
    title = norm(review.get("title"))
    body = norm(review.get("body"))
    product_name = norm(review.get("productName") or product.get("title"))
    profile_text = profile_attribute_text(review)
    text = norm(" ".join([title, body, profile_text]))
    height_raw, height = parse_height(text)
    weight_raw, weight = parse_num(WEIGHT_RE, text, 700)
    waist_raw, waist = parse_num(WAIST_RE, text, 90)
    hips_raw, hips = parse_num(HIPS_RE, text, 90)
    bust_raw, bust = parse_num(BUST_RE, text, 70)
    inseam_raw, inseam = parse_num(INSEAM_RE, text, 45)
    age_raw, age = parse_num(AGE_RE, text, 100)
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    product_url = normalize_product_url(review.get("productUrl")) or product_url_for(product)
    row = {header: "" for header in HEADERS}
    row.update({
        "created_at_display": norm(review.get("dateCreated")),
        "id": f"{norm(review.get('reviewId'))}-{image_index}",
        "original_url_display": image_url,
        "product_page_url_display": product_url,
        "user_comment": text,
        "date_review_submitted_raw": norm(review.get("dateCreated")),
        "height_in_display": maybe_num(height),
        "review_date": norm(review.get("dateCreated"))[:10],
        "source_site_display": SOURCE_SITE,
        "fetched_at": fetched_at,
        "updated_at": fetched_at,
        "brand": BRAND,
        "waist_raw_display": waist_raw,
        "hips_raw": hips_raw,
        "age_raw": age_raw,
        "waist_in": maybe_num(waist),
        "hips_in_display": maybe_num(hips),
        "age_years_display": maybe_num(age),
        "search_fts": " ".join([BRAND, product_name, text]),
        "weight_display_display": maybe_num(weight),
        "clothing_type_id": classify_product(product, product_name),
        "reviewer_name_raw": norm(reviewer.get("displayName")),
        "inseam_inches_display": maybe_num(inseam),
        "size_display": parse_size(review, text),
        "bust_in_number_display": maybe_num(bust),
        "weight_lbs_display": maybe_num(weight),
        "product_title_raw": product_name,
        "product_description_raw": strip_tags(product.get("body_html")),
        "product_detail_raw": norm(review.get("productVariantName")),
        "product_category_raw": norm(product.get("product_type")),
        "product_variant_raw": norm(review.get("productVariantName")),
    })
    return row


def has_measurement(row: Dict[str, str]) -> bool:
    return any(row.get(key) for key in ["height_in_display", "weight_display_display", "weight_lbs_display", "bust_in_number_display", "hips_in_display", "waist_in", "inseam_inches_display"])


def is_qualified(row: Dict[str, str]) -> bool:
    return bool(row.get("original_url_display") and (row.get("product_page_url_display") or row.get("monetized_product_url_display")) and row.get("size_display") and has_measurement(row))


def dedupe_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        key = (row.get("id", "").rsplit("-", 1)[0], row.get("original_url_display", "").split("?", 1)[0])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def scrape(limit_pages: Optional[int] = None) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = now_iso()
    products, product_sources = fetch_products()
    by_okendo_id = {f"shopify-{product.get('id')}": product for product in products}
    okendo_product_cache: Dict[str, Dict[str, object]] = {}
    catalog_excluded = sum(1 for product in products if skip_reason(product))
    summaries = {f"shopify-{product.get('id')}": {"product_id": product.get("id"), "product_title": product.get("title"), "product_url": product_url_for(product), "skipped_from_output": bool(skip_reason(product)), "skip_reason": skip_reason(product), "reviews_seen": 0, "media_rows": 0} for product in products}
    rows: List[Dict[str, str]] = []
    url = okendo_store_reviews_url()
    seen_urls = set()
    pages = 0
    reviews_seen = 0
    media_reviews_seen = 0
    stopped_reason = ""
    fetched_at = now_iso()
    while url and url not in seen_urls:
        seen_urls.add(url)
        payload = fetch_json(url)
        reviews = [item for item in payload.get("reviews", []) if isinstance(item, dict)]
        pages += 1
        page_media_reviews = 0
        for review in reviews:
            reviews_seen += 1
            product_id = norm(review.get("productId"))
            product = by_okendo_id.get(product_id) or {"id": product_id.replace("shopify-", ""), "handle": norm(review.get("productHandle")), "title": norm(review.get("productName")), "product_type": "", "body_html": "", "tags": []}
            summary = summaries.setdefault(product_id, {"product_id": product_id, "product_title": norm(review.get("productName")), "product_url": normalize_product_url(review.get("productUrl")), "skipped_from_output": bool(skip_reason(product)), "skip_reason": skip_reason(product), "reviews_seen": 0, "media_rows": 0})
            summary["reviews_seen"] = int(summary["reviews_seen"]) + 1
            urls = media_urls(review)
            if urls:
                page_media_reviews += 1
                media_reviews_seen += 1
            if skip_reason(product) or not classify_product(product, norm(review.get("productName"))):
                continue
            if not (normalize_product_url(review.get("productUrl")) or product_url_for(product)):
                if product_id not in okendo_product_cache:
                    okendo_product_cache[product_id] = fetch_okendo_product(product_id)
                product = okendo_product_cache.get(product_id) or product
                if product.get("url"):
                    summary["product_url"] = product_url_for(product)
            for index, image_url in enumerate(urls, start=1):
                rows.append(row_for(review, product, image_url, index, fetched_at))
                summary["media_rows"] = int(summary["media_rows"]) + 1
        print(f"review_page={pages} reviews={len(reviews)} media_reviews={page_media_reviews} rows={len(rows)}", flush=True)
        if limit_pages and pages >= limit_pages:
            stopped_reason = "limit_pages"
            break
        if pages > 1 and page_media_reviews == 0:
            stopped_reason = "first_media_sorted_page_without_media"
            break
        next_url = norm(payload.get("nextUrl"))
        url = urljoin("https://api.okendo.io/v1/", next_url.lstrip("/")) if next_url else ""
    rows = dedupe_rows(rows)
    product_summaries = list(summaries.values())
    summary: Dict[str, object] = {
        "site": SOURCE_SITE,
        "retailer": "kyteliving_com",
        "adapter": "shopify_catalog_plus_okendo_store_media_feed",
        "okendo_store_id": OKENDO_STORE_ID,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "products_excluded_from_output": catalog_excluded,
        "review_pages_scanned": pages,
        "reviews_seen_in_store_feed": reviews_seen,
        "media_reviews_seen_in_store_feed": media_reviews_seen,
        "exhaustive_review_paging": False,
        "store_feed_stop_reason": stopped_reason or "no_next_url",
        "product_summaries": product_summaries,
        "okendo_products_enriched": len(okendo_product_cache),
        "started_at": started_at,
        "finished_at": now_iso(),
    }
    return rows, summary


def enrich_summary(summary: Dict[str, object], rows: Sequence[Dict[str, str]]) -> Dict[str, object]:
    urls = {row.get("product_page_url_display") or row.get("monetized_product_url_display") for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display")}
    summary.update({
        "rows_written": len(rows),
        "distinct_reviews": len({row.get("id", "").rsplit("-", 1)[0] for row in rows if row.get("id")}),
        "distinct_images": len({row.get("original_url_display") for row in rows if row.get("original_url_display")}),
        "rows_with_distinct_product_url": len(urls),
        "rows_with_product_url": sum(1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display")),
        "rows_with_customer_image": sum(1 for row in rows if row.get("original_url_display")),
        "rows_with_customer_ordered_size": sum(1 for row in rows if row.get("size_display") and row.get("size_display").lower() != "unknown"),
        "rows_with_any_measurement": sum(1 for row in rows if has_measurement(row)),
        "rows_supabase_qualified": sum(1 for row in rows if is_qualified(row)),
        "output_csv": str(OUTPUT_CSV),
        "summary_json": str(SUMMARY_JSON),
    })
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    limit_pages = None
    if "--limit-review-pages" in argv:
        limit_pages = int(argv[argv.index("--limit-review-pages") + 1])
    try:
        rows, summary = scrape(limit_pages=limit_pages)
    except BlockedScrapeError as exc:
        print(f"Stopping on blocked response: {exc}", file=sys.stderr)
        return 2
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    summary = enrich_summary(summary, rows)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ["products_discovered", "products_scanned", "products_excluded_from_output", "review_pages_scanned", "reviews_seen_in_store_feed", "media_reviews_seen_in_store_feed", "rows_written", "distinct_reviews", "distinct_images", "rows_with_distinct_product_url", "rows_with_customer_image", "rows_with_customer_ordered_size", "rows_with_any_measurement", "rows_supabase_qualified", "store_feed_stop_reason"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
