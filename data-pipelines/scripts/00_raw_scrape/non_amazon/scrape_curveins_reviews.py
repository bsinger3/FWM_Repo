#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
    ProductContext,
    ReviewImage,
    build_intake_row,
    classify_clothing_type,
    dedupe_rows,
    normalize_whitespace,
    strip_tags,
    utc_now,
    write_intake_csv,
)


SITE_ROOT = "https://curveins.com"
DOMAIN = "curveins.com"
RETAILER = "curveins_com"
CATALOG_URL = f"{SITE_ROOT}/products.json"
OKENDO_STORE_ID = "f88c6516-040e-498d-a23a-2586e74155d1"
OKENDO_API_ROOT = "https://api.okendo.io/v1"

try:
    from step1_intake_utils import STEP1_OUTPUT_ROOT
except ImportError:  # pragma: no cover
    STEP1_OUTPUT_ROOT = Path(__file__).resolve().parents[4] / "data-pipelines" / "non-amazon" / "data" / "step_1_raw_scraping_data"

OUTPUT_DIR = STEP1_OUTPUT_ROOT / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 FWM"
PRESSURE_STATUS_CODES = {401, 403, 407, 408, 409, 423, 429, 430, 503}
BLOCK_MARKERS = [
    "Just a moment...",
    "challenges.cloudflare.com",
    "cf-chl",
    "Attention Required! | Cloudflare",
    "datadome",
    "Please verify you are a human",
    "verify you are human",
    "Access denied",
]

APPAREL_RE = re.compile(
    r"\b(dress|jumpsuit|romper|skirt|top|shirt|blouse|sleeve|pants?|jeans|leggings|shorts?)\b",
    re.I,
)
OUT_OF_SCOPE_RE = re.compile(r"\b(gift card|shipping|insurance|bag|belt|hat|jewelry|necklace|earrings|shoes?)\b", re.I)


class PressureStop(RuntimeError):
    pass


def request_text(url: str, *, accept: str = "text/html,application/json,*/*", referer: str = SITE_ROOT) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        },
    )
    try:
        with urlopen(req, timeout=45) as response:
            status = getattr(response, "status", 200)
            text = response.read().decode("utf-8-sig", "replace")
    except HTTPError as exc:
        if exc.code in PRESSURE_STATUS_CODES:
            text = request_text_with_curl(url, accept=accept, referer=referer)
            if text:
                return text
            raise PressureStop(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
        raise
    except URLError as exc:
        raise PressureStop(f"request_failed: {url}: {exc}") from exc
    if status in PRESSURE_STATUS_CODES:
        raise PressureStop(f"blocked_or_rate_limited_http_{status}: {url}")
    lower = text.lower()
    if any(marker.lower() in lower for marker in BLOCK_MARKERS):
        raise PressureStop(f"blocked_or_challenged_response: {url}")
    return text


def request_text_with_curl(url: str, *, accept: str, referer: str) -> str:
    command = [
        "curl",
        "-L",
        "-sS",
        "--max-time",
        "45",
        "-H",
        f"Accept: {accept}",
        "-H",
        "Accept-Language: en-US,en;q=0.9",
        "-H",
        f"Referer: {referer}",
        "-H",
        f"User-Agent: {USER_AGENT}",
        "-w",
        "\n__FWM_HTTP_STATUS__:%{http_code}",
        url,
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    marker = "\n__FWM_HTTP_STATUS__:"
    if marker not in result.stdout:
        return result.stdout
    body, status_text = result.stdout.rsplit(marker, 1)
    try:
        status = int(status_text.strip())
    except ValueError:
        return ""
    if status in PRESSURE_STATUS_CODES or status >= 400:
        return ""
    lower = body.lower()
    if any(marker_text.lower() in lower for marker_text in BLOCK_MARKERS):
        return ""
    return body


def request_json(url: str, *, referer: str = SITE_ROOT) -> Dict[str, object]:
    return json.loads(request_text(url, accept="application/json,text/plain,*/*", referer=referer))


def product_url(handle: str) -> str:
    return f"{SITE_ROOT}/products/{handle}"


def fetch_catalog(limit: int, max_pages: int, delay: float) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    page_counts: List[Dict[str, object]] = []
    seen_handles = set()
    for page in range(1, max_pages + 1):
        url = f"{CATALOG_URL}?limit={limit}&page={page}"
        payload = request_json(url)
        page_products = payload.get("products", []) or []
        page_counts.append({"page": page, "url": url, "products": len(page_products)})
        if not page_products:
            break
        for product in page_products:
            if not isinstance(product, dict):
                continue
            handle = normalize_whitespace(product.get("handle"))
            if not handle or handle in seen_handles:
                continue
            seen_handles.add(handle)
            products.append(product)
        print(f"[catalog page {page}] products={len(page_products)} total={len(products)}", flush=True)
        if len(page_products) < limit:
            break
        if delay:
            time.sleep(delay)
    return products, page_counts


def product_context(product: Dict[str, object]) -> ProductContext:
    handle = normalize_whitespace(product.get("handle"))
    variants = product.get("variants") if isinstance(product.get("variants"), list) else []
    variant_titles: List[str] = []
    for variant in variants[:200]:
        if not isinstance(variant, dict):
            continue
        title = normalize_whitespace(variant.get("title"))
        if title and title.lower() != "default title" and title not in variant_titles:
            variant_titles.append(title)
    return ProductContext(
        url=product_url(handle),
        title=normalize_whitespace(product.get("title")),
        description=strip_tags(product.get("body_html")),
        detail=" | ".join(variant_titles),
        category=normalize_whitespace(product.get("product_type")),
        brand=normalize_whitespace(product.get("vendor")) or "CURVE INS",
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=urlparse(SITE_ROOT).netloc,
        provider_hints="Shopify products.json; Okendo store review JSON",
    )


def is_apparel(product: Dict[str, object]) -> bool:
    context = product_context(product)
    tags = product.get("tags") if isinstance(product.get("tags"), list) else []
    text = normalize_whitespace(
        " ".join([context.title, context.category, context.description, " ".join(str(tag) for tag in tags)])
    )
    if OUT_OF_SCOPE_RE.search(text) and not APPAREL_RE.search(text):
        return False
    return bool(classify_clothing_type(context) or APPAREL_RE.search(text))


def media_url(item: Dict[str, object]) -> str:
    image_urls = item.get("imageUrls") if isinstance(item.get("imageUrls"), dict) else {}
    return normalize_whitespace(
        item.get("fullSizeUrl")
        or item.get("largeUrl")
        or item.get("thumbnailUrl")
        or image_urls.get("fullSizeUrl")
        or image_urls.get("largeUrl")
        or image_urls.get("thumbnailUrl")
    )


def review_media_items(review: Dict[str, object]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    media = review.get("media") if isinstance(review.get("media"), list) else []
    for item in media:
        if not isinstance(item, dict):
            continue
        if normalize_whitespace(item.get("type")).lower() not in {"", "image", "photo"}:
            continue
        url = media_url(item)
        if not url:
            continue
        items.append(
            {
                "image_url": url,
                "alt": normalize_whitespace(item.get("alt") or item.get("imageAlt")),
                "stream_id": normalize_whitespace(item.get("streamId") or item.get("dynamicKey")),
            }
        )
    return items


def normalize_product_url(value: object, fallback: str = "") -> str:
    url = normalize_whitespace(value) or fallback
    if url.startswith("//"):
        url = f"https:{url}"
    if url.startswith("/"):
        url = urljoin(SITE_ROOT, url)
    return url


def reviews_from_payload(payload: Dict[str, object]) -> List[Dict[str, object]]:
    return [item for item in payload.get("reviews", []) if isinstance(item, dict)] if isinstance(payload.get("reviews"), list) else []


def next_reviews_url(payload: Dict[str, object]) -> str:
    next_url = normalize_whitespace(payload.get("reviewsNextUrl") or payload.get("nextUrl"))
    if not next_url:
        return ""
    if next_url.startswith("/"):
        next_url = f"{OKENDO_API_ROOT}{next_url}"
    return next_url


def store_reviews_url(limit: int) -> str:
    return f"{OKENDO_API_ROOT}/stores/{OKENDO_STORE_ID}/reviews?limit={limit}&orderBy=has_media%20desc"


def purchased_size_from_variant(value: object) -> str:
    variant = normalize_whitespace(value)
    if not variant:
        return ""
    first_part = normalize_whitespace(variant.split("/", 1)[0])
    size_part = normalize_whitespace(variant.split(" / ", 1)[0])
    return size_part or first_part or variant


def review_context(review: Dict[str, object], catalog_by_id: Dict[str, ProductContext], catalog_by_handle: Dict[str, ProductContext]) -> ProductContext:
    product_id = normalize_whitespace(review.get("productId")).replace("shopify-", "")
    handle = normalize_whitespace(review.get("productHandle"))
    context = catalog_by_id.get(product_id) or catalog_by_handle.get(handle)
    product_url_value = normalize_product_url(review.get("productUrl"), product_url(handle) if handle else "")
    if context:
        return context
    return ProductContext(
        url=product_url_value,
        title=normalize_whitespace(review.get("productName")),
        category="Dresses",
        brand="CURVE INS",
        product_id=product_id,
        handle=handle,
        shop_domain=DOMAIN,
        provider_hints="Okendo store review JSON",
    )


def row_for_review(context: ProductContext, review: Dict[str, object], media: Dict[str, str], fetched_at: str) -> Dict[str, str]:
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    product_url_value = normalize_product_url(review.get("productUrl"), context.url)
    review_id = normalize_whitespace(review.get("reviewId")) or hashlib.md5(
        f"{product_url_value}|{media['image_url']}|{review.get('body')}".encode("utf-8")
    ).hexdigest()
    review_image = ReviewImage(
        image_url=media["image_url"],
        review_id=f"curveins-okendo-{review_id}-{hashlib.md5(media['image_url'].encode('utf-8')).hexdigest()[:8]}",
        review_title=normalize_whitespace(review.get("title")),
        review_body=normalize_whitespace(review.get("body")),
        reviewer_name=normalize_whitespace(reviewer.get("displayName")),
        date_raw=normalize_whitespace(review.get("dateCreated")),
        review_date=normalize_whitespace(review.get("dateCreated"))[:10],
        size_raw=purchased_size_from_variant(review.get("productVariantName")),
        rating=normalize_whitespace(review.get("rating")),
        extra={
            "image_source_type": "customer_review_image",
            "image_source_detail": "Okendo public store review image",
            "product_url": product_url_value,
            "product_title": normalize_whitespace(review.get("productName")) or context.title,
            "product_category": context.category,
            "product_detail": context.detail,
            "product_variant": normalize_whitespace(review.get("productVariantName")),
        },
    )
    return build_intake_row(context, review_image, fetched_at)


def normalize_model_height(value: str) -> str:
    raw = normalize_whitespace(value).replace("’", "'").replace("”", '"')
    match = re.fullmatch(r"(\d)\s*'\s*(\d)0\s*''?", raw)
    if match:
        return f"{match.group(1)}'{match.group(2)}\""
    match = re.fullmatch(r"(\d)\s*'\s*(\d{1,2})(?:\.\d+)?\s*''?", raw)
    if match:
        inches = int(match.group(2))
        if 0 <= inches <= 11:
            return f"{match.group(1)}'{inches}\""
    return raw


def model_measurements(product: Dict[str, object]) -> Dict[str, str]:
    text = strip_tags(product.get("body_html"))
    if "Model's Measurements" not in text and "Model Wears" not in text:
        return {}
    fields = {
        "size": r"\bModel\s+Wears\s*:\s*([A-Za-z0-9\-/]+)",
        "height": r"\bHeight\s*:\s*([0-9'\". ]+)",
        "bust": r"\bBust\s*:\s*(\d{2,3}(?:\.\d+)?)",
        "waist": r"\bWaist\s*:\s*(\d{2,3}(?:\.\d+)?)",
        "hips": r"\bHips\s*:\s*(\d{2,3}(?:\.\d+)?)",
    }
    parsed: Dict[str, str] = {}
    for key, pattern in fields.items():
        match = re.search(pattern, text, re.I)
        if match:
            parsed[key] = normalize_whitespace(match.group(1))
    if "height" in parsed:
        parsed["height"] = normalize_model_height(parsed["height"])
    return parsed if parsed.get("size") and any(parsed.get(key) for key in ("height", "bust", "waist", "hips")) else {}


def first_product_image(product: Dict[str, object]) -> str:
    images = product.get("images") if isinstance(product.get("images"), list) else []
    for image in images:
        if isinstance(image, dict):
            url = normalize_whitespace(image.get("src"))
            if url:
                return url
    return ""


def row_for_catalog_model(product: Dict[str, object], fetched_at: str) -> Optional[Dict[str, str]]:
    context = product_context(product)
    if not is_apparel(product):
        return None
    measurements = model_measurements(product)
    image_url = first_product_image(product)
    if not measurements or not image_url:
        return None
    body_parts = [
        f"Model is {measurements['height']}" if measurements.get("height") else "",
        f"wearing size {measurements['size']}",
        f"Bust: {measurements['bust']} in." if measurements.get("bust") else "",
        f"Waist: {measurements['waist']} in." if measurements.get("waist") else "",
        f"Hips: {measurements['hips']} in." if measurements.get("hips") else "",
    ]
    review = ReviewImage(
        image_url=image_url,
        review_id=f"curveins-catalog-model-{context.product_id}-{hashlib.md5(image_url.encode('utf-8')).hexdigest()[:8]}",
        review_body=normalize_whitespace(" ".join(body_parts)),
        size_raw=measurements["size"],
        extra={
            "image_source_type": "catalog_model_image",
            "image_source_detail": "public Shopify products.json catalog image with model measurements from product description",
            "product_url": context.url,
            "product_title": context.title,
            "product_category": context.category,
            "product_detail": context.detail,
        },
    )
    return build_intake_row(context, review, fetched_at)


def collect_okendo_rows(
    catalog_by_id: Dict[str, ProductContext],
    catalog_by_handle: Dict[str, ProductContext],
    limit: int,
    max_pages: int,
    delay: float,
    fetched_at: str,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    rows: List[Dict[str, str]] = []
    current_url = store_reviews_url(limit)
    seen_media_urls = set()
    pages_scanned = 0
    reviews_seen = 0
    media_reviews_seen = 0
    errors: List[str] = []
    for _page in range(max_pages):
        try:
            payload = request_json(current_url)
        except PressureStop as exc:
            errors.append(str(exc))
            break
        pages_scanned += 1
        page_reviews = reviews_from_payload(payload)
        reviews_seen += len(page_reviews)
        page_media_count = 0
        if not page_reviews:
            break
        for review in page_reviews:
            media_items = review_media_items(review)
            if media_items:
                media_reviews_seen += 1
            context = review_context(review, catalog_by_id, catalog_by_handle)
            for media in media_items:
                page_media_count += 1
                if media["image_url"] in seen_media_urls:
                    continue
                seen_media_urls.add(media["image_url"])
                rows.append(row_for_review(context, review, media, fetched_at))
        print(
            f"[okendo page {pages_scanned}] reviews={len(page_reviews)} media={page_media_count} rows={len(rows)}",
            flush=True,
        )
        next_url = next_reviews_url(payload)
        if not next_url or page_media_count == 0:
            break
        current_url = next_url
        if delay:
            time.sleep(delay)
    return rows, {
        "review_pages_scanned": pages_scanned,
        "reviews_seen": reviews_seen,
        "media_reviews_seen": media_reviews_seen,
        "matching_review_images": len(seen_media_urls),
        "errors": errors,
    }


def strict_customer_qualified_rows(rows: Sequence[Dict[str, str]]) -> int:
    return sum(
        1
        for row in rows
        if row.get("original_url_display")
        and row.get("image_source_type") == "customer_review_image"
        and row.get("product_page_url_display")
        and row.get("size_display")
        and any(row.get(field) for field in MEASUREMENT_FIELDS)
    )


def catalog_model_qualified_rows(rows: Sequence[Dict[str, str]]) -> int:
    return sum(
        1
        for row in rows
        if row.get("original_url_display")
        and row.get("image_source_type") == "catalog_model_image"
        and row.get("product_page_url_display")
        and row.get("size_display")
        and any(row.get(field) for field in ("height_in_display", "waist_in", "hips_in_display", "bust_in_display"))
    )


def scrape(args: argparse.Namespace) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    products, page_counts = fetch_catalog(args.catalog_limit, args.max_catalog_pages, args.request_delay_seconds)
    if args.handles:
        wanted_handles = {normalize_whitespace(handle) for handle in args.handles.split(",") if normalize_whitespace(handle)}
        products = [product for product in products if normalize_whitespace(product.get("handle")) in wanted_handles]

    catalog_by_id = {product_context(product).product_id: product_context(product) for product in products}
    catalog_by_handle = {product_context(product).handle: product_context(product) for product in products}

    catalog_rows: List[Dict[str, str]] = []
    catalog_products_with_model = 0
    if not args.no_catalog_models:
        for index, product in enumerate(products, start=1):
            row = row_for_catalog_model(product, started_at)
            if row:
                catalog_rows.append(row)
                catalog_products_with_model += 1
            if index % 100 == 0:
                print(f"[catalog models] scanned={index} rows={len(catalog_rows)}", flush=True)

    okendo_rows, okendo_summary = collect_okendo_rows(
        catalog_by_id,
        catalog_by_handle,
        args.okendo_limit,
        args.max_okendo_pages,
        args.request_delay_seconds,
        started_at,
    )
    rows = dedupe_rows([*okendo_rows, *catalog_rows])
    finished_at = utc_now()
    errors = list(okendo_summary.get("errors", []))
    exhaustive = not errors and okendo_summary["review_pages_scanned"] < args.max_okendo_pages
    return rows, {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_catalog_models_okendo_store_media_reviews",
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": {
            "shopify_products_json": {
                "endpoint": CATALOG_URL,
                "page_counts": page_counts,
                "unique_handles": len(products),
            }
        },
        "products_discovered": len(products),
        "products_scanned": len(products),
        "product_pages_scanned": 0,
        "review_pages_scanned": okendo_summary["review_pages_scanned"],
        "reviews_seen": okendo_summary["reviews_seen"],
        "media_reviews_seen": okendo_summary["media_reviews_seen"],
        "matching_review_images": okendo_summary["matching_review_images"],
        "catalog_products_with_model_measurements": catalog_products_with_model,
        "catalog_model_rows_enabled": not args.no_catalog_models,
        "customer_review_feed_used": True,
        "exhaustive_review_paging": exhaustive,
        "coverage_exhaustive": exhaustive,
        "scrape_scope_status": "public_catalog_models_and_okendo_media_complete" if exhaustive else "stopped_or_limited",
        "access_policy": "public Shopify products.json and Okendo review JSON only; stop on 429/captcha/WAF",
        "errors": errors,
    }


def write_outputs(rows: Sequence[Dict[str, str]], summary: Dict[str, object]) -> None:
    write_intake_csv(rows, OUTPUT_CSV)
    rows_with_product_url = sum(1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display"))
    rows_with_measurements = sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS))
    rows_with_customer_image = sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image")
    rows_with_catalog_image = sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "catalog_model_image")
    rows_with_size = sum(1 for row in rows if row.get("size_display") and row.get("size_display") != "unknown")
    payload = dict(summary)
    payload.update(
        {
            "output_csv": str(OUTPUT_CSV),
            "summary_json": str(SUMMARY_JSON),
            "rows_written": len(rows),
            "distinct_reviews": len({row.get("id", "") for row in rows if row.get("id")}),
            "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
            "distinct_product_urls": len({row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}),
            "rows_with_distinct_product_url": rows_with_product_url,
            "rows_with_any_measurement": rows_with_measurements,
            "rows_with_customer_image": rows_with_customer_image,
            "rows_with_customer_review_image": rows_with_customer_image,
            "rows_with_catalog_model_image": rows_with_catalog_image,
            "rows_with_customer_ordered_size": rows_with_size,
            "rows_with_size": rows_with_size,
            "rows_supabase_qualified": strict_customer_qualified_rows(rows),
            "rows_catalog_model_qualified": catalog_model_qualified_rows(rows),
        }
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Curveins public Okendo review images and catalog model rows.")
    parser.add_argument("--catalog-limit", type=int, default=250)
    parser.add_argument("--max-catalog-pages", type=int, default=30)
    parser.add_argument("--handles", default="", help="Comma-separated Shopify product handles to scrape after catalog discovery.")
    parser.add_argument("--okendo-limit", type=int, default=100)
    parser.add_argument("--max-okendo-pages", type=int, default=200)
    parser.add_argument("--request-delay-seconds", type=float, default=0.2)
    parser.add_argument("--no-catalog-models", action="store_true")
    args = parser.parse_args(argv)
    rows, summary = scrape(args)
    write_outputs(rows, summary)
    print(f"Rows written: {len(rows)}")
    print(f"Products discovered: {summary['products_discovered']}")
    print(f"Review pages scanned: {summary['review_pages_scanned']}")
    print(f"Okendo images: {summary['matching_review_images']}")
    print(f"Catalog model rows: {summary['catalog_products_with_model_measurements']}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
