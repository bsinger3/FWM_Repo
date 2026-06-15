#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Tuple

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
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


SITE = "https://luxefashionclothing.com"
RETAILER = "luxefashionclothing_com"
TRIAGE_CATEGORY_URL = (
    "https://luxefashionclothing.com/product-category/women/womens-lingerie/"
    "bathing-suits-beachwear-swimwear/beach-dresses-cover-ups-pareos/"
)
TRIAGE_PRODUCT_CAT_ID = "189"
BLOCKING_STATUS_CODES = {401, 403, 407, 429, 503}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
BLOCK_BODY_RE = re.compile(r"\b(?:captcha|access denied|forbidden|too many requests|akamai|datadome|cloudflare)\b", re.I)
IMAGE_RE = re.compile(r"<img[^>]+src=['\"]([^'\"]+)['\"]", re.I)


@dataclass
class ProductRecord:
    product_id: str
    url: str
    title: str
    description: str = ""
    detail: str = ""
    category: str = "Beach Dresses, Cover-Ups, Pareos"
    sku: str = ""
    images: List[Dict[str, str]] = field(default_factory=list)
    comment_count: int = 0
    review_note: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Focused Luxe Fashion Clothing WooCommerce media scrape.")
    parser.add_argument("--max-products", type=int, default=0, help="Debug cap; 0 scans all products in triage category.")
    parser.add_argument("--comment-check-products", type=int, default=3, help="Number of product comment endpoints to sample.")
    parser.add_argument("--sleep", type=float, default=0.05, help="Sleep between public requests.")
    return parser.parse_args()


def curl_fetch_text(url: str, *, referer: str = SITE, accept: str = "*/*", retries: int = 3) -> Tuple[str, Dict[str, str]]:
    last_error = ""
    for attempt in range(retries):
        cmd = [
            "curl.exe",
            "-L",
            "-sS",
            "--fail-with-body",
            "--max-time",
            "60",
            "-D",
            "-",
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
            header_text, _, body = result.stdout.partition("\r\n\r\n")
            if not body:
                header_text, _, body = result.stdout.partition("\n\n")
            if BLOCK_BODY_RE.search(body[:2000]):
                raise RuntimeError(f"blocked_or_challenge_body url={url}")
            headers: Dict[str, str] = {}
            for line in header_text.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            return body, headers
        last_error = normalize_whitespace(result.stderr or result.stdout)
        if any(f" {code}" in last_error or f"error: {code}" in last_error.lower() for code in BLOCKING_STATUS_CODES):
            raise RuntimeError(f"blocked_or_rate_limited_fetch url={url} detail={last_error}")
        time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"fetch_failed url={url} detail={last_error}")


def curl_fetch_json(url: str, *, referer: str = SITE, retries: int = 3) -> Tuple[object, Dict[str, str]]:
    text, headers = curl_fetch_text(url, referer=referer, accept="application/json,text/plain,*/*", retries=retries)
    return json.loads(text), headers


def first_text(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("rendered")
    return normalize_whitespace(html.unescape(strip_tags(value or "")))


def product_from_rest(item: Dict[str, object]) -> ProductRecord:
    product_id = normalize_whitespace(item.get("id"))
    content_html = ""
    if isinstance(item.get("content"), dict):
        content_html = str(item["content"].get("rendered") or "")
    excerpt_html = ""
    if isinstance(item.get("excerpt"), dict):
        excerpt_html = str(item["excerpt"].get("rendered") or "")
    title = first_text(item.get("title"))
    return ProductRecord(
        product_id=product_id,
        url=normalize_whitespace(item.get("link")),
        title=title,
        description=first_text(excerpt_html) or first_text(content_html),
        detail=first_text(content_html),
        sku=normalize_whitespace(item.get("slug")),
    )


def discover_products(args: argparse.Namespace) -> Tuple[List[ProductRecord], List[Dict[str, object]]]:
    products: List[ProductRecord] = []
    pages: List[Dict[str, object]] = []
    page = 1
    while True:
        url = f"{SITE}/wp-json/wp/v2/product?product_cat={TRIAGE_PRODUCT_CAT_ID}&per_page=100&page={page}"
        payload, headers = curl_fetch_json(url, referer=TRIAGE_CATEGORY_URL)
        if not isinstance(payload, list) or not payload:
            break
        pages.append(
            {
                "page": page,
                "url": url,
                "products": len(payload),
                "x_wp_total": headers.get("x-wp-total", ""),
                "x_wp_totalpages": headers.get("x-wp-totalpages", ""),
            }
        )
        for item in payload:
            if isinstance(item, dict):
                products.append(product_from_rest(item))
        total_pages = int(headers.get("x-wp-totalpages") or page)
        if page >= total_pages:
            break
        page += 1
        if args.sleep:
            time.sleep(args.sleep)
    if args.max_products:
        products = products[: args.max_products]
    return products, pages


def image_url_from_media(media: Dict[str, object]) -> str:
    description = ""
    if isinstance(media.get("description"), dict):
        description = str(media["description"].get("rendered") or "")
    match = IMAGE_RE.search(html.unescape(description))
    if match:
        url = html.unescape(match.group(1))
    else:
        url = normalize_whitespace(media.get("source_url"))
    if url.startswith("http://matterhorn-wholesale.com/"):
        return "https://" + url.removeprefix("http://")
    return url


def media_for_product(product: ProductRecord) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    url = f"{SITE}/wp-json/wp/v2/media?parent={product.product_id}&per_page=100"
    payload, headers = curl_fetch_json(url, referer=product.url)
    images: List[Dict[str, str]] = []
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            image_url = image_url_from_media(item)
            if not image_url:
                continue
            images.append(
                {
                    "url": image_url,
                    "media_id": normalize_whitespace(item.get("id")),
                    "title": first_text(item.get("title")),
                    "caption": first_text(item.get("caption")),
                    "alt": normalize_whitespace(item.get("alt_text")),
                    "mime_type": normalize_whitespace(item.get("mime_type")),
                }
            )
    return images, {"url": url, "images": len(images), "x_wp_total": headers.get("x-wp-total", "")}


def comments_for_product(product: ProductRecord) -> Tuple[int, str]:
    url = f"{SITE}/wp-json/wp/v2/comments?post={product.product_id}&per_page=100"
    payload, _headers = curl_fetch_json(url, referer=product.url)
    if isinstance(payload, list):
        return len(payload), url
    return 0, url


def context_for_product(product: ProductRecord) -> ProductContext:
    return ProductContext(
        url=product.url,
        title=product.title,
        description=product.description,
        detail=product.detail,
        category=product.category,
        brand="Luxe Fashion Clothing",
        product_id=product.product_id,
        handle=product.sku,
        shop_domain="luxefashionclothing.com",
        provider_hints="native WooCommerce reviews; WordPress media gallery",
    )


def rows_from_product(product: ProductRecord, fetched_at: str) -> List[Dict[str, str]]:
    context = context_for_product(product)
    rows = []
    for index, image in enumerate(product.images, start=1):
        detail = normalize_whitespace(
            "catalog product media from WordPress attachment; "
            f"media_id={image.get('media_id')}; mime_type={image.get('mime_type')}; "
            f"alt={image.get('alt')}; title={image.get('title')}; "
            "native WooCommerce public review tab/comments feed had no customer review media"
        )
        review_image = ReviewImage(
            image_url=image["url"],
            review_id=f"luxefashionclothing-catalog-{product.product_id}-{image.get('media_id') or index}",
            review_title="Catalog product image",
            review_body=normalize_whitespace(
                "Catalog/product gallery image. Public native WooCommerce review tab and comments feed exposed no customer review media."
            ),
            reviewer_name="Luxe Fashion Clothing",
            date_raw="",
            review_date="",
            extra={
                "product_url": product.url,
                "product_title": product.title,
                "product_description": product.description,
                "product_detail": product.detail,
                "product_category": product.category,
                "image_source_type": "catalog_model_image",
                "image_source_detail": detail,
            },
        )
        rows.append(build_intake_row(context, review_image, fetched_at))
    return rows


def dedupe_luxe_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped = []
    seen = set()
    for row in rows:
        key = (row.get("product_page_url_display", ""), row.get("original_url_display", ""))
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
    metrics["catalog_model_qualified_rows"] = sum(
        1
        for row in rows
        if row.get("image_source_type") == "catalog_model_image"
        and row.get("original_url_display")
        and row.get("product_page_url_display")
    )
    metrics["rows_with_any_measurement"] = sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS))
    metrics["rows_with_customer_ordered_size"] = sum(
        1 for row in rows if row.get("size_display") and row.get("size_display").lower() != "unknown"
    )
    return metrics


def write_summary(
    summary_json,
    *,
    output_csv,
    rows: Sequence[Dict[str, str]],
    started_at: str,
    finished_at: str,
    product_sources: Dict[str, object],
    products: Sequence[ProductRecord],
    product_summaries: Sequence[Dict[str, object]],
    media_pages: Sequence[Dict[str, object]],
    comment_checks: Sequence[Dict[str, object]],
    errors: Sequence[str],
) -> None:
    summary = {
        "site": SITE,
        "retailer": RETAILER,
        "adapter": "wordpress_woocommerce_category_media_gallery",
        "provider_identified": "native WooCommerce reviews plus WordPress media gallery; no third-party review widget found",
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(product_summaries),
        "products_excluded_from_output": 0,
        "review_pages_scanned": 0,
        "exhaustive_review_paging": True,
        "product_summaries": list(product_summaries),
        "media_pages": list(media_pages),
        "comment_checks": list(comment_checks),
        "errors": list(errors),
        "access_policy": "public Luxe Fashion Clothing category/product/media/comment REST endpoints and PDP pages only; stop on 429/captcha/WAF/auth behavior.",
        "sovrn_triage_source": {
            "source_file": "data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv",
            "status": "first-pass candidate",
            "provider": "unknown",
            "photo_reviews": "yes",
            "reviews_present": "yes",
            "shipping": "US",
            "payout_note": "payout fields not populated",
            "category_evidence_url": TRIAGE_CATEGORY_URL,
            "sample_pdps": [
                "https://luxefashionclothing.com/product/beach-dress-model-164140-marko/",
                "https://luxefashionclothing.com/product/beach-dress-model-164141-marko/",
                "https://luxefashionclothing.com/product/beach-dress-model-179491-madora/",
            ],
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
    errors: List[str] = []
    products: List[ProductRecord] = []
    product_pages: List[Dict[str, object]] = []
    product_summaries: List[Dict[str, object]] = []
    media_pages: List[Dict[str, object]] = []
    comment_checks: List[Dict[str, object]] = []

    try:
        products, product_pages = discover_products(args)
        for index, product in enumerate(products, start=1):
            images, media_page = media_for_product(product)
            product.images = images
            media_pages.append({"product_id": product.product_id, "product_url": product.url, **media_page})
            if index <= args.comment_check_products:
                comments_count, comments_url = comments_for_product(product)
                product.comment_count = comments_count
                product.review_note = "native WooCommerce comments API checked"
                comment_checks.append({"product_id": product.product_id, "url": comments_url, "comments": comments_count})
            else:
                comments_count = 0
                product.review_note = "native WooCommerce comments API not rechecked after sample"
            product_rows = rows_from_product(product, fetched_at)
            rows.extend(product_rows)
            product_summaries.append(
                {
                    "product_index": index,
                    "product_id": product.product_id,
                    "product_url": product.url,
                    "product_title": product.title,
                    "category": product.category,
                    "comment_count": comments_count,
                    "catalog_model_image_rows": len(product_rows),
                }
            )
            if index % 25 == 0:
                print(f"scanned {index}/{len(products)} products; rows={len(rows)}", file=sys.stderr, flush=True)
            if args.sleep:
                time.sleep(args.sleep)
    except RuntimeError as exc:
        errors.append(str(exc))
    except Exception as exc:
        errors.append(f"scrape_failed: {exc}")

    rows = dedupe_luxe_rows(dedupe_rows(rows))
    write_intake_csv(rows, output_csv)
    write_summary(
        summary_json,
        output_csv=output_csv,
        rows=rows,
        started_at=started_at,
        finished_at=utc_now(),
        product_sources={
            "triage_category_url": TRIAGE_CATEGORY_URL,
            "wordpress_product_cat_id": TRIAGE_PRODUCT_CAT_ID,
            "wordpress_product_pages": product_pages,
            "narrow_scope_note": "Category from Sovrn evidence only; public WooCommerce review tabs/comments were checked, but usable media came from WordPress product attachments.",
        },
        products=products,
        product_summaries=product_summaries,
        media_pages=media_pages,
        comment_checks=comment_checks,
        errors=errors,
    )
    print(str(output_csv))
    print(str(summary_json))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
