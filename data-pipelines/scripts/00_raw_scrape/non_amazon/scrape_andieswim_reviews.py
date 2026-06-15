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

PIPELINE_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, legacy_raw_run_dir, raw_scraped_data_root, reports_root  # noqa: E402
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


SITE_ROOT = "https://andieswim.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
OKENDO_STORE_ID = "d47c3b09-1c8d-4b29-b158-9f2d9489623e"
OKENDO_API_ROOT = f"https://api.okendo.io/v1/stores/{OKENDO_STORE_ID}"
RETAILER = "andieswim_com"
BRAND = "Andie Swim"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
DEFAULT_REQUEST_DELAY_SECONDS = 0.5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = legacy_raw_run_dir(RETAILER)
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"
CHECKPOINT_JSON = OUTPUT_DIR / f"{RETAILER}_store_reviews_checkpoint.json"
CHECKPOINT_ROWS_JSONL = OUTPUT_DIR / f"{RETAILER}_store_reviews_rows.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def polite_pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def load_jsonl_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append({str(key): str(value) for key, value in payload.items()})
    return rows


def append_jsonl_rows(path: Path, rows: Sequence[Dict[str, str]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True))
            handle.write("\n")


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
            if exc.code == 429:
                raise RuntimeError(f"Stopped after HTTP 429 Too Many Requests for {query_url}") from exc
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
        shop_domain="andie-swim-1.myshopify.com",
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


def okendo_store_reviews_url() -> str:
    return f"{OKENDO_API_ROOT}/reviews"


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


def attribute_text(review: Dict[str, object]) -> str:
    parts: List[str] = []
    for source in (review.get("productAttributes"), review.get("attributesWithRating")):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, dict):
                continue
            title = norm(item.get("title")).rstrip(":")
            value = item.get("value")
            if isinstance(value, list):
                value_text = ", ".join(norm(part) for part in value if norm(part))
            else:
                value_text = norm(value)
            if title and value_text:
                parts.append(f"{title}: {value_text}")
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    reviewer_attributes = reviewer.get("attributes")
    if isinstance(reviewer_attributes, list):
        for item in reviewer_attributes:
            if not isinstance(item, dict):
                continue
            title = norm(item.get("title")).rstrip(":")
            value = item.get("value")
            if isinstance(value, list):
                value_text = ", ".join(norm(part) for part in value if norm(part))
            else:
                value_text = norm(value)
            if title and value_text:
                parts.append(f"{title}: {value_text}")
    return " ".join(parts)


def purchased_size(review: Dict[str, object], fallback: str) -> str:
    for source in (review.get("productAttributes"),):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, dict):
                continue
            title = norm(item.get("title")).lower()
            value = norm(item.get("value"))
            if value and "size" in title and "purchase" in title:
                return value
    return fallback


def normalize_review_body(review: Dict[str, object]) -> str:
    return strip_tags(" ".join(part for part in [review.get("body"), attribute_text(review)] if norm(part)))


def review_to_rows(review: Dict[str, object], context: ProductContext, fetched_at: str) -> List[Dict[str, str]]:
    urls = media_urls(review)
    if not urls:
        return []
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    color, size = variant_parts(review.get("productVariantName"))
    size = purchased_size(review, size)
    product_url = normalize_product_url(review.get("productUrl"), context.url)
    if "/products/" not in product_url:
        return []
    product_title = norm(review.get("productName")) or context.title
    review_date = norm(review.get("dateCreated")).split("T", 1)[0]
    rows: List[Dict[str, str]] = []
    for image_index, image_url in enumerate(urls, start=1):
        review_image = ReviewImage(
            image_url=image_url,
            review_id=f"{norm(review.get('reviewId'))}-{image_index}" if norm(review.get("reviewId")) else "",
            review_title=strip_tags(review.get("title")),
            review_body=normalize_review_body(review),
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
        "are_reviews_grouped": bool(payload.get("areReviewsGrouped")) if "payload" in locals() else False,
        "errors": errors,
    }


def context_from_review(review: Dict[str, object], products_by_id: Dict[str, Dict[str, object]], products_by_handle: Dict[str, Dict[str, object]]) -> ProductContext:
    product_id = norm(review.get("productId")).removeprefix("shopify-")
    handle = norm(review.get("productHandle"))
    product = products_by_id.get(product_id) or products_by_handle.get(handle)
    if product:
        return product_context(product)
    product_url = normalize_product_url(review.get("productUrl"), SITE_ROOT)
    return ProductContext(
        url=product_url,
        title=norm(review.get("productName")),
        category="",
        brand=BRAND,
        product_id=product_id,
        handle=handle,
        shop_domain="andie-swim-1.myshopify.com",
        provider_hints="Okendo",
    )


def fetch_store_reviews(
    products: List[Dict[str, object]],
    limit_pages: Optional[int],
    delay: float,
    *,
    checkpoint_path: Optional[Path] = None,
    checkpoint_rows_path: Optional[Path] = None,
    resume: bool = False,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    products_by_id = {norm(product.get("id")): product for product in products if norm(product.get("id"))}
    products_by_handle = {norm(product.get("handle")): product for product in products if norm(product.get("handle"))}
    rows: List[Dict[str, str]] = load_jsonl_rows(checkpoint_rows_path) if resume and checkpoint_rows_path else []
    errors: List[str] = []
    review_count = 0
    media_review_count = 0
    pages = 0
    next_url = okendo_store_reviews_url()
    params: Optional[Dict[str, object]] = {"limit": REVIEWS_PER_PAGE}
    product_stats: Dict[str, Dict[str, object]] = {}
    if resume and checkpoint_path and checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        next_url = norm(checkpoint.get("next_url")) or ""
        params = None
        review_count = int(checkpoint.get("reviews_seen") or 0)
    elif checkpoint_rows_path and checkpoint_rows_path.exists():
        checkpoint_rows_path.unlink()
    while next_url:
        if limit_pages is not None and pages >= limit_pages:
            break
        try:
            payload = fetch_json(next_url, params=params, referer=SOURCE_SITE, delay=delay)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            break
        params = None
        page_reviews = [item for item in payload.get("reviews", []) if isinstance(item, dict)]
        if not page_reviews:
            break
        pages += 1
        review_count += len(page_reviews)
        page_rows: List[Dict[str, str]] = []
        for review in page_reviews:
            context = context_from_review(review, products_by_id, products_by_handle)
            review_rows = review_to_rows(review, context, utc_now())
            if review_rows:
                media_review_count += 1
                rows.extend(review_rows)
                page_rows.extend(review_rows)
            key = context.url or norm(review.get("productUrl")) or norm(review.get("productId"))
            stats = product_stats.setdefault(
                key,
                {
                    "product_url": context.url,
                    "product_title": norm(review.get("productName")) or context.title,
                    "product_type": context.category,
                    "shopify_product_id": context.product_id,
                    "adapter_used": "okendo_store_level",
                    "reviews_seen": 0,
                    "media_reviews": 0,
                    "rows": 0,
                },
            )
            stats["reviews_seen"] = int(stats["reviews_seen"]) + 1
            stats["media_reviews"] = int(stats["media_reviews"]) + (1 if review_rows else 0)
            stats["rows"] = int(stats["rows"]) + len(review_rows)
        print(f"[review page {pages}] reviews={len(page_reviews)} total_reviews={review_count} rows={len(rows)}", flush=True)
        relative_next = norm(payload.get("nextUrl"))
        next_url = urljoin("https://api.okendo.io/v1/", relative_next.lstrip("/")) if relative_next else ""
        if checkpoint_rows_path:
            append_jsonl_rows(checkpoint_rows_path, page_rows)
        if checkpoint_path:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_path.write_text(
                json.dumps(
                    {
                        "retailer": RETAILER,
                        "updated_at": utc_now(),
                        "review_pages_scanned": pages,
                        "reviews_seen": review_count,
                        "rows_collected": len(rows),
                        "rows_checkpoint": str(checkpoint_rows_path) if checkpoint_rows_path else "",
                        "distinct_product_urls_seen": len(product_stats),
                        "next_url": next_url,
                        "complete": not bool(next_url),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
    return rows, {
        "review_pages_scanned": pages,
        "reviews_seen": review_count,
        "media_reviews_seen": media_review_count,
        "product_summaries": list(product_stats.values()),
        "errors": errors,
    }


def scrape(
    limit_products: Optional[int],
    limit_review_pages: Optional[int],
    request_delay_seconds: float,
    *,
    discovery_mode: str,
    checkpoint_path: Optional[Path],
    checkpoint_rows_path: Optional[Path],
    resume: bool,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    if discovery_mode == "products-json":
        products, product_sources = fetch_products(limit_products, request_delay_seconds)
    else:
        products = []
        product_sources = [
            {
                "source": "okendo_store_reviews",
                "count": 0,
                "note": "Store-feed-assisted retry avoids Shopify products.json after prior 429; product URLs/handles come from public Okendo review rows.",
            }
        ]
    all_rows, store_meta = fetch_store_reviews(
        products,
        limit_review_pages,
        request_delay_seconds,
        checkpoint_path=checkpoint_path,
        checkpoint_rows_path=checkpoint_rows_path,
        resume=resume,
    )
    product_summaries = store_meta["product_summaries"]
    errors = [{"scope": "store_reviews", "errors": store_meta.get("errors")}] if store_meta.get("errors") else []
    rows = dedupe_rows(all_rows)
    rows.sort(key=lambda row: (row.get("review_date", ""), row.get("product_page_url_display", ""), row.get("original_url_display", "")), reverse=True)
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "okendo_store_level",
        "okendo_store_id": OKENDO_STORE_ID,
        "started_at": started_at,
        "finished_at": utc_now(),
        "output_csv": str(OUTPUT_CSV),
        "product_sources": product_sources,
        "products_discovered": len(products) if products else len(product_summaries),
        "products_scanned": len(products) if products else len(product_summaries),
        "product_pages_scanned": len(products) if products else len(product_summaries),
        "review_pages_scanned": store_meta["review_pages_scanned"],
        "product_review_count_hint": store_meta["reviews_seen"],
        "store_reviews_seen": store_meta["reviews_seen"],
        "store_media_reviews_seen": store_meta["media_reviews_seen"],
        "products_with_review_rows": sum(1 for item in product_summaries if int(item["rows"]) > 0),
        "product_summaries": product_summaries,
        "errors": errors,
        "access_policy": f"public_product_and_review_pages_only; no_auth_bypass; no_captcha_bypass; restricted_or_unavailable_pages_are_skipped; polite_retries; request_delay_seconds={request_delay_seconds}",
        "discovery_method": "okendo_store_reviews_product_url_feed" if discovery_mode == "store-feed" else "shopify_products_json_and_okendo_store_reviews",
        "scrape_scope_status": (
            "full_store_review_feed_complete"
            if discovery_mode == "store-feed" and limit_review_pages is None and not errors
            else "full_catalog_attempted"
            if discovery_mode == "products-json" and limit_products is None and limit_review_pages is None
            else "limited_smoke"
        ),
        "full_catalog_scrape_complete": discovery_mode == "products-json" and limit_products is None and limit_review_pages is None and not errors,
        "full_store_review_feed_complete": discovery_mode == "store-feed" and limit_review_pages is None and not errors,
        "seed_scrape_only": False,
        "warnings": [
            "Store-feed-assisted run: every collected row is tied to an Okendo product URL, but this did not paginate Shopify products.json."
        ]
        if discovery_mode == "store-feed"
        else [],
    }
    summary.update(validate_rows(rows))
    return rows, summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Andie Swim public Okendo product review images into the Step 1 intake schema.")
    parser.add_argument("--limit-products", type=int)
    parser.add_argument("--limit-review-pages", "--limit-pages-per-product", dest="limit_review_pages", type=int)
    parser.add_argument("--request-delay-seconds", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS)
    parser.add_argument(
        "--discovery-mode",
        choices=["store-feed", "products-json"],
        default="store-feed",
        help="Default uses the public Okendo store review feed for product URLs to avoid Shopify products.json pressure.",
    )
    parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Do not write the store review pagination checkpoint.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume store-feed pagination from the checkpoint and merge rows from the row sidecar.",
    )
    args = parser.parse_args(argv)
    checkpoint_path = None if args.no_checkpoint else CHECKPOINT_JSON
    checkpoint_rows_path = None if args.no_checkpoint else CHECKPOINT_ROWS_JSONL
    rows, summary = scrape(
        args.limit_products,
        args.limit_review_pages,
        args.request_delay_seconds,
        discovery_mode=args.discovery_mode,
        checkpoint_path=checkpoint_path,
        checkpoint_rows_path=checkpoint_rows_path,
        resume=args.resume,
    )
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
