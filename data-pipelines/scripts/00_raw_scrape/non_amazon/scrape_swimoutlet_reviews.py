#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
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
OUTPUT_DIR = legacy_raw_run_dir(RETAILER)
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"
CATALOG_CHECKPOINT_JSON = OUTPUT_DIR / f"{RETAILER}_products_json_catalog_checkpoint.json"
SITEMAP_PRODUCTS_JSON = OUTPUT_DIR / f"{RETAILER}_sitemap_product_urls.json"
STORE_REVIEWS_CHECKPOINT_JSON = OUTPUT_DIR / f"{RETAILER}_okendo_store_reviews_checkpoint.json"


class StopScrapeError(RuntimeError):
    pass


class RateLimitError(StopScrapeError):
    pass


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
            if exc.code in {403, 429, 503}:
                raise RateLimitError(f"Stopped after HTTP {exc.code} for {query_url}") from exc
            if exc.code not in {408, 500, 502, 504}:
                raise
        except (URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(min(2**attempt, 20) + delay)
    raise RuntimeError(f"Failed JSON request for {query_url}: {last_error}")


def fetch_text(url: str, referer: str = SOURCE_SITE, retries: int = 2, delay: float = DEFAULT_REQUEST_DELAY_SECONDS) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xml,text/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": referer,
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            polite_pause(delay)
            return text
        except HTTPError as exc:
            last_error = exc
            if exc.code in {403, 429, 503}:
                raise RateLimitError(f"Stopped after HTTP {exc.code} for {url}") from exc
            if exc.code not in {408, 500, 502, 504}:
                raise
        except URLError as exc:
            last_error = exc
        time.sleep(min(2**attempt, 20) + delay)
    raise RuntimeError(f"Failed text request for {url}: {last_error}")


def load_catalog_checkpoint() -> Dict[str, object]:
    if not CATALOG_CHECKPOINT_JSON.exists():
        return {"pages": {}, "sources": [], "catalog_complete": False}
    try:
        payload = json.loads(CATALOG_CHECKPOINT_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"pages": {}, "sources": [], "catalog_complete": False, "warnings": ["checkpoint_json_decode_failed"]}
    if not isinstance(payload, dict):
        return {"pages": {}, "sources": [], "catalog_complete": False, "warnings": ["checkpoint_payload_not_object"]}
    payload.setdefault("pages", {})
    payload.setdefault("sources", [])
    payload.setdefault("catalog_complete", False)
    return payload


def write_catalog_checkpoint(checkpoint: Dict[str, object]) -> None:
    CATALOG_CHECKPOINT_JSON.parent.mkdir(parents=True, exist_ok=True)
    checkpoint["updated_at"] = utc_now()
    CATALOG_CHECKPOINT_JSON.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")


def discover_sitemap_product_urls(delay: float) -> Dict[str, object]:
    if SITEMAP_PRODUCTS_JSON.exists():
        try:
            payload = json.loads(SITEMAP_PRODUCTS_JSON.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("product_url_count"):
                print(f"[sitemap checkpoint] product_urls={payload.get('product_url_count')}", flush=True)
                return payload
        except json.JSONDecodeError:
            pass
    root_text = fetch_text(f"{SITE_ROOT}/sitemap.xml", delay=delay)
    sitemap_urls: List[str] = []
    for match in re.findall(r"<loc>([^<]*sitemap_products_[^<]+)</loc>", root_text, re.I):
        sitemap_url = html.unescape(match)
        if sitemap_url not in sitemap_urls:
            sitemap_urls.append(sitemap_url)
    product_urls: List[str] = []
    seen = set()
    sources: List[Dict[str, object]] = []
    for sitemap_url in sitemap_urls:
        sitemap_text = fetch_text(sitemap_url, referer=f"{SITE_ROOT}/sitemap.xml", delay=delay)
        page_urls: List[str] = []
        for loc in re.findall(r"<loc>(https?://[^<]+/products/[^<]+)</loc>", sitemap_text, re.I):
            product_url = html.unescape(loc).split("?", 1)[0].rstrip("/")
            if product_url in seen:
                continue
            seen.add(product_url)
            page_urls.append(product_url)
            product_urls.append(product_url)
        sources.append({"source": "sitemap_products", "url": sitemap_url, "count": len(page_urls)})
        print(f"[sitemap] products={len(page_urls)} total={len(product_urls)} url={sitemap_url}", flush=True)
    payload = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "fetched_at": utc_now(),
        "sitemap_count": len(sitemap_urls),
        "product_url_count": len(product_urls),
        "sources": sources,
        "product_urls": product_urls,
    }
    SITEMAP_PRODUCTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    SITEMAP_PRODUCTS_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_store_reviews_checkpoint() -> Dict[str, object]:
    if not STORE_REVIEWS_CHECKPOINT_JSON.exists():
        return {"pages": [], "rows": [], "product_summaries": {}, "complete": False}
    try:
        payload = json.loads(STORE_REVIEWS_CHECKPOINT_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"pages": [], "rows": [], "product_summaries": {}, "complete": False, "warnings": ["store_reviews_checkpoint_json_decode_failed"]}
    if not isinstance(payload, dict):
        return {"pages": [], "rows": [], "product_summaries": {}, "complete": False, "warnings": ["store_reviews_checkpoint_payload_not_object"]}
    payload.setdefault("pages", [])
    payload.setdefault("rows", [])
    payload.setdefault("product_summaries", {})
    payload.setdefault("complete", False)
    return payload


def write_store_reviews_checkpoint(checkpoint: Dict[str, object]) -> None:
    STORE_REVIEWS_CHECKPOINT_JSON.parent.mkdir(parents=True, exist_ok=True)
    checkpoint["updated_at"] = utc_now()
    STORE_REVIEWS_CHECKPOINT_JSON.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")


def is_product_linked_customer_row(row: Dict[str, str]) -> bool:
    if row.get("image_source_type") != "customer_review_image":
        return True
    return "/products/" in (row.get("product_page_url_display") or "")


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


def checkpoint_products(checkpoint: Dict[str, object]) -> List[Dict[str, object]]:
    pages = checkpoint.get("pages") if isinstance(checkpoint.get("pages"), dict) else {}
    products: List[Dict[str, object]] = []
    for page_key in sorted(pages, key=lambda value: int(value)):
        page_payload = pages.get(page_key)
        if not isinstance(page_payload, dict):
            continue
        page_products = page_payload.get("products")
        if isinstance(page_products, list):
            products.extend(item for item in page_products if isinstance(item, dict))
    return products


def fetch_products(limit_products: Optional[int], delay: float, resume_catalog: bool) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]:
    checkpoint = load_catalog_checkpoint() if resume_catalog else {"pages": {}, "sources": [], "catalog_complete": False}
    pages = checkpoint.get("pages") if isinstance(checkpoint.get("pages"), dict) else {}
    sources: List[Dict[str, object]] = list(checkpoint.get("sources", [])) if isinstance(checkpoint.get("sources"), list) else []
    page = 1
    if pages:
        page = max(int(page_key) for page_key in pages) + 1
        print(f"[catalog checkpoint] loaded_pages={len(pages)} next_page={page}", flush=True)
    while not checkpoint.get("catalog_complete"):
        try:
            payload = fetch_json(PRODUCTS_JSON_URL, {"limit": PRODUCTS_PER_PAGE, "page": page}, delay=delay, retries=2)
        except HTTPError as exc:
            if exc.code == 400 and page > 1:
                checkpoint["products_json_boundary"] = {
                    "page": page,
                    "status": "HTTP 400 Bad Request",
                    "detail": "Stopped products.json pagination at public endpoint boundary after checkpointing prior pages.",
                    "stopped_at": utc_now(),
                }
                write_catalog_checkpoint(checkpoint)
                print(f"[catalog boundary] page={page} status=HTTP 400 after total={checkpoint.get('products_discovered_so_far')}", flush=True)
                break
            raise
        page_products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        pages[str(page)] = {"page": page, "count": len(page_products), "products": page_products, "fetched_at": utc_now()}
        checkpoint["pages"] = pages
        source = {"source": "products.json", "page": page, "count": len(page_products)}
        sources.append(source)
        checkpoint["sources"] = list(checkpoint.get("sources", [])) + [source]
        checkpoint["last_catalog_page_attempted"] = page
        checkpoint["products_discovered_so_far"] = len(checkpoint_products(checkpoint))
        write_catalog_checkpoint(checkpoint)
        if not page_products:
            checkpoint["catalog_complete"] = True
            write_catalog_checkpoint(checkpoint)
            break
        print(f"[catalog page {page}] products={len(page_products)} total={checkpoint['products_discovered_so_far']}", flush=True)
        discovered_so_far = int(checkpoint.get("products_discovered_so_far") or 0)
        if len(page_products) < PRODUCTS_PER_PAGE or (limit_products is not None and discovered_so_far >= limit_products):
            if len(page_products) < PRODUCTS_PER_PAGE:
                checkpoint["catalog_complete"] = True
                write_catalog_checkpoint(checkpoint)
            break
        page += 1
    products = checkpoint_products(checkpoint)
    if limit_products is not None:
        products = products[:limit_products]
    sources.append({"source": "products_json_full_catalog", "count": len(products)})
    return products, sources, checkpoint


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


def normalize_review_body(review: Dict[str, object]) -> str:
    return strip_tags(" ".join(part for part in [review.get("body"), attribute_text(review)] if norm(part)))


def review_to_rows(review: Dict[str, object], context: ProductContext, fetched_at: str) -> List[Dict[str, str]]:
    urls = media_urls(review)
    if not urls:
        return []
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    color, size = variant_parts(review.get("productVariantName"))
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
        shop_domain="swimoutlet.myshopify.com",
        provider_hints="Okendo",
    )


MODEL_TEXT_RE = re.compile(
    r"(?:(?:model|model is|model's)[^.\n]*(?:height|wearing|wears|size|measurements)[^.\n]*[.\n]?){1,3}",
    re.I,
)


def catalog_model_rows(product: Dict[str, object], context: ProductContext, fetched_at: str) -> List[Dict[str, str]]:
    text = strip_tags(product.get("body_html"))
    if not re.search(r"\bmodel\b", text, re.I):
        return []
    snippets = [norm(match.group(0)) for match in MODEL_TEXT_RE.finditer(text)]
    model_text = " ".join(snippets) or text
    if not re.search(r"\b(?:height|wearing|wears|size|measurements?)\b", model_text, re.I):
        return []
    images = product.get("images") if isinstance(product.get("images"), list) else []
    image_urls: List[str] = []
    for image in images[:6]:
        if not isinstance(image, dict):
            continue
        image_url = norm(image.get("src"))
        if image_url and image_url not in image_urls:
            image_urls.append(image_url)
    if not image_urls:
        return []
    rows: List[Dict[str, str]] = []
    for image_index, image_url in enumerate(image_urls[:2], start=1):
        review_image = ReviewImage(
            image_url=image_url,
            review_id=f"catalog-model-{context.product_id}-{image_index}",
            review_title="Catalog model measurements",
            review_body=model_text,
            date_raw=fetched_at,
            review_date=fetched_at.split("T", 1)[0],
            size_raw="",
            extra={
                "product_url": context.url,
                "product_title": context.title,
                "product_category": context.category,
                "product_detail": context.detail,
                "image_source_type": "catalog_model_image",
                "image_source_detail": "public Shopify product image with model-size or model-measurement text from product description",
            },
        )
        rows.append(build_intake_row(context, review_image, fetched_at))
    return rows


def fetch_store_reviews(
    products: List[Dict[str, object]],
    limit_pages: Optional[int],
    delay: float,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    products_by_id = {norm(product.get("id")): product for product in products if norm(product.get("id"))}
    products_by_handle = {norm(product.get("handle")): product for product in products if norm(product.get("handle"))}
    checkpoint = load_store_reviews_checkpoint()
    rows: List[Dict[str, str]] = [
        row
        for row in checkpoint.get("rows", [])
        if isinstance(row, dict) and is_product_linked_customer_row(row)
    ]
    errors: List[str] = []
    review_count = int(checkpoint.get("reviews_seen") or 0)
    media_review_count = int(checkpoint.get("media_reviews_seen") or 0)
    pages = len(checkpoint.get("pages", [])) if isinstance(checkpoint.get("pages"), list) else 0
    next_url = "" if checkpoint.get("complete") else (norm(checkpoint.get("next_url")) or okendo_store_reviews_url())
    params: Optional[Dict[str, object]] = None if checkpoint.get("next_url") else {"limit": REVIEWS_PER_PAGE}
    product_stats: Dict[str, Dict[str, object]] = checkpoint.get("product_summaries") if isinstance(checkpoint.get("product_summaries"), dict) else {}
    if rows or pages:
        print(f"[review checkpoint] pages={pages} reviews={review_count} rows={len(rows)} next={'yes' if next_url else 'no'}", flush=True)
    while next_url:
        if checkpoint.get("complete"):
            break
        if limit_pages is not None and pages >= limit_pages:
            break
        try:
            payload = fetch_json(next_url, params=params, referer=SOURCE_SITE, delay=delay, retries=2)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            break
        params = None
        page_reviews = [item for item in payload.get("reviews", []) if isinstance(item, dict)]
        if not page_reviews:
            break
        pages += 1
        page_row_count = 0
        review_count += len(page_reviews)
        for review in page_reviews:
            context = context_from_review(review, products_by_id, products_by_handle)
            review_rows = review_to_rows(review, context, utc_now())
            if review_rows:
                media_review_count += 1
                rows.extend(review_rows)
                page_row_count += len(review_rows)
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
        checkpoint.update(
            {
                "pages": list(checkpoint.get("pages", [])) + [{"page": pages, "reviews": len(page_reviews), "rows": page_row_count, "fetched_at": utc_now()}],
                "rows": rows,
                "reviews_seen": review_count,
                "media_reviews_seen": media_review_count,
                "product_summaries": product_stats,
                "next_url": next_url,
                "complete": not bool(next_url),
            }
        )
        write_store_reviews_checkpoint(checkpoint)
    return rows, {
        "review_pages_scanned": pages,
        "reviews_seen": review_count,
        "media_reviews_seen": media_review_count,
        "product_summaries": list(product_stats.values()),
        "errors": errors,
    }


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


def scrape(limit_products: Optional[int], limit_review_pages: Optional[int], request_delay_seconds: float, resume_catalog: bool) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    products, product_sources, catalog_checkpoint = fetch_products(limit_products, request_delay_seconds, resume_catalog)
    sitemap_payload = discover_sitemap_product_urls(request_delay_seconds)
    all_rows, store_meta = fetch_store_reviews(products, limit_review_pages, request_delay_seconds)
    customer_product_summaries = store_meta["product_summaries"]
    catalog_model_count = 0
    for product in products:
        context = product_context(product)
        model_rows = catalog_model_rows(product, context, utc_now())
        catalog_model_count += len(model_rows)
        all_rows.extend(model_rows)
    product_summaries: List[Dict[str, object]] = customer_product_summaries
    errors: List[Dict[str, object]] = []
    if store_meta.get("errors"):
        errors.append({"scope": "store_reviews", "errors": store_meta.get("errors")})
    rows = dedupe_rows(all_rows)
    rows.sort(key=lambda row: (row.get("review_date", ""), row.get("product_page_url_display", ""), row.get("original_url_display", "")), reverse=True)
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "okendo_store_level_plus_catalog_model_rows",
        "okendo_store_id": OKENDO_STORE_ID,
        "started_at": started_at,
        "finished_at": utc_now(),
        "output_csv": str(OUTPUT_CSV),
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "product_pages_scanned": len(products),
        "review_pages_scanned": store_meta["review_pages_scanned"],
        "product_review_count_hint": store_meta["reviews_seen"],
        "store_reviews_seen": store_meta["reviews_seen"],
        "store_media_reviews_seen": store_meta["media_reviews_seen"],
        "catalog_model_rows_before_dedupe": catalog_model_count,
        "products_with_review_rows": sum(1 for item in product_summaries if int(item["rows"]) > 0),
        "product_summaries": product_summaries,
        "errors": errors,
        "access_policy": f"public_product_and_review_pages_only; no_auth_bypass; no_captcha_bypass; restricted_or_unavailable_pages_are_skipped; polite_retries; request_delay_seconds={request_delay_seconds}",
        "catalog_checkpoint_json": str(CATALOG_CHECKPOINT_JSON),
        "sitemap_products_json": str(SITEMAP_PRODUCTS_JSON),
        "store_reviews_checkpoint_json": str(STORE_REVIEWS_CHECKPOINT_JSON),
        "catalog_checkpoint_pages": len(catalog_checkpoint.get("pages", {})) if isinstance(catalog_checkpoint.get("pages"), dict) else 0,
        "products_json_boundary": catalog_checkpoint.get("products_json_boundary", {}),
        "sitemap_product_url_count": sitemap_payload.get("product_url_count"),
        "sitemap_product_sitemap_count": sitemap_payload.get("sitemap_count"),
        "catalog_complete": bool(sitemap_payload.get("product_url_count")) and not catalog_checkpoint.get("products_json_boundary", {}).get("rate_limited"),
        "discovery_method": "shopify_products_json_checkpointed_sitemap_products_and_okendo_store_reviews",
        "scrape_scope_status": "full_catalog_attempted" if limit_products is None and limit_review_pages is None else "bounded_resume",
        "full_catalog_scrape_complete": limit_products is None and limit_review_pages is None and bool(sitemap_payload.get("product_url_count")) and not errors,
        "seed_scrape_only": False,
        "warnings": [],
    }
    summary.update(validate_rows(rows))
    return rows, summary


def read_existing_catalog_model_rows() -> List[Dict[str, str]]:
    if not OUTPUT_CSV.exists():
        return []
    with OUTPUT_CSV.open(newline="", encoding="utf-8-sig") as handle:
        return [
            dict(row)
            for row in csv.DictReader(handle)
            if row.get("original_url_display") and row.get("image_source_type") == "catalog_model_image"
        ]


def store_feed_only_summary_base() -> Dict[str, object]:
    if SUMMARY_JSON.exists():
        try:
            payload = json.loads(SUMMARY_JSON.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
    return {}


def scrape_store_feed_only(limit_review_pages: Optional[int], request_delay_seconds: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    customer_rows, store_meta = fetch_store_reviews([], limit_review_pages, request_delay_seconds)
    catalog_model_rows_existing = read_existing_catalog_model_rows()
    rows = dedupe_rows([*customer_rows, *catalog_model_rows_existing])
    rows.sort(key=lambda row: (row.get("review_date", ""), row.get("product_page_url_display", ""), row.get("original_url_display", "")), reverse=True)
    base = store_feed_only_summary_base()
    product_summaries = store_meta["product_summaries"]
    errors: List[Dict[str, object]] = []
    if store_meta.get("errors"):
        errors.append({"scope": "store_reviews", "errors": store_meta.get("errors")})
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "okendo_store_level_resume_plus_existing_catalog_model_rows",
        "okendo_store_id": OKENDO_STORE_ID,
        "started_at": started_at,
        "finished_at": utc_now(),
        "output_csv": str(OUTPUT_CSV),
        "product_sources": base.get("product_sources", []),
        "products_discovered": base.get("products_discovered", 0),
        "products_scanned": base.get("products_scanned", 0),
        "product_pages_scanned": base.get("product_pages_scanned", base.get("products_scanned", 0)),
        "review_pages_scanned": store_meta["review_pages_scanned"],
        "product_review_count_hint": store_meta["reviews_seen"],
        "store_reviews_seen": store_meta["reviews_seen"],
        "store_media_reviews_seen": store_meta["media_reviews_seen"],
        "catalog_model_rows_before_dedupe": len(catalog_model_rows_existing),
        "products_with_review_rows": sum(1 for item in product_summaries if int(item["rows"]) > 0),
        "product_summaries": product_summaries,
        "errors": errors,
        "access_policy": f"public_product_and_review_pages_only; no_auth_bypass; no_captcha_bypass; stop_immediately_on_403_429_503; checkpointed_store_feed_resume; request_delay_seconds={request_delay_seconds}",
        "catalog_checkpoint_json": str(CATALOG_CHECKPOINT_JSON),
        "sitemap_products_json": str(SITEMAP_PRODUCTS_JSON),
        "store_reviews_checkpoint_json": str(STORE_REVIEWS_CHECKPOINT_JSON),
        "catalog_checkpoint_pages": base.get("catalog_checkpoint_pages", 0),
        "products_json_boundary": base.get("products_json_boundary", {}),
        "sitemap_product_url_count": base.get("sitemap_product_url_count"),
        "sitemap_product_sitemap_count": base.get("sitemap_product_sitemap_count"),
        "catalog_complete": base.get("catalog_complete", False),
        "discovery_method": "okendo_store_reviews_checkpoint_only_existing_catalog_context",
        "scrape_scope_status": "store_feed_resume_complete" if load_store_reviews_checkpoint().get("complete") else "store_feed_resume_bounded",
        "full_catalog_scrape_complete": bool(load_store_reviews_checkpoint().get("complete")) and not errors,
        "seed_scrape_only": False,
        "warnings": [
            "Store-feed-only resume skipped reloading the large products.json checkpoint; product context comes from Okendo review fields plus existing catalog-model rows."
        ],
    }
    summary.update(validate_rows(rows))
    return rows, summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape SwimOutlet public Okendo product review images into the Step 1 intake schema.")
    parser.add_argument("--limit-products", type=int)
    parser.add_argument("--limit-review-pages", "--limit-pages-per-product", dest="limit_review_pages", type=int)
    parser.add_argument("--request-delay-seconds", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS)
    parser.add_argument("--no-resume-catalog", action="store_true")
    parser.add_argument("--store-feed-only", action="store_true", help="Resume only the Okendo store-review feed from checkpoint.")
    args = parser.parse_args(argv)
    try:
        if args.store_feed_only:
            rows, summary = scrape_store_feed_only(args.limit_review_pages, args.request_delay_seconds)
        else:
            rows, summary = scrape(args.limit_products, args.limit_review_pages, args.request_delay_seconds, not args.no_resume_catalog)
    except RateLimitError as exc:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        summary = {
            "site": SITE_ROOT,
            "retailer": RETAILER,
            "adapter": "okendo_store_level_plus_catalog_model_rows",
            "started_at": utc_now(),
            "finished_at": utc_now(),
            "output_csv": str(OUTPUT_CSV),
            "catalog_checkpoint_json": str(CATALOG_CHECKPOINT_JSON),
            "scrape_scope_status": "blocked_rate_limited",
            "full_catalog_scrape_complete": False,
            "errors": [{"type": "http_429", "detail": str(exc)}],
            "warnings": ["Stopped immediately on HTTP 429; no retry escalation or bypass attempted."],
        }
        SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(str(exc))
        print(f"Summary: {SUMMARY_JSON}")
        return 2
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
