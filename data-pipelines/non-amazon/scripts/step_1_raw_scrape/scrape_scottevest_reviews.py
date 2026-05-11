#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
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
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    validate_rows,
    write_intake_csv,
)


SITE_ROOT = "https://www.scottevest.com"
RETAILER = "scottevest_com"
BRAND = "SCOTTeVEST"
SHOP_DOMAIN = "scotteveststore.myshopify.com"
OKENDO_STORE_ID = "fa23fdf4-f05c-41d8-a7f1-1b2a2a8a2038"
OKENDO_API_ROOT = f"https://api.okendo.io/v1/stores/{OKENDO_STORE_ID}"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
DEFAULT_REQUEST_DELAY_SECONDS = 0.25
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
CHALLENGE_RE = re.compile(
    r"\b(?:captcha|cloudflare|datadome|access denied|attention required|verify you are human|blocked)\b",
    re.I,
)
NON_CLOTHING_RE = re.compile(r"\b(?:gift\s*cards?|gift\s*wrap|mask|hat|gloves?|strap|extender|bag)\b", re.I)
WOMENS_PRODUCT_RE = re.compile(
    r"\b(?:for women|women'?s?|dress(?:es)?|skorts?|skirts?|cardigans?|trench|tanks?)\b",
    re.I,
)
MENS_PRODUCT_RE = re.compile(r"\b(?:for men|men'?s?|boxers?|boxer\s*briefs?)\b", re.I)

ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_CSV, SUMMARY_JSON = output_paths(RETAILER)


class StopScrape(RuntimeError):
    pass


def norm(value: object) -> str:
    return normalize_whitespace(value)


def pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def fetch_text(url: str, *, referer: str = SITE_ROOT, retries: int = 3, delay: float = DEFAULT_REQUEST_DELAY_SECONDS) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/json,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": referer,
            },
        )
        try:
            with urlopen(req, timeout=45) as resp:
                body = resp.read().decode("utf-8", "replace")
            if CHALLENGE_RE.search(body[:5000]):
                raise StopScrape(f"Stopping on challenge-like response for {url}")
            pause(delay)
            return body
        except HTTPError as exc:
            last_error = exc
            if exc.code in {403, 429}:
                raise StopScrape(f"Stopping on HTTP {exc.code} for {url}") from exc
            if exc.code not in {408, 500, 502, 503, 504}:
                raise
        except URLError as exc:
            last_error = exc
        time.sleep(min(2**attempt, 8) + delay)
    raise RuntimeError(f"Failed text request for {url}: {last_error}")


def fetch_json(
    url: str,
    params: Optional[Dict[str, object]] = None,
    *,
    referer: str = SITE_ROOT,
    delay: float = DEFAULT_REQUEST_DELAY_SECONDS,
) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    return json.loads(fetch_text(query_url, referer=referer, delay=delay))


def product_url_for(product: Dict[str, object]) -> str:
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def discover_products(delay: float) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    by_handle: Dict[str, Dict[str, object]] = {}
    sources: List[Dict[str, object]] = []

    page = 1
    while True:
        payload = fetch_json(f"{SITE_ROOT}/products.json", {"limit": PRODUCTS_PER_PAGE, "page": page}, delay=delay)
        products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        sources.append({"source": "products.json", "page": page, "count": len(products)})
        for product in products:
            handle = norm(product.get("handle"))
            if handle:
                by_handle[handle] = product
        if len(products) < PRODUCTS_PER_PAGE:
            break
        page += 1

    sitemap_index = fetch_text(f"{SITE_ROOT}/sitemap.xml", delay=delay)
    sitemap_urls = [
        html.unescape(match)
        for match in re.findall(r"<loc>(https://www\.scottevest\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index, re.I)
    ]
    missing = 0
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url, delay=delay)
        urls = sorted(set(re.findall(r"https://www\.scottevest\.com/products/[^<\s\"']+", text, re.I)))
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        for url in urls:
            handle = html.unescape(url).split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
            if handle and handle not in by_handle:
                by_handle[handle] = {
                    "id": "",
                    "handle": handle,
                    "title": handle.replace("-", " ").title(),
                    "vendor": BRAND,
                    "product_type": "",
                    "body_html": "",
                    "variants": [],
                    "tags": [],
                }
                missing += 1
    sources.append({"source": "reconciled_products", "count": len(by_handle), "sitemap_missing_from_products_json": missing})
    return list(by_handle.values()), sources


def variant_detail(product: Dict[str, object]) -> str:
    variants = product.get("variants")
    vals: List[str] = []
    if isinstance(variants, list):
        for variant in variants[:300]:
            if not isinstance(variant, dict):
                continue
            title = norm(variant.get("title"))
            if title and title.lower() != "default title" and title not in vals:
                vals.append(title)
    return " | ".join(vals)


def tags_text(product: Dict[str, object]) -> str:
    tags = product.get("tags")
    if isinstance(tags, list):
        return " ".join(norm(tag) for tag in tags)
    return norm(tags)


def product_context(product: Dict[str, object]) -> ProductContext:
    return ProductContext(
        url=product_url_for(product),
        title=norm(product.get("title")),
        description=strip_tags(product.get("body_html")),
        detail=variant_detail(product),
        category=norm(product.get("product_type")),
        brand=norm(product.get("vendor")) or BRAND,
        product_id=norm(product.get("id")),
        handle=norm(product.get("handle")),
        shop_domain=SHOP_DOMAIN,
        provider_hints="Okendo",
        raw_html=tags_text(product),
    )


def output_skip_reason(context: ProductContext) -> str:
    text = f"{context.title} {context.category} {context.handle} {context.raw_html}".lower()
    if NON_CLOTHING_RE.search(text):
        return "out_of_scope_non_clothing_or_gift_item"
    if MENS_PRODUCT_RE.search(text):
        return "out_of_scope_not_womens_clothing"
    if context.category.lower() != "women" and not WOMENS_PRODUCT_RE.search(text):
        return "out_of_scope_not_womens_clothing"
    return ""


def okendo_reviews_url(product_id: str) -> str:
    return f"{OKENDO_API_ROOT}/products/shopify-{product_id}/reviews"


def media_urls(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    media = review.get("media")
    if not isinstance(media, list):
        return urls
    for item in media:
        if not isinstance(item, dict):
            continue
        media_type = norm(item.get("type")).lower()
        if media_type and media_type not in {"image", "photo"}:
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


def format_attribute_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(norm(item) for item in value if norm(item))
    return norm(value)


def attribute_lines(review: Dict[str, object]) -> List[str]:
    lines: List[str] = []
    for source_name in ["productAttributes", "attributesWithRating"]:
        source = review.get(source_name)
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, dict):
                continue
            title = norm(item.get("title")).rstrip(":")
            value_text = format_attribute_value(item.get("value"))
            if title and value_text:
                lines.append(f"{title}: {value_text}")
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    attrs = reviewer.get("attributes")
    if isinstance(attrs, list):
        for item in attrs:
            if not isinstance(item, dict):
                continue
            title = norm(item.get("title")).rstrip(":")
            value_text = format_attribute_value(item.get("value"))
            if title and value_text:
                lines.append(f"{title}: {value_text}")
    return lines


def variant_parts(value: object) -> Tuple[str, str]:
    text = norm(value)
    if " / " not in text:
        return "", text
    parts = [norm(part) for part in text.split(" / ") if norm(part)]
    if len(parts) < 2:
        return "", text
    return parts[0], parts[-1]


def ordered_size(review: Dict[str, object], fallback: str) -> str:
    for source in (review.get("productAttributes"),):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, dict):
                continue
            title = norm(item.get("title")).lower()
            value = format_attribute_value(item.get("value"))
            if value and "size" in title and any(token in title for token in ["ordered", "purchased", "wear", "bought"]):
                return value
    return fallback


def normalized_product_url(value: object, fallback: str) -> str:
    text = norm(value)
    if text.startswith("//"):
        text = "https:" + text
    if text.startswith("/"):
        text = urljoin(SITE_ROOT, text)
    return (text or fallback).split("?", 1)[0].rstrip("/")


def review_to_rows(review: Dict[str, object], context: ProductContext, fetched_at: str, skipped_from_output: bool) -> List[Dict[str, str]]:
    urls = media_urls(review)
    if not urls or skipped_from_output:
        return []
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    color, size = variant_parts(review.get("productVariantName"))
    size = ordered_size(review, size)
    product_url = normalized_product_url(review.get("productUrl"), context.url)
    product_title = norm(review.get("productName")) or context.title
    comment = " | ".join(part for part in [normalize_whitespace(review.get("body")), " | ".join(attribute_lines(review))] if part)
    review_date = norm(review.get("dateCreated")).split("T", 1)[0]
    row_context = ProductContext(**{**context.__dict__, "url": product_url, "title": product_title, "color": color})
    rows: List[Dict[str, str]] = []
    for image_index, image_url in enumerate(urls, start=1):
        review_image = ReviewImage(
            image_url=image_url,
            review_id=f"{norm(review.get('reviewId'))}-{image_index}" if norm(review.get("reviewId")) else "",
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
                "product_description": context.description,
                "product_detail": context.detail,
                "product_category": context.category,
                "product_variant": norm(review.get("productVariantName")),
                "image_source_type": "customer_review_image",
                "image_source_detail": "Okendo review image",
            },
        )
        rows.append(build_intake_row(row_context, review_image, fetched_at))
    return rows


def fetch_product_reviews(
    context: ProductContext,
    *,
    skipped_from_output: bool,
    limit_review_pages: Optional[int],
    delay: float,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    rows: List[Dict[str, str]] = []
    pages = 0
    reviews_seen = 0
    media_reviews_seen = 0
    errors: List[str] = []
    if not context.product_id:
        return rows, {
            "product_url": context.url,
            "product_title": context.title,
            "product_type": context.category,
            "shopify_product_id": context.product_id,
            "skipped_from_output": skipped_from_output,
            "skip_reason": "missing_shopify_product_id" if skipped_from_output else "",
            "reviews_seen": 0,
            "media_reviews_seen": 0,
            "rows": 0,
            "review_pages_scanned": 0,
            "errors": ["missing_shopify_product_id"],
        }
    next_url = okendo_reviews_url(context.product_id)
    params: Optional[Dict[str, object]] = {"limit": REVIEWS_PER_PAGE}
    while next_url:
        if limit_review_pages is not None and pages >= limit_review_pages:
            break
        try:
            payload = fetch_json(next_url, params=params, referer=context.url, delay=delay)
        except StopScrape:
            raise
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
            if media_urls(review):
                media_reviews_seen += 1
            rows.extend(review_to_rows(review, context, utc_now(), skipped_from_output))
        relative_next = norm(payload.get("nextUrl"))
        next_url = urljoin("https://api.okendo.io/v1/", relative_next.lstrip("/")) if relative_next else ""
    return rows, {
        "product_url": context.url,
        "product_title": context.title,
        "product_type": context.category,
        "shopify_product_id": context.product_id,
        "skipped_from_output": skipped_from_output,
        "skip_reason": output_skip_reason(context) if skipped_from_output else "",
        "reviews_seen": reviews_seen,
        "media_reviews_seen": media_reviews_seen,
        "rows": len(rows),
        "review_pages_scanned": pages,
        "errors": errors,
    }


def scrape(limit_products: Optional[int], limit_review_pages: Optional[int], delay: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    products, product_sources = discover_products(delay)
    if limit_products is not None:
        products = products[:limit_products]
    all_rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    for index, product in enumerate(products, start=1):
        context = product_context(product)
        skip_reason = output_skip_reason(context)
        product_rows, product_summary = fetch_product_reviews(
            context,
            skipped_from_output=bool(skip_reason),
            limit_review_pages=limit_review_pages,
            delay=delay,
        )
        all_rows.extend(product_rows)
        product_summaries.append(product_summary)
        if product_summary.get("errors"):
            errors.append(f"{context.url}: {product_summary['errors']}")
        print(
            f"[product {index}/{len(products)}] reviews={product_summary['reviews_seen']} "
            f"media_reviews={product_summary['media_reviews_seen']} rows={product_summary['rows']} {context.title}",
            flush=True,
        )
    rows = dedupe_rows(all_rows)
    rows.sort(key=lambda row: (row.get("review_date", ""), row.get("product_page_url_display", ""), row.get("original_url_display", "")), reverse=True)
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_sitemap_and_okendo_product_reviews",
        "okendo_store_id": OKENDO_STORE_ID,
        "started_at": started_at,
        "finished_at": utc_now(),
        "output_csv": str(OUTPUT_CSV),
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "products_target_scanned": sum(1 for item in product_summaries if not item.get("skipped_from_output")),
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "review_pages_scanned": sum(int(item.get("review_pages_scanned") or 0) for item in product_summaries),
        "product_review_count_hint": sum(int(item.get("reviews_seen") or 0) for item in product_summaries),
        "products_with_review_rows": sum(1 for item in product_summaries if int(item.get("rows") or 0) > 0),
        "exhaustive_review_paging": limit_review_pages is None and not errors,
        "target_scope": "women_clothing_only",
        "product_summaries": product_summaries,
        "errors": errors,
        "access_policy": (
            "public_shopify_catalog_and_public_okendo_product_reviews_only; "
            "no_auth_bypass; no_captcha_bypass; stop_on_403_429_or_challenge; "
            f"request_delay_seconds={delay}"
        ),
        "scrape_scope_status": "full_public_catalog_attempted" if limit_products is None and limit_review_pages is None else "limited_smoke",
    }
    summary.update(validate_rows(rows))
    return rows, summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape SCOTTeVEST public Okendo review images into the Step 1 intake schema.")
    parser.add_argument("--limit-products", type=int)
    parser.add_argument("--limit-review-pages", type=int)
    parser.add_argument("--request-delay-seconds", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS)
    args = parser.parse_args(argv)
    rows, summary = scrape(args.limit_products, args.limit_review_pages, args.request_delay_seconds)
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
