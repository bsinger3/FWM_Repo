#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import math
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
    ProductContext,
    ReviewImage,
    build_intake_row,
    canonical_product_url,
    dedupe_rows,
    normalize_ordered_size,
    normalize_whitespace,
    output_paths,
    review_date_from_raw,
    strip_tags,
    utc_now,
    validate_rows,
    write_intake_csv,
)


SITE = "https://spanx.com"
RETAILER = "spanx_com"
YOTPO_APP_KEY = "PRZxHghLYKMWCTmuTuGTzVGDbnWOdoHYjOpVCQiL"
YOTPO_PER_PAGE = 100
BLOCKING_STATUS_CODES = {401, 403, 407, 429, 503}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

WOMENS_CLOTHING_RE = re.compile(
    r"\b("
    r"bras?|bralettes?|bodysuits?|shapewear|pant(?:y|ies)|briefs?|thongs?|tangas?|shorts?|"
    r"jeans?|pants?|trousers?|leggings?|jeggings?|skorts?|skirts?|dresses?|"
    r"tops?|tees?|t-?shirts?|shirts?|tanks?|camis?|sweaters?|cardigans?|jackets?|"
    r"blazers?|jumpsuits?|rompers?|swimsuits?|bikinis?|coverups?|underwear"
    r")\b",
    re.I,
)
NON_OUTPUT_RE = re.compile(
    r"\b("
    r"gift\s*cards?|wash\s*bag|laundry|detergent|hosiery|tights?|socks?|"
    r"arm\s*tights?|strap|hanger|accessor(?:y|ies)|men|mens|men's|kids?|girls?|boys?"
    r")\b",
    re.I,
)
YOTPO_BLOCK_RE = re.compile(r"\b(?:captcha|access denied|forbidden|too many requests|akamai|datadome|cloudflare)\b", re.I)


@dataclass
class ProductRecord:
    url: str
    handle: str
    product_id: str = ""
    title: str = ""
    description: str = ""
    image_urls: List[str] = field(default_factory=list)
    source_names: set[str] = field(default_factory=set)
    page_error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape SPANX public Yotpo review images.")
    parser.add_argument("--max-products", type=int, default=0, help="Debug cap; 0 scans every discovered product.")
    parser.add_argument("--max-review-pages", type=int, default=0, help="Debug cap per product; 0 scans all Yotpo pages.")
    parser.add_argument("--sleep", type=float, default=0.05, help="Sleep between public requests.")
    return parser.parse_args()


def curl_fetch_text(url: str, *, referer: str = SITE, accept: str = "*/*", retries: int = 3) -> str:
    last_error = ""
    for attempt in range(retries):
        cmd = [
            "curl.exe",
            "-L",
            "-sS",
            "--fail-with-body",
            "--max-time",
            "60",
            "-A",
            USER_AGENT,
            "-H",
            f"Accept: {accept}",
            "-H",
            "Accept-Language: en-US,en;q=0.9",
        ]
        if referer:
            cmd.extend(["-e", referer])
        cmd.append(url)
        result = subprocess.run(
            cmd,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode == 0:
            if YOTPO_BLOCK_RE.search(result.stdout[:2000]):
                raise RuntimeError(f"blocked_or_challenge_body url={url}")
            return result.stdout
        last_error = normalize_whitespace(result.stderr or result.stdout)
        if any(f" {code}" in last_error or f"error: {code}" in last_error.lower() for code in BLOCKING_STATUS_CODES):
            raise RuntimeError(f"blocked_or_rate_limited_fetch url={url} detail={last_error}")
        time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"fetch_failed url={url} detail={last_error}")


def curl_fetch_json(url: str, *, referer: str = SITE, retries: int = 3) -> Dict[str, object]:
    return json.loads(curl_fetch_text(url, referer=referer, accept="application/json,text/plain,*/*", retries=retries))


def handle_from_url(url: str) -> str:
    parsed = urlparse(url)
    if "/products/" not in parsed.path:
        return ""
    return parsed.path.split("/products/", 1)[1].split("/", 1)[0].removesuffix(".js")


def sitemap_index_urls() -> List[str]:
    text = curl_fetch_text(f"{SITE}/sitemap.xml", accept="application/xml,text/xml,*/*")
    root = ET.fromstring(text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [
        normalize_whitespace(html.unescape(loc.text or ""))
        for loc in root.findall(".//sm:loc", ns)
        if loc.text and "/sitemap/products/" in loc.text
    ]


def discover_products_from_sitemaps() -> Tuple[Dict[str, ProductRecord], Dict[str, object]]:
    products: Dict[str, ProductRecord] = {}
    source_pages: List[Dict[str, object]] = []
    ns = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "image": "http://www.google.com/schemas/sitemap-image/1.1",
    }
    for sitemap_url in sitemap_index_urls():
        text = curl_fetch_text(sitemap_url, accept="application/xml,text/xml,*/*")
        root = ET.fromstring(text)
        page_products = 0
        for url_node in root.findall(".//sm:url", ns):
            loc = url_node.find("sm:loc", ns)
            product_url = canonical_product_url(html.unescape(loc.text or "")) if loc is not None else ""
            handle = handle_from_url(product_url)
            if not handle:
                continue
            image_urls = []
            for image_loc in url_node.findall("image:image/image:loc", ns):
                image_url = normalize_whitespace(html.unescape(image_loc.text or ""))
                if image_url:
                    image_urls.append(image_url)
            page_products += 1
            record = ProductRecord(
                url=product_url,
                handle=handle,
                image_urls=list(dict.fromkeys(image_urls)),
                source_names={"product_sitemap"},
            )
            if handle in products:
                products[handle].source_names.update(record.source_names)
                for image_url in record.image_urls:
                    if image_url not in products[handle].image_urls:
                        products[handle].image_urls.append(image_url)
            else:
                products[handle] = record
        source_pages.append({"url": sitemap_url, "products": page_products})
    return products, {"product_sitemap_pages": source_pages, "unique_product_urls": len(products)}


def json_ld_product(html_text: str) -> Dict[str, object]:
    for block in re.findall(r"<script[^>]+type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", html_text, re.I | re.S):
        try:
            payload = json.loads(html.unescape(block.strip()))
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(value).lower() == "product" for value in types):
                return item
    return {}


def first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.I | re.S)
    return normalize_whitespace(html.unescape(match.group(1))) if match else ""


def hydrate_product_page(product: ProductRecord) -> None:
    html_text = curl_fetch_text(product.url, referer=SITE, accept="text/html,*/*")
    payload = json_ld_product(html_text)
    product.product_id = first_match(r"productGroupID['\"]?\s*:\s*['\"]gid://shopify/Product/(\d+)['\"]", html_text)
    product.product_id = product.product_id or first_match(r"gid://shopify/Product/(\d+)", html_text)
    product.title = normalize_whitespace(payload.get("name") if payload else "") or first_match(
        r"<meta[^>]+property=['\"]og:title['\"][^>]+content=['\"]([^'\"]+)['\"]", html_text
    )
    product.description = strip_tags(normalize_whitespace(payload.get("description") if payload else "")) or first_match(
        r"<meta[^>]+name=['\"]description['\"][^>]+content=['\"]([^'\"]+)['\"]", html_text
    )
    if YOTPO_APP_KEY not in html_text and "PUBLIC_YOTPO_KEY" not in html_text:
        product.page_error = "public_yotpo_key_not_seen_on_pdp"


def product_scope(product: ProductRecord) -> Tuple[bool, str]:
    text = normalize_whitespace(" ".join([product.title, product.handle, product.description, product.url]))
    if NON_OUTPUT_RE.search(text):
        return False, "outside_current_scope_accessory_mens_kids_or_non_clothing"
    if WOMENS_CLOTHING_RE.search(text):
        return True, ""
    return True, "spanx_apparel_default_in_scope"


def yotpo_reviews_url(product_id: str, page: int) -> str:
    return (
        f"https://api-cdn.yotpo.com/v1/widget/{YOTPO_APP_KEY}/products/{product_id}/reviews.json"
        f"?page={page}&per_page={YOTPO_PER_PAGE}&sort=images"
    )


def response_from_payload(payload: Dict[str, object]) -> Dict[str, object]:
    response = payload.get("response")
    return response if isinstance(response, dict) else {}


def custom_fields(review: Dict[str, object]) -> Dict[str, str]:
    mapped: Dict[str, str] = {}
    fields = review.get("custom_fields")
    if not isinstance(fields, dict):
        return mapped
    for field in fields.values():
        if not isinstance(field, dict):
            continue
        title = normalize_whitespace(field.get("title"))
        value = normalize_whitespace(field.get("value"))
        if title and value:
            mapped[title] = value
    return mapped


def image_urls_from_review(review: Dict[str, object]) -> List[str]:
    urls = []
    images = review.get("images_data") or review.get("images") or []
    if not isinstance(images, list):
        return urls
    for image in images:
        if not isinstance(image, dict):
            continue
        image_url = normalize_whitespace(image.get("original_url") or image.get("originalUrl") or image.get("url"))
        if image_url:
            urls.append(image_url)
    return list(dict.fromkeys(urls))


def comment_with_fields(review: Dict[str, object], fields: Dict[str, str]) -> Tuple[str, str]:
    title = normalize_whitespace(review.get("title"))
    body = normalize_whitespace(review.get("content"))
    additions = []
    for label in [
        "Size",
        "Sizing",
        "Length",
        "Height",
        "Body Type",
        "Purchased For",
        "Flattered my",
        "Waist",
        "Hips",
        "Bust",
    ]:
        if fields.get(label):
            additions.append(f"{label}: {fields[label]}")
    return title, normalize_whitespace(" ".join([body, " ".join(additions)]))


def size_from_fields(fields: Dict[str, str]) -> str:
    for label in ["Size", "Size Purchased", "Purchased Size"]:
        if fields.get(label):
            return normalize_ordered_size(fields[label])
    return ""


def context_for_product(product: ProductRecord) -> ProductContext:
    return ProductContext(
        url=product.url,
        title=product.title,
        description=product.description,
        brand="SPANX",
        product_id=product.product_id,
        handle=product.handle,
        shop_domain="spanx-com.myshopify.com",
        provider_hints="Yotpo",
    )


def fetch_yotpo_reviews(product: ProductRecord, max_review_pages: int) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    if not product.product_id:
        return [], {"pages_scanned": 0, "total_reviews_reported": 0, "error": "missing_shopify_product_id"}
    reviews: List[Dict[str, object]] = []
    pages_scanned = 0
    total = 0
    for page in range(1, 10000):
        if max_review_pages and page > max_review_pages:
            break
        payload = curl_fetch_json(yotpo_reviews_url(product.product_id, page), referer=product.url, retries=3)
        response = response_from_payload(payload)
        status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
        if status and status.get("code") not in {None, 200}:
            raise RuntimeError(f"yotpo_non_200_status product={product.url} status={status}")
        pagination = response.get("pagination") if isinstance(response.get("pagination"), dict) else {}
        total = int(pagination.get("total") or total or 0)
        page_reviews = response.get("reviews") if isinstance(response.get("reviews"), list) else []
        pages_scanned += 1
        reviews.extend([review for review in page_reviews if isinstance(review, dict)])
        total_pages = math.ceil(total / YOTPO_PER_PAGE) if total else page
        if page >= total_pages or len(page_reviews) < YOTPO_PER_PAGE:
            break
    return reviews, {"pages_scanned": pages_scanned, "total_reviews_reported": total}


def rows_from_reviews(product: ProductRecord, reviews: Sequence[Dict[str, object]], fetched_at: str) -> List[Dict[str, str]]:
    context = context_for_product(product)
    rows: List[Dict[str, str]] = []
    for review in reviews:
        image_urls = image_urls_from_review(review)
        if not image_urls:
            continue
        review_id = normalize_whitespace(review.get("id"))
        fields = custom_fields(review)
        title, body = comment_with_fields(review, fields)
        reviewer = review.get("user") if isinstance(review.get("user"), dict) else {}
        date_raw = normalize_whitespace(review.get("created_at"))
        for image_index, image_url in enumerate(image_urls, start=1):
            review_image = ReviewImage(
                image_url=image_url,
                review_id=f"spanx-yotpo-{review_id}-{image_index}" if review_id else "",
                review_title=title,
                review_body=body,
                reviewer_name=normalize_whitespace(reviewer.get("display_name") or reviewer.get("displayName")),
                date_raw=date_raw,
                review_date=review_date_from_raw(date_raw),
                size_raw=size_from_fields(fields),
                rating=normalize_whitespace(review.get("score")),
                extra={
                    "product_url": product.url,
                    "product_title": product.title,
                    "product_description": product.description,
                    "image_source_type": "customer_review_image",
                    "image_source_detail": normalize_whitespace(
                        f"public Yotpo product review image; yotpo_review_id={review_id}; rating={normalize_whitespace(review.get('score'))}"
                    ),
                },
            )
            rows.append(build_intake_row(context, review_image, fetched_at))
    return rows


def dedupe_spanx_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped = []
    seen = set()
    for row in rows:
        row_id = row.get("id", "")
        image_url = row.get("original_url_display", "")
        key = (row_id, image_url) if row_id.startswith("spanx-yotpo-") else (
            row.get("product_page_url_display", ""),
            image_url,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def summary_metrics(rows: Sequence[Dict[str, str]]) -> Dict[str, object]:
    metrics = validate_rows(rows)
    metrics["rows_with_customer_image"] = metrics["rows_with_customer_review_image"]
    metrics["rows_with_distinct_product_url"] = metrics["distinct_products"]
    metrics["rows_supabase_qualified"] = metrics["supabase_qualified_rows"]
    metrics["rows_with_any_measurement"] = sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS))
    metrics["rows_with_customer_ordered_size"] = sum(
        1 for row in rows if row.get("size_display") and row.get("size_display").lower() != "unknown"
    )
    return metrics


def write_summary(
    summary_json: Path,
    *,
    output_csv: Path,
    rows: Sequence[Dict[str, str]],
    started_at: str,
    finished_at: str,
    product_sources: Dict[str, object],
    products_discovered: int,
    products_scanned: int,
    products_excluded_from_output: int,
    review_pages_scanned: int,
    exhaustive_review_paging: bool,
    product_summaries: Sequence[Dict[str, object]],
    errors: Sequence[str],
) -> None:
    summary = {
        "site": SITE,
        "retailer": RETAILER,
        "adapter": "product_sitemap_pdp_yotpo_product_reviews",
        "yotpo_app_key": YOTPO_APP_KEY,
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": product_sources,
        "products_discovered": products_discovered,
        "products_scanned": products_scanned,
        "products_excluded_from_output": products_excluded_from_output,
        "review_pages_scanned": review_pages_scanned,
        "exhaustive_review_paging": exhaustive_review_paging,
        "product_summaries": list(product_summaries),
        "errors": list(errors),
        "access_policy": "public SPANX sitemap/product pages and public Yotpo product review JSON only; stop on 429/captcha/WAF/auth behavior.",
        "sovrn_triage_source": {
            "source_file": "data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv",
            "status": "first-pass candidate",
            "provider": "Yotpo",
            "photo_reviews": "yes",
            "shipping": "CA|GB|US",
            "estimated_commission_per_click": "$0.14",
        },
    }
    summary.update(summary_metrics(rows))
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    started_at = utc_now()
    fetched_at = started_at
    output_csv, summary_json = output_paths(RETAILER)
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []

    try:
        products_by_handle, product_sources = discover_products_from_sitemaps()
    except Exception as exc:
        errors.append(f"product_discovery_failed: {exc}")
        write_summary(
            summary_json,
            output_csv=output_csv,
            rows=[],
            started_at=started_at,
            finished_at=utc_now(),
            product_sources={},
            products_discovered=0,
            products_scanned=0,
            products_excluded_from_output=0,
            review_pages_scanned=0,
            exhaustive_review_paging=False,
            product_summaries=[],
            errors=errors,
        )
        return 2

    products = list(products_by_handle.values())
    products_discovered = len(products)
    if args.max_products:
        products = products[: args.max_products]

    review_pages_scanned = 0
    products_excluded_from_output = 0
    stopped_for_block = False

    for index, product in enumerate(products, start=1):
        try:
            hydrate_product_page(product)
            in_scope, skip_reason = product_scope(product)
            if in_scope:
                reviews, stats = fetch_yotpo_reviews(product, args.max_review_pages)
                product_rows = rows_from_reviews(product, reviews, fetched_at)
                rows.extend(product_rows)
            else:
                reviews = []
                stats = {"pages_scanned": 0, "total_reviews_reported": 0}
                product_rows = []
                products_excluded_from_output += 1
        except RuntimeError as exc:
            errors.append(str(exc))
            if re.search(r"blocked|rate_limited|captcha|challenge|403|429|503", str(exc), re.I):
                stopped_for_block = True
                break
            reviews = []
            stats = {"pages_scanned": 0, "total_reviews_reported": 0, "error": str(exc)}
            product_rows = []
            in_scope = False
            skip_reason = "product_fetch_or_review_fetch_failed"
        except Exception as exc:
            errors.append(f"product_failed product={product.url}: {exc}")
            reviews = []
            stats = {"pages_scanned": 0, "total_reviews_reported": 0, "error": str(exc)}
            product_rows = []
            in_scope = False
            skip_reason = "product_fetch_or_review_fetch_failed"

        review_pages_scanned += int(stats.get("pages_scanned") or 0)
        product_summaries.append(
            {
                "product_index": index,
                "product_url": product.url,
                "product_handle": product.handle,
                "shopify_product_id": product.product_id,
                "product_title": product.title,
                "source_names": sorted(product.source_names),
                "in_scope_for_output": in_scope,
                "skipped_from_output": not in_scope,
                "skip_reason": skip_reason,
                "reviews_reported_by_yotpo": stats.get("total_reviews_reported", 0),
                "review_pages_scanned": stats.get("pages_scanned", 0),
                "reviews_seen": len(reviews),
                "customer_review_image_rows": len(product_rows),
                "page_error": product.page_error,
            }
        )
        if index % 50 == 0:
            print(f"scanned {index}/{len(products)} products; rows={len(rows)}", file=sys.stderr, flush=True)
        if args.sleep:
            time.sleep(args.sleep)

    rows = dedupe_spanx_rows(dedupe_rows(rows))
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    write_summary(
        summary_json,
        output_csv=output_csv,
        rows=rows,
        started_at=started_at,
        finished_at=finished_at,
        product_sources=product_sources,
        products_discovered=products_discovered,
        products_scanned=len(product_summaries),
        products_excluded_from_output=products_excluded_from_output,
        review_pages_scanned=review_pages_scanned,
        exhaustive_review_paging=args.max_review_pages == 0 and not stopped_for_block,
        product_summaries=product_summaries,
        errors=errors,
    )
    print(str(output_csv))
    print(str(summary_json))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
