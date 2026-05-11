#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
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


SITE_ROOT = "https://stackathletics.com"
DOMAIN = "stackathletics.com"
RETAILER = "stackathletics_com"
CATALOG_URL = f"{SITE_ROOT}/products.json"
OKENDO_API_ROOT = "https://api.okendo.io/v1"

try:
    from step1_intake_utils import STEP1_OUTPUT_ROOT
except ImportError:  # pragma: no cover
    STEP1_OUTPUT_ROOT = Path(__file__).resolve().parents[4] / "data-pipelines" / "non-amazon" / "data" / "step_1_raw_scraping_data"

OUTPUT_DIR = STEP1_OUTPUT_ROOT / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema_summary.json"

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
    r"\b(bra|dress|legging|shorts?|skirt|tank|tee|t-shirt|top|jacket|hoodie|sweatshirt|pant|jogger)\b",
    re.I,
)
OUT_OF_SCOPE_RE = re.compile(r"\b(credit|shipping|protection|gift card|hat|sock|bag|bottle|sticker)\b", re.I)


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
        brand=normalize_whitespace(product.get("vendor")) or "Stack Athletics",
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=urlparse(SITE_ROOT).netloc,
        provider_hints="Okendo product-page JSON",
    )


def is_apparel(product: Dict[str, object]) -> bool:
    context = product_context(product)
    text = normalize_whitespace(
        " ".join(
            [
                context.title,
                context.category,
                context.description,
                " ".join(str(tag) for tag in product.get("tags", []) or []),
            ]
        )
    )
    if OUT_OF_SCOPE_RE.search(text) and not APPAREL_RE.search(text):
        return False
    return bool(classify_clothing_type(context) or APPAREL_RE.search(text))


def parse_okendo_metafields(product_html: str) -> List[Dict[str, object]]:
    payloads: List[Dict[str, object]] = []
    for match in re.finditer(r'<script[^>]+data-oke-metafield-data[^>]*>(.*?)</script>', product_html, re.I | re.S):
        raw = html.unescape(match.group(1)).strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


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


def normalize_product_url(value: object, fallback: str) -> str:
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


def row_for_review(context: ProductContext, review: Dict[str, object], media: Dict[str, str], fetched_at: str) -> Dict[str, str]:
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    product_url_value = normalize_product_url(review.get("productUrl"), context.url)
    review_id = normalize_whitespace(review.get("reviewId")) or hashlib.md5(
        f"{context.url}|{media['image_url']}|{review.get('body')}".encode("utf-8")
    ).hexdigest()
    review_image = ReviewImage(
        image_url=media["image_url"],
        review_id=f"stack-okendo-{review_id}-{hashlib.md5(media['image_url'].encode('utf-8')).hexdigest()[:8]}",
        review_title=normalize_whitespace(review.get("title")),
        review_body=normalize_whitespace(review.get("body")),
        reviewer_name=normalize_whitespace(reviewer.get("displayName")),
        date_raw=normalize_whitespace(review.get("dateCreated")),
        review_date=normalize_whitespace(review.get("dateCreated"))[:10],
        rating=normalize_whitespace(review.get("rating")),
        extra={
            "image_source_type": "customer_review_image",
            "image_source_detail": "Okendo public product review image",
            "product_url": product_url_value,
            "product_title": normalize_whitespace(review.get("productName")) or context.title,
            "product_category": context.category,
            "product_detail": context.detail,
        },
    )
    return build_intake_row(context, review_image, fetched_at)


def collect_product_rows(
    product: Dict[str, object],
    delay: float,
    max_review_pages: int,
    fetched_at: str,
) -> Tuple[List[Dict[str, str]], Dict[str, object], int]:
    context = product_context(product)
    summary: Dict[str, object] = {
        "product_id": context.product_id,
        "product_url": context.url,
        "product_title": context.title,
        "product_type": context.category,
        "clothing_type_id": classify_clothing_type(context),
        "review_count_hint": 0,
        "media_count_hint": 0,
        "review_pages_scanned": 0,
        "reviews_seen": 0,
        "matching_review_images": 0,
        "rows": 0,
        "skipped_from_output": False,
        "skip_reason": "",
        "errors": [],
    }
    if not is_apparel(product):
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "out_of_scope_non_apparel"
        return [], summary, 0
    product_html = request_text(context.url)
    payloads = parse_okendo_metafields(product_html)
    payload = next((item for item in payloads if isinstance(item.get("reviewAggregate"), dict) or item.get("reviews")), {})
    if not payload:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "no_okendo_product_payload"
        return [], summary, 0
    aggregate = payload.get("reviewAggregate") if isinstance(payload.get("reviewAggregate"), dict) else {}
    media_count_hint = int(aggregate.get("mediaCount") or 0)
    summary["media_count_hint"] = media_count_hint
    summary["review_count_hint"] = int(aggregate.get("reviewCount") or aggregate.get("ratingAndReviewCount") or 0)

    rows: List[Dict[str, str]] = []
    pages_scanned = 0
    current_payload = payload
    current_url = ""
    seen_review_ids = set()
    seen_media_urls = set()
    for _page in range(max_review_pages):
        pages_scanned += 1
        page_reviews = reviews_from_payload(current_payload)
        summary["reviews_seen"] = int(summary["reviews_seen"]) + len(page_reviews)
        for review in page_reviews:
            review_id = normalize_whitespace(review.get("reviewId"))
            seen_review_ids.add(review_id)
            for media in review_media_items(review):
                key = media["image_url"]
                if key in seen_media_urls:
                    continue
                seen_media_urls.add(key)
                rows.append(row_for_review(context, review, media, fetched_at))
        if media_count_hint and len(seen_media_urls) >= media_count_hint:
            break
        next_url = next_reviews_url(current_payload)
        if not next_url:
            break
        current_url = next_url
        if delay:
            time.sleep(delay)
        current_payload = request_json(current_url, referer=context.url)
    summary["review_pages_scanned"] = pages_scanned
    summary["media_review_ids_discovered"] = len([rid for rid in seen_review_ids if rid])
    summary["matching_review_images"] = len(seen_media_urls)
    summary["rows"] = len(rows)
    if media_count_hint and len(seen_media_urls) < media_count_hint:
        summary["errors"].append(f"media_count_hint_not_fully_reached: {len(seen_media_urls)}/{media_count_hint}")
    return rows, summary, pages_scanned


def strict_supabase_qualified_rows(rows: Sequence[Dict[str, str]]) -> int:
    return sum(
        1
        for row in rows
        if row.get("original_url_display")
        and row.get("image_source_type") == "customer_review_image"
        and row.get("product_page_url_display")
        and row.get("size_display")
        and any(row.get(field) for field in MEASUREMENT_FIELDS)
    )


def scrape(args: argparse.Namespace) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    products, page_counts = fetch_catalog(args.catalog_limit, args.max_catalog_pages, args.request_delay_seconds)
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    review_pages_scanned = 0
    scanned = 0
    for index, product in enumerate(products, start=1):
        try:
            product_rows, summary, pages = collect_product_rows(
                product,
                args.request_delay_seconds,
                args.max_review_pages_per_product,
                started_at,
            )
        except PressureStop as exc:
            context = product_context(product)
            errors.append(f"{context.url}: {exc}")
            print(f"[stop] {context.url}: {exc}", flush=True)
            break
        rows.extend(product_rows)
        product_summaries.append(summary)
        review_pages_scanned += pages
        scanned += 1
        print(
            f"[product {index}/{len(products)}] rows={len(product_rows)} total={len(rows)} "
            f"media={summary['matching_review_images']}/{summary['media_count_hint']} {product.get('handle')}",
            flush=True,
        )
        if args.limit_products and scanned >= args.limit_products:
            break
        if args.request_delay_seconds:
            time.sleep(args.request_delay_seconds)
    rows = dedupe_rows(rows)
    finished_at = utc_now()
    exhaustive = not errors and not args.limit_products and scanned == len(products)
    return rows, {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_product_page_okendo_media_reviews",
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
        "products_scanned": scanned,
        "product_pages_scanned": scanned,
        "review_pages_scanned": review_pages_scanned,
        "exhaustive_review_paging": exhaustive,
        "coverage_exhaustive": exhaustive,
        "scrape_scope_status": "full_public_catalog_okendo_media_complete" if exhaustive else "stopped_or_limited",
        "catalog_model_rows_enabled": False,
        "customer_review_feed_used": True,
        "access_policy": "public Shopify products.json, product pages, and Okendo review JSON only; stop on 429/captcha/WAF",
        "product_summaries": product_summaries,
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "errors": errors,
    }


def write_outputs(rows: Sequence[Dict[str, str]], summary: Dict[str, object]) -> None:
    write_intake_csv(rows, OUTPUT_CSV)
    rows_with_product_url = sum(1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display"))
    rows_with_measurements = sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS))
    rows_with_customer_image = sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image")
    rows_with_catalog_image = sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "catalog_model_image")
    rows_with_ordered_size = sum(1 for row in rows if row.get("size_display") and row.get("size_display") != "unknown")
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
            "rows_with_customer_ordered_size": rows_with_ordered_size,
            "rows_with_size": rows_with_ordered_size,
            "rows_supabase_qualified": strict_supabase_qualified_rows(rows),
            "rows_catalog_model_qualified": 0,
        }
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Stack Athletics public Okendo review images.")
    parser.add_argument("--catalog-limit", type=int, default=250)
    parser.add_argument("--max-catalog-pages", type=int, default=20)
    parser.add_argument("--limit-products", type=int, default=0)
    parser.add_argument("--max-review-pages-per-product", type=int, default=200)
    parser.add_argument("--request-delay-seconds", type=float, default=0.25)
    args = parser.parse_args(argv)
    rows, summary = scrape(args)
    write_outputs(rows, summary)
    print(f"Rows written: {len(rows)}")
    print(f"Products discovered: {summary['products_discovered']}")
    print(f"Products scanned: {summary['products_scanned']}")
    print(f"Review pages scanned: {summary['review_pages_scanned']}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
