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
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
    ProductContext,
    ReviewImage,
    build_intake_row,
    canonical_product_url,
    dedupe_rows,
    normalize_whitespace,
    strip_tags,
    utc_now,
    write_intake_csv,
)


SITE_ROOT = "https://www.ladyblacktie.com"
RETAILER = "ladyblacktie_com"
SHOP_DOMAIN = "f9da5c-58.myshopify.com"
JUDGEME_ALL_REVIEWS_URL = "https://api.judge.me/reviews/all_reviews_js_based"

try:
    from step1_intake_utils import STEP1_OUTPUT_ROOT
except ImportError:  # pragma: no cover
    STEP1_OUTPUT_ROOT = Path(__file__).resolve().parents[4] / "data-pipelines" / "non-amazon" / "data" / "step_1_raw_scraping_data"

OUTPUT_DIR = STEP1_OUTPUT_ROOT / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema_summary.json"

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

REVIEW_BLOCK_RE = re.compile(
    r"(<div class='jdgm-rev jdgm-divider-top'.*?)(?=<div class='jdgm-rev jdgm-divider-top'|</div>\s*<div class='jdgm-paginate'|$)",
    re.S,
)
PRODUCT_LINK_RE = re.compile(r"<a href='([^']+)'[^>]*class='jdgm-rev__prod-link'[^>]*>(.*?)</a>", re.S)
CUSTOMER_IMAGE_RE = re.compile(
    r"<a class='(?![^']*jdgm-rev__product-picture)[^']*jdgm-rev__pic-link[^']*'[^>]+href='([^']+)'",
    re.S,
)
APPAREL_RE = re.compile(
    r"\b(bridesmaid|cocktail|dress|dresses|formal|gown|jumpsuit|maxi|midi|mini|romper|skirt|wedding)\b",
    re.I,
)


class PressureStop(RuntimeError):
    pass


def request_text(url: str, *, accept: str = "text/html,application/xml;q=0.9,*/*;q=0.8") -> str:
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


def request_json(url: str) -> Dict[str, object]:
    text = request_text(url, accept="application/json,text/plain,*/*")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PressureStop(f"non_json_response: {url}") from exc
    if not isinstance(payload, dict):
        raise PressureStop(f"unexpected_json_response: {url}")
    return payload


def attr(block: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}='([^']*)'|{re.escape(name)}=\"([^\"]*)\"", block)
    if not match:
        return ""
    return normalize_whitespace(unescape(match.group(1) or match.group(2) or ""))


def discover_product_urls() -> Tuple[List[str], Dict[str, object]]:
    root = request_text(f"{SITE_ROOT}/sitemap.xml")
    sitemap_urls = [unescape(url) for url in re.findall(r"<loc>(.*?)</loc>", root)]
    product_sitemaps = [url for url in sitemap_urls if "sitemap_products_" in url]
    products: List[str] = []
    source_pages: List[Dict[str, object]] = []
    seen = set()
    for sitemap_url in product_sitemaps:
        normalized_sitemap_url = sitemap_url.replace("&amp;", "&")
        xml = request_text(normalized_sitemap_url)
        urls = [unescape(url) for url in re.findall(r"<loc>(.*?)</loc>", xml)]
        product_urls = [canonical_product_url(url) for url in urls if "/products/" in url]
        source_pages.append({"url": normalized_sitemap_url, "products": len(product_urls)})
        for product_url in product_urls:
            if product_url and product_url not in seen:
                seen.add(product_url)
                products.append(product_url)
    return products, {
        "sitemap_index": f"{SITE_ROOT}/sitemap.xml",
        "product_sitemaps": source_pages,
        "unique_product_urls": len(products),
    }


def reviews_url(page: int) -> str:
    query = urlencode(
        {
            "shop_domain": SHOP_DOMAIN,
            "platform": "shopify",
            "sort_by": "with_media",
            "per_page": 100,
            "page": page,
        }
    )
    return f"{JUDGEME_ALL_REVIEWS_URL}?{query}"


def review_blocks(html: str) -> List[str]:
    return [match.group(1) for match in REVIEW_BLOCK_RE.finditer(html)]


def text_between(block: str, pattern: str) -> str:
    match = re.search(pattern, block, re.S)
    return strip_tags(match.group(1)) if match else ""


def product_from_review(block: str) -> Tuple[str, str]:
    match = PRODUCT_LINK_RE.search(block)
    if not match:
        return "", ""
    product_url = canonical_product_url(urljoin(SITE_ROOT, unescape(match.group(1)).split("#", 1)[0]))
    product_title = strip_tags(match.group(2))
    return product_url, product_title


def customer_images(block: str) -> List[str]:
    urls: List[str] = []
    for raw_url in CUSTOMER_IMAGE_RE.findall(block):
        image_url = unescape(raw_url)
        if "judgeme.imgix.net" not in image_url:
            continue
        if image_url not in urls:
            urls.append(image_url)
    return urls


def parse_review(block: str, fetched_at: str) -> List[Dict[str, str]]:
    review_id = attr(block, "data-review-id")
    date_raw = attr(block, "data-content")
    reviewer = text_between(block, r"<span class='jdgm-rev__author'>(.*?)</span>")
    title = text_between(block, r"<b class='jdgm-rev__title'>(.*?)</b>")
    body = text_between(block, r"<div class='jdgm-rev__body'>(.*?)</div>")
    product_url, product_title = product_from_review(block)
    images = customer_images(block)
    if not product_url or not images:
        return []
    context = ProductContext(
        url=product_url,
        title=product_title,
        brand="Lady Black Tie",
        shop_domain=SHOP_DOMAIN,
        provider_hints="Judge.me all_reviews_js_based with_media",
    )
    rows: List[Dict[str, str]] = []
    for index, image_url in enumerate(images, start=1):
        fallback_id = hashlib.md5(f"{product_url}|{image_url}|{title}|{body}".encode("utf-8")).hexdigest()[:16]
        review = ReviewImage(
            image_url=image_url,
            review_id=f"{review_id}-{index}" if review_id else f"ladyblacktie-{fallback_id}-{index}",
            review_title=title,
            review_body=body,
            reviewer_name=reviewer,
            date_raw=date_raw,
            size_raw="unknown",
            extra={
                "image_source_type": "customer_review_image",
                "image_source_detail": "public Judge.me all-reviews media feed",
                "product_url": product_url,
                "product_title": product_title,
            },
        )
        rows.append(build_intake_row(context, review, fetched_at))
    return rows


def in_scope_row(row: Dict[str, str], product_urls: set[str]) -> bool:
    product_url = canonical_product_url(row.get("product_page_url_display", ""))
    title = normalize_whitespace(row.get("product_title_raw", ""))
    if product_url in product_urls:
        return True
    return bool(APPAREL_RE.search(title))


def scrape(args: argparse.Namespace) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    product_urls, product_source = discover_product_urls()
    product_url_set = set(product_urls)
    rows: List[Dict[str, str]] = []
    review_pages: List[Dict[str, object]] = []
    errors: List[str] = []
    product_reviews_count_hint: Optional[int] = None
    shop_reviews_count_hint: Optional[int] = None
    pages_scanned = 0

    for page in range(1, args.max_review_pages + 1):
        payload = request_json(reviews_url(page))
        html = unescape(str(payload.get("html") or ""))
        blocks = review_blocks(html)
        if page == 1:
            product_reviews_count_hint = int(payload.get("number_of_product_reviews") or 0)
            shop_reviews_count_hint = int(payload.get("number_of_shop_reviews") or 0)
        review_pages.append({"page": page, "blocks": len(blocks), "html_bytes": len(html)})
        if not blocks:
            break
        pages_scanned += 1
        page_rows: List[Dict[str, str]] = []
        for block in blocks:
            page_rows.extend(parse_review(block, started_at))
        page_rows = [row for row in page_rows if in_scope_row(row, product_url_set)]
        rows.extend(page_rows)
        print(f"[review page {page}] blocks={len(blocks)} rows={len(page_rows)} total={len(rows)}", flush=True)
        if args.limit_review_pages and page >= args.limit_review_pages:
            break
        if args.request_delay_seconds:
            time.sleep(args.request_delay_seconds)

    rows = dedupe_rows(rows)
    row_counts: Dict[str, int] = {}
    for row in rows:
        product_url = canonical_product_url(row.get("product_page_url_display", ""))
        row_counts[product_url] = row_counts.get(product_url, 0) + 1
    product_summaries = [
        {
            "product_url": product_url,
            "rows": row_counts.get(product_url, 0),
            "skipped_from_output": row_counts.get(product_url, 0) == 0,
            "skip_reason": "no_customer_review_media_rows_in_store_feed" if row_counts.get(product_url, 0) == 0 else "",
        }
        for product_url in product_urls
    ]
    finished_at = utc_now()
    exhaustive = not errors and not args.limit_review_pages and bool(review_pages) and review_pages[-1].get("blocks") == 0
    return rows, {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_sitemap_judgeme_all_reviews_with_media",
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": {"shopify_sitemap": product_source},
        "products_discovered": len(product_urls),
        "products_scanned": len(product_urls),
        "product_pages_scanned": 0,
        "review_pages_scanned": pages_scanned,
        "review_page_requests": review_pages,
        "product_reviews_count_hint": product_reviews_count_hint,
        "shop_reviews_count_hint": shop_reviews_count_hint,
        "exhaustive_review_paging": exhaustive,
        "coverage_exhaustive": exhaustive,
        "scrape_scope_status": "full_public_judgeme_media_feed_complete" if exhaustive else "stopped_or_limited",
        "product_summaries": product_summaries,
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "access_policy": "public sitemap and public Judge.me all_reviews_js_based endpoint; no auth bypass; stop on 429/captcha/WAF",
        "errors": errors,
    }


def strict_qualified_rows(rows: Sequence[Dict[str, str]]) -> int:
    return sum(
        1
        for row in rows
        if row.get("original_url_display")
        and row.get("image_source_type") == "customer_review_image"
        and (row.get("product_page_url_display") or row.get("monetized_product_url_display"))
        and row.get("size_display")
        and row.get("size_display", "").lower() != "unknown"
        and any(row.get(field) for field in MEASUREMENT_FIELDS)
    )


def write_outputs(rows: Sequence[Dict[str, str]], summary: Dict[str, object]) -> None:
    write_intake_csv(rows, OUTPUT_CSV)
    rows_with_product_url = sum(1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display"))
    rows_with_measurements = sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS))
    rows_with_customer_image = sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image")
    rows_with_ordered_size = sum(1 for row in rows if row.get("size_display") and row.get("size_display", "").lower() != "unknown")
    payload = dict(summary)
    payload.update(
        {
            "output_csv": str(OUTPUT_CSV),
            "summary_json": str(SUMMARY_JSON),
            "rows_written": len(rows),
            "distinct_reviews": len({(row.get("id") or "").rsplit("-", 1)[0] for row in rows if row.get("id")}),
            "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
            "distinct_product_urls": len({row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}),
            "rows_with_distinct_product_url": rows_with_product_url,
            "rows_with_any_measurement": rows_with_measurements,
            "rows_with_customer_image": rows_with_customer_image,
            "rows_with_customer_ordered_size": rows_with_ordered_size,
            "rows_supabase_qualified": strict_qualified_rows(rows),
        }
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Lady Black Tie customer review media from public Judge.me feed.")
    parser.add_argument("--max-review-pages", type=int, default=100)
    parser.add_argument("--limit-review-pages", type=int, default=0)
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
