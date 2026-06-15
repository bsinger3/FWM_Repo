#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
    ProductContext,
    ReviewImage,
    build_intake_row,
    canonical_product_url,
    classify_clothing_type,
    dedupe_rows,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    write_intake_csv,
)


SITE_ROOT = "https://byltbasics.com"
RETAILER = "byltbasics_com"
SHOP_DOMAIN = "bylt-apparel.myshopify.com"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
OKENDO_API_ROOT = "https://api.okendo.io/v1"
OKENDO_STORE_ID = "10fc1c91-91ae-44af-8a41-f643ec1fb074"

OUTPUT_CSV, SUMMARY_JSON = output_paths(RETAILER)
OUTPUT_DIR = OUTPUT_CSV.parent

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
    "Verifying your connection",
]

OKENDO_PRODUCT_RE = re.compile(r'(?:data-oke-product-id|product-id)="shopify-(\d+)"')
LD_JSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
META_RE_TEMPLATE = r'<meta[^>]+(?:name|property)="{name}"[^>]+content="([^"]+)"'
SIZE_TOKEN_RE = re.compile(r"^\s*(XXS|XS|S|M|L|XL|XXL|XXXL|[1-5]X|[1-5]XL|[0-9]{1,2})\b", re.I)


class PressureStop(RuntimeError):
    pass


def request_text(url: str, *, accept: str = "text/html,application/xml,application/json,*/*") -> str:
    last_error: Exception | None = None
    for attempt in range(1, 4):
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
            with urlopen(req, timeout=60) as response:
                status = getattr(response, "status", 200)
                text = response.read().decode("utf-8-sig", "replace")
            break
        except HTTPError as exc:
            if exc.code in PRESSURE_STATUS_CODES:
                raise PressureStop(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
            raise
        except (TimeoutError, URLError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(1.5 * attempt)
                continue
            raise PressureStop(f"request_failed_after_retries: {url}: {exc}") from exc
    else:
        raise PressureStop(f"request_failed_after_retries: {url}: {last_error}")
    if status in PRESSURE_STATUS_CODES:
        raise PressureStop(f"blocked_or_rate_limited_http_{status}: {url}")
    lower = text.lower()
    if any(marker.lower() in lower for marker in BLOCK_MARKERS):
        raise PressureStop(f"blocked_or_challenged_response: {url}")
    return text


def request_json(url: str) -> Dict[str, object]:
    payload = json.loads(request_text(url, accept="application/json,text/plain,*/*"))
    if not isinstance(payload, dict):
        raise PressureStop(f"unexpected_json_response: {url}")
    return payload


def discover_product_urls(delay: float) -> Tuple[List[str], List[Dict[str, object]]]:
    index = request_text(SITEMAP_URL, accept="application/xml,text/xml,*/*")
    sitemap_urls = [html.unescape(url) for url in re.findall(r"<loc>(.*?)</loc>", index)]
    product_sitemaps = [url for url in sitemap_urls if "/sitemap/products/" in url]
    urls: List[str] = []
    source_pages: List[Dict[str, object]] = []
    seen = set()
    for sitemap_url in product_sitemaps:
        xml = request_text(sitemap_url, accept="application/xml,text/xml,*/*")
        product_urls = [
            canonical_product_url(html.unescape(url))
            for url in re.findall(r"<loc>(https://byltbasics\.com/products/[^<]+)</loc>", xml)
        ]
        source_pages.append({"url": sitemap_url, "products": len(product_urls)})
        for product_url in product_urls:
            if product_url and product_url not in seen:
                seen.add(product_url)
                urls.append(product_url)
        print(f"[sitemap] {sitemap_url} products={len(product_urls)} total={len(urls)}", flush=True)
        if delay:
            time.sleep(delay)
    return urls, source_pages


def meta_content(page_html: str, name: str) -> str:
    match = re.search(META_RE_TEMPLATE.format(name=re.escape(name)), page_html)
    return normalize_whitespace(html.unescape(match.group(1))) if match else ""


def product_json(page_html: str) -> Dict[str, object]:
    for raw in LD_JSON_RE.findall(page_html):
        try:
            payload = json.loads(html.unescape(raw))
        except json.JSONDecodeError:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "Product":
                return item
    return {}


def context_from_page(product_url: str, page_html: str) -> Tuple[ProductContext, str]:
    product = product_json(page_html)
    title = normalize_whitespace(product.get("name")) or meta_content(page_html, "og:title")
    description = strip_tags(product.get("description")) or meta_content(page_html, "og:description") or meta_content(page_html, "description")
    images = product.get("image") if isinstance(product.get("image"), list) else []
    image_url = normalize_whitespace(images[0] if images else "") or meta_content(page_html, "og:image")
    product_id_match = OKENDO_PRODUCT_RE.search(page_html)
    product_id = product_id_match.group(1) if product_id_match else ""
    handle = product_url.rstrip("/").rsplit("/", 1)[-1]
    return (
        ProductContext(
            url=product_url,
            title=title,
            description=description,
            detail="",
            category="",
            brand="BYLT Basics",
            variant="",
            product_id=product_id,
            handle=handle,
            shop_domain=SHOP_DOMAIN,
            provider_hints="Public product page plus public Okendo product reviews",
        ),
        image_url,
    )


def okendo_reviews_url(product_id: str, limit: int) -> str:
    return f"{OKENDO_API_ROOT}/stores/{OKENDO_STORE_ID}/products/shopify-{product_id}/reviews?limit={limit}&orderBy=date%20desc"


def fetch_okendo_reviews(product_id: str, limit: int, delay: float) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    if not product_id:
        return [], []
    reviews: List[Dict[str, object]] = []
    page_summaries: List[Dict[str, object]] = []
    seen_next = set()
    next_url = okendo_reviews_url(product_id, limit)
    while next_url:
        if next_url in seen_next:
            raise PressureStop("okendo_next_url_loop")
        seen_next.add(next_url)
        url = urljoin(f"{OKENDO_API_ROOT}/", next_url.lstrip("/")) if next_url.startswith("/") else next_url
        payload = request_json(url)
        page_reviews = [item for item in payload.get("reviews", []) if isinstance(item, dict)]
        reviews.extend(page_reviews)
        page_summaries.append({"url": url, "reviews": len(page_reviews)})
        next_url = normalize_whitespace(payload.get("nextUrl") or payload.get("reviewsNextUrl"))
        if delay:
            time.sleep(delay)
    return reviews, page_summaries


def attr_text(review: Dict[str, object]) -> str:
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    attrs = reviewer.get("attributes") if isinstance(reviewer.get("attributes"), list) else []
    parts = []
    for attr in attrs:
        if not isinstance(attr, dict):
            continue
        title = normalize_whitespace(attr.get("title"))
        value = normalize_whitespace(attr.get("value"))
        if title and value:
            parts.append(f"{title}: {value}.")
    return normalize_whitespace(" ".join(parts))


def review_size(review: Dict[str, object]) -> str:
    variant = normalize_whitespace(review.get("productVariantName"))
    if "/" in variant:
        maybe_size = variant.rsplit("/", 1)[-1].strip()
        match = SIZE_TOKEN_RE.match(maybe_size)
        if match:
            return match.group(1).upper()
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    attrs = reviewer.get("attributes") if isinstance(reviewer.get("attributes"), list) else []
    for attr in attrs:
        title = normalize_whitespace(attr.get("title") if isinstance(attr, dict) else "").lower()
        value = normalize_whitespace(attr.get("value") if isinstance(attr, dict) else "")
        if "usual clothing size" in title:
            match = SIZE_TOKEN_RE.match(value)
            if match:
                return match.group(1).upper()
    return ""


def reviewer_name(review: Dict[str, object]) -> str:
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    return normalize_whitespace(reviewer.get("displayName") or reviewer.get("name"))


def rows_from_reviews(context: ProductContext, reviews: Sequence[Dict[str, object]], fetched_at: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for review in reviews:
        body = normalize_whitespace(review.get("body"))
        image_url = normalize_whitespace(review.get("productImageUrl"))
        if not body or not image_url:
            continue
        body_with_attrs = normalize_whitespace(" ".join(part for part in [body, attr_text(review)] if part))
        review_id = normalize_whitespace(review.get("reviewId")) or hashlib.md5(
            f"{context.url}|{body}".encode("utf-8")
        ).hexdigest()[:16]
        review_product_url = normalize_whitespace(review.get("productUrl"))
        if review_product_url.startswith("//"):
            review_product_url = f"https:{review_product_url}"
        row = build_intake_row(
            context,
            ReviewImage(
                image_url=image_url,
                review_id=f"bylt-okendo-{review_id}",
                review_title=normalize_whitespace(review.get("title")),
                review_body=body_with_attrs,
                reviewer_name=reviewer_name(review),
                date_raw=normalize_whitespace(review.get("dateCreated")),
                size_raw=review_size(review),
                rating=normalize_whitespace(review.get("rating")),
                extra={
                    "image_source_type": "catalog_product_image",
                    "image_source_detail": "public Okendo review joined to public product/variant image; no customer review media exposed in Okendo payload",
                    "product_url": canonical_product_url(review_product_url or context.url),
                    "product_title": normalize_whitespace(review.get("productName")) or context.title,
                    "product_variant": normalize_whitespace(review.get("productVariantName")) or context.variant,
                },
            ),
            fetched_at,
        )
        rows.append(row)
    return rows


def customer_supabase_qualified_rows(rows: Sequence[Dict[str, str]]) -> int:
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
    product_urls, sitemap_pages = discover_product_urls(args.request_delay_seconds)
    rows: List[Dict[str, str]] = []
    errors: List[str] = []
    product_summaries: List[Dict[str, object]] = []
    scanned = 0
    review_pages_scanned = 0
    type_counts = Counter()

    for index, product_url in enumerate(product_urls, start=1):
        try:
            page_html = request_text(product_url)
            context, _fallback_image = context_from_page(product_url, page_html)
            reviews, page_summaries = fetch_okendo_reviews(context.product_id, args.okendo_page_size, args.request_delay_seconds)
        except PressureStop as exc:
            errors.append(f"{product_url}: {exc}")
            print(f"[stop] {product_url}: {exc}", flush=True)
            break
        scanned += 1
        type_counts[context.category or "unknown"] += 1
        product_rows = rows_from_reviews(context, reviews, started_at)
        rows.extend(product_rows)
        review_pages_scanned += len(page_summaries)
        product_summaries.append(
            {
                "product_url": product_url,
                "product_title": context.title,
                "shopify_product_id": context.product_id,
                "product_type": context.category,
                "clothing_type_id": classify_clothing_type(context),
                "okendo_review_pages": len(page_summaries),
                "okendo_reviews": len(reviews),
                "rows": len(product_rows),
                "skipped_from_output": not bool(product_rows),
                "skip_reason": "" if product_rows else "no_okendo_review_rows_with_product_image",
            }
        )
        print(f"[product {index}/{len(product_urls)}] reviews={len(reviews)} rows={len(product_rows)} total={len(rows)} {context.handle}", flush=True)
        if args.limit_products and scanned >= args.limit_products:
            break
        if args.request_delay_seconds:
            time.sleep(args.request_delay_seconds)

    rows = dedupe_rows(rows)
    finished_at = utc_now()
    exhaustive = not errors and not args.limit_products and scanned == len(product_urls)
    return rows, {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "sitemap_every_product_page_okendo_reviews_product_images",
        "okendo_store_id": OKENDO_STORE_ID,
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": {
            "sitemap": {"endpoint": SITEMAP_URL, "source_pages": sitemap_pages, "unique_product_urls": len(product_urls)},
            "reconciled_unique_product_urls": len(product_urls),
            "product_type_counts": dict(type_counts.most_common()),
        },
        "products_discovered": len(product_urls),
        "products_scanned": scanned,
        "product_pages_scanned": scanned,
        "review_pages_scanned": review_pages_scanned,
        "coverage_exhaustive": exhaustive,
        "full_catalog_scrape_complete": exhaustive,
        "scrape_scope_status": "full_public_sitemap_product_pages_and_okendo_reviews_complete" if exhaustive else "stopped_or_limited",
        "customer_review_feed_used": True,
        "customer_review_images_exposed": False,
        "access_policy": "public sitemaps, every public product page, and public Okendo review API only; stop on 429/captcha/WAF",
        "product_summaries": product_summaries,
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "errors": errors,
    }


def write_outputs(rows: Sequence[Dict[str, str]], summary: Dict[str, object]) -> None:
    write_intake_csv(rows, OUTPUT_CSV)
    payload = dict(summary)
    payload.update(
        {
            "output_csv": str(OUTPUT_CSV),
            "summary_json": str(SUMMARY_JSON),
            "rows_written": len(rows),
            "distinct_reviews": len({row.get("id", "") for row in rows if row.get("id")}),
            "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
            "distinct_product_urls": len({row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}),
            "rows_with_distinct_product_url": sum(1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display")),
            "rows_with_any_measurement": sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS)),
            "rows_with_customer_image": sum(1 for row in rows if row.get("image_source_type") == "customer_review_image"),
            "rows_with_customer_review_image": sum(1 for row in rows if row.get("image_source_type") == "customer_review_image"),
            "rows_with_catalog_model_image": sum(1 for row in rows if row.get("image_source_type") == "catalog_model_image"),
            "rows_with_catalog_product_image": sum(1 for row in rows if row.get("image_source_type") == "catalog_product_image"),
            "rows_with_customer_ordered_size": sum(
                1 for row in rows if row.get("size_display") and row.get("size_display", "").lower() != "unknown"
            ),
            "rows_supabase_qualified": customer_supabase_qualified_rows(rows),
        }
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape every BYLT Basics product page and public Okendo reviews.")
    parser.add_argument("--okendo-page-size", type=int, default=100)
    parser.add_argument("--limit-products", type=int, default=0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.2)
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
