#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
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


SITE_ROOT = "https://www.jennikayne.com"
RETAILER = "jennikayne_com"
SHOP_DOMAIN = "jennikayne-prod.myshopify.com"
CATALOG_URL = f"{SITE_ROOT}/products.json"
YOTPO_APP_KEY = "SL07maOFcf3dBQcQCVtgs9CRRP9PvEvDUQ80O5Yw"
YOTPO_REVIEWS_ROOT = f"https://api-cdn.yotpo.com/v1/widget/{YOTPO_APP_KEY}/products"

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

APPAREL_RE = re.compile(
    r"\b(blazer|blouse|cardigan|cashmere|coat|dress|duster|jacket|jean|jumpsuit|legging|pant|pullover|shirt|short|skirt|sweater|tee|top|trouser)\b",
    re.I,
)


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
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": SITE_ROOT,
            "Referer": referer,
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urlopen(req, timeout=60) as response:
                status = getattr(response, "status", 200)
                text = response.read().decode("utf-8-sig", "replace")
            if status in PRESSURE_STATUS_CODES:
                raise PressureStop(f"blocked_or_rate_limited_http_{status}: {url}")
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise PressureStop(f"unexpected_json_response: {url}")
            return payload
        except HTTPError as exc:
            if exc.code in PRESSURE_STATUS_CODES:
                raise PressureStop(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
            last_error = exc
        except (TimeoutError, URLError, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt < 3:
            time.sleep(1.5 * attempt)
    raise PressureStop(f"request_failed_after_retries: {url}: {last_error}")


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


def tag_value(tags: Iterable[object], prefixes: Sequence[str]) -> str:
    lowered = [prefix.lower() + ":" for prefix in prefixes]
    for tag in tags:
        text = normalize_whitespace(tag)
        lower = text.lower()
        for prefix in lowered:
            if lower.startswith(prefix):
                return normalize_whitespace(text.split(":", 1)[1])
    return ""


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
        brand=normalize_whitespace(product.get("vendor")) or "Jenni Kayne",
        color=tag_value(tags, ["Color", "Colour"]),
        variant=normalize_whitespace(first_variant.get("title") if isinstance(first_variant, dict) else ""),
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=SHOP_DOMAIN,
        provider_hints="Shopify product page plus public Yotpo widget reviews",
    )


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


def yotpo_reviews_url(product_id: str, page: int, per_page: int) -> str:
    return f"{YOTPO_REVIEWS_ROOT}/{product_id}/reviews.json?{urlencode({'per_page': per_page, 'page': page})}"


def fetch_yotpo_reviews(product_id: str, product_url_value: str, per_page: int, delay: float) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    if not product_id:
        return [], []
    first = request_json(yotpo_reviews_url(product_id, 1, per_page), referer=product_url_value)
    response = first.get("response") if isinstance(first.get("response"), dict) else {}
    pagination = response.get("pagination") if isinstance(response.get("pagination"), dict) else {}
    total = int(pagination.get("total") or 0)
    pages = math.ceil(total / per_page) if total else 0
    reviews: List[Dict[str, object]] = []
    page_summaries: List[Dict[str, object]] = []
    for page in range(1, pages + 1):
        payload = first if page == 1 else request_json(yotpo_reviews_url(product_id, page, per_page), referer=product_url_value)
        resp = payload.get("response") if isinstance(payload.get("response"), dict) else {}
        page_reviews = resp.get("reviews") or []
        if not isinstance(page_reviews, list):
            page_reviews = []
        reviews.extend(review for review in page_reviews if isinstance(review, dict))
        page_summaries.append({"page": page, "reviews": len(page_reviews), "total_hint": total})
        if delay:
            time.sleep(delay)
    return reviews, page_summaries


def user_name(review: Dict[str, object]) -> str:
    user = review.get("user") if isinstance(review.get("user"), dict) else {}
    return normalize_whitespace(user.get("display_name") or user.get("name"))


def review_images(review: Dict[str, object]) -> List[str]:
    images = review.get("images_data")
    if not isinstance(images, list):
        return []
    urls: List[str] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        image_url = normalize_whitespace(image.get("original_url") or image.get("thumb_url"))
        if image_url and image_url not in urls:
            urls.append(image_url)
    return urls


def rows_from_reviews(
    product: Dict[str, object],
    context: ProductContext,
    reviews: Sequence[Dict[str, object]],
    fetched_at: str,
) -> List[Dict[str, str]]:
    if not is_apparel(product):
        return []
    rows: List[Dict[str, str]] = []
    for review in reviews:
        body = normalize_whitespace(review.get("content") or review.get("comment"))
        title = normalize_whitespace(review.get("title"))
        images = review_images(review)
        if not body or not images:
            continue
        review_id = normalize_whitespace(review.get("id")) or hashlib.md5(
            f"{context.url}|{body}".encode("utf-8")
        ).hexdigest()[:16]
        for index, image_url in enumerate(images, start=1):
            row = build_intake_row(
                context,
                ReviewImage(
                    image_url=image_url,
                    review_id=f"jennikayne-yotpo-{review_id}-{index}",
                    review_title=title,
                    review_body=body,
                    reviewer_name=user_name(review),
                    date_raw=normalize_whitespace(review.get("created_at")),
                    rating=normalize_whitespace(review.get("score")),
                    extra={
                        "image_source_type": "customer_review_image",
                        "image_source_detail": "public Yotpo widget review image",
                        "product_url": canonical_product_url(context.url),
                        "product_title": context.title,
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
    yotpo_products_with_reviews = 0

    for index, product in enumerate(products, start=1):
        context = context_for_product(product)
        try:
            request_text(context.url)
        except PressureStop as exc:
            errors.append(f"{context.url}: {exc}")
            print(f"[stop] {context.url}: {exc}", flush=True)
            break
        scanned += 1
        product_rows: List[Dict[str, str]] = []
        page_summaries: List[Dict[str, object]] = []
        skip_reason = ""
        if not is_apparel(product):
            skip_reason = "out_of_scope_non_apparel"
        try:
            reviews, page_summaries = fetch_yotpo_reviews(context.product_id, context.url, args.yotpo_page_size, args.request_delay_seconds)
        except PressureStop as exc:
            errors.append(f"{context.url}: {exc}")
            print(f"[stop] {context.url}: {exc}", flush=True)
            break
        if reviews:
            yotpo_products_with_reviews += 1
        review_pages_scanned += len(page_summaries)
        product_rows = rows_from_reviews(product, context, reviews, started_at)
        if not product_rows and not skip_reason:
            skip_reason = "no_customer_image_reviews"
        rows.extend(product_rows)
        product_summaries.append(
            {
                "product_url": context.url,
                "product_title": context.title,
                "shopify_product_id": context.product_id,
                "product_type": context.category,
                "clothing_type_id": classify_clothing_type(context),
                "is_apparel": is_apparel(product),
                "yotpo_review_pages": len(page_summaries),
                "yotpo_reviews": sum(int(item.get("reviews") or 0) for item in page_summaries),
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
    return rows, {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_every_product_page_yotpo_product_reviews",
        "yotpo_app_key": YOTPO_APP_KEY,
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
        "yotpo_products_with_reviews": yotpo_products_with_reviews,
        "coverage_exhaustive": exhaustive,
        "full_catalog_scrape_complete": exhaustive,
        "scrape_scope_status": "full_public_catalog_product_pages_and_yotpo_reviews_complete" if exhaustive else "stopped_or_limited",
        "customer_review_feed_used": True,
        "customer_review_images_exposed": bool(rows),
        "access_policy": "public Shopify products.json, every public product page, and public Yotpo widget API only; stop on 429/captcha/WAF",
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
    parser = argparse.ArgumentParser(description="Scrape every Jenni Kayne product page and public Yotpo product reviews.")
    parser.add_argument("--catalog-limit", type=int, default=250)
    parser.add_argument("--max-catalog-pages", type=int, default=20)
    parser.add_argument("--yotpo-page-size", type=int, default=100)
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
