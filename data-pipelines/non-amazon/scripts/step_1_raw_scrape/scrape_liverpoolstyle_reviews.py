#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from typing import Dict, List
from urllib.parse import quote

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


SITE_ROOT = "https://liverpoolstyle.com"
DOMAIN = "liverpoolstyle.com"
KLAVIYO_COMPANY_ID = "JeMYJL"
KLAVIYO_API_ROOT = "https://fast.a.klaviyo.com/reviews/api"
KLAVIYO_IMAGE_ROOT = "https://klaviyo.s3.amazonaws.com/reviews/images"


def product_url(handle: str) -> str:
    return f"{SITE_ROOT}/products/{handle}"


def product_context(product: Dict[str, object]) -> ProductContext:
    handle = normalize_whitespace(product.get("handle"))
    title = normalize_whitespace(product.get("title"))
    product_type = normalize_whitespace(product.get("product_type"))
    vendor = normalize_whitespace(product.get("vendor")) or "Liverpool Los Angeles"
    description = strip_tags(product.get("body_html"))
    tags = product.get("tags") if isinstance(product.get("tags"), list) else []
    category = normalize_whitespace(" ".join(str(tag) for tag in tags if tag)) or product_type
    variants = product.get("variants") if isinstance(product.get("variants"), list) else []
    first_variant = variants[0] if variants and isinstance(variants[0], dict) else {}
    color = normalize_whitespace(first_variant.get("option2") or first_variant.get("option1"))
    variant = normalize_whitespace(first_variant.get("title"))
    return ProductContext(
        url=product_url(handle),
        title=title,
        description=description,
        category=category,
        brand=vendor,
        color=color,
        variant=variant,
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain="liverpool-jeans-company.myshopify.com",
        provider_hints="klaviyo",
        raw_html="",
    )


def discover_products() -> List[Dict[str, object]]:
    products: List[Dict[str, object]] = []
    seen_ids = set()
    for page in range(1, 10000):
        payload = fetch_json(f"{SITE_ROOT}/products.json?limit=250&page={page}", referer=SITE_ROOT)
        batch = payload.get("products") if isinstance(payload, dict) else []
        if not isinstance(batch, list) or not batch:
            break
        new_count = 0
        for product in batch:
            if not isinstance(product, dict):
                continue
            product_id = normalize_whitespace(product.get("id"))
            if product_id in seen_ids:
                continue
            seen_ids.add(product_id)
            products.append(product)
            new_count += 1
        print(f"[{DOMAIN} products.json page {page}] {new_count} new products", flush=True)
        if len(batch) < 250:
            break
    return products


def klaviyo_image_url(image_uuid: str) -> str:
    image_uuid = normalize_whitespace(image_uuid).lstrip("/")
    return f"{KLAVIYO_IMAGE_ROOT}/{image_uuid}"


def klaviyo_image_uuids(value: object) -> List[str]:
    text = normalize_whitespace(value)
    if not text:
        return []
    return [part.strip().lstrip("/") for part in text.split(",") if part.strip()]


def klaviyo_reviews_url(product_id: str, *, offset: int = 0, media: bool = True, limit: int = 50) -> str:
    media_value = "true" if media else "false"
    return (
        f"{KLAVIYO_API_ROOT}/client_reviews/{product_id}/"
        f"?product_id={product_id}&company_id={KLAVIYO_COMPANY_ID}"
        f"&limit={limit}&offset={offset}&sort=3&filter=&type=reviews&media={media_value}"
        "&kl_review_uuid=&preferred_country=US&tz=America%2FNew_York"
    )


def fetch_review_counts(product_ids: List[str]) -> Dict[str, Dict[str, object]]:
    counts: Dict[str, Dict[str, object]] = {}
    for index in range(0, len(product_ids), 50):
        chunk = product_ids[index : index + 50]
        encoded = quote(json.dumps(chunk, separators=(",", ":")))
        payload = fetch_json(
            f"{KLAVIYO_API_ROOT}/client_reviews/?company_id={KLAVIYO_COMPANY_ID}&products={encoded}",
            referer=SITE_ROOT,
        )
        for product in payload.get("products") or []:
            if isinstance(product, dict):
                shopify_id = normalize_whitespace(product.get("shopify_id") or product.get("external_id"))
                if shopify_id:
                    counts[shopify_id] = product
        print(f"[{DOMAIN} klaviyo counts {index + len(chunk)}/{len(product_ids)}]", flush=True)
        time.sleep(0.1)
    return counts


def answer_text(value: object) -> str:
    if isinstance(value, list):
        return normalize_whitespace(", ".join(str(item) for item in value if item is not None))
    return normalize_whitespace(value)


def review_body(review: Dict[str, object]) -> str:
    parts = [normalize_whitespace(review.get("content"))]
    question_answers = review.get("question_answers")
    if isinstance(question_answers, dict):
        for answer in question_answers.values():
            if not isinstance(answer, dict):
                continue
            label = normalize_whitespace(answer.get("label"))
            raw_answer = answer_text(answer.get("answer"))
            if label and raw_answer:
                parts.append(f"{label}: {raw_answer}")
    return normalize_whitespace(" ".join(part for part in parts if part))


def review_size(review: Dict[str, object]) -> str:
    variant = review.get("product_variant")
    if isinstance(variant, dict):
        title = normalize_whitespace(variant.get("title"))
        if title and title.lower() != "none":
            return title.split("/")[0].strip()
    return ""


def fetch_media_reviews(context: ProductContext) -> tuple[List[ReviewImage], int, int]:
    reviews: List[ReviewImage] = []
    pages_scanned = 0
    filtered_count = 0
    for offset in range(0, 10000, 50):
        payload = fetch_json(klaviyo_reviews_url(context.product_id, offset=offset), referer=context.url)
        pages_scanned += 1
        filtered_count = int(payload.get("filtered_count") or filtered_count or 0)
        batch = payload.get("reviews") or []
        if not isinstance(batch, list) or not batch:
            break
        for item in batch:
            if not isinstance(item, dict):
                continue
            image_uuids = klaviyo_image_uuids(item.get("image_uuid"))
            if not image_uuids:
                continue
            product = item.get("product") if isinstance(item.get("product"), dict) else {}
            handle = normalize_whitespace(product.get("handle") or product.get("shopify_handle") or context.handle)
            product_url_value = product_url(handle) if handle else context.url
            for image_index, image_uuid in enumerate(image_uuids, start=1):
                reviews.append(
                    ReviewImage(
                        image_url=klaviyo_image_url(image_uuid),
                        review_id=f"klaviyo-{normalize_whitespace(item.get('id'))}",
                        review_title=normalize_whitespace(item.get("title")),
                        review_body=review_body(item),
                        reviewer_name=normalize_whitespace(item.get("author")),
                        date_raw=normalize_whitespace(item.get("created_at")),
                        size_raw=review_size(item),
                        rating=normalize_whitespace(item.get("rating")),
                        extra={
                            "product_url": product_url_value,
                            "product_title": normalize_whitespace(product.get("name")) or context.title,
                            "product_description": context.description,
                            "product_category": context.category,
                            "product_variant": normalize_whitespace(
                                (item.get("product_variant") or {}).get("title")
                                if isinstance(item.get("product_variant"), dict)
                                else ""
                            ),
                        },
                    )
                )
        if not payload.get("has_more"):
            break
        time.sleep(0.1)
    return reviews, pages_scanned, filtered_count


def main() -> int:
    started_at = utc_now()
    products = discover_products()
    product_by_id = {normalize_whitespace(product.get("id")): product for product in products}
    review_counts = fetch_review_counts([product_id for product_id in product_by_id if product_id])
    product_summaries: List[Dict[str, object]] = []
    in_scope_count = 0
    out_of_scope_count = 0
    review_pages_scanned = 0
    products_with_reviews = 0
    total_public_reviews = 0
    rows: List[Dict[str, str]] = []
    errors: List[str] = []
    fetched_at = utc_now()
    for index, product in enumerate(products, start=1):
        context = product_context(product)
        clothing_type = classify_clothing_type(context)
        in_scope = bool(clothing_type)
        if in_scope:
            in_scope_count += 1
        else:
            out_of_scope_count += 1
        count_payload = review_counts.get(context.product_id, {})
        review_count = int(count_payload.get("review_count") or 0)
        if review_count:
            products_with_reviews += 1
            total_public_reviews += review_count
        product_reviews: List[ReviewImage] = []
        media_review_count = 0
        if in_scope and review_count:
            try:
                product_reviews, pages_scanned, media_review_count = fetch_media_reviews(context)
                review_pages_scanned += pages_scanned
            except Exception as exc:
                errors.append(f"{context.url}: klaviyo media reviews failed: {exc}")
        product_rows = [build_intake_row(context, review, fetched_at) for review in product_reviews if review.image_url]
        rows.extend(product_rows)
        product_summaries.append(
            {
                "product_url": context.url,
                "product_title": context.title,
                "shopify_product_id": context.product_id,
                "provider_hints": context.provider_hints,
                "adapter_used": "klaviyo-media" if in_scope and review_count else "klaviyo-counts-only",
                "public_review_count": review_count,
                "public_media_review_count": media_review_count,
                "matching_review_images": len(product_rows),
                "product_index": index,
                "clothing_type_id": clothing_type,
                "skipped_from_output": not in_scope,
                "skip_reason": "" if in_scope else "out_of_current_womens_clothing_scope_or_unclear_product_type",
            }
        )
        if index % 50 == 0:
            print(f"[{DOMAIN} klaviyo media {index}/{len(products)}] rows={len(rows)}", flush=True)
    rows = dedupe_rows(rows)
    output_csv, summary_json = output_paths(DOMAIN)
    write_intake_csv(rows, output_csv)
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
        adapter="shopify-products-json-catalog; klaviyo-media",
        product_summaries=product_summaries,
        errors=errors,
    )
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    payload.update(
        {
            "seed_url_count": 1,
            "seed_urls": [f"{SITE_ROOT}/products/kelsey-trouser-14"],
            "discovery_method": "shopify_products_json",
            "catalog_discovery_attempted": True,
            "product_sources": {
                "shopify_products_json": len(products),
                "klaviyo_client_reviews_batch_counts": len(review_counts),
            },
            "products_discovered": len(products),
            "product_pages_scanned": len(products),
            "products_with_public_reviews": products_with_reviews,
            "total_public_reviews_reported_by_klaviyo": total_public_reviews,
            "products_excluded_from_output": out_of_scope_count,
            "products_in_current_womens_clothing_scope": in_scope_count,
            "rows_with_distinct_product_url": payload.get("distinct_products", 0),
            "rows_with_customer_image": payload.get("rows_with_image_url", 0),
            "rows_supabase_qualified": payload.get("rows_with_image_product_size_and_measurement", 0),
            "scrape_scope_status": "full_catalog_attempted",
            "full_catalog_scrape_complete": True,
            "seed_scrape_only": False,
            "aggregate_feed_used": True,
            "review_pages_scanned": review_pages_scanned,
            "exhaustive_review_paging": True,
            "warnings": [
                "Liverpool Style uses Klaviyo Reviews; only reviews with public image_uuid media are written as Step 1 rows.",
                "Catalog/model images are not written to Step 1 because original_url_display must be a shopper/customer review image.",
            ],
        }
    )
    summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                DOMAIN: {
                    "output_csv": str(output_csv),
                    "summary_json": str(summary_json),
                    "products_discovered": len(products),
                    "products_in_scope": in_scope_count,
                    "products_excluded_from_output": out_of_scope_count,
                    "products_with_public_reviews": products_with_reviews,
                    "total_public_reviews": total_public_reviews,
                    "rows": len(rows),
                }
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
