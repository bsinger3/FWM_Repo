#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from html import unescape
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
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


SITE_ROOT = "https://www.curvykate.com"
RETAILER = "curvykate_com"
CATALOG_URL = f"{SITE_ROOT}/products.json"
FEEFO_MERCHANT_ID = "curvy-kate-brand-parent"
FEEFO_REVIEWS_URL = "https://api.feefo.com/api/10/reviews/product"

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
]

PARENT_SKU_RE = re.compile(r'data-parent-product-sku="([^"]+)"', re.I)
APPAREL_RE = re.compile(r"\b(bikini|bra|brief|lingerie|short|swim|swimsuit|thong|top)\b", re.I)


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


def request_json(url: str) -> Dict[str, object]:
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
        brand=normalize_whitespace(product.get("vendor")) or "Curvy Kate",
        color=tag_value(tags, "Colour"),
        variant=normalize_whitespace(first_variant.get("title") if isinstance(first_variant, dict) else ""),
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=urlparse(SITE_ROOT).netloc,
        provider_hints="Shopify product page plus public Feefo product reviews",
    )


def tag_value(tags: Iterable[object], prefix: str) -> str:
    prefix_lower = prefix.lower() + ":"
    for tag in tags:
        text = normalize_whitespace(tag)
        if text.lower().startswith(prefix_lower):
            return normalize_whitespace(text.split(":", 1)[1])
    return ""


def product_text(product: Dict[str, object]) -> str:
    return normalize_whitespace(
        " ".join(
            str(part or "")
            for part in [
                product.get("title"),
                product.get("product_type"),
                " ".join(str(tag) for tag in product.get("tags", []) or []),
                strip_tags(product.get("body_html")),
            ]
        )
    )


def is_apparel(product: Dict[str, object]) -> bool:
    context = context_for_product(product)
    text = product_text(product)
    return bool(classify_clothing_type(context) or APPAREL_RE.search(text))


def product_images(product: Dict[str, object]) -> List[str]:
    images = product.get("images") if isinstance(product.get("images"), list) else []
    urls: List[str] = []
    seen = set()
    for image in images:
        if not isinstance(image, dict):
            continue
        src = normalize_whitespace(image.get("src"))
        if src:
            image_url = src if src.startswith("http") else f"https:{src}"
            if image_url not in seen:
                seen.add(image_url)
                urls.append(image_url)
    return urls


def parent_sku_from_page(product: Dict[str, object], product_html: str) -> str:
    match = PARENT_SKU_RE.search(product_html)
    if match:
        return normalize_whitespace(unescape(match.group(1))).lower()
    handle = normalize_whitespace(product.get("handle"))
    return re.sub(r"-(?:black|blue|brown|cream|green|grey|gray|ivory|multi|orange|pink|purple|red|white|yellow).*$", "", handle)


def feefo_reviews_url(parent_sku: str, page: int, page_size: int) -> str:
    return f"{FEEFO_REVIEWS_URL}?{urlencode({'merchant_identifier': FEEFO_MERCHANT_ID, 'parent_product_sku': parent_sku, 'page': page, 'page_size': page_size})}"


def fetch_feefo_reviews(parent_sku: str, page_size: int, delay: float) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    reviews: List[Dict[str, object]] = []
    page_summaries: List[Dict[str, object]] = []
    first = request_json(feefo_reviews_url(parent_sku, 1, page_size))
    meta = ((first.get("summary") or {}).get("meta") or {}) if isinstance(first.get("summary"), dict) else {}
    pages = int(meta.get("pages") or 0)
    count = int(meta.get("count") or 0)
    pages = max(pages, 1 if count else 0)
    for page in range(1, pages + 1):
        payload = first if page == 1 else request_json(feefo_reviews_url(parent_sku, page, page_size))
        page_reviews = payload.get("reviews") or []
        if not isinstance(page_reviews, list):
            page_reviews = []
        reviews.extend(review for review in page_reviews if isinstance(review, dict))
        page_summaries.append({"page": page, "reviews": len(page_reviews), "count_hint": count})
        if delay:
            time.sleep(delay)
    return reviews, page_summaries


def rows_from_reviews(
    product: Dict[str, object],
    context: ProductContext,
    parent_sku: str,
    reviews: Sequence[Dict[str, object]],
    fetched_at: str,
) -> List[Dict[str, str]]:
    image_urls = product_images(product)
    if not image_urls:
        return []
    rows: List[Dict[str, str]] = []
    for review in reviews:
        customer = review.get("customer") if isinstance(review.get("customer"), dict) else {}
        for product_review in review.get("products") or []:
            if not isinstance(product_review, dict):
                continue
            review_body = normalize_whitespace(product_review.get("review"))
            if not review_body:
                continue
            feefo_product = product_review.get("product") if isinstance(product_review.get("product"), dict) else {}
            review_id = normalize_whitespace(product_review.get("id")) or hashlib.md5(
                f"{context.url}|{parent_sku}|{review_body}".encode("utf-8")
            ).hexdigest()[:16]
            rating = ""
            if isinstance(product_review.get("rating"), dict):
                rating = normalize_whitespace(product_review["rating"].get("rating"))
            for image_index, image_url in enumerate(image_urls, start=1):
                row = build_intake_row(
                    context,
                    ReviewImage(
                        image_url=image_url,
                        review_id=f"curvykate-feefo-{review_id}",
                        review_body=review_body,
                        reviewer_name=normalize_whitespace(customer.get("display_name") if isinstance(customer, dict) else ""),
                        reviewer_profile_url=normalize_whitespace(review.get("url")),
                        date_raw=normalize_whitespace(product_review.get("created_at") or review.get("last_updated_date")),
                        rating=rating,
                        extra={
                            "image_source_type": "catalog_product_image",
                            "image_source_detail": (
                                "public Feefo review text joined to public Shopify product gallery image "
                                f"{image_index} of {len(image_urls)}; no customer review images exposed"
                            ),
                            "product_url": canonical_product_url(normalize_whitespace(feefo_product.get("url")) or context.url),
                            "product_title": normalize_whitespace(feefo_product.get("title")) or context.title,
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
    feefo_cache: Dict[str, Tuple[List[Dict[str, object]], List[Dict[str, object]]]] = {}
    parent_to_products: Dict[str, List[str]] = defaultdict(list)
    type_counts = Counter(normalize_whitespace(product.get("product_type")) or "unknown" for product in products)
    scanned = 0

    for index, product in enumerate(products, start=1):
        context = context_for_product(product)
        try:
            product_html = request_text(context.url)
        except PressureStop as exc:
            errors.append(f"{context.url}: {exc}")
            print(f"[stop] {context.url}: {exc}", flush=True)
            break
        scanned += 1
        parent_sku = parent_sku_from_page(product, product_html)
        parent_to_products[parent_sku].append(context.url)
        product_rows: List[Dict[str, str]] = []
        skip_reason = ""
        if not is_apparel(product):
            skip_reason = "out_of_scope_non_apparel"
        elif not parent_sku:
            skip_reason = "missing_feefo_parent_sku"
        else:
            if parent_sku not in feefo_cache:
                try:
                    feefo_cache[parent_sku] = fetch_feefo_reviews(parent_sku, args.feefo_page_size, args.request_delay_seconds)
                except PressureStop as exc:
                    errors.append(f"{context.url}: {exc}")
                    print(f"[stop] {context.url}: {exc}", flush=True)
                    break
            reviews, _page_summaries = feefo_cache.get(parent_sku, ([], []))
            product_rows = rows_from_reviews(product, context, parent_sku, reviews, started_at)
            if not product_rows:
                skip_reason = "no_feefo_review_rows_or_no_catalog_image"
        rows.extend(product_rows)
        product_summaries.append(
            {
                "product_url": context.url,
                "product_title": context.title,
                "shopify_product_id": context.product_id,
                "product_type": context.category,
                "clothing_type_id": classify_clothing_type(context),
                "feefo_parent_sku": parent_sku,
                "shopify_product_gallery_images": len(product_images(product)),
                "rows": len(product_rows),
                "skipped_from_output": not bool(product_rows),
                "skip_reason": skip_reason,
            }
        )
        print(f"[product {index}/{len(products)}] rows={len(product_rows)} total={len(rows)} {context.handle}", flush=True)
        if args.limit_products and scanned >= args.limit_products:
            break
        if args.request_delay_seconds:
            time.sleep(args.request_delay_seconds)

    rows = dedupe_rows(rows)
    finished_at = utc_now()
    exhaustive = not errors and not args.limit_products and scanned == len(products)
    feefo_page_summaries = {
        parent_sku: {"pages": pages, "reviews": len(reviews), "product_urls": parent_to_products.get(parent_sku, [])}
        for parent_sku, (reviews, pages) in feefo_cache.items()
    }
    return rows, {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_every_product_page_feefo_parent_product_reviews",
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
        "review_pages_scanned": sum(len(item["pages"]) for item in feefo_page_summaries.values()),
        "feefo_parent_skus_scanned": len(feefo_cache),
        "feefo_review_page_summaries": feefo_page_summaries,
        "coverage_exhaustive": exhaustive,
        "full_catalog_scrape_complete": exhaustive,
        "scrape_scope_status": "full_public_catalog_product_pages_and_feefo_reviews_complete" if exhaustive else "stopped_or_limited",
        "customer_review_feed_used": True,
        "customer_review_images_exposed": False,
        "catalog_image_strategy": "all public Shopify product gallery images joined to each public Feefo product review",
        "access_policy": "public Shopify products.json, every public product page, and public Feefo product review API only; stop on 429/captcha/WAF",
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
    parser = argparse.ArgumentParser(description="Scrape every Curvy Kate product page and public Feefo product reviews.")
    parser.add_argument("--catalog-limit", type=int, default=250)
    parser.add_argument("--max-catalog-pages", type=int, default=20)
    parser.add_argument("--feefo-page-size", type=int, default=100)
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
