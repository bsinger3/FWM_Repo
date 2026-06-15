#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
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
    strip_tags,
    utc_now,
    write_intake_csv,
)


SITE = "https://www.selfieleslie.com"
RETAILER = "selfieleslie_com"
SHOP_DOMAIN = "selfieleslie-us.myshopify.com"
YOTPO_APP_KEY = "Inmz3p1Af2S6wKVjL5q5zBZ2V4J6Vc8npQvu5trG"
YOTPO_PER_PAGE = 100
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
BLOCKING_STATUS_CODES = {401, 403, 407, 429, 503}

WOMENS_CLOTHING_RE = re.compile(
    r"\b("
    r"dress(?:es)?|gowns?|jumpsuits?|rompers?|tops?|tees?|shirts?|blouses?|sweaters?|"
    r"cardigans?|jackets?|coats?|blazers?|skirts?|skorts?|shorts?|pants?|jeans?|"
    r"leggings?|sets?|bikinis?|swimsuits?|coverups?|bodysuits?"
    r")\b",
    re.I,
)
NON_OUTPUT_RE = re.compile(
    r"\b("
    r"gift\s*cards?|sunglasses?|bags?|belts?|earrings?|rings?|necklaces?|bracelets?|"
    r"heels?|sandals?|shoes?|boots?|slippers?|hats?|caps?|hair\s*clips?"
    r")\b",
    re.I,
)


@dataclass
class ProductRecord:
    url: str
    handle: str
    product_id: str = ""
    yotpo_id: str = ""
    title: str = ""
    vendor: str = ""
    product_type: str = ""
    tags: List[str] = field(default_factory=list)
    description: str = ""
    variant: str = ""
    color: str = ""
    source_names: set[str] = field(default_factory=set)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Selfie Leslie public Yotpo review images.")
    parser.add_argument("--max-review-pages", type=int, default=0, help="Debug cap; 0 scans all Yotpo pages.")
    parser.add_argument("--sleep", type=float, default=0.02, help="Sleep between public requests.")
    return parser.parse_args()


def curl_fetch_text(url: str, *, referer: str = SITE, accept: str = "*/*", retries: int = 3) -> str:
    last_error = ""
    for attempt in range(retries):
        cmd = [
            "curl",
            "-L",
            "-sS",
            "--fail-with-body",
            "--max-time",
            "60",
            "-A",
            USER_AGENT,
            "-H",
            f"Accept: {accept}",
        ]
        if referer:
            cmd.extend(["-e", referer])
        cmd.append(url)
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode == 0:
            return result.stdout
        last_error = normalize_whitespace(result.stderr or result.stdout)
        if any(f" {code}" in last_error or f"error: {code}" in last_error.lower() for code in BLOCKING_STATUS_CODES):
            raise RuntimeError(f"blocked_or_rate_limited_fetch url={url} detail={last_error}")
        time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"fetch_failed url={url} detail={last_error}")


def curl_fetch_json(url: str, *, referer: str = SITE, retries: int = 3) -> Dict[str, object]:
    return json.loads(curl_fetch_text(url, referer=referer, accept="application/json,text/plain,*/*", retries=retries))


def color_from_product(title: str, tags: Iterable[str], variant: str = "") -> str:
    for tag in tags:
        if tag.lower().startswith("color:"):
            return normalize_whitespace(tag.split(":", 1)[1]).title()
    tokens = normalize_whitespace(f"{title} {variant}").split()
    if tokens:
        tail = " ".join(tokens[-2:])
        if not re.search(r"\b(dress|romper|top|skirt|bottom|set|gown|jumpsuit)\b", tail, re.I):
            return tail.title()
        return tokens[-1].title()
    return ""


def product_from_shopify(item: Dict[str, object], source_name: str) -> Optional[ProductRecord]:
    handle = normalize_whitespace(item.get("handle"))
    if not handle:
        return None
    tags_raw = item.get("tags")
    tags = [normalize_whitespace(tag) for tag in tags_raw if normalize_whitespace(tag)] if isinstance(tags_raw, list) else []
    variants = item.get("variants") if isinstance(item.get("variants"), list) else []
    variant = ""
    if variants and isinstance(variants[0], dict):
        variant = normalize_whitespace(variants[0].get("title"))
    title = normalize_whitespace(item.get("title"))
    return ProductRecord(
        url=f"{SITE}/products/{handle}",
        handle=handle,
        product_id=normalize_whitespace(item.get("id")),
        title=title,
        vendor=normalize_whitespace(item.get("vendor")),
        product_type=normalize_whitespace(item.get("product_type") or item.get("type")),
        tags=tags,
        description=strip_tags(item.get("body_html") or item.get("description") or ""),
        variant=variant,
        color=color_from_product(title, tags, variant),
        source_names={source_name},
    )


def merge_product(target: ProductRecord, incoming: ProductRecord) -> None:
    target.source_names.update(incoming.source_names)
    for attr in ["product_id", "yotpo_id", "title", "vendor", "product_type", "description", "variant", "color"]:
        if not getattr(target, attr) and getattr(incoming, attr):
            setattr(target, attr, getattr(incoming, attr))
    if not target.tags and incoming.tags:
        target.tags = incoming.tags


def discover_products_json() -> Tuple[Dict[str, ProductRecord], List[Dict[str, object]]]:
    products: Dict[str, ProductRecord] = {}
    pages: List[Dict[str, object]] = []
    for page in range(1, 10000):
        url = f"{SITE}/products.json?limit=250&page={page}"
        try:
            payload = curl_fetch_json(url)
        except RuntimeError as exc:
            pages.append({"page": page, "url": url, "products": 0, "error": str(exc)})
            break
        items = payload.get("products") if isinstance(payload, dict) else []
        if not isinstance(items, list) or not items:
            pages.append({"page": page, "url": url, "products": 0})
            break
        pages.append({"page": page, "url": url, "products": len(items)})
        for item in items:
            if not isinstance(item, dict):
                continue
            record = product_from_shopify(item, "products_json")
            if not record:
                continue
            existing = products.get(record.handle)
            if existing:
                merge_product(existing, record)
            else:
                products[record.handle] = record
        if len(items) < 250:
            break
    return products, pages


def sitemap_urls() -> List[str]:
    xml = curl_fetch_text(f"{SITE}/sitemap.xml", accept="application/xml,text/xml,*/*")
    root = ET.fromstring(xml)
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [normalize_whitespace(node.text) for node in root.findall(".//sm:loc", namespace) if node.text]


def discover_sitemap_products(existing: Dict[str, ProductRecord]) -> List[Dict[str, object]]:
    source_pages: List[Dict[str, object]] = []
    product_sitemaps = [url for url in sitemap_urls() if "sitemap_products_" in url]
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    for sitemap_url in product_sitemaps:
        xml = curl_fetch_text(sitemap_url.replace("&amp;", "&"), accept="application/xml,text/xml,*/*")
        root = ET.fromstring(xml)
        product_urls = [
            normalize_whitespace(node.text)
            for node in root.findall(".//sm:url/sm:loc", namespace)
            if node.text and "/products/" in node.text
        ]
        source_pages.append({"url": sitemap_url.replace("&amp;", "&"), "products": len(product_urls)})
        for product_url in product_urls:
            handle = product_url.split("/products/", 1)[1].split("/", 1)[0]
            if not handle:
                continue
            record = ProductRecord(
                url=canonical_product_url(product_url),
                handle=handle,
                source_names={"sitemap"},
            )
            existing_record = existing.get(handle)
            if existing_record:
                merge_product(existing_record, record)
            else:
                existing[handle] = record
    return source_pages


def is_in_scope_product(product: ProductRecord) -> bool:
    haystack = " ".join([product.title, product.product_type, product.description, " ".join(product.tags), product.url])
    return bool(WOMENS_CLOTHING_RE.search(haystack)) and not bool(NON_OUTPUT_RE.search(haystack))


def yotpo_reviews_url(page: int) -> str:
    return (
        f"https://api.yotpo.com/v1/widget/{YOTPO_APP_KEY}/reviews.json"
        f"?page={page}&per_page={YOTPO_PER_PAGE}&sort=images"
    )


def response_from_payload(payload: Dict[str, object]) -> Dict[str, object]:
    response = payload.get("response")
    return response if isinstance(response, dict) else {}


def yotpo_custom_fields(review: Dict[str, object]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    custom_fields = review.get("custom_fields") if isinstance(review.get("custom_fields"), dict) else {}
    for field in custom_fields.values():
        if not isinstance(field, dict):
            continue
        title = normalize_whitespace(field.get("title")).lower()
        value = normalize_whitespace(field.get("value"))
        if title and value:
            values[title] = value
    return values


def media_urls(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    images = review.get("images_data") or review.get("images") or []
    if not isinstance(images, list):
        return urls
    for image in images:
        if not isinstance(image, dict):
            continue
        image_url = normalize_whitespace(image.get("original_url") or image.get("url") or image.get("thumb_url"))
        if image_url and image_url not in urls:
            urls.append(image_url)
    return urls


def context_for_product(product: ProductRecord) -> ProductContext:
    return ProductContext(
        url=product.url,
        title=product.title,
        description=product.description,
        category=product.product_type,
        brand=product.vendor or "Selfie Leslie",
        color=product.color,
        variant=product.variant,
        product_id=product.product_id,
        handle=product.handle,
        shop_domain=SHOP_DOMAIN,
        provider_hints="Yotpo public aggregate review feed",
    )


def augment_comment(title: str, body: str, fields: Dict[str, str]) -> str:
    extras = []
    for key in ["height", "weight", "fit"]:
        if fields.get(key):
            extras.append(f"{key.title()}: {fields[key]}.")
    return normalize_whitespace(" ".join([title, body, *extras]))


def scrape_reviews(
    products_by_shopify_id: Dict[str, ProductRecord],
    args: argparse.Namespace,
    fetched_at: str,
) -> Tuple[List[Dict[str, str]], List[Dict[str, object]], List[Dict[str, object]], int, int]:
    first_payload = curl_fetch_json(yotpo_reviews_url(1))
    first_response = response_from_payload(first_payload)
    pagination = first_response.get("pagination") if isinstance(first_response.get("pagination"), dict) else {}
    total_reviews = int(pagination.get("total") or 0)
    total_pages = math.ceil(total_reviews / YOTPO_PER_PAGE) if total_reviews else 1
    if args.max_review_pages:
        total_pages = min(total_pages, args.max_review_pages)

    rows: List[Dict[str, str]] = []
    review_pages: List[Dict[str, object]] = []
    product_counts: Dict[str, int] = {}
    yotpo_to_product: Dict[str, ProductRecord] = {}
    distinct_reviews_with_images = set()
    seen = set()

    for page in range(1, total_pages + 1):
        payload = first_payload if page == 1 else curl_fetch_json(yotpo_reviews_url(page))
        response = response_from_payload(payload)
        products = response.get("products") if isinstance(response.get("products"), list) else []
        for item in products:
            if not isinstance(item, dict):
                continue
            yotpo_id = normalize_whitespace(item.get("id"))
            shopify_id = normalize_whitespace(item.get("domain_key"))
            product = products_by_shopify_id.get(shopify_id)
            if product and yotpo_id:
                product.yotpo_id = yotpo_id
                yotpo_to_product[yotpo_id] = product

        page_reviews = response.get("reviews") if isinstance(response.get("reviews"), list) else []
        page_image_rows = 0
        for review in page_reviews:
            if not isinstance(review, dict):
                continue
            review_id = normalize_whitespace(review.get("id"))
            product = yotpo_to_product.get(normalize_whitespace(review.get("product_id")))
            image_urls = media_urls(review)
            if not product or not image_urls:
                continue
            distinct_reviews_with_images.add(review_id)
            if not is_in_scope_product(product):
                continue
            fields = yotpo_custom_fields(review)
            size = normalize_ordered_size(fields.get("size") or "")
            reviewer = review.get("user") if isinstance(review.get("user"), dict) else {}
            comment = augment_comment(
                normalize_whitespace(review.get("title")),
                normalize_whitespace(review.get("content")),
                fields,
            )
            context = context_for_product(product)
            for image_index, image_url in enumerate(image_urls, start=1):
                stable_key = (review_id, image_url)
                if stable_key in seen:
                    continue
                seen.add(stable_key)
                review_image = ReviewImage(
                    image_url=image_url,
                    review_id=f"selfieleslie-yotpo-{review_id}-{image_index}",
                    review_title="",
                    review_body=comment,
                    reviewer_name=normalize_whitespace(reviewer.get("display_name")),
                    date_raw=normalize_whitespace(review.get("created_at")),
                    size_raw=size,
                    rating=normalize_whitespace(review.get("score")),
                    extra={
                        "image_source_type": "customer_review_image",
                        "image_source_detail": "public Yotpo aggregate review image",
                    },
                )
                rows.append(build_intake_row(context, review_image, fetched_at))
                product_counts[product.url] = product_counts.get(product.url, 0) + 1
                page_image_rows += 1
        review_pages.append(
            {
                "page": page,
                "reviews": len(page_reviews),
                "image_rows_retained": page_image_rows,
                "url": yotpo_reviews_url(page),
            }
        )
        print(f"[selfieleslie yotpo aggregate page {page}/{total_pages}] -> {page_image_rows} image rows", flush=True)
        time.sleep(args.sleep)

    product_summaries = [
        {
            "product_url": product.url,
            "product_title": product.title,
            "shopify_product_id": product.product_id,
            "yotpo_product_id": product.yotpo_id,
            "adapter_used": "yotpo_aggregate_sort_images",
            "matching_review_images": product_counts.get(product.url, 0),
            "skipped_from_output": not is_in_scope_product(product),
            "skip_reason": "" if is_in_scope_product(product) else "not_womens_clothing_scope_or_accessory",
        }
        for product in sorted(products_by_shopify_id.values(), key=lambda item: item.url)
    ]
    return rows, product_summaries, review_pages, total_reviews, len(distinct_reviews_with_images)


def summarize(rows: List[Dict[str, str]], products: Dict[str, ProductRecord]) -> Dict[str, int]:
    product_urls = {row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}
    return {
        "products_discovered": len(products),
        "products_scanned": len(products),
        "products_excluded_from_output": sum(1 for product in products.values() if not is_in_scope_product(product)),
        "rows_written": len(rows),
        "distinct_reviews": len({row.get("id", "").rsplit("-", 1)[0] for row in rows if row.get("id")}),
        "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
        "rows_with_distinct_product_url": len(product_urls),
        "rows_with_any_measurement": sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS)),
        "rows_with_customer_image": sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image"),
        "rows_with_customer_ordered_size": sum(1 for row in rows if row.get("size_display") and row.get("size_display") != "unknown"),
        "rows_supabase_qualified": sum(
            1
            for row in rows
            if row.get("original_url_display")
            and row.get("product_page_url_display")
            and row.get("size_display")
            and row.get("size_display") != "unknown"
            and any(row.get(field) for field in MEASUREMENT_FIELDS)
        ),
    }


def main() -> int:
    args = parse_args()
    started_at = utc_now()
    fetched_at = started_at

    products, products_json_pages = discover_products_json()
    sitemap_pages = discover_sitemap_products(products)
    products_by_shopify_id = {product.product_id: product for product in products.values() if product.product_id}
    rows, product_summaries, review_pages, total_reviews, distinct_reviews_with_images = scrape_reviews(
        products_by_shopify_id,
        args,
        fetched_at,
    )
    rows = dedupe_rows(rows)

    output_csv, summary_json = output_paths(RETAILER)
    write_intake_csv(rows, output_csv)
    metrics = summarize(rows, products)
    summary = {
        "site": SITE,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_sitemap_yotpo_aggregate_reviews",
        "yotpo_app_key": YOTPO_APP_KEY,
        "shop_domain": SHOP_DOMAIN,
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": utc_now(),
        "product_sources": {
            "products_json_pages": products_json_pages,
            "sitemap_product_pages": sitemap_pages,
            "unique_product_urls": len(products),
        },
        "review_pages_scanned": len(review_pages),
        "reviews_reported_by_yotpo": total_reviews,
        "distinct_media_reviews_seen_before_scope_filter": distinct_reviews_with_images,
        "exhaustive_review_paging": args.max_review_pages == 0,
        "review_paging_note": "Scanned every public Yotpo aggregate review page with sort=images; retained customer-image rows only.",
        "product_summaries": product_summaries,
        "review_pages": review_pages,
        "access_policy": "public Shopify catalog/sitemap and public Yotpo widget API only; no auth, captcha, or WAF bypass.",
        **metrics,
    }
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ["output_csv", "rows_written", "rows_supabase_qualified"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
