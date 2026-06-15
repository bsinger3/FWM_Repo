#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlencode
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


SITE_ROOT = "https://unboundmerino.com"
RETAILER = "unboundmerino_com"
SHOP_DOMAIN = "unbound-merino.myshopify.com"
CATALOG_URL = f"{SITE_ROOT}/products.json"
OKENDO_API_ROOT = "https://api.okendo.io/v1"
OKENDO_STORE_ID = "4acb93f7-7852-4912-a029-9309cd03fcf2"

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
OKENDO_BLOCK_RE = re.compile(r'<script type="application/json" data-oke-metafield-data="">\s*(.*?)\s*</script>', re.S)
SIZE_TOKEN_RE = re.compile(r"^\s*(XXS|XS|S|M|L|XL|XXL|XXXL|[1-5]X|[1-5]XL|[0-9]{1,2})\b", re.I)


class PressureStop(RuntimeError):
    pass


def request_text(url: str, *, accept: str = "text/html,application/json,*/*") -> str:
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


def request_json(url: str, *, referer: str = SITE_ROOT) -> Dict[str, object]:
    text = request_text(url, accept="application/json,text/plain,*/*")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise PressureStop(f"unexpected_json_response: {url}")
    return payload


def product_url(handle: str) -> str:
    return f"{SITE_ROOT}/products/{handle}"


def fetch_catalog(limit: int, max_pages: int, delay: float) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    page_counts: List[Dict[str, object]] = []
    seen_handles = set()
    for page in range(1, max_pages + 1):
        url = f"{CATALOG_URL}?{urlencode({'limit': limit, 'page': page})}"
        payload = request_json(url)
        page_products = payload.get("products") or []
        if not isinstance(page_products, list):
            raise PressureStop(f"unexpected_products_json_shape: {url}")
        page_counts.append({"page": page, "url": url, "products": len(page_products)})
        if not page_products:
            break
        for product in page_products:
            if not isinstance(product, dict):
                continue
            handle = normalize_whitespace(product.get("handle"))
            if handle and handle not in seen_handles:
                seen_handles.add(handle)
                products.append(product)
        print(f"[catalog page {page}] products={len(page_products)} total={len(products)}", flush=True)
        if len(page_products) < limit:
            break
        if delay:
            time.sleep(delay)
    return products, page_counts


def context_for_product(product: Dict[str, object]) -> ProductContext:
    handle = normalize_whitespace(product.get("handle"))
    first_variant = (product.get("variants") or [{}])[0] if isinstance(product.get("variants"), list) else {}
    tags = product.get("tags", []) or []
    return ProductContext(
        url=product_url(handle),
        title=normalize_whitespace(product.get("title")),
        description=strip_tags(product.get("body_html")),
        detail=normalize_whitespace(" ".join(str(tag) for tag in tags)),
        category=normalize_whitespace(product.get("product_type")),
        brand=normalize_whitespace(product.get("vendor")) or "Unbound Merino",
        variant=normalize_whitespace(first_variant.get("title") if isinstance(first_variant, dict) else ""),
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=SHOP_DOMAIN,
        provider_hints="Shopify product page plus public Okendo reviews",
    )


def parse_okendo_payloads(product_html: str) -> List[Dict[str, object]]:
    payloads: List[Dict[str, object]] = []
    for raw in OKENDO_BLOCK_RE.findall(product_html):
        try:
            payload = json.loads(html.unescape(raw))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("reviews"), list):
            payloads.append(payload)
    return payloads


def fetch_okendo_review_pages(first_payloads: Sequence[Dict[str, object]], delay: float) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    reviews: List[Dict[str, object]] = []
    page_summaries: List[Dict[str, object]] = []
    seen_next = set()
    next_url = ""
    for payload in first_payloads:
        page_reviews = [item for item in payload.get("reviews", []) if isinstance(item, dict)]
        reviews.extend(page_reviews)
        page_summaries.append({"source": "product_page_metafield", "reviews": len(page_reviews)})
        if not next_url:
            next_url = normalize_whitespace(payload.get("reviewsNextUrl"))
    while next_url:
        if next_url in seen_next:
            raise PressureStop("okendo_next_url_loop")
        seen_next.add(next_url)
        url = urljoin(f"{OKENDO_API_ROOT}/", next_url.lstrip("/")) if next_url.startswith("/") else next_url
        payload = request_json(url)
        page_reviews = [item for item in payload.get("reviews", []) if isinstance(item, dict)]
        reviews.extend(page_reviews)
        page_summaries.append({"source": "okendo_api", "url": url, "reviews": len(page_reviews)})
        next_url = normalize_whitespace(payload.get("reviewsNextUrl"))
        if delay:
            time.sleep(delay)
    return reviews, page_summaries


def review_size(review: Dict[str, object]) -> str:
    attrs = review.get("productAttributes")
    if isinstance(attrs, list):
        for attr in attrs:
            if not isinstance(attr, dict):
                continue
            title = normalize_whitespace(attr.get("title")).lower()
            value = attr.get("value")
            if "size" in title:
                raw = value[0] if isinstance(value, list) and value else value
                match = SIZE_TOKEN_RE.match(normalize_whitespace(raw))
                if match:
                    return match.group(1).upper()
    variant = normalize_whitespace(review.get("productVariantName"))
    if "/" in variant:
        maybe_size = variant.rsplit("/", 1)[-1].strip()
        match = SIZE_TOKEN_RE.match(maybe_size)
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
        review_id = normalize_whitespace(review.get("reviewId")) or hashlib.md5(
            f"{context.url}|{body}".encode("utf-8")
        ).hexdigest()[:16]
        row = build_intake_row(
            context,
            ReviewImage(
                image_url=image_url,
                review_id=f"unboundmerino-okendo-{review_id}",
                review_title=normalize_whitespace(review.get("title")),
                review_body=body,
                reviewer_name=reviewer_name(review),
                date_raw=normalize_whitespace(review.get("dateCreated")),
                size_raw=review_size(review),
                rating=normalize_whitespace(review.get("rating")),
                extra={
                    "image_source_type": "catalog_product_image",
                    "image_source_detail": "public Okendo review joined to public product/variant image; no customer review media exposed in Okendo payload",
                    "product_url": canonical_product_url(context.url),
                    "product_title": context.title,
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
    products, page_counts = fetch_catalog(args.catalog_limit, args.max_catalog_pages, args.request_delay_seconds)
    rows: List[Dict[str, str]] = []
    errors: List[str] = []
    product_summaries: List[Dict[str, object]] = []
    type_counts = Counter(normalize_whitespace(product.get("product_type")) or "unknown" for product in products)
    scanned = 0
    review_pages_scanned = 0

    for index, product in enumerate(products, start=1):
        context = context_for_product(product)
        try:
            product_html = request_text(context.url)
            payloads = parse_okendo_payloads(product_html)
            reviews, page_summaries = fetch_okendo_review_pages(payloads, args.request_delay_seconds)
        except PressureStop as exc:
            errors.append(f"{context.url}: {exc}")
            print(f"[stop] {context.url}: {exc}", flush=True)
            break
        scanned += 1
        product_rows = rows_from_reviews(context, reviews, started_at)
        rows.extend(product_rows)
        review_pages_scanned += len(page_summaries)
        product_summaries.append(
            {
                "product_url": context.url,
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
        print(f"[product {index}/{len(products)}] reviews={len(reviews)} rows={len(product_rows)} total={len(rows)} {context.handle}", flush=True)
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
        "adapter": "shopify_every_product_page_okendo_reviews_product_images",
        "okendo_store_id": OKENDO_STORE_ID,
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": {
            "shopify_products_json": {
                "endpoint": CATALOG_URL,
                "page_counts": page_counts,
                "unique_handles": len(products),
                "product_type_counts": dict(type_counts.most_common()),
            },
            "reconciled_unique_product_urls": len(products),
        },
        "products_discovered": len(products),
        "products_scanned": scanned,
        "product_pages_scanned": scanned,
        "review_pages_scanned": review_pages_scanned,
        "coverage_exhaustive": exhaustive,
        "full_catalog_scrape_complete": exhaustive,
        "scrape_scope_status": "full_public_catalog_product_pages_and_okendo_reviews_complete" if exhaustive else "stopped_or_limited",
        "customer_review_feed_used": True,
        "customer_review_images_exposed": False,
        "access_policy": "public Shopify products.json, every public product page, embedded public Okendo metafields, and public Okendo pagination API only; stop on 429/captcha/WAF",
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
    parser = argparse.ArgumentParser(description="Scrape every Unbound Merino product page and public Okendo reviews.")
    parser.add_argument("--catalog-limit", type=int, default=250)
    parser.add_argument("--max-catalog-pages", type=int, default=20)
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
