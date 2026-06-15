#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse, urlencode
from urllib.request import Request, urlopen

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    normalize_whitespace,
    output_paths,
    review_date_from_raw,
    strip_tags,
    utc_now,
    validate_rows,
    write_intake_csv,
)


SITE_ROOT = "https://www.wearfigs.com"
RETAILER = "wearfigs_com"
BRAND = "FIGS"
GRAPHQL_URL = f"{SITE_ROOT}/catalog/graphql"
REVIEWS_PER_PAGE = 50
DEFAULT_REQUEST_DELAY_SECONDS = 0.2
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
CHALLENGE_RE = re.compile(
    r"\b(?:captcha|cloudflare|datadome|access denied|attention required|verify you are human|blocked)\b",
    re.I,
)
NON_CLOTHING_RE = re.compile(
    r"\b(?:socks?|shoes?|clogs?|bag|tote|cap|hat|beanie|badge|compression|mask|gift|water bottle|mug|pin|stethoscope)\b",
    re.I,
)
WOMENS_RE = re.compile(r"\bwomens?\b|\bwomen'?s\b", re.I)
MENS_RE = re.compile(r"\bmens?\b|\bmen'?s\b", re.I)
HEIGHT_BUCKET_RE = re.compile(r"\b(?:or less|or above|\d['’]\d+\s*-\s*\d['’]\d+)\b", re.I)

OUTPUT_CSV, SUMMARY_JSON = output_paths(RETAILER)

GET_FILTERED_REVIEWS_QUERY = """
query getFilteredReviews($filterInput: FilterInput!, $pageNum: Int!, $numPerPage: Int!) {
  filteredReviews(filterInput: $filterInput, pageNum: $pageNum, numPerPage: $numPerPage) {
    pagination { numPages pageNum numPerPage }
    reviews {
      reviewer
      title
      content
      createdAt
      score
      customFields { key title value formId }
      imageUrls
    }
  }
}
"""


class StopScrape(RuntimeError):
    pass


def norm(value: object) -> str:
    return normalize_whitespace(value)


def pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def fetch_text(url: str, *, referer: str = SITE_ROOT, delay: float = DEFAULT_REQUEST_DELAY_SECONDS) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        },
    )
    try:
        with urlopen(req, timeout=45) as resp:
            text = resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code in {403, 429}:
            raise StopScrape(f"Stopping on HTTP {exc.code} for {url}") from exc
        raise
    except URLError:
        raise
    if CHALLENGE_RE.search(text[:5000]):
        raise StopScrape(f"Stopping on challenge-like response for {url}")
    pause(delay)
    return text


def post_graphql(
    operation_name: str,
    query: str,
    variables: Dict[str, object],
    *,
    referer: str,
    delay: float,
) -> Dict[str, object]:
    body = json.dumps(
        {"operationName": operation_name, "query": query, "variables": variables},
        ensure_ascii=True,
    ).encode("utf-8")
    req = Request(
        GRAPHQL_URL,
        data=body,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Referer": referer,
            "x-figs-shop-region": "US",
            "x-figs-shop-locale": "en-US",
            "x-figs-shop-currency": "USD",
            "x-figs-shop-name": "figsscrubs",
        },
    )
    try:
        with urlopen(req, timeout=45) as resp:
            text = resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code in {403, 429}:
            raise StopScrape(f"Stopping on HTTP {exc.code} for {GRAPHQL_URL}") from exc
        raise
    if CHALLENGE_RE.search(text[:5000]):
        raise StopScrape("Stopping on challenge-like GraphQL response")
    pause(delay)
    payload = json.loads(text)
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return payload


def discover_sitemap_products(delay: float) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    index = fetch_text(f"{SITE_ROOT}/sitemap.xml", delay=delay)
    sitemap_urls = [
        html.unescape(match)
        for match in re.findall(r"<loc>(https://www\.wearfigs\.com/[^<]*sitemap-products[^<]*)</loc>", index, re.I)
    ]
    by_key: Dict[Tuple[str, str], Dict[str, object]] = {}
    by_handle: Dict[str, Dict[str, object]] = {}
    sources: List[Dict[str, object]] = [{"source": "sitemap_index", "count": len(sitemap_urls)}]
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url, delay=delay)
        urls = [html.unescape(match) for match in re.findall(r"<loc>(https://www\.wearfigs\.com/[^<]+)</loc>", text, re.I)]
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        for url in urls:
            parsed = urlparse(url)
            if "/products/" not in parsed.path:
                continue
            handle = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            color = norm(parse_qs(parsed.query).get("color", [""])[0])
            key = (handle, color)
            item = {
                "handle": handle,
                "color": color,
                "url": f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" + (f"?{urlencode({'color': color})}" if color else ""),
            }
            by_key[key] = item
            by_handle.setdefault(handle, item)
    products = list(by_handle.values())
    sources.append({"source": "reconciled_unique_product_handles", "count": len(products), "color_url_count": len(by_key)})
    return products, sources


def skip_reason(product: Dict[str, object]) -> str:
    text = f"{product.get('handle')} {product.get('title')} {product.get('category')} {product.get('detail')}".lower()
    if NON_CLOTHING_RE.search(text):
        return "out_of_scope_non_clothing_accessory_or_footwear"
    if MENS_RE.search(text) and not WOMENS_RE.search(text):
        return "out_of_scope_not_womens_clothing"
    if not WOMENS_RE.search(text):
        return "out_of_scope_not_womens_clothing"
    return ""


def first_match(patterns: Sequence[str], text: str, flags: int = re.I | re.S) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return norm(html.unescape(match.group(1)))
    return ""


def product_context_from_page(product: Dict[str, object], page_text: str) -> ProductContext:
    title = first_match(
        [
            r"<meta[^>]+property=['\"]og:title['\"][^>]+content=['\"]([^'\"]+)['\"]",
            r"<title[^>]*>(.*?)</title>",
        ],
        page_text,
    )
    title = re.sub(r"\s*[·|]\s*FIGS.*$", "", title).strip()
    description = first_match(
        [
            r"<meta[^>]+property=['\"]og:description['\"][^>]+content=['\"]([^'\"]+)['\"]",
            r"<meta[^>]+name=['\"]description['\"][^>]+content=['\"]([^'\"]+)['\"]",
        ],
        page_text,
    )
    product_id = first_match([r"shopifyProductId\\\":\\\"gid://shopify/Product/(\d+)"], page_text)
    if not product_id:
        product_id = first_match([r"shopifyProductId\":\"gid://shopify/Product/(\d+)"], page_text)
    color = norm(product.get("color")) or first_match([r'"color"\s*:\s*"([^"]+)"'], page_text)
    fit_text = " | ".join(dict.fromkeys(re.findall(r"Model is [^<\\]+?Wearing [A-Z0-9/]+", page_text, re.I)))
    if not fit_text:
        fit_text = first_match([r"fitModelsDescriptions\\\":\[(.*?)\]"], page_text)
    category = "Women's Clothing" if product["handle"].startswith("womens-") else ""
    detail = " | ".join(part for part in [fit_text, first_match([r"<div[^>]*id=['\"]product-details-fit['\"][^>]*>.*?<div[^>]*>(.*?)</div>"], page_text)] if part)
    return ProductContext(
        url=norm(product["url"]),
        title=title,
        description=description,
        detail=strip_tags(detail),
        category=category,
        brand=BRAND,
        color=color,
        product_id=product_id,
        handle=norm(product["handle"]),
        shop_domain="figsscrubs.myshopify.com",
        provider_hints="FIGS GraphQL/Yotpo image CDN",
        raw_html=page_text,
    )


def custom_field_lines(review: Dict[str, object]) -> Tuple[List[str], str, bool]:
    lines: List[str] = []
    size = ""
    height_is_bucket = False
    fields = review.get("customFields")
    if not isinstance(fields, list):
        return lines, size, height_is_bucket
    for field in fields:
        if not isinstance(field, dict):
            continue
        title = norm(field.get("title")).rstrip(":")
        value = norm(field.get("value"))
        if not value:
            continue
        if title.lower() == "size purchased":
            size = value
        if title.lower() == "height" and HEIGHT_BUCKET_RE.search(value):
            height_is_bucket = True
        lines.append(f"{title}: {value}" if title else value)
    return lines, size, height_is_bucket


def review_to_rows(review: Dict[str, object], context: ProductContext, fetched_at: str, review_index: int) -> List[Dict[str, str]]:
    urls = review.get("imageUrls")
    if not isinstance(urls, list) or not urls:
        return []
    field_lines, size, height_is_bucket = custom_field_lines(review)
    comment = " | ".join(part for part in [norm(review.get("content")), " | ".join(field_lines)] if part)
    review_date = review_date_from_raw(norm(review.get("createdAt")))
    rows: List[Dict[str, str]] = []
    for image_index, image_url in enumerate([norm(url) for url in urls if norm(url)], start=1):
        review_image = ReviewImage(
            image_url=image_url,
            review_id=f"{context.product_id}-{review_date}-{review_index}-{image_index}",
            review_title=strip_tags(review.get("title")),
            review_body=comment,
            reviewer_name=norm(review.get("reviewer")),
            date_raw=norm(review.get("createdAt")),
            review_date=review_date,
            size_raw=size,
            rating=norm(review.get("score")),
            extra={
                "product_url": context.url,
                "product_title": context.title,
                "product_description": context.description,
                "product_detail": context.detail,
                "product_category": context.category,
                "product_variant": context.color,
                "image_source_type": "customer_review_image",
                "image_source_detail": "FIGS public review image",
            },
        )
        row = build_intake_row(context, review_image, fetched_at)
        if height_is_bucket:
            row["height_raw"] = ""
            row["height_in_display"] = ""
        rows.append(row)
    return rows


def fetch_review_rows(context: ProductContext, limit_pages: Optional[int], delay: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    rows: List[Dict[str, str]] = []
    if not context.product_id:
        return rows, {"review_pages_scanned": 0, "review_count_hint": 0, "media_reviews_seen": 0, "errors": ["missing_shopify_product_id"]}
    page = 1
    total_rows_hint = 0
    media_reviews_seen = 0
    while True:
        if limit_pages is not None and page > limit_pages:
            break
        payload = post_graphql(
            "getFilteredReviews",
            GET_FILTERED_REVIEWS_QUERY,
            {"filterInput": {"productId": context.product_id, "pictured": True}, "pageNum": page, "numPerPage": REVIEWS_PER_PAGE},
            referer=context.url,
            delay=delay,
        )
        filtered = ((payload.get("data") or {}).get("filteredReviews") or {}) if isinstance(payload.get("data"), dict) else {}
        pagination = filtered.get("pagination") if isinstance(filtered, dict) else {}
        reviews = [item for item in filtered.get("reviews", []) if isinstance(item, dict)] if isinstance(filtered, dict) else []
        if isinstance(pagination, dict):
            total_rows_hint = int(pagination.get("numPages") or total_rows_hint or 0)
        if not reviews:
            break
        for index, review in enumerate(reviews, start=((page - 1) * REVIEWS_PER_PAGE) + 1):
            if review.get("imageUrls"):
                media_reviews_seen += 1
            rows.extend(review_to_rows(review, context, utc_now(), index))
        page_count = max(1, math.ceil(total_rows_hint / REVIEWS_PER_PAGE)) if total_rows_hint else page
        if page >= page_count:
            break
        page += 1
    return rows, {
        "review_pages_scanned": page if total_rows_hint or rows else 0,
        "review_count_hint": total_rows_hint,
        "media_reviews_seen": media_reviews_seen,
        "errors": [],
    }


def scrape(limit_products: Optional[int], limit_review_pages: Optional[int], delay: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    products, product_sources = discover_sitemap_products(delay)
    if limit_products is not None:
        products = products[:limit_products]
    all_rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    for index, product in enumerate(products, start=1):
        product_summary = {
            "product_url": product["url"],
            "product_title": "",
            "handle": product["handle"],
            "color": product.get("color", ""),
            "shopify_product_id": "",
            "skipped_from_output": False,
            "skip_reason": "",
            "review_pages_scanned": 0,
            "review_count_hint": 0,
            "media_reviews_seen": 0,
            "rows": 0,
            "errors": [],
        }
        rough_skip = skip_reason(product)
        try:
            page_text = fetch_text(str(product["url"]), delay=delay)
            context = product_context_from_page(product, page_text)
            product_summary.update(
                {
                    "product_title": context.title,
                    "shopify_product_id": context.product_id,
                    "skip_reason": rough_skip or skip_reason({**product, "title": context.title, "category": context.category, "detail": context.detail}),
                }
            )
            product_summary["skipped_from_output"] = bool(product_summary["skip_reason"])
            if not product_summary["skipped_from_output"]:
                rows, review_meta = fetch_review_rows(context, limit_review_pages, delay)
                all_rows.extend(rows)
                product_summary.update(review_meta)
                product_summary["rows"] = len(rows)
        except StopScrape:
            raise
        except Exception as exc:  # noqa: BLE001
            product_summary["errors"] = [str(exc)]
            errors.append(f"{product['url']}: {exc}")
        product_summaries.append(product_summary)
        print(
            f"[product {index}/{len(products)}] pages={product_summary['review_pages_scanned']} "
            f"media_reviews={product_summary['media_reviews_seen']} rows={product_summary['rows']} "
            f"{product_summary.get('product_title') or product['handle']}",
            flush=True,
        )
    rows = dedupe_rows(all_rows)
    rows.sort(key=lambda row: (row.get("review_date", ""), row.get("product_page_url_display", ""), row.get("original_url_display", "")), reverse=True)
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "wearfigs_sitemap_product_pages_and_public_graphql_filtered_review_images",
        "started_at": started_at,
        "finished_at": utc_now(),
        "output_csv": str(OUTPUT_CSV),
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "products_target_scanned": sum(1 for item in product_summaries if not item.get("skipped_from_output")),
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "review_pages_scanned": sum(int(item.get("review_pages_scanned") or 0) for item in product_summaries),
        "product_review_count_hint": sum(int(item.get("review_count_hint") or 0) for item in product_summaries),
        "products_with_review_rows": sum(1 for item in product_summaries if int(item.get("rows") or 0) > 0),
        "exhaustive_review_paging": limit_review_pages is None and not errors,
        "target_scope": "women_clothing_only",
        "product_summaries": product_summaries,
        "errors": errors,
        "access_policy": (
            "public_sitemap_product_pages_and_public_graphql_reviews_only; "
            "no_auth_bypass; no_captcha_bypass; stop_on_403_429_or_challenge; "
            f"request_delay_seconds={delay}"
        ),
        "scrape_scope_status": "full_public_sitemap_attempted" if limit_products is None and limit_review_pages is None else "limited_smoke",
    }
    summary.update(validate_rows(rows))
    return rows, summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape FIGS public review images into the Step 1 intake schema.")
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
