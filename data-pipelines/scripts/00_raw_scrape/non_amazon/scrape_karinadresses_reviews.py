#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
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


SITE_ROOT = "https://www.karinadresses.com"
DOMAIN = "karinadresses.com"
RETAILER = "karinadresses_com"
CATALOG_URL = f"{SITE_ROOT}/products.json"
MYSHOPIFY_DOMAIN = "karinadresses.myshopify.com"
GROWAVE_AUTH_URL = (
    f"{SITE_ROOT}/apps/ssw/storefront-api/storefront-authentication-service/v2/auth/proxy"
)
GROWAVE_REVIEWS_URL = f"{SITE_ROOT}/apps/ssw/storefront-api/reviews-storefront/v2/review/getReviewList"

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
    r"\b(dress|skirt|top|tee|t-shirt|shirt|cardigan|jacket|sweater|sleeve|wrap|vest)\b",
    re.I,
)
OUT_OF_SCOPE_RE = re.compile(r"\b(gift card|shipping|insurance|mask|scrunchie|headband|bag|sticker)\b", re.I)


class PressureStop(RuntimeError):
    pass


def request_text(
    url: str,
    *,
    method: str = "GET",
    body: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    accept: str = "text/html,application/json,*/*",
    referer: str = SITE_ROOT,
) -> str:
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
    }
    request_headers.update(headers or {})
    req = Request(url, data=body, headers=request_headers, method=method)
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


def request_json(url: str, *, headers: Optional[Dict[str, str]] = None, referer: str = SITE_ROOT) -> Dict[str, object]:
    return json.loads(request_text(url, accept="application/json,text/plain,*/*", headers=headers, referer=referer))


def post_json(url: str, payload: Dict[str, object], *, headers: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    return json.loads(
        request_text(
            url,
            method="POST",
            body=body,
            headers=request_headers,
            accept="application/json,text/plain,*/*",
        )
    )


def product_url(handle: str) -> str:
    return f"{SITE_ROOT}/products/{handle}"


def fetch_catalog(limit: int, max_pages: int, delay: float) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    page_counts: List[Dict[str, object]] = []
    seen_handles = set()
    for page in range(1, max_pages + 1):
        url = f"{CATALOG_URL}?{urlencode({'limit': limit, 'page': page})}"
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
        brand="Karina Dresses",
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=MYSHOPIFY_DOMAIN,
        provider_hints="Growave public review API",
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


def growave_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Gw-Token-Strategy": "growave",
    }


def growave_guest_token() -> str:
    url = f"{GROWAVE_AUTH_URL}?{urlencode({'x-gw-current-app': 'default', 'shop': MYSHOPIFY_DOMAIN})}"
    payload = post_json(url, {"token": None}, headers={"X-Gw-Token-Strategy": "growave"})
    token = normalize_whitespace(payload.get("token"))
    if not token:
        raise PressureStop("growave_auth_returned_no_guest_token")
    return token


def growave_reviews_page(token: str, *, offset: int, per_page: int) -> Dict[str, object]:
    params = [
        ("x-gw-current-app", "default"),
        ("onlyWithMedia", "true"),
        ("perPage", str(per_page)),
        ("offset", str(offset)),
        ("sortingOptions[]", "mostRelevant"),
    ]
    return request_json(
        f"{GROWAVE_REVIEWS_URL}?{urlencode(params)}",
        headers=growave_headers(token),
    )


def image_url(image: Dict[str, object]) -> str:
    sizes = image.get("sizes") if isinstance(image.get("sizes"), list) else []
    best = ""
    best_width = -1
    for size in sizes:
        if not isinstance(size, dict):
            continue
        url = normalize_whitespace(size.get("url"))
        width = int(size.get("w") or 0)
        if url and width >= best_width:
            best = url
            best_width = width
    return best or normalize_whitespace(image.get("url"))


def attribute_text(review: Dict[str, object]) -> str:
    parts: List[str] = []
    for key in ["productAttributeAnswers", "customerAttributeAnswers"]:
        values = review.get(key) if isinstance(review.get(key), list) else []
        for item in values:
            if not isinstance(item, dict):
                continue
            title = normalize_whitespace(item.get("title") or item.get("name") or item.get("question"))
            value = normalize_whitespace(item.get("value") or item.get("answer"))
            if title and value:
                parts.append(f"{title}: {value}")
    return " ".join(parts)


def row_for_review(
    review: Dict[str, object],
    image: Dict[str, object],
    context_by_product_id: Dict[str, ProductContext],
    fetched_at: str,
) -> Dict[str, str]:
    product = review.get("product") if isinstance(review.get("product"), dict) else {}
    product_id = normalize_whitespace(product.get("id"))
    context = context_by_product_id.get(product_id) or ProductContext(
        url="",
        brand="Karina Dresses",
        product_id=product_id,
        shop_domain=MYSHOPIFY_DOMAIN,
        provider_hints="Growave public review API",
    )
    customer = review.get("customer") if isinstance(review.get("customer"), dict) else {}
    img_url = image_url(image)
    image_id = normalize_whitespace(image.get("id"))
    review_id = normalize_whitespace(review.get("uid") or review.get("id"))
    review_image = ReviewImage(
        image_url=img_url,
        review_id=f"karinadresses-growave-{review_id}-{image_id}",
        review_title=normalize_whitespace(review.get("title")),
        review_body=normalize_whitespace(" ".join([normalize_whitespace(review.get("body")), attribute_text(review)])),
        reviewer_name=normalize_whitespace(customer.get("name")),
        date_raw=normalize_whitespace(review.get("createdAt")),
        review_date=normalize_whitespace(review.get("createdAt"))[:10],
        rating=normalize_whitespace(review.get("rating")),
        extra={
            "image_source_type": "customer_review_image",
            "image_source_detail": "Growave public store review image",
            "product_url": context.url,
            "product_title": context.title,
            "product_description": context.description,
            "product_category": context.category,
            "product_detail": context.detail,
        },
    )
    return build_intake_row(context, review_image, fetched_at)


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
    product_contexts = {context.product_id: context for context in map(product_context, products) if context.product_id}
    apparel_ids = {
        normalize_whitespace(product.get("id"))
        for product in products
        if isinstance(product, dict) and is_apparel(product)
    }
    token = growave_guest_token()
    rows: List[Dict[str, str]] = []
    review_pages: List[Dict[str, object]] = []
    product_summaries: Dict[str, Dict[str, object]] = {}
    errors: List[str] = []
    offset = 0
    total_count = None
    while True:
        try:
            payload = growave_reviews_page(token, offset=offset, per_page=args.review_page_size)
        except PressureStop as exc:
            errors.append(str(exc))
            break
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        current_offset = int(payload.get("currentOffset") or offset)
        per_page = int(payload.get("perPage") or args.review_page_size)
        total_count = int(payload.get("totalCount") or 0)
        review_pages.append(
            {
                "offset": current_offset,
                "requested_per_page": args.review_page_size,
                "returned_per_page": per_page,
                "items": len(items),
                "total_count": total_count,
            }
        )
        print(f"[reviews offset {current_offset}] items={len(items)} total_count={total_count}", flush=True)
        if not items:
            break
        for review in items:
            if not isinstance(review, dict):
                continue
            product = review.get("product") if isinstance(review.get("product"), dict) else {}
            product_id = normalize_whitespace(product.get("id"))
            summary = product_summaries.setdefault(
                product_id,
                {
                    "product_id": product_id,
                    "product_url": product_contexts.get(product_id, ProductContext(url="")).url,
                    "product_title": product_contexts.get(product_id, ProductContext(url="")).title,
                    "in_catalog": product_id in product_contexts,
                    "in_apparel_catalog_scope": product_id in apparel_ids,
                    "reviews_seen": 0,
                    "matching_review_images": 0,
                    "rows": 0,
                },
            )
            summary["reviews_seen"] = int(summary["reviews_seen"]) + 1
            images = review.get("images") if isinstance(review.get("images"), list) else []
            if product_id not in apparel_ids:
                summary["skip_reason"] = "not_found_in_public_apparel_catalog"
                continue
            for image in images:
                if not isinstance(image, dict):
                    continue
                if not image_url(image):
                    continue
                summary["matching_review_images"] = int(summary["matching_review_images"]) + 1
                rows.append(row_for_review(review, image, product_contexts, started_at))
                summary["rows"] = int(summary["rows"]) + 1
        offset = current_offset + per_page
        if args.limit_review_pages and len(review_pages) >= args.limit_review_pages:
            break
        if total_count is not None and offset >= total_count:
            break
        if args.request_delay_seconds:
            time.sleep(args.request_delay_seconds)
    rows = dedupe_rows(rows)
    finished_at = utc_now()
    exhaustive = not errors and not args.limit_review_pages and (total_count is None or offset >= total_count)
    return rows, {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_growave_store_media_reviews",
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
        "products_in_apparel_scope": len(apparel_ids),
        "review_pages_scanned": len(review_pages),
        "growave_media_review_total_count": total_count,
        "growave_review_pages": review_pages,
        "exhaustive_review_paging": exhaustive,
        "coverage_exhaustive": exhaustive,
        "scrape_scope_status": "full_public_growave_media_feed_complete" if exhaustive else "stopped_or_limited",
        "catalog_model_rows_enabled": False,
        "customer_review_feed_used": True,
        "access_policy": "public Shopify products.json and public Growave app-proxy review JSON only; stop on 429/captcha/WAF",
        "product_summaries": list(product_summaries.values()),
        "products_excluded_from_output": sum(1 for item in product_summaries.values() if item.get("skip_reason")),
        "errors": errors,
    }


def write_outputs(rows: Sequence[Dict[str, str]], summary: Dict[str, object]) -> None:
    write_intake_csv(rows, OUTPUT_CSV)
    rows_with_product_url = sum(1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display"))
    rows_with_measurements = sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS))
    rows_with_customer_image = sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image")
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
            "rows_with_catalog_model_image": 0,
            "rows_with_customer_ordered_size": rows_with_ordered_size,
            "rows_with_size": rows_with_ordered_size,
            "rows_supabase_qualified": strict_supabase_qualified_rows(rows),
            "rows_catalog_model_qualified": 0,
        }
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Karina Dresses public Growave review images.")
    parser.add_argument("--catalog-limit", type=int, default=250)
    parser.add_argument("--max-catalog-pages", type=int, default=20)
    parser.add_argument("--review-page-size", type=int, default=30)
    parser.add_argument("--limit-review-pages", type=int, default=0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.25)
    args = parser.parse_args(argv)
    rows, summary = scrape(args)
    write_outputs(rows, summary)
    print(f"Rows written: {len(rows)}")
    print(f"Products discovered: {summary['products_discovered']}")
    print(f"Review pages scanned: {summary['review_pages_scanned']}")
    print(f"Growave media reviews: {summary['growave_media_review_total_count']}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
