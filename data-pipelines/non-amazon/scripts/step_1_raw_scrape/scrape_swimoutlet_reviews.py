#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    strip_tags,
    validate_rows,
    write_intake_csv,
)


SITE_ROOT = "https://www.swimoutlet.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
OKENDO_STORE_ID = "2915ad0c-3ac4-4e21-b85f-e0308a320c04"
OKENDO_API_ROOT = f"https://api.okendo.io/v1/stores/{OKENDO_STORE_ID}"
RETAILER = "swimoutlet_com"
BRAND = "SwimOutlet"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
DEFAULT_REQUEST_DELAY_SECONDS = 0.5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def polite_pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, referer: str = SOURCE_SITE, retries: int = 4, delay: float = DEFAULT_REQUEST_DELAY_SECONDS) -> Dict[str, object]:
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
                "Referer": referer,
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                payload = json.load(resp)
            polite_pause(delay)
            return payload
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
        except (URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(min(2**attempt, 20) + delay)
    raise RuntimeError(f"Failed JSON request for {query_url}: {last_error}")


def product_url_for(product: Dict[str, object]) -> str:
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def product_context(product: Dict[str, object]) -> ProductContext:
    variants = [item for item in product.get("variants", []) if isinstance(item, dict)] if isinstance(product.get("variants"), list) else []
    variant_titles: List[str] = []
    for variant in variants[:200]:
        title = norm(variant.get("title"))
        if title and title.lower() != "default title" and title not in variant_titles:
            variant_titles.append(title)
    tags = product.get("tags")
    tags_text = " ".join(str(tag) for tag in tags) if isinstance(tags, list) else norm(tags)
    return ProductContext(
        url=product_url_for(product),
        title=norm(product.get("title")),
        description=strip_tags(product.get("body_html")),
        detail=" | ".join(variant_titles),
        category=norm(product.get("product_type")),
        brand=norm(product.get("vendor")) or BRAND,
        product_id=norm(product.get("id")),
        handle=norm(product.get("handle")),
        shop_domain="swimoutlet.myshopify.com",
        provider_hints="Okendo",
        raw_html=tags_text,
    )


def fetch_products(limit_products: Optional[int], delay: float) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    sources: List[Dict[str, object]] = []
    page = 1
    while True:
        payload = fetch_json(PRODUCTS_JSON_URL, {"limit": PRODUCTS_PER_PAGE, "page": page}, delay=delay)
        page_products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        sources.append({"source": "products.json", "page": page, "count": len(page_products)})
        if not page_products:
            break
        products.extend(page_products)
        print(f"[catalog page {page}] products={len(page_products)} total={len(products)}", flush=True)
        if len(page_products) < PRODUCTS_PER_PAGE or (limit_products is not None and len(products) >= limit_products):
            break
        page += 1
    if limit_products is not None:
        products = products[:limit_products]
    sources.append({"source": "products_json_full_catalog", "count": len(products)})
    return products, sources


def okendo_reviews_url(product_id: object) -> str:
    return f"{OKENDO_API_ROOT}/products/shopify-{product_id}/reviews"


def normalize_product_url(value: object, fallback: str) -> str:
    text = norm(value)
    if text.startswith("//"):
        text = "https:" + text
    if text.startswith("/"):
        text = urljoin(SITE_ROOT, text)
    return (text or fallback).split("?", 1)[0].rstrip("/")


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
            or item.get("thumbnailUrl")
            or image_urls.get("fullSizeUrl")
            or image_urls.get("largeUrl")
            or image_urls.get("thumbnailUrl")
        )
        if url and url not in urls:
            urls.append(url)
    return urls


def variant_parts(value: object) -> Tuple[str, str]:
    text = norm(value)
    if " / " not in text:
        return "", text
    parts = [norm(part) for part in text.split(" / ") if norm(part)]
    if len(parts) < 2:
        return "", text
    return parts[0], parts[-1]


def review_to_rows(review: Dict[str, object], context: ProductContext, fetched_at: str) -> List[Dict[str, str]]:
    urls = media_urls(review)
    if not urls:
        return []
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    color, size = variant_parts(review.get("productVariantName"))
    product_url = normalize_product_url(review.get("productUrl"), context.url)
    product_title = norm(review.get("productName")) or context.title
    review_date = norm(review.get("dateCreated")).split("T", 1)[0]
    rows: List[Dict[str, str]] = []
    for image_index, image_url in enumerate(urls, start=1):
        review_image = ReviewImage(
            image_url=image_url,
            review_id=f"{norm(review.get('reviewId'))}-{image_index}" if norm(review.get("reviewId")) else "",
            review_title=strip_tags(review.get("title")),
            review_body=strip_tags(review.get("body")),
            reviewer_name=norm(reviewer.get("displayName")),
            date_raw=norm(review.get("dateCreated")),
            review_date=review_date,
            size_raw=size,
            rating=norm(review.get("rating")),
            extra={
                "product_url": product_url,
                "product_title": product_title,
                "product_variant": norm(review.get("productVariantName")),
                "product_category": context.category,
                "product_detail": context.detail,
            },
        )
        row_context = ProductContext(**{**context.__dict__, "url": product_url, "title": product_title, "color": color})
        rows.append(build_intake_row(row_context, review_image, fetched_at))
    return rows


def fetch_product_reviews(context: ProductContext, limit_pages: Optional[int], delay: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    rows: List[Dict[str, str]] = []
    errors: List[str] = []
    pages = 0
    reviews_seen = 0
    next_url = okendo_reviews_url(context.product_id)
    params: Optional[Dict[str, object]] = {"limit": REVIEWS_PER_PAGE}
    while next_url:
        if limit_pages is not None and pages >= limit_pages:
            break
        try:
            payload = fetch_json(next_url, params=params, referer=context.url, delay=delay)
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
            rows.extend(review_to_rows(review, context, utc_now()))
        relative_next = norm(payload.get("nextUrl"))
        next_url = urljoin("https://api.okendo.io/v1/", relative_next.lstrip("/")) if relative_next else ""
    return rows, {
        "review_pages_scanned": pages,
        "review_count_hint": reviews_seen,
        "matching_review_images": len(rows),
        "errors": errors,
    }


def scrape(limit_products: Optional[int], limit_pages_per_product: Optional[int], request_delay_seconds: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    products, product_sources = fetch_products(limit_products, request_delay_seconds)
    all_rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[Dict[str, object]] = []
    for idx, product in enumerate(products, start=1):
        context = product_context(product)
        product_rows, meta = fetch_product_reviews(context, limit_pages_per_product, request_delay_seconds)
        all_rows.extend(product_rows)
        if meta.get("errors"):
            errors.append({"product_url": context.url, "errors": meta.get("errors")})
        product_summaries.append(
            {
                "product_index": idx,
                "product_url": context.url,
                "product_title": context.title,
                "product_type": context.category,
                "shopify_product_id": context.product_id,
                "adapter_used": "okendo_product_level",
                "review_pages_scanned": meta["review_pages_scanned"],
                "review_count_hint": meta["review_count_hint"],
                "matching_review_images": meta["matching_review_images"],
                "rows": len(product_rows),
                "errors": meta.get("errors", []),
            }
        )
        print(f"[product {idx}/{len(products)}] reviews={meta['review_count_hint']} pages={meta['review_pages_scanned']} rows={len(product_rows)} url={context.url}", flush=True)
    rows = dedupe_rows(all_rows)
    rows.sort(key=lambda row: (row.get("review_date", ""), row.get("product_page_url_display", ""), row.get("original_url_display", "")), reverse=True)
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "okendo_product_level",
        "okendo_store_id": OKENDO_STORE_ID,
        "started_at": started_at,
        "finished_at": utc_now(),
        "output_csv": str(OUTPUT_CSV),
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "product_pages_scanned": len(products),
        "review_pages_scanned": sum(int(item["review_pages_scanned"]) for item in product_summaries),
        "product_review_count_hint": sum(int(item["review_count_hint"]) for item in product_summaries),
        "products_with_review_rows": sum(1 for item in product_summaries if int(item["rows"]) > 0),
        "product_summaries": product_summaries,
        "errors": errors,
        "access_policy": f"public_product_and_review_pages_only; no_auth_bypass; no_captcha_bypass; restricted_or_unavailable_pages_are_skipped; polite_retries; request_delay_seconds={request_delay_seconds}",
        "discovery_method": "shopify_products_json",
        "scrape_scope_status": "full_catalog_attempted" if limit_products is None else "limited_smoke",
        "full_catalog_scrape_complete": limit_products is None,
        "seed_scrape_only": False,
        "warnings": [],
    }
    summary.update(validate_rows(rows))
    return rows, summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape SwimOutlet public Okendo product review images into the Step 1 intake schema.")
    parser.add_argument("--limit-products", type=int)
    parser.add_argument("--limit-pages-per-product", type=int)
    parser.add_argument("--request-delay-seconds", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS)
    args = parser.parse_args(argv)
    rows, summary = scrape(args.limit_products, args.limit_pages_per_product, args.request_delay_seconds)
    write_intake_csv(rows, OUTPUT_CSV)
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Rows written: {len(rows)}")
    print(f"Qualified rows: {summary.get('rows_with_image_product_size_and_measurement', 0)}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
