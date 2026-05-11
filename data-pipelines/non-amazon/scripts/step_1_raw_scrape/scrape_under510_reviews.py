#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse, urlsplit, urlunsplit
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


RETAILER = "under510_com"
SITE_ROOT = "https://www.under510.com"
SOURCE_SITE = f"{SITE_ROOT}/"
SHOP_DOMAIN = "under-510.myshopify.com"
BRAND = "Under 510"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
OKENDO_STORE_ID = "1ad7d4ce-94b0-4b57-a469-fffa3c5bfbff"
OKENDO_API_ROOT = f"https://api.okendo.io/v1/stores/{OKENDO_STORE_ID}"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
DEFAULT_REQUEST_DELAY_SECONDS = 0.25
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema_summary.json"

BLOCK_TEXT_RE = re.compile(
    r"cf-chl|cloudflare challenge|access denied|temporarily blocked|bot protection|"
    r"unusual traffic|attention required|verify you are human|captcha challenge|perimeterx|datadome",
    re.I,
)
NON_CLOTHING_RE = re.compile(r"\b(gift\s*card|shipping|returns?\s*protection|warranty|insurance)\b", re.I)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def polite_pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def request_url(url: str, *, accept: str, referer: str, delay: float) -> bytes:
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
        with urlopen(req, timeout=60) as resp:
            content = resp.read()
            content_type = resp.headers.get("content-type", "")
    except HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError(f"Stopped after HTTP 429 for {url}") from exc
        if exc.code in {401, 403}:
            body = exc.read().decode("utf-8", "replace")
            if BLOCK_TEXT_RE.search(body):
                raise RuntimeError(f"Stopped after block/challenge response HTTP {exc.code} for {url}") from exc
        raise
    if "text/html" in content_type or "json" in content_type or "xml" in content_type:
        preview = content[:200000].decode("utf-8", "replace")
        if BLOCK_TEXT_RE.search(preview):
            raise RuntimeError(f"Stopped after captcha/WAF-like content for {url}")
    polite_pause(delay)
    return content


def fetch_text(url: str, *, referer: str = SOURCE_SITE, delay: float = DEFAULT_REQUEST_DELAY_SECONDS) -> str:
    return request_url(
        url,
        accept="text/html,application/xml,text/xml,*/*",
        referer=referer,
        delay=delay,
    ).decode("utf-8", "replace")


def fetch_json(
    url: str,
    params: Optional[Dict[str, object]] = None,
    *,
    referer: str = SOURCE_SITE,
    delay: float = DEFAULT_REQUEST_DELAY_SECONDS,
) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    content = request_url(query_url, accept="application/json,text/plain,*/*", referer=referer, delay=delay)
    return json.loads(content.decode("utf-8", "replace"))


def clean_url(value: object, base: str = SITE_ROOT) -> str:
    text = html.unescape(norm(value)).replace("&amp;", "&")
    if not text:
        return ""
    if text.startswith("//"):
        text = "https:" + text
    if text.startswith("/"):
        text = urljoin(base, text)
    parts = urlsplit(text)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def product_url_for(product: Dict[str, object]) -> str:
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def is_excluded_product(product: Dict[str, object], product_url: str) -> Tuple[bool, str]:
    tags = product.get("tags")
    tags_text = " ".join(str(tag) for tag in tags) if isinstance(tags, list) else norm(tags)
    text = " ".join(
        norm(part)
        for part in [
            product.get("title"),
            product.get("handle"),
            product.get("product_type"),
            product.get("vendor"),
            tags_text,
            product_url,
        ]
        if part
    )
    if NON_CLOTHING_RE.search(text):
        return True, "non_clothing_or_service_product"
    return False, ""


def fetch_products(delay: float, limit_products: Optional[int] = None) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    product_sources: List[Dict[str, object]] = []
    for page in range(1, 10000):
        payload = fetch_json(PRODUCTS_JSON_URL, {"limit": PRODUCTS_PER_PAGE, "page": page}, delay=delay)
        page_products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        product_sources.append({"source": "products.json", "page": page, "count": len(page_products)})
        if not page_products:
            break
        products.extend(page_products)
        print(f"[catalog page {page}] products={len(page_products)} total={len(products)}", flush=True)
        if len(page_products) < PRODUCTS_PER_PAGE:
            break

    sitemap_index = fetch_text(SITEMAP_URL, delay=delay)
    sitemap_urls = [
        html.unescape(match)
        for match in re.findall(r"<loc>(https://www\.under510\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index, re.I)
        if "/en-" not in match
    ]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url, delay=delay)
        urls = sorted({clean_url(url) for url in re.findall(r"https://www\.under510\.com/products/[^<\s\"']+", text)})
        product_sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        sitemap_product_urls.extend(urls)

    by_url: Dict[str, Dict[str, object]] = {}
    for product in products:
        url = product_url_for(product)
        if url:
            by_url[clean_url(url)] = product
    missing = [url for url in sorted(set(sitemap_product_urls)) if clean_url(url) not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[clean_url(url)] = {
            "id": "",
            "handle": handle,
            "title": handle.replace("-", " ").title(),
            "product_type": "",
            "body_html": "",
            "vendor": BRAND,
            "tags": [],
            "variants": [],
            "options": [],
        }
    product_sources.append(
        {
            "source": "reconciled_products",
            "count": len(by_url),
            "sitemap_missing_from_products_json": len(missing),
            "duplicates_removed": len(products) + len(set(sitemap_product_urls)) - len(by_url),
        }
    )
    reconciled = list(by_url.values())
    if limit_products is not None:
        reconciled = reconciled[:limit_products]
        product_sources.append({"source": "limit_products_debug", "count": len(reconciled)})
    return reconciled, product_sources


def product_context(product: Dict[str, object]) -> ProductContext:
    variants = product.get("variants") if isinstance(product.get("variants"), list) else []
    variant_titles: List[str] = []
    for variant in variants[:250]:
        if not isinstance(variant, dict):
            continue
        title = norm(variant.get("title"))
        if title and title.lower() != "default title" and title not in variant_titles:
            variant_titles.append(title)
    return ProductContext(
        url=product_url_for(product),
        title=norm(product.get("title")),
        description=strip_tags(product.get("body_html")),
        detail=" | ".join(variant_titles),
        category=norm(product.get("product_type")),
        brand=norm(product.get("vendor")) or BRAND,
        product_id=norm(product.get("id")),
        handle=norm(product.get("handle")),
        shop_domain=SHOP_DOMAIN,
        provider_hints="Okendo",
    )


def hydrate_product_from_js(product: Dict[str, object], delay: float) -> Dict[str, object]:
    if norm(product.get("id")):
        return product
    url = product_url_for(product)
    if not url:
        return product
    try:
        payload = fetch_json(f"{url}.js", referer=url, delay=delay)
    except Exception:
        return product
    if isinstance(payload, dict):
        product.update(
            {
                "id": payload.get("id") or product.get("id"),
                "title": payload.get("title") or product.get("title"),
                "product_type": payload.get("type") or product.get("product_type"),
                "body_html": payload.get("description") or product.get("body_html"),
                "vendor": payload.get("vendor") or product.get("vendor"),
                "variants": payload.get("variants") if isinstance(payload.get("variants"), list) else product.get("variants"),
                "options": payload.get("options") if isinstance(payload.get("options"), list) else product.get("options"),
            }
        )
    return product


def parse_okendo_metafield(html_text: str) -> Dict[str, object]:
    match = re.search(r'<script[^>]+data-oke-metafield-data[^>]*>(.*?)</script>', html_text, re.I | re.S)
    if not match:
        return {}
    raw = html.unescape(match.group(1)).strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def image_url_from_media(media: Dict[str, object]) -> str:
    image_urls = media.get("imageUrls") if isinstance(media.get("imageUrls"), dict) else {}
    return norm(
        media.get("fullSizeUrl")
        or media.get("largeUrl")
        or media.get("thumbnailUrl")
        or image_urls.get("fullSizeUrl")
        or image_urls.get("largeUrl")
        or image_urls.get("thumbnailUrl")
    )


def collect_product_media(
    products: List[Dict[str, object]],
    delay: float,
) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, Dict[str, object]], List[Dict[str, object]], List[str]]:
    media_by_review: Dict[str, List[Dict[str, str]]] = {}
    product_stats: Dict[str, Dict[str, object]] = {}
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []

    for index, raw_product in enumerate(products, start=1):
        product = hydrate_product_from_js(raw_product, delay)
        context = product_context(product)
        product_url = context.url
        excluded, skip_reason = is_excluded_product(product, product_url)
        summary: Dict[str, object] = {
            "product_index": index,
            "product_id": context.product_id,
            "product_title": context.title,
            "product_type": context.category,
            "product_url": product_url,
            "adapter_used": "okendo_product_page_metafield",
            "review_count_hint": 0,
            "media_count_hint": 0,
            "media_review_ids_discovered": 0,
            "review_pages_scanned": 0,
            "reviews_seen": 0,
            "matching_review_images": 0,
            "rows": 0,
            "errors": [],
            "skipped_from_output": excluded,
            "skip_reason": skip_reason,
        }
        product_stats[context.product_id or product_url] = summary
        if not product_url:
            summary["errors"] = ["missing_product_url"]
            product_summaries.append(summary)
            continue
        try:
            page_html = fetch_text(product_url, referer=SOURCE_SITE, delay=delay)
            payload = parse_okendo_metafield(page_html)
        except Exception as exc:  # noqa: BLE001
            error = f"{product_url}: {exc}"
            summary["errors"] = [str(exc)]
            errors.append(error)
            product_summaries.append(summary)
            if "429" in str(exc) or "captcha" in str(exc).lower() or "waf" in str(exc).lower() or "challenge" in str(exc).lower():
                raise
            continue
        aggregate = payload.get("reviewAggregate") if isinstance(payload.get("reviewAggregate"), dict) else {}
        summary["review_count_hint"] = int(aggregate.get("reviewCount") or aggregate.get("ratingAndReviewCount") or 0)
        media_items = [item for item in payload.get("media", []) if isinstance(item, dict)] if isinstance(payload.get("media"), list) else []
        summary["media_count_hint"] = int(aggregate.get("mediaCount") or len(media_items))
        seen_review_ids = set()
        for media in media_items:
            if norm(media.get("type")).lower() not in {"", "image", "photo"}:
                continue
            review_id = norm(media.get("reviewId"))
            image_url = image_url_from_media(media)
            if not review_id or not image_url:
                continue
            media_by_review.setdefault(review_id, [])
            media_payload = {
                "image_url": image_url,
                "image_alt": norm(media.get("imageAlt")),
                "stream_id": norm(media.get("streamId")),
                "product_id": norm(media.get("productId")).removeprefix("shopify-"),
                "date_created": norm(media.get("dateCreated")),
                "source_product_url": product_url,
                "source_product_title": context.title,
                "source_product_category": context.category,
                "source_product_detail": context.detail,
            }
            key = (media_payload["image_url"], media_payload["stream_id"])
            existing_keys = {(item.get("image_url"), item.get("stream_id")) for item in media_by_review[review_id]}
            if key not in existing_keys:
                media_by_review[review_id].append(media_payload)
            seen_review_ids.add(review_id)
        summary["media_review_ids_discovered"] = len(seen_review_ids)
        product_summaries.append(summary)
        print(
            f"[product {index}/{len(products)}] media_reviews={summary['media_review_ids_discovered']} "
            f"review_hint={summary['review_count_hint']} {context.handle}",
            flush=True,
        )
    return media_by_review, product_stats, product_summaries, errors


def okendo_store_reviews_url() -> str:
    return f"{OKENDO_API_ROOT}/reviews"


def normalize_product_url(value: object, fallback: str = "") -> str:
    product_url = clean_url(value or fallback)
    if product_url and product_url.startswith("https://under510.com"):
        product_url = product_url.replace("https://under510.com", SITE_ROOT, 1)
    return product_url


def attribute_pairs(review: Dict[str, object]) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
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
            if title and value_text != "":
                pairs.append((title, value_text))
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
                pairs.append((title, value_text))
    return pairs


def attribute_text(review: Dict[str, object]) -> str:
    return " ".join(f"{title}: {value}" for title, value in attribute_pairs(review))


def parse_height_inches(value: str) -> str:
    match = re.search(r"(\d)\s*(?:ft|feet|foot|['’])\s*(\d{1,2})?", value, re.I)
    if not match:
        return ""
    return str(int(match.group(1)) * 12 + int(match.group(2) or 0))


def numeric_value(value: str, *, max_value: Optional[float] = None) -> str:
    match = re.search(r"\d+(?:\.\d+)?", value)
    if not match:
        return ""
    number = float(match.group(0))
    if max_value is not None and number > max_value:
        return ""
    return str(int(number)) if number == int(number) else f"{number:.2f}".rstrip("0").rstrip(".")


def apply_structured_attributes(row: Dict[str, str], review: Dict[str, object]) -> None:
    variant = norm(review.get("productVariantName"))
    if variant and not row.get("size_display"):
        row["size_display"] = variant
    parts = [norm(part) for part in variant.split(" / ") if norm(part)]
    if len(parts) >= 2:
        row["waist_raw_display"] = row.get("waist_raw_display") or parts[0]
        row["waist_in"] = row.get("waist_in") or numeric_value(parts[0], max_value=80)
        row["inseam_inches_display"] = row.get("inseam_inches_display") or numeric_value(parts[1], max_value=50)

    for title, value in attribute_pairs(review):
        lowered = title.lower()
        if "height" in lowered:
            row["height_raw"] = row.get("height_raw") or value
            row["height_in_display"] = row.get("height_in_display") or parse_height_inches(value)
        elif "weight" in lowered:
            row["weight_raw"] = row.get("weight_raw") or value
            row["weight_display_display"] = row.get("weight_display_display") or value
        elif "waist" in lowered:
            row["waist_raw_display"] = row.get("waist_raw_display") or value
            row["waist_in"] = row.get("waist_in") or numeric_value(value, max_value=80)
        elif "inseam" in lowered:
            row["inseam_inches_display"] = row.get("inseam_inches_display") or numeric_value(value, max_value=50)
        elif "old" in lowered or "age" in lowered:
            row["age_raw"] = row.get("age_raw") or value


def context_from_review(
    review: Dict[str, object],
    products_by_id: Dict[str, Dict[str, object]],
    products_by_handle: Dict[str, Dict[str, object]],
    products_by_title: Dict[str, Dict[str, object]],
    products_by_url: Dict[str, Dict[str, object]],
) -> ProductContext:
    product_id = norm(review.get("productId")).removeprefix("shopify-")
    handle = norm(review.get("productHandle"))
    product_name = norm(review.get("productName"))
    review_url = normalize_product_url(review.get("productUrl"), "")
    product = (
        products_by_url.get(clean_url(review_url))
        or products_by_id.get(product_id)
        or products_by_handle.get(handle)
        or products_by_title.get(product_name.lower())
    )
    if product:
        return product_context(product)
    product_url = review_url or normalize_product_url(review.get("productUrl"), SITE_ROOT)
    if not product_url and handle:
        product_url = f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}"
    return ProductContext(
        url=product_url,
        title=product_name,
        category="",
        brand=BRAND,
        product_id=product_id,
        handle=handle,
        shop_domain=SHOP_DOMAIN,
        provider_hints="Okendo",
    )


def review_media_urls(review: Dict[str, object], media_by_review: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, str]]:
    review_id = norm(review.get("reviewId"))
    urls = list(media_by_review.get(review_id, []))
    media = review.get("media")
    if isinstance(media, list):
        for item in media:
            if not isinstance(item, dict):
                continue
            if norm(item.get("type")).lower() not in {"", "image", "photo"}:
                continue
            image_url = image_url_from_media(item)
            if image_url:
                urls.append(
                    {
                        "image_url": image_url,
                        "image_alt": norm(item.get("imageAlt")),
                        "stream_id": norm(item.get("streamId")),
                        "product_id": norm(item.get("productId")).removeprefix("shopify-"),
                        "date_created": norm(item.get("dateCreated")),
                        "source_product_url": "",
                        "source_product_title": "",
                        "source_product_category": "",
                        "source_product_detail": "",
                    }
                )
    deduped: List[Dict[str, str]] = []
    seen = set()
    for item in urls:
        key = (item.get("image_url"), item.get("stream_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def review_to_rows(
    review: Dict[str, object],
    context: ProductContext,
    media_items: Sequence[Dict[str, str]],
    fetched_at: str,
) -> List[Dict[str, str]]:
    if not media_items:
        return []
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    source_product_url = next((norm(item.get("source_product_url")) for item in media_items if norm(item.get("source_product_url"))), "")
    source_product_title = next((norm(item.get("source_product_title")) for item in media_items if norm(item.get("source_product_title"))), "")
    source_product_category = next((norm(item.get("source_product_category")) for item in media_items if norm(item.get("source_product_category"))), "")
    source_product_detail = next((norm(item.get("source_product_detail")) for item in media_items if norm(item.get("source_product_detail"))), "")
    product_url = normalize_product_url(source_product_url, context.url) if source_product_url else normalize_product_url(review.get("productUrl"), context.url)
    if "/products/" not in product_url:
        return []
    product_title = source_product_title if source_product_url else norm(review.get("productName")) or context.title
    product_category = source_product_category or context.category
    product_detail = source_product_detail or context.detail
    review_date = norm(review.get("dateCreated")).split("T", 1)[0]
    comment = strip_tags(" ".join(part for part in [review.get("body"), attribute_text(review)] if norm(part)))
    rows: List[Dict[str, str]] = []
    for index, media in enumerate(media_items, start=1):
        size = norm(review.get("productVariantName"))
        review_image = ReviewImage(
            image_url=media["image_url"],
            review_id=f"{norm(review.get('reviewId'))}-{index}" if norm(review.get("reviewId")) else "",
            review_title=strip_tags(review.get("title")),
            review_body=comment,
            reviewer_name=norm(reviewer.get("displayName")),
            date_raw=norm(review.get("dateCreated")),
            review_date=review_date,
            size_raw=size,
            rating=norm(review.get("rating")),
            extra={
                "product_url": product_url,
                "product_title": product_title,
                "product_variant": size,
                "product_category": product_category,
                "product_detail": product_detail,
                "image_source_type": "customer_review_image",
                "image_source_detail": "okendo_review_media",
            },
        )
        row_context = ProductContext(**{**context.__dict__, "url": product_url, "title": product_title, "category": product_category, "detail": product_detail})
        row = build_intake_row(row_context, review_image, fetched_at)
        apply_structured_attributes(row, review)
        rows.append(row)
    return rows


def scan_store_reviews(
    products: List[Dict[str, object]],
    media_by_review: Dict[str, List[Dict[str, str]]],
    product_stats: Dict[str, Dict[str, object]],
    *,
    delay: float,
    limit_review_pages: Optional[int],
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    products_by_id = {norm(product.get("id")): product for product in products if norm(product.get("id"))}
    products_by_handle = {norm(product.get("handle")): product for product in products if norm(product.get("handle"))}
    products_by_title = {norm(product.get("title")).lower(): product for product in products if norm(product.get("title"))}
    products_by_url = {clean_url(product_url_for(product)): product for product in products if product_url_for(product)}
    target_review_ids = set(media_by_review)
    found_review_ids = set()
    rows: List[Dict[str, str]] = []
    errors: List[str] = []
    pages = 0
    reviews_seen = 0
    media_reviews_seen = 0
    next_url = okendo_store_reviews_url()
    params: Optional[Dict[str, object]] = {"limit": REVIEWS_PER_PAGE}

    while next_url:
        if limit_review_pages is not None and pages >= limit_review_pages:
            break
        try:
            payload = fetch_json(next_url, params=params, referer=SOURCE_SITE, delay=delay)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            if "429" in str(exc) or "captcha" in str(exc).lower() or "waf" in str(exc).lower() or "challenge" in str(exc).lower():
                raise
            break
        params = None
        page_reviews = [item for item in payload.get("reviews", []) if isinstance(item, dict)]
        if not page_reviews:
            break
        pages += 1
        reviews_seen += len(page_reviews)
        for review in page_reviews:
            context = context_from_review(review, products_by_id, products_by_handle, products_by_title, products_by_url)
            product_key = context.product_id or context.url or norm(review.get("productId"))
            stat = product_stats.get(product_key)
            if stat is not None:
                stat["review_pages_scanned"] = int(stat.get("review_pages_scanned") or 0) + 1
                stat["reviews_seen"] = int(stat.get("reviews_seen") or 0) + 1
            media_items = review_media_urls(review, media_by_review)
            if not media_items:
                continue
            media_reviews_seen += 1
            found_review_ids.add(norm(review.get("reviewId")))
            review_rows = review_to_rows(review, context, media_items, utc_now())
            rows.extend(review_rows)
            if stat is not None:
                stat["matching_review_images"] = int(stat.get("matching_review_images") or 0) + len(review_rows)
                stat["rows"] = int(stat.get("rows") or 0) + len(review_rows)
        missing_targets = len(target_review_ids - found_review_ids)
        print(
            f"[review page {pages}] reviews={len(page_reviews)} total_reviews={reviews_seen} "
            f"rows={len(rows)} missing_media_reviews={missing_targets}",
            flush=True,
        )
        relative_next = norm(payload.get("nextUrl"))
        next_url = urljoin("https://api.okendo.io/v1/", relative_next.lstrip("/")) if relative_next else ""

    return rows, {
        "review_pages_scanned": pages,
        "reviews_seen": reviews_seen,
        "media_reviews_seen": media_reviews_seen,
        "media_review_ids_targeted": len(target_review_ids),
        "media_review_ids_joined": len(found_review_ids),
        "media_review_ids_unjoined": len(target_review_ids - found_review_ids),
        "exhaustive_review_paging": limit_review_pages is None and not next_url and not errors,
        "next_url_remaining": next_url,
        "errors": errors,
    }


def scrape(limit_products: Optional[int], limit_review_pages: Optional[int], delay: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    products, product_sources = fetch_products(delay, limit_products=limit_products)
    media_by_review, product_stats, product_summaries, product_page_errors = collect_product_media(products, delay)
    rows, review_meta = scan_store_reviews(
        products,
        media_by_review,
        product_stats,
        delay=delay,
        limit_review_pages=limit_review_pages,
    )
    rows = dedupe_rows(rows)
    rows.sort(
        key=lambda row: (
            row.get("review_date", ""),
            row.get("product_page_url_display", ""),
            row.get("original_url_display", ""),
        ),
        reverse=True,
    )
    product_summaries = list(product_stats.values())
    products_excluded = sum(1 for item in product_summaries if item.get("skipped_from_output"))
    summary: Dict[str, object] = {
        "site": "under510.com",
        "retailer": RETAILER,
        "adapter": "shopify_catalog_plus_okendo_product_media_joined_to_store_reviews",
        "scope_note": "Under 510 is a men's short-stature apparel retailer; scraped because this run explicitly requested under510_com.",
        "okendo_store_id": OKENDO_STORE_ID,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "product_pages_scanned": len(products),
        "products_excluded_from_output": products_excluded,
        "review_pages_scanned": review_meta["review_pages_scanned"],
        "exhaustive_review_paging": review_meta["exhaustive_review_paging"],
        "product_review_count_hint": sum(int(item.get("review_count_hint") or 0) for item in product_summaries),
        "product_media_count_hint": sum(int(item.get("media_count_hint") or 0) for item in product_summaries),
        "store_reviews_seen": review_meta["reviews_seen"],
        "store_media_reviews_seen": review_meta["media_reviews_seen"],
        "media_review_ids_targeted": review_meta["media_review_ids_targeted"],
        "media_review_ids_joined": review_meta["media_review_ids_joined"],
        "media_review_ids_unjoined": review_meta["media_review_ids_unjoined"],
        "products_with_review_rows": sum(1 for item in product_summaries if int(item.get("rows") or 0) > 0),
        "output_csv": str(OUTPUT_CSV),
        "summary_json": str(SUMMARY_JSON),
        "started_at": started_at,
        "finished_at": utc_now(),
        "product_summaries": product_summaries,
        "errors": [{"scope": "product_pages", "errors": product_page_errors}] if product_page_errors else [],
        "review_errors": review_meta["errors"],
        "access_policy": (
            "public_product_and_review_pages_only; no_auth_bypass; no_captcha_bypass; "
            f"stop_on_429_captcha_waf; request_delay_seconds={delay}"
        ),
        "scrape_scope_status": "full_catalog_and_store_review_feed_complete"
        if limit_products is None and limit_review_pages is None and review_meta["exhaustive_review_paging"]
        else "limited_debug_run",
    }
    validation = validate_rows(rows)
    summary.update(validation)
    summary["rows_with_distinct_product_url"] = validation.get("distinct_products", 0)
    summary["rows_with_customer_image"] = validation.get("rows_with_customer_review_image", 0)
    summary["rows_supabase_qualified"] = validation.get("supabase_qualified_rows", 0)
    return rows, summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Under 510 public Okendo review images into the Step 1 schema.")
    parser.add_argument("--limit-products", type=int, help="Debug only: limit catalog products.")
    parser.add_argument("--limit-review-pages", type=int, help="Debug only: limit store review pages.")
    parser.add_argument("--request-delay-seconds", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS)
    args = parser.parse_args(argv)

    rows, summary = scrape(args.limit_products, args.limit_review_pages, args.request_delay_seconds)
    write_intake_csv(rows, OUTPUT_CSV)
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Rows written: {len(rows)}")
    print(f"Qualified rows: {summary.get('rows_supabase_qualified', 0)}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
