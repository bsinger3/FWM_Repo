#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from html import unescape
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
    dedupe_rows,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    write_intake_csv,
)


SITE_ROOT = "https://www.barse.com"
RETAILER = "barse_com"
SHOP_DOMAIN = "barse-jewelry.myshopify.com"
JUDGEME_ALL_REVIEWS_URL = "https://api.judge.me/reviews/all_reviews_js_based"

OUTPUT_CSV, SUMMARY_JSON = output_paths(RETAILER)
OUTPUT_DIR = OUTPUT_CSV.parent

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
CUSTOMER_IMAGE_RE = re.compile(
    r"<a class='(?![^']*jdgm-rev__product-picture)[^']*jdgm-rev__pic-link[^']*'[^>]+href='([^']+)'",
    re.S,
)


class PressureStop(RuntimeError):
    pass


def request_text(url: str, *, accept: str = "text/html,application/json,*/*") -> str:
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


def products_url(page: int) -> str:
    return f"{SITE_ROOT}/products.json?{urlencode({'limit': 250, 'page': page})}"


def discover_products(max_pages: int, delay_seconds: float) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    products: List[Dict[str, object]] = []
    page_summaries: List[Dict[str, object]] = []
    type_counts: Counter[str] = Counter()
    for page in range(1, max_pages + 1):
        payload = request_json(products_url(page))
        page_products = payload.get("products") or []
        if not isinstance(page_products, list):
            raise PressureStop(f"unexpected_products_json_shape: {products_url(page)}")
        page_summaries.append({"page": page, "products": len(page_products)})
        if not page_products:
            break
        for product in page_products:
            if not isinstance(product, dict):
                continue
            products.append(product)
            product_type = normalize_whitespace(product.get("product_type") or "unknown") or "unknown"
            type_counts[product_type] += 1
        print(f"[catalog page {page}] products={len(page_products)} total={len(products)}", flush=True)
        if delay_seconds:
            time.sleep(delay_seconds)
    return products, {
        "endpoint": f"{SITE_ROOT}/products.json",
        "page_requests": page_summaries,
        "product_type_counts": dict(type_counts.most_common()),
        "exhaustive": bool(page_summaries) and page_summaries[-1].get("products") == 0,
    }


def reviews_url(page: int, sort_by: str = "") -> str:
    params = {
        "shop_domain": SHOP_DOMAIN,
        "platform": "shopify",
        "per_page": 100,
        "page": page,
    }
    if sort_by:
        params["sort_by"] = sort_by
    return f"{JUDGEME_ALL_REVIEWS_URL}?{urlencode(params)}"


def review_blocks(html: str) -> List[str]:
    return [match.group(1) for match in REVIEW_BLOCK_RE.finditer(html)]


def customer_images(block: str) -> List[str]:
    urls: List[str] = []
    for raw_url in CUSTOMER_IMAGE_RE.findall(block):
        image_url = unescape(raw_url)
        if "judgeme.imgix.net" not in image_url:
            continue
        if image_url not in urls:
            urls.append(image_url)
    return urls


def probe_review_feed(max_review_pages: int, delay_seconds: float) -> Dict[str, object]:
    media_probes: List[Dict[str, object]] = []
    for sort_by in ("with_pictures", "with_media"):
        payload = request_json(reviews_url(1, sort_by=sort_by))
        html = unescape(str(payload.get("html") or ""))
        blocks = review_blocks(html)
        media_probes.append(
            {
                "sort_by": sort_by,
                "html_bytes": len(html),
                "blocks": len(blocks),
                "customer_image_links": sum(len(customer_images(block)) for block in blocks),
                "number_of_product_reviews": int(payload.get("number_of_product_reviews") or 0),
                "number_of_shop_reviews": int(payload.get("number_of_shop_reviews") or 0),
            }
        )
        if delay_seconds:
            time.sleep(delay_seconds)

    sampled_pages: List[Dict[str, object]] = []
    sampled_image_links = 0
    total_blocks = 0
    for page in range(1, max_review_pages + 1):
        payload = request_json(reviews_url(page))
        html = unescape(str(payload.get("html") or ""))
        blocks = review_blocks(html)
        image_links = sum(len(customer_images(block)) for block in blocks)
        sampled_pages.append({"page": page, "blocks": len(blocks), "customer_image_links": image_links, "html_bytes": len(html)})
        total_blocks += len(blocks)
        sampled_image_links += image_links
        print(f"[review sample page {page}] blocks={len(blocks)} customer_image_links={image_links}", flush=True)
        if not blocks or image_links:
            break
        if delay_seconds:
            time.sleep(delay_seconds)

    return {
        "media_endpoint_probes": media_probes,
        "sampled_recent_review_pages": sampled_pages,
        "sampled_recent_review_blocks": total_blocks,
        "sampled_customer_image_links": sampled_image_links,
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


def scrape(args: argparse.Namespace) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    products, product_source = discover_products(args.max_catalog_pages, args.request_delay_seconds)
    review_probe = probe_review_feed(args.max_review_sample_pages, args.request_delay_seconds)
    rows: List[Dict[str, str]] = []
    finished_at = utc_now()
    product_type_counts = product_source.get("product_type_counts", {})
    jewelry_product_count = sum(
        int(count)
        for product_type, count in product_type_counts.items()
        if re.search(r"\b(necklaces?|rings?|bracelets?|earrings?)\b", str(product_type), re.I)
    )
    all_media_empty = all(
        item.get("blocks") == 0 and item.get("customer_image_links") == 0
        for item in review_probe.get("media_endpoint_probes", [])
    )
    sample_media_empty = int(review_probe.get("sampled_customer_image_links") or 0) == 0
    return rows, {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_judgeme_media_probe",
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": {"shopify_products_json": product_source},
        "products_discovered": len(products),
        "products_scanned": len(products),
        "product_pages_scanned": 0,
        "review_pages_scanned": len(review_probe.get("sampled_recent_review_pages", [])),
        "review_probe": review_probe,
        "coverage_exhaustive": bool(product_source.get("exhaustive")) and all_media_empty,
        "scrape_scope_status": (
            "completed_no_public_review_images_or_apparel_fit_signal"
            if all_media_empty and sample_media_empty
            else "completed_probe_only_review_media_unclear"
        ),
        "jewelry_product_count": jewelry_product_count,
        "access_policy": "public Shopify products.json and public Judge.me all_reviews_js_based endpoint; no auth bypass; stop on 429/captcha/WAF",
        "errors": [],
    }


def write_outputs(rows: Sequence[Dict[str, str]], summary: Dict[str, object]) -> None:
    rows = dedupe_rows(rows)
    write_intake_csv(rows, OUTPUT_CSV)
    payload = dict(summary)
    payload.update(
        {
            "output_csv": str(OUTPUT_CSV),
            "summary_json": str(SUMMARY_JSON),
            "rows_written": len(rows),
            "distinct_reviews": len({(row.get("id") or "").rsplit("-", 1)[0] for row in rows if row.get("id")}),
            "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
            "distinct_product_urls": len({row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}),
            "rows_with_distinct_product_url": sum(
                1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display")
            ),
            "rows_with_any_measurement": sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS)),
            "rows_with_customer_image": sum(
                1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image"
            ),
            "rows_with_customer_ordered_size": sum(
                1 for row in rows if row.get("size_display") and row.get("size_display", "").lower() != "unknown"
            ),
            "rows_supabase_qualified": strict_qualified_rows(rows),
        }
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Probe Barse public Shopify/Judge.me reviews for usable Step 1 review media.")
    parser.add_argument("--max-catalog-pages", type=int, default=100)
    parser.add_argument("--max-review-sample-pages", type=int, default=3)
    parser.add_argument("--request-delay-seconds", type=float, default=0.2)
    args = parser.parse_args(argv)
    rows, summary = scrape(args)
    write_outputs(rows, summary)
    print(f"Rows written: {len(rows)}")
    print(f"Products discovered: {summary['products_discovered']}")
    print(f"Review sample pages scanned: {summary['review_pages_scanned']}")
    print(f"Status: {summary['scrape_scope_status']}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
