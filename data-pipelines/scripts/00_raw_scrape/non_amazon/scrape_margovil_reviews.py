#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode, urljoin, urlparse

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    classify_clothing_type,
    dedupe_rows,
    fetch_json,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    write_intake_csv,
    write_summary,
)


SITE_ROOT = "https://www.margovil.com"
SHOP_DOMAIN = "margovil.myshopify.com"
BRAND = "Margovil"
PRODUCTS_PER_PAGE = 250
JUDGEME_WIDGET_URL = "https://api.judge.me/reviews/reviews_for_widget"


def build_url(url: str, params: Dict[str, object]) -> str:
    return f"{url}?{urlencode(params)}"


def unique(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        clean = normalize_whitespace(value)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def extract_attr(fragment: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}=['\"]([^'\"]*)['\"]", fragment, re.I)
    return normalize_whitespace(html.unescape(match.group(1))) if match else ""


def first_or_blank(patterns: Sequence[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return match.group(1)
    return ""


def split_review_blocks(html_text: str) -> List[str]:
    marker = r"<div[^>]+class=['\"][^'\"]*jdgm-rev\b"
    starts = [match.start() for match in re.finditer(marker, html_text, re.I)]
    blocks: List[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else min(len(html_text), start + 30000)
        blocks.append(html_text[start:end])
    return blocks


def product_url(handle: str) -> str:
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}"


def discover_products() -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    product_sources: List[Dict[str, object]] = []
    seen_handles = set()
    for page in range(1, 10000):
        api_url = f"{SITE_ROOT}/products.json?limit={PRODUCTS_PER_PAGE}&page={page}"
        payload = fetch_json(api_url, referer=SITE_ROOT, retries=3)
        batch = [item for item in payload.get("products", []) if isinstance(item, dict)]
        product_sources.append({"source": "products.json", "page": page, "count": len(batch)})
        if not batch:
            break
        for product in batch:
            handle = normalize_whitespace(product.get("handle"))
            if not handle or handle in seen_handles:
                continue
            seen_handles.add(handle)
            products.append(product)
        if len(batch) < PRODUCTS_PER_PAGE:
            break
        time.sleep(0.2)
    return products, product_sources


def context_from_product(product: Dict[str, object]) -> ProductContext:
    title = normalize_whitespace(product.get("title"))
    handle = normalize_whitespace(product.get("handle"))
    body_html = strip_tags(product.get("body_html"))
    tags = product.get("tags") if isinstance(product.get("tags"), list) else []
    category = normalize_whitespace(product.get("product_type") or " ".join(str(tag) for tag in tags))
    return ProductContext(
        url=product_url(handle),
        title=title,
        description=body_html,
        category=category,
        brand=normalize_whitespace(product.get("vendor")) or BRAND,
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=SHOP_DOMAIN,
        provider_hints="Judge.me",
    )


def is_margovil_womens_scope(context: ProductContext) -> bool:
    text = f"{context.title} {context.category} {context.url}".lower()
    if any(term in text for term in ["gift card", "shipping protection", "returns protection"]):
        return False
    return bool(classify_clothing_type(context))


def same_product_url(left: str, right: str) -> bool:
    left_parsed = urlparse(left)
    right_parsed = urlparse(right)
    left_path = left_parsed.path.rstrip("/")
    right_path = right_parsed.path.rstrip("/")
    return left_path == right_path and "/products/" in left_path


def parse_widget_html(widget_html: str, context: ProductContext) -> List[ReviewImage]:
    reviews: List[ReviewImage] = []
    for block in split_review_blocks(widget_html):
        review_id = extract_attr(block, "data-review-id")
        title = strip_tags(first_or_blank([r"<b[^>]+class=['\"][^'\"]*jdgm-rev__title[^'\"]*['\"][^>]*>(.*?)</b>"], block))
        body = strip_tags(first_or_blank([r"<div[^>]+class=['\"][^'\"]*jdgm-rev__body[^'\"]*['\"][^>]*>(.*?)</div>"], block))
        author = strip_tags(first_or_blank([r"<span[^>]+class=['\"][^'\"]*jdgm-rev__author[^'\"]*['\"][^>]*>(.*?)</span>"], block))
        date_raw = extract_attr(block, "data-content") or extract_attr(block, "data-created-at")
        size = ""
        for label, value in re.findall(
            r"jdgm-rev__cf-ans__title[^>]*>(.*?)</b>\s*<span[^>]+class=['\"][^'\"]*jdgm-rev__cf-ans__value[^'\"]*['\"][^>]*>(.*?)</span>",
            block,
            re.I | re.S,
        ):
            if "size" in strip_tags(label).lower():
                size = strip_tags(value)
                break

        product_url_from_review = ""
        product_title_from_review = ""
        product_match = re.search(
            r"<a\b(?=[^>]*class=['\"][^'\"]*jdgm-rev__prod-link[^'\"]*['\"])(?=[^>]*href=['\"]([^'\"]+)['\"])[^>]*>(.*?)</a>",
            block,
            re.I | re.S,
        )
        if product_match:
            product_url_from_review = normalize_whitespace(html.unescape(product_match.group(1)))
            if product_url_from_review.startswith("/"):
                product_url_from_review = urljoin(context.url, product_url_from_review)
            product_title_from_review = strip_tags(product_match.group(2))

        if product_url_from_review and not same_product_url(product_url_from_review, context.url):
            continue

        images = unique(
            html.unescape(match)
            for match in re.findall(
                r"(?:data-mfp-src|data-src|href|src)=['\"]([^'\"]+\.(?:jpg|jpeg|png|webp)(?:\?[^'\"]*)?)['\"]",
                block,
                re.I,
            )
            if "judgeme.imgix.net" in match
        )
        for image_url in images:
            reviews.append(
                ReviewImage(
                    image_url=image_url,
                    review_id=review_id,
                    review_title=title,
                    review_body=body,
                    reviewer_name=author,
                    date_raw=date_raw,
                    size_raw=size,
                    extra={
                        "product_url": context.url,
                        "product_title": product_title_from_review or context.title,
                        "product_description": context.description,
                        "product_category": context.category,
                    },
                )
            )
    return reviews


def scrape_judgeme_reviews(context: ProductContext) -> Tuple[List[ReviewImage], Optional[str], int]:
    if not context.product_id:
        return [], None, 0
    reviews: List[ReviewImage] = []
    seen = set()
    pages_scanned = 0
    params = {
        "url": urlparse(SITE_ROOT).netloc,
        "shop_domain": SHOP_DOMAIN,
        "platform": "shopify",
        "per_page": 20,
        "page": 1,
        "product_id": context.product_id,
        "sort_by": "with_pictures",
    }
    for page in range(1, 10000):
        params["page"] = page
        try:
            payload = fetch_json(build_url(JUDGEME_WIDGET_URL, params), referer=context.url, retries=2)
        except Exception as exc:
            return reviews, f"{context.url}: Judge.me widget failed: {exc}", pages_scanned
        pages_scanned += 1
        widget_html = html.unescape(str(payload.get("html") or ""))
        batch = parse_widget_html(widget_html, context)
        page_reviews = []
        for review in batch:
            key = (review.review_id, review.image_url)
            if key in seen:
                continue
            seen.add(key)
            page_reviews.append(review)
        reviews.extend(page_reviews)
        total_count = int(payload.get("total_count") or 0)
        if not page_reviews or page * int(params["per_page"]) >= total_count:
            break
        time.sleep(0.1)
    return reviews, None, pages_scanned


def scrape() -> Dict[str, object]:
    started_at = utc_now()
    products, product_sources = discover_products()
    fetched_at = utc_now()
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    review_pages_scanned = 0

    for index, product in enumerate(products, start=1):
        context = context_from_product(product)
        if not is_margovil_womens_scope(context):
            product_summaries.append(
                {
                    "product_url": context.url,
                    "product_title": context.title,
                    "provider_hints": context.provider_hints,
                    "adapter_used": "skipped-out-of-scope",
                    "matching_review_images": 0,
                    "product_index": index,
                    "skipped_from_output": True,
                    "skip_reason": "no women's clothing type matched title/category",
                }
            )
            print(f"[margovil.com {index}/{len(products)}] {context.title or context.url} -> skipped out of scope", flush=True)
            continue
        reviews, error, pages = scrape_judgeme_reviews(context)
        review_pages_scanned += pages
        if error:
            errors.append(error)
        product_rows = [build_intake_row(context, review, fetched_at) for review in reviews]
        rows.extend(product_rows)
        product_summaries.append(
            {
                "product_url": context.url,
                "product_title": context.title,
                "provider_hints": context.provider_hints,
                "adapter_used": "judgeme-product-widget",
                "matching_review_images": len(product_rows),
                "review_pages_scanned": pages,
                "product_index": index,
            }
        )
        print(f"[margovil.com {index}/{len(products)}] {context.title or context.url} -> {len(product_rows)} rows", flush=True)

    rows = dedupe_rows(rows)
    output_csv, summary_json = output_paths("margovil.com")
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    write_summary(
        summary_json,
        site=SITE_ROOT,
        retailer="margovil.com",
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=finished_at,
        products_scanned=len(products),
        adapter="judgeme-product-widget-no-aggregate-fallback",
        product_summaries=product_summaries,
        errors=errors,
    )
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    summary["product_sources"] = product_sources
    summary["products_discovered"] = len(products)
    summary["products_excluded_from_output"] = sum(1 for item in product_summaries if item.get("skipped_from_output"))
    summary["review_pages_scanned"] = review_pages_scanned
    summary["exhaustive_review_paging"] = True
    summary["aggregate_review_feed_used"] = False
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    summary = scrape()
    print(json.dumps({summary["retailer"]: summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
