#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from html import unescape
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlencode, urljoin

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    STEP1_OUTPUT_ROOT,
    build_intake_row,
    dedupe_rows,
    fetch_json,
    fetch_text,
    normalize_whitespace,
    strip_tags,
    utc_now,
    write_intake_csv,
)


SITE_ROOT = "https://enell.com"
SOURCE_SITE = f"{SITE_ROOT}/"
RETAILER = "enell_com"
SHOPIFY_DOMAIN = "enell.myshopify.com"
LOOX_ROOT = "https://loox.io"
LOOX_CLIENT_ID = "f5GL4jJUwm"
OUTPUT_DIR = STEP1_OUTPUT_ROOT / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"
PRODUCTS_JSON = f"{SITE_ROOT}/products.json"

REVIEW_CARD_RE = re.compile(
    r"(<div[^>]+data-id=[\"'][^\"']+[\"'][^>]+class=[\"'][^\"']*grid-item-wrap[^\"']*[\"'][\s\S]*?)"
    r"(?=<div[^>]+data-id=[\"'][^\"']+[\"'][^>]+class=[\"'][^\"']*grid-item-wrap|</div><div[^>]+style=[\"']text-align:center;padding:20px)",
    re.I,
)


def product_url(handle: str) -> str:
    return f"{SITE_ROOT}/products/{handle}"


def absolute_url(raw_url: str, base: str = LOOX_ROOT) -> str:
    raw_url = normalize_whitespace(unescape(raw_url))
    if raw_url.startswith("//"):
        return f"https:{raw_url}"
    return urljoin(base, raw_url)


def first_match(patterns: Sequence[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return normalize_whitespace(unescape(match.group(1)))
    return ""


def attr(block: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}=[\"']([^\"']*)[\"']", block)
    return normalize_whitespace(unescape(match.group(1))) if match else ""


def data_testid_text(block: str, review_id: str, suffix: str) -> str:
    match = re.search(
        rf"data-testid=[\"']review-{re.escape(review_id)}-{suffix}[\"'][^>]*>([\s\S]*?)</div>",
        block,
        flags=re.I,
    )
    return strip_tags(match.group(1)) if match else ""


def loox_hash_from_html(html: str) -> str:
    return first_match([r"loox_global_hash\s*=\s*[\"']?([^\"';<]+)"], html)


def review_count_from_html(html: str) -> Tuple[int, str]:
    rating = first_match([r"ratingValue[\"']?\s*:\s*([0-9.]+)", r"\"ratingValue\"\s*:\s*([0-9.]+)"], html)
    count_raw = first_match([r"reviewCount[\"']?\s*:\s*(\d+)", r"\"reviewCount\"\s*:\s*(\d+)"], html)
    try:
        return int(count_raw), rating
    except ValueError:
        return 0, rating


def loox_reviews_url(product_id: str, loox_hash: str, page: int = 1, total: int = 0) -> str:
    query: Dict[str, object] = {"h": loox_hash}
    if page > 1:
        query.update({"total": total, "variant": "visible", "language": "en", "page": page})
    return f"{LOOX_ROOT}/widget/{LOOX_CLIENT_ID}/reviews/{product_id}?{urlencode(query)}"


def review_date_from_time_ms(value: str) -> str:
    if not value:
        return ""
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def reviewer_name(block: str, review_id: str) -> str:
    return normalize_whitespace(re.sub(r"\bVerified\b", "", data_testid_text(block, review_id, "title"), flags=re.I))


def review_rating(block: str, review_id: str) -> str:
    match = re.search(
        rf"data-testid=[\"']review-{re.escape(review_id)}-stars[\"'][\s\S]*?aria-label=[\"'][^\"']*?(\d+(?:\.\d+)?)\s*/\s*5",
        block,
        flags=re.I,
    )
    return match.group(1) if match else ""


def review_images(block: str) -> List[str]:
    urls: List[str] = []
    for raw_url in re.findall(r"<img[^>]+src=[\"']([^\"']+)[\"'][^>]+alt=[\"']Customer photo review", block, flags=re.I):
        url = absolute_url(raw_url)
        if url not in urls:
            urls.append(url)
    return urls


def next_page_query(html: str) -> Dict[str, str]:
    match = re.search(r"id=[\"']loadMore[\"'][^>]+data-url=[\"']([^\"']+)[\"']", html, flags=re.I)
    if not match:
        return {}
    parsed = parse_qs(unescape(match.group(1)), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items() if values}


def parse_total(query: Dict[str, str], fallback: int) -> int:
    try:
        return int(query.get("total") or fallback or 0)
    except ValueError:
        return fallback


def context_for_product(product: Dict[str, object], page_html: str) -> ProductContext:
    handle = normalize_whitespace(product.get("handle"))
    title = normalize_whitespace(product.get("title"))
    body = strip_tags(product.get("body_html"))
    tags = ", ".join(str(tag) for tag in product.get("tags") or [])
    return ProductContext(
        url=product_url(handle),
        title=title,
        description=body,
        detail=tags,
        category=normalize_whitespace(product.get("product_type")),
        brand="Enell",
        product_id=str(product.get("id") or first_match([r"data-product-id=[\"'](\d+)"], page_html)),
        handle=handle,
        shop_domain=SHOPIFY_DOMAIN,
        provider_hints="Loox product review iframe",
        raw_html=page_html,
    )


def rows_from_card(block: str, context: ProductContext) -> List[Dict[str, str]]:
    review_id = attr(block, "data-id")
    if not review_id:
        return []
    text = data_testid_text(block, review_id, "text")
    date_raw = first_match([rf"data-time=[\"'](\d+)[\"'][^>]+data-testid=[\"']review-{re.escape(review_id)}-date"], block)
    review_date = review_date_from_time_ms(date_raw)
    rows: List[Dict[str, str]] = []
    for index, image_url in enumerate(review_images(block), start=1):
        digest = hashlib.md5(f"{context.url}|{review_id}|{image_url}".encode("utf-8")).hexdigest()[:12]
        review = ReviewImage(
            image_url=image_url,
            review_id=f"enell-loox-{review_id}-{index}-{digest}",
            review_body=text,
            reviewer_name=reviewer_name(block, review_id),
            date_raw=review_date,
            review_date=review_date,
            rating=review_rating(block, review_id),
            extra={
                "image_source_type": "customer_review_image",
                "image_source_detail": "public Loox product review iframe",
                "product_url": context.url,
                "product_title": context.title,
                "product_description": context.description,
                "product_category": context.category,
                "loox_review_id": review_id,
            },
        )
        rows.append(build_intake_row(context, review, utc_now()))
    return rows


def fetch_loox_reviews(context: ProductContext, loox_hash: str, expected_total: int, max_pages: Optional[int], delay: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    rows: List[Dict[str, str]] = []
    pages: List[Dict[str, object]] = []
    page = 1
    total = expected_total
    while True:
        if max_pages and page > max_pages:
            break
        html = fetch_text(loox_reviews_url(context.product_id, loox_hash, page, total), referer=context.url)
        cards = REVIEW_CARD_RE.findall(html)
        page_rows: List[Dict[str, str]] = []
        for card in cards:
            page_rows.extend(rows_from_card(card, context))
        rows.extend(page_rows)
        query = next_page_query(html)
        total = parse_total(query, total)
        pages.append({"page": page, "cards": len(cards), "customer_image_rows": len(page_rows), "bytes": len(html), "next_page": query.get("page", "")})
        if not cards or not query.get("page"):
            break
        page = int(query["page"])
        time.sleep(delay)
    return rows, {"review_pages_scanned": len(pages), "review_count_hint": total, "review_pages": pages}


def discover_products(limit: Optional[int]) -> List[Dict[str, object]]:
    products: List[Dict[str, object]] = []
    page = 1
    while True:
        payload = fetch_json(f"{PRODUCTS_JSON}?limit=250&page={page}", referer=SOURCE_SITE)
        batch = payload.get("products") if isinstance(payload, dict) else []
        if not batch:
            break
        products.extend(batch)
        if limit and len(products) >= limit:
            return products[:limit]
        page += 1
    return products


def scrape(args: argparse.Namespace) -> Dict[str, object]:
    products = discover_products(args.limit_products or None)
    all_rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    for product in products:
        handle = normalize_whitespace(product.get("handle"))
        if args.only_handle and handle != args.only_handle:
            continue
        url = product_url(handle)
        try:
            page_html = fetch_text(url, referer=SOURCE_SITE)
            loox_hash = loox_hash_from_html(page_html)
            review_count, rating = review_count_from_html(page_html)
            context = context_for_product(product, page_html)
            rows, meta = fetch_loox_reviews(context, loox_hash, review_count, args.max_review_pages or None, args.delay_seconds)
            all_rows.extend(rows)
            product_summaries.append(
                {
                    "product_url": url,
                    "product_id": context.product_id,
                    "title": context.title,
                    "loox_hash_found": bool(loox_hash),
                    "review_count_hint": review_count,
                    "rating_hint": rating,
                    "customer_review_image_rows": len(rows),
                    "meta": meta,
                }
            )
        except Exception as exc:
            errors.append(f"{url}: {exc}")
        if args.only_handle:
            break
        time.sleep(args.product_delay_seconds)
    rows = dedupe_rows(all_rows)
    write_intake_csv(rows, OUTPUT_CSV)
    summary = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_product_page_loox_customer_images",
        "review_platform_provider": "Loox",
        "loox_client_id": LOOX_CLIENT_ID,
        "access_policy": "public Shopify products.json/product pages and public Loox review iframe only; no auth bypass",
        "products_discovered": len(products),
        "products_scanned": len(product_summaries),
        "rows_written": len(rows),
        "rows_with_customer_review_image": sum(1 for row in rows if row.get("image_source_type") == "customer_review_image"),
        "distinct_image_urls": len({row.get("original_url_display") for row in rows if row.get("original_url_display")}),
        "distinct_review_ids": len({row.get("id") for row in rows if row.get("id")}),
        "product_summaries": product_summaries,
        "errors": errors,
        "output_csv": str(OUTPUT_CSV),
        "summary_json": str(SUMMARY_JSON),
        "finished_at": utc_now(),
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Enell customer review photos from public Loox review iframes.")
    parser.add_argument("--limit-products", type=int, default=0)
    parser.add_argument("--only-handle", default="")
    parser.add_argument("--max-review-pages", type=int, default=0)
    parser.add_argument("--delay-seconds", type=float, default=0.2)
    parser.add_argument("--product-delay-seconds", type=float, default=0.5)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    summary = scrape(parse_args(argv))
    print(json.dumps({key: summary[key] for key in ["products_scanned", "rows_written", "rows_with_customer_review_image", "distinct_image_urls"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
