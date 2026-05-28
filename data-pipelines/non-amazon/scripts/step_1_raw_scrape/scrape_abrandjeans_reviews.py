#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    output_paths,
    utc_now,
    validate_rows,
    write_intake_csv,
)


SITE_ROOT = "https://abrandjeans.com"
RETAILER = "abrandjeans_com"
SAMPLE_CATEGORY_URL = f"{SITE_ROOT}/collections/womens-clothing-new-arrivals"
SAMPLE_PDP_URLS = [
    f"{SITE_ROOT}/products/00-wide-eva",
    f"{SITE_ROOT}/products/00-wide-tara",
    f"{SITE_ROOT}/products/00-wide-kaia-worn",
]
OUTPUT_CSV, SUMMARY_JSON = output_paths(RETAILER)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
PRESSURE_STATUS_CODES = {401, 403, 407, 423, 429, 430, 503}
BLOCK_RE = re.compile(
    r"\b(?:captcha|cloudflare challenge|cf-chl|datadome|perimeterx|awswaf|access denied|"
    r"attention required|verify you are human|temporarily blocked)\b",
    re.I,
)


class StopScrape(RuntimeError):
    pass


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def strip_tags(value: object) -> str:
    return norm(re.sub(r"<[^>]+>", " ", str(value or "")))


def fetch_text(url: str, *, referer: str = SITE_ROOT, delay: float = 0.35, accept: str = "text/html,application/json,*/*") -> str:
    time.sleep(delay)
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        },
    )
    try:
        with urlopen(request, timeout=45) as response:
            status = int(getattr(response, "status", 200))
            text = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code in PRESSURE_STATUS_CODES:
            raise StopScrape(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
        raise
    except URLError as exc:
        raise StopScrape(f"network_error: {url}: {exc}") from exc
    if status in PRESSURE_STATUS_CODES:
        raise StopScrape(f"blocked_or_rate_limited_http_{status}: {url}")
    if BLOCK_RE.search(text[:120_000]):
        raise StopScrape(f"blocked_or_challenged_response: {url}")
    return text


def fetch_json(url: str, *, referer: str, delay: float) -> Dict[str, object]:
    text = fetch_text(url, referer=referer, delay=delay, accept="application/json,text/plain,*/*")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise StopScrape(f"unexpected_json_response: {url}")
    return payload


def category_product_links(html_text: str) -> List[str]:
    links: List[str] = []
    for match in re.findall(r"href=['\"]([^'\"]*/products/[^'\"#?]+)", html_text, re.I):
        url = urljoin(SITE_ROOT, html.unescape(match))
        if url not in links:
            links.append(url)
    return links


def first_match(patterns: Sequence[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return norm(match.group(1))
    return ""


def product_id_from_html(html_text: str) -> str:
    product_id = first_match([r"productId=shopify-(\d+)", r'"productId":"gid://shopify/Product/(\d+)"'], html_text)
    return product_id


def subscriber_id_from_html(html_text: str) -> str:
    return first_match(
        [
            r"subscriberId=([0-9a-f-]{36})",
            r'"subscriberId"\s*:\s*"([0-9a-f-]{36})"',
            r"api\.okendo\.io/v1/stores/([0-9a-f-]{36})",
        ],
        html_text,
    )


def product_context(url: str, html_text: str) -> ProductContext:
    product_id = product_id_from_html(html_text)
    title = strip_tags(first_match([r"<title[^>]*>(.*?)</title>"], html_text)).replace("Buy ", "").replace(" Online | Abrand Jeans", "")
    handle = url.rstrip("/").rsplit("/", 1)[-1]
    brand = "Abrand Jeans"
    product_name = first_match([r'"productName"\s*:\s*"([^"]+)"', r'"title"\s*:\s*"([^"]+)"'], html_text) or title
    variants = re.findall(r'"sku"\s*:\s*"([^"]+)"', html_text)
    size_values = re.findall(r'"name"\s*:\s*"size"\s*,\s*"values"\s*:\s*\[(.*?)\]', html_text, re.I | re.S)
    sizes = []
    if size_values:
        sizes = [norm(item.strip('"')) for item in re.findall(r'"([^"]+)"', size_values[0])]
    return ProductContext(
        url=url,
        title=product_name,
        description="",
        detail=" | ".join(variants[:50]),
        category="Women's Clothing New Arrivals",
        brand=brand,
        product_id=product_id,
        handle=handle,
        shop_domain="abrandjeans.com",
        provider_hints=f"Okendo subscriber {subscriber_id_from_html(html_text)}; sizes {'/'.join(sizes)}",
        raw_html=html_text,
    )


def extract_media_urls(value: object) -> List[str]:
    urls: List[str] = []
    if isinstance(value, str):
        urls.extend(re.findall(r"(?:https?:)?//[^'\"\s,<>]+\.(?:jpg|jpeg|png|webp)(?:\?[^'\"\s,<>]*)?", value, re.I))
    elif isinstance(value, list):
        for item in value:
            urls.extend(extract_media_urls(item))
    elif isinstance(value, dict):
        for key in ["url", "mediaUrl", "imageUrl", "fullSizeUrl", "thumbnailUrl", "src"]:
            if value.get(key):
                urls.append(str(value[key]))
        for key in ["media", "images", "videos"]:
            if key in value:
                urls.extend(extract_media_urls(value[key]))
    normalized = [f"https:{url}" if url.startswith("//") else url for url in urls]
    normalized = [url for url in normalized if re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", url, re.I)]
    full_size = [
        url
        for url in normalized
        if "d=120x120" not in url.lower() and "crop=center" not in url.lower()
    ]
    return list(dict.fromkeys(full_size or normalized))


def review_size_and_measurement_blob(review: Dict[str, object]) -> Tuple[str, str]:
    attrs = review.get("reviewer", {}).get("attributes") if isinstance(review.get("reviewer"), dict) else []
    size = ""
    parts: List[str] = []
    if isinstance(attrs, list):
        for attr in attrs:
            if not isinstance(attr, dict):
                continue
            title = norm(attr.get("title"))
            raw_value = attr.get("value")
            if isinstance(raw_value, dict):
                value = norm(raw_value.get("countryName") or raw_value.get("name") or json.dumps(raw_value))
            else:
                value = norm(raw_value)
            if not title or not value:
                continue
            parts.append(f"{title}: {value}")
            if title.lower() in {"size bought", "size"} and not size:
                size = value
    variant = norm(review.get("productVariantName"))
    if not size and variant:
        size = variant.rsplit("/", 1)[-1].strip()
    return size, "; ".join(parts)


def fetch_okendo_reviews(subscriber_id: str, product_id: str, product_url: str, delay: float) -> Tuple[List[Dict[str, object]], int]:
    reviews: List[Dict[str, object]] = []
    pages = 0
    params = {"limit": 100, "orderBy": "has_media desc"}
    url = f"https://api.okendo.io/v1/stores/{subscriber_id}/products/shopify-{product_id}/reviews?{urlencode(params)}"
    seen = set()
    while url and url not in seen:
        seen.add(url)
        payload = fetch_json(url, referer=product_url, delay=delay)
        pages += 1
        items = payload.get("reviews") or payload.get("data") or []
        if isinstance(items, list):
            reviews.extend(item for item in items if isinstance(item, dict))
        next_url = norm(payload.get("nextUrl") or payload.get("reviewsNextUrl"))
        url = f"https://api.okendo.io/v1{next_url}" if next_url.startswith("/") else next_url
    return reviews, pages


def rows_from_reviews(context: ProductContext, reviews: Iterable[Dict[str, object]], fetched_at: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for review in reviews:
        media_urls = extract_media_urls(review.get("media") or review.get("images") or [])
        # Okendo productImageUrl is a catalog image, not a customer-uploaded review photo.
        media_urls = [url for url in media_urls if url != norm(review.get("productImageUrl"))]
        if not media_urls:
            continue
        size, attrs_blob = review_size_and_measurement_blob(review)
        body = norm(review.get("body") or review.get("reviewBody"))
        if attrs_blob:
            body = norm(f"{body} {attrs_blob}")
        reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
        product_url = norm(review.get("productUrl"))
        if product_url.startswith("//"):
            product_url = "https:" + product_url
        for index, image_url in enumerate(media_urls, start=1):
            rows.append(
                build_intake_row(
                    context,
                    ReviewImage(
                        image_url=image_url,
                        review_id=f"abrandjeans-okendo-{norm(review.get('reviewId') or review.get('id'))}-{index}",
                        review_title=norm(review.get("title")),
                        review_body=body,
                        reviewer_name=norm(reviewer.get("displayName") or review.get("reviewerDisplayName")),
                        date_raw=norm(review.get("dateCreated") or review.get("createdAt")),
                        size_raw=size,
                        rating=norm(review.get("rating")),
                        extra={
                            "product_url": product_url or context.url,
                            "product_title": norm(review.get("productName")) or context.title,
                            "product_variant": norm(review.get("productVariantName")),
                            "image_source_type": "customer_review_image",
                            "image_source_detail": "okendo_review_media",
                        },
                    ),
                    fetched_at,
                )
            )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Abrand Jeans public category/PDP Okendo review media scrape.")
    parser.add_argument("--max-products", type=int, default=80)
    parser.add_argument("--request-delay-seconds", type=float, default=0.35)
    args = parser.parse_args(argv)

    started_at = utc_now()
    fetched_at = started_at
    category_html = ""
    product_summaries: List[Dict[str, object]] = []
    rows: List[Dict[str, str]] = []
    errors: List[str] = []
    stop_reason = ""
    review_pages_scanned = 0

    try:
        category_html = fetch_text(SAMPLE_CATEGORY_URL, delay=args.request_delay_seconds)
        product_urls = list(dict.fromkeys([*SAMPLE_PDP_URLS, *category_product_links(category_html)]))[: args.max_products]
        for idx, product_url in enumerate(product_urls, start=1):
            html_text = fetch_text(product_url, referer=SAMPLE_CATEGORY_URL, delay=args.request_delay_seconds)
            context = product_context(product_url, html_text)
            subscriber_id = subscriber_id_from_html(html_text)
            summary = {
                "url": product_url,
                "product_id": context.product_id,
                "title": context.title,
                "subscriber_id": subscriber_id,
                "reviews_seen": 0,
                "review_pages_scanned": 0,
                "customer_media_rows": 0,
                "skip_reason": "",
            }
            if not subscriber_id or not context.product_id:
                summary["skip_reason"] = "missing_public_okendo_subscriber_or_product_id"
                product_summaries.append(summary)
                continue
            reviews, pages = fetch_okendo_reviews(subscriber_id, context.product_id, product_url, args.request_delay_seconds)
            review_pages_scanned += pages
            product_rows = rows_from_reviews(context, reviews, fetched_at)
            summary["reviews_seen"] = len(reviews)
            summary["review_pages_scanned"] = pages
            summary["customer_media_rows"] = len(product_rows)
            if not product_rows:
                summary["skip_reason"] = "okendo_reviews_have_no_customer_media"
            rows.extend(product_rows)
            product_summaries.append(summary)
            print(f"[{idx}/{len(product_urls)}] {context.handle} reviews={len(reviews)} rows={len(product_rows)}", flush=True)
    except StopScrape as exc:
        stop_reason = str(exc)
        errors.append(stop_reason)

    rows = dedupe_rows(rows)
    unique_rows: List[Dict[str, str]] = []
    seen_review_images = set()
    for row in rows:
        key = (row.get("id") or "", row.get("original_url_display") or "")
        if key in seen_review_images:
            continue
        seen_review_images.add(key)
        unique_rows.append(row)
    rows = unique_rows
    write_intake_csv(rows, OUTPUT_CSV)
    finished_at = utc_now()
    validation = validate_rows(rows)
    summary = {
        "site": "abrandjeans.com",
        "retailer": RETAILER,
        "adapter": "shopify_category_product_pages_okendo_public_reviews",
        "triage_bucket": "sovrn_first_pass_scrape_candidate",
        "triage_source": "data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv",
        "merchant": "Abrand Jeans",
        "review_platform_provider": "Okendo",
        "photo_reviews_present_triage": True,
        "reviews_present_triage": True,
        "shipping_geos": "US",
        "commission_model": "CPC",
        "cpc_amount": "not populated in triage",
        "access_policy": "public category/product pages and public Okendo review API only; stop_on_429_captcha_waf_auth",
        "sample_category_url": SAMPLE_CATEGORY_URL,
        "sample_pdp_urls": SAMPLE_PDP_URLS,
        "product_sources": {
            "sample_category_pages": 1,
            "sample_product_pages": len(SAMPLE_PDP_URLS),
            "category_product_links_found": len(category_product_links(category_html)) if category_html else 0,
            "product_pages_checked": len(product_summaries),
        },
        "products_discovered": len(product_summaries),
        "products_scanned": len(product_summaries),
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skip_reason")),
        "review_pages_scanned": review_pages_scanned,
        "exhaustive_review_paging": not stop_reason,
        "coverage_exhaustive": not stop_reason and len(product_summaries) < args.max_products,
        "blocked": bool(stop_reason),
        "stop_reason": stop_reason or "completed_public_okendo_scan",
        "output_csv": str(OUTPUT_CSV),
        "started_at": started_at,
        "finished_at": finished_at,
        "product_summaries": product_summaries,
        "errors": errors,
    }
    summary.update(validation)
    summary["rows_with_distinct_product_url"] = validation.get("distinct_products", 0)
    summary["rows_with_customer_image"] = validation.get("rows_with_customer_review_image", 0)
    summary["rows_with_customer_ordered_size"] = validation.get("rows_with_customer_ordered_size", 0)
    summary["rows_supabase_qualified"] = validation.get("supabase_qualified_rows", 0)
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {SUMMARY_JSON}")
    print(f"Rows written: {len(rows)}")
    print(f"Stop reason: {summary['stop_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
