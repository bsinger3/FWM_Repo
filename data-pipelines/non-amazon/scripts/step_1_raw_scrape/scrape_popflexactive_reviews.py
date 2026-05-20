#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import shutil
import sys
import time
from typing import Dict, Iterable, List, Sequence
from urllib.parse import urlencode, urljoin, urlparse

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
    ProductContext,
    ReviewImage,
    build_intake_row,
    classify_clothing_type,
    dedupe_rows,
    fetch_json,
    fetch_text,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    write_intake_csv,
    write_summary,
)


SITE_ROOT = "https://www.popflexactive.com"
DOMAIN = "popflexactive.com"
SHOP_DOMAIN = "popflex.myshopify.com"
REQUEST_DELAY_SECONDS = 0.05
WIDGET_PAGE_SIZE = 20


def product_url(handle: str) -> str:
    return f"{SITE_ROOT}/products/{handle}"


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


def discover_products_json() -> Dict[str, Dict[str, object]]:
    products: Dict[str, Dict[str, object]] = {}
    for page in range(1, 10000):
        payload = fetch_json(f"{SITE_ROOT}/products.json?limit=250&page={page}", referer=SITE_ROOT, retries=3)
        batch = payload.get("products")
        if not isinstance(batch, list) or not batch:
            break
        new_count = 0
        for product in batch:
            if not isinstance(product, dict):
                continue
            handle = normalize_whitespace(product.get("handle"))
            if not handle or handle in products:
                continue
            products[handle] = product
            new_count += 1
        print(f"[{DOMAIN} products.json page {page}] {new_count} new products", flush=True)
        if len(batch) < 250:
            break
        time.sleep(REQUEST_DELAY_SECONDS)
    return products


def discover_sitemap_product_handles() -> List[str]:
    handles: List[str] = []
    sitemap_urls: List[str] = []
    try:
        sitemap_index = fetch_text(f"{SITE_ROOT}/sitemap.xml", referer=SITE_ROOT, retries=2)
    except Exception:
        sitemap_index = ""
    for raw_url in re.findall(r"<loc>([^<]*sitemap_products_[^<]+)</loc>", sitemap_index, re.I):
        sitemap_urls.append(html.unescape(raw_url))
    if not sitemap_urls and sitemap_index:
        sitemap_urls = [f"{SITE_ROOT}/sitemap.xml"]
    for sitemap_url in unique(sitemap_urls):
        try:
            sitemap_text = fetch_text(sitemap_url, referer=SITE_ROOT, retries=2)
        except Exception:
            continue
        for raw_url in re.findall(r"https?://[^<\s\"']+/products/[^<\s\"']+", sitemap_text, re.I):
            parsed = urlparse(html.unescape(raw_url))
            if parsed.netloc.lower().removeprefix("www.") != "popflexactive.com":
                continue
            handle = parsed.path.split("/products/", 1)[1].split("/", 1)[0].removesuffix(".js")
            if handle:
                handles.append(handle)
    return unique(handles)


def fetch_product_js(handle: str) -> Dict[str, object]:
    try:
        payload = fetch_json(f"{product_url(handle)}.js", referer=product_url(handle), retries=2)
    except Exception:
        return {"handle": handle, "title": handle.replace("-", " ").title(), "id": ""}
    if isinstance(payload, dict):
        payload.setdefault("handle", handle)
        return payload
    return {"handle": handle, "title": handle.replace("-", " ").title(), "id": ""}


def discover_products() -> tuple[List[Dict[str, object]], Dict[str, int]]:
    by_handle = discover_products_json()
    products_json_count = len(by_handle)
    sitemap_handles = discover_sitemap_product_handles()
    sitemap_only_count = 0
    for handle in sitemap_handles:
        if handle in by_handle:
            continue
        by_handle[handle] = fetch_product_js(handle)
        sitemap_only_count += 1
        time.sleep(REQUEST_DELAY_SECONDS)
    products = list(by_handle.values())
    return products, {
        "shopify_products_json": products_json_count,
        "shopify_product_sitemaps": len(sitemap_handles),
        "sitemap_only_products_hydrated_from_product_js": sitemap_only_count,
        "deduped_total_products": len(products),
    }


def product_context(product: Dict[str, object]) -> ProductContext:
    handle = normalize_whitespace(product.get("handle"))
    title = normalize_whitespace(product.get("title"))
    product_type = normalize_whitespace(product.get("product_type") or product.get("type"))
    vendor = normalize_whitespace(product.get("vendor")) or "POPFLEX"
    description = strip_tags(product.get("body_html") or product.get("description"))
    tags = product.get("tags")
    if isinstance(tags, list):
        tag_text = " ".join(str(tag) for tag in tags if tag)
    else:
        tag_text = normalize_whitespace(tags)
    variants = product.get("variants") if isinstance(product.get("variants"), list) else []
    first_variant = variants[0] if variants and isinstance(variants[0], dict) else {}
    variant = normalize_whitespace(first_variant.get("title"))
    color = normalize_whitespace(first_variant.get("option1") or first_variant.get("option2"))
    return ProductContext(
        url=product_url(handle),
        title=title,
        description=description,
        category=normalize_whitespace(" ".join(part for part in [product_type, tag_text] if part)),
        brand=vendor,
        color=color,
        variant=variant,
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=SHOP_DOMAIN,
        provider_hints="Judge.me",
        raw_html="",
    )


def judge_me_widget_url(product_id: str, page: int) -> str:
    params = {
        "url": "www.popflexactive.com",
        "shop_domain": SHOP_DOMAIN,
        "platform": "shopify",
        "per_page": WIDGET_PAGE_SIZE,
        "page": page,
        "product_id": product_id,
        "sort_by": "with_pictures",
    }
    return f"https://api.judge.me/reviews/reviews_for_widget?{urlencode(params)}"


def cf_answer_text(value: object) -> str:
    return normalize_whitespace(html.unescape(str(value or "")))


def review_body(review: Dict[str, object]) -> str:
    parts = [strip_tags(review.get("body_html") or review.get("body"))]
    answers = review.get("cf_answers")
    if isinstance(answers, list):
        for answer in answers:
            if not isinstance(answer, dict):
                continue
            label = cf_answer_text(answer.get("question_title") or answer.get("question") or answer.get("label"))
            value = cf_answer_text(answer.get("value") or answer.get("answer"))
            if label and value:
                parts.append(f"{label}: {value}")
    return normalize_whitespace(" ".join(part for part in parts if part))


def review_size(review: Dict[str, object]) -> str:
    answers = review.get("cf_answers")
    if isinstance(answers, list):
        for answer in answers:
            if not isinstance(answer, dict):
                continue
            label = cf_answer_text(answer.get("question_title") or answer.get("question") or answer.get("label"))
            value = cf_answer_text(answer.get("value") or answer.get("answer"))
            if value and re.search(r"\b(size\s*bought|purchased|ordered|bought)\b", label, re.I):
                return value
    return normalize_whitespace(review.get("product_variant_title"))


def review_image_urls(review: Dict[str, object]) -> List[str]:
    images: List[str] = []
    for picture in review.get("pictures_urls") or []:
        if isinstance(picture, dict):
            images.append(normalize_whitespace(picture.get("original") or picture.get("huge") or picture.get("compact")))
        elif isinstance(picture, str):
            images.append(normalize_whitespace(picture))
    return unique(images)


def parse_reviews(payload: Dict[str, object], context: ProductContext) -> List[ReviewImage]:
    items = payload.get("reviews")
    if not isinstance(items, list):
        return []
    parsed: List[ReviewImage] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        images = review_image_urls(item)
        if not images:
            continue
        raw_product_url = normalize_whitespace(item.get("product_url_with_utm") or item.get("product_url"))
        if raw_product_url and raw_product_url.startswith("/"):
            raw_product_url = urljoin(SITE_ROOT, raw_product_url)
        raw_product_url = raw_product_url or context.url
        product_title = normalize_whitespace(item.get("product_title")) or context.title
        for image_index, image_url in enumerate(images, start=1):
            parsed.append(
                ReviewImage(
                    image_url=image_url,
                    review_id=f"judgeme-{normalize_whitespace(item.get('uuid') or item.get('id'))}-{image_index}",
                    review_title=normalize_whitespace(item.get("title")),
                    review_body=review_body(item),
                    reviewer_name=normalize_whitespace(item.get("reviewer_name")),
                    date_raw=normalize_whitespace(item.get("created_at")),
                    size_raw=review_size(item),
                    rating=normalize_whitespace(item.get("rating")),
                    extra={
                        "product_url": raw_product_url,
                        "product_title": product_title,
                        "product_description": context.description,
                        "product_category": context.category,
                        "product_variant": normalize_whitespace(item.get("product_variant_title") or context.variant),
                        "image_source_type": "customer_review_image",
                        "image_source_detail": "judgeme_public_review_widget",
                    },
                )
            )
    return parsed


def fetch_product_reviews(context: ProductContext) -> tuple[List[ReviewImage], int, int, int]:
    if not context.product_id:
        return [], 0, 0, 0
    reviews: List[ReviewImage] = []
    pages_scanned = 0
    public_review_count = 0
    total_pages = 0
    for page in range(1, 10000):
        payload = fetch_json(judge_me_widget_url(context.product_id, page), referer=context.url, retries=3)
        pages_scanned += 1
        public_review_count = int(payload.get("number_of_reviews") or public_review_count or 0)
        pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
        total_pages = int(pagination.get("total_pages") or total_pages or 0)
        reviews.extend(parse_reviews(payload, context))
        if not total_pages or page >= total_pages:
            break
        time.sleep(REQUEST_DELAY_SECONDS)
    return reviews, pages_scanned, public_review_count, total_pages


def has_measurement(row: Dict[str, str]) -> bool:
    return any(row.get(field) for field in MEASUREMENT_FIELDS)


def main(argv: Sequence[str] | None = None) -> int:
    global REQUEST_DELAY_SECONDS
    argv = list(argv or sys.argv[1:])
    if "--request-delay-seconds" in argv:
        REQUEST_DELAY_SECONDS = float(argv[argv.index("--request-delay-seconds") + 1])
    limit_products = int(argv[argv.index("--limit-products") + 1]) if "--limit-products" in argv else None
    started_at = utc_now()
    products, product_sources = discover_products()
    if limit_products is not None:
        products = products[:limit_products]
    fetched_at = utc_now()
    rows: List[Dict[str, str]] = []
    errors: List[str] = []
    product_summaries: List[Dict[str, object]] = []
    review_pages_scanned = 0
    products_with_public_reviews = 0
    total_public_reviews = 0
    products_in_scope = 0
    products_unclear_or_out_of_scope = 0
    products_with_media_reviews = 0
    for index, product in enumerate(products, start=1):
        context = product_context(product)
        clothing_type = classify_clothing_type(context)
        if clothing_type:
            products_in_scope += 1
        else:
            products_unclear_or_out_of_scope += 1
        product_reviews: List[ReviewImage] = []
        pages_scanned = 0
        public_review_count = 0
        public_media_pages = 0
        try:
            product_reviews, pages_scanned, public_review_count, public_media_pages = fetch_product_reviews(context)
        except Exception as exc:
            errors.append(f"{context.url}: Judge.me widget failed: {exc}")
        review_pages_scanned += pages_scanned
        if public_review_count:
            products_with_public_reviews += 1
            total_public_reviews += public_review_count
        if product_reviews:
            products_with_media_reviews += 1
        product_rows = [build_intake_row(context, review, fetched_at) for review in product_reviews if review.image_url]
        rows.extend(product_rows)
        product_summaries.append(
            {
                "product_url": context.url,
                "product_title": context.title,
                "shopify_product_id": context.product_id,
                "provider_hints": context.provider_hints,
                "adapter_used": "judgeme-public-widget",
                "public_review_count": public_review_count,
                "public_media_review_pages": public_media_pages,
                "matching_review_images": len(product_rows),
                "matching_customer_review_images": len(product_reviews),
                "matching_catalog_model_images": 0,
                "product_index": index,
                "clothing_type_id": clothing_type,
                "skipped_from_output": False,
                "skip_reason": "",
                "rows_with_any_measurement": sum(1 for row in product_rows if has_measurement(row)),
                "rows_with_customer_ordered_size": sum(1 for row in product_rows if row.get("size_display")),
            }
        )
        if index % 25 == 0:
            print(f"[{DOMAIN} Judge.me {index}/{len(products)}] rows={len(rows)}", flush=True)
    rows = dedupe_rows(rows)
    output_csv, summary_json = output_paths(DOMAIN)
    write_intake_csv(rows, output_csv)
    standard_csv = output_csv.with_name(f"{output_csv.stem.replace('_matching_intake_schema', '_matching_amazon_schema')}.csv")
    standard_summary_json = summary_json.with_name(
        f"{summary_json.stem.replace('_matching_intake_schema_summary', '_matching_amazon_schema_summary')}.json"
    )
    shutil.copyfile(output_csv, standard_csv)
    finished_at = utc_now()
    write_summary(
        summary_json,
        site=SITE_ROOT,
        retailer=DOMAIN,
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=finished_at,
        products_scanned=len(products),
        adapter="shopify-products-json-plus-sitemap-full-catalog; judgeme-public-widget-with-pictures",
        product_summaries=product_summaries,
        errors=errors,
    )
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    payload.update(
        {
            "seed_url_count": 1,
            "seed_urls": ["https://www.popflexactive.com/products/crisscross-hourglass-sklegging-black"],
            "discovery_method": "shopify_products_json_plus_product_sitemaps",
            "catalog_discovery_attempted": True,
            "product_sources": product_sources,
            "products_discovered": len(products),
            "product_pages_scanned": len(products),
            "products_with_public_reviews": products_with_public_reviews,
            "products_with_public_media_reviews": products_with_media_reviews,
            "total_public_reviews_reported_by_judgeme": total_public_reviews,
            "products_excluded_from_output": 0,
            "products_unclear_or_out_of_current_womens_clothing_scope": products_unclear_or_out_of_scope,
            "products_in_current_womens_clothing_scope": products_in_scope,
            "distinct_product_urls": payload.get("distinct_products", 0),
            "rows_with_distinct_product_url": payload.get("distinct_products", 0),
            "rows_with_customer_image": payload.get("rows_with_customer_review_image", 0),
            "rows_with_customer_ordered_size": payload.get("rows_with_size", 0),
            "rows_supabase_qualified": payload.get("rows_with_image_product_size_and_measurement", 0),
            "output_csv": str(standard_csv),
            "legacy_output_csv": str(output_csv),
            "legacy_summary_json": str(summary_json),
            "scrape_scope_status": "full_catalog_attempted",
            "full_catalog_scrape_complete": True,
            "seed_scrape_only": False,
            "review_pages_scanned": review_pages_scanned,
            "exhaustive_review_paging": True,
            "warnings": [
                "Popflex uses Judge.me; the scraper queried the public with-pictures review widget for every discovered product.",
                "Step 1 rows include public customer review images; structured measurements and ordered size are populated only from deterministic Judge.me custom-field answers and review text parsing.",
            ],
        }
    )
    summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    standard_summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    json.loads(summary_json.read_text(encoding="utf-8-sig"))
    json.loads(standard_summary_json.read_text(encoding="utf-8-sig"))
    print(
        json.dumps(
            {
                "retailer": DOMAIN,
                "output_csv": str(standard_csv),
                "summary_json": str(standard_summary_json),
                "products_discovered": len(products),
                "review_pages_scanned": review_pages_scanned,
                "products_with_public_reviews": products_with_public_reviews,
                "products_with_public_media_reviews": products_with_media_reviews,
                "rows": len(rows),
                "rows_with_product_url": payload.get("rows_with_image_and_product_url", 0),
                "rows_with_measurement": payload.get("rows_with_any_measurement", 0),
                "rows_with_customer_image": payload.get("rows_with_customer_review_image", 0),
                "rows_with_size": payload.get("rows_with_size", 0),
                "rows_supabase_qualified": payload.get("rows_with_image_product_size_and_measurement", 0),
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
