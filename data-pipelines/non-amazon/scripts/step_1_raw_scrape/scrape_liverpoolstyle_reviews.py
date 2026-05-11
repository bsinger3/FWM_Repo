#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from typing import Dict, List, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
    ProductContext,
    ReviewImage,
    USER_AGENT,
    build_intake_row,
    classify_clothing_type,
    dedupe_rows,
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
REQUEST_DELAY_SECONDS = 0.75


class PressureStop(RuntimeError):
    pass


def fetch_json_public(url: str, *, referer: str = "", timeout: int = 45) -> Dict[str, object]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8-sig", errors="replace"))
    except HTTPError as exc:
        if exc.code in {401, 403, 407, 408, 409, 423, 429, 430, 503}:
            raise PressureStop(f"stopping on HTTP {exc.code} for {url}") from exc
        raise
    except URLError as exc:
        raise PressureStop(f"stopping on URL error for {url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON from {url}: {exc}") from exc


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
        payload = fetch_json_public(f"{SITE_ROOT}/products.json?limit=250&page={page}", referer=SITE_ROOT)
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
        time.sleep(REQUEST_DELAY_SECONDS)
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
        payload = fetch_json_public(
            f"{KLAVIYO_API_ROOT}/client_reviews/?company_id={KLAVIYO_COMPANY_ID}&products={encoded}",
            referer=SITE_ROOT,
        )
        for product in payload.get("products") or []:
            if isinstance(product, dict):
                shopify_id = normalize_whitespace(product.get("shopify_id") or product.get("external_id"))
                if shopify_id:
                    counts[shopify_id] = product
        print(f"[{DOMAIN} klaviyo counts {index + len(chunk)}/{len(product_ids)}]", flush=True)
        time.sleep(REQUEST_DELAY_SECONDS)
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
        payload = fetch_json_public(klaviyo_reviews_url(context.product_id, offset=offset), referer=context.url)
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
        time.sleep(REQUEST_DELAY_SECONDS)
    return reviews, pages_scanned, filtered_count


def product_image_urls(product: Dict[str, object]) -> List[str]:
    images = product.get("images") if isinstance(product.get("images"), list) else []
    urls: List[str] = []
    seen = set()
    for image in images:
        if not isinstance(image, dict):
            continue
        src = normalize_whitespace(image.get("src"))
        if not src or src in seen:
            continue
        seen.add(src)
        urls.append(src)
    return urls


def model_measurement_text(context: ProductContext) -> str:
    text = normalize_whitespace(" ".join([context.description, context.detail, context.category]))
    model_patterns = [
        r"(?:model|model\s+info|model\s+is|our\s+model|she\s+is)[^.]{0,220}(?:wearing|wears|size|height|waist|hips|bust|inseam)[^.]{0,220}",
        r"(?:wearing|wears)\s+(?:a\s+)?(?:size\s+)?[A-Za-z0-9/.\- ]{1,16}[^.]{0,180}(?:model|height|waist|hips|bust|inseam)[^.]{0,180}",
    ]
    matches = [match.group(0) for pattern in model_patterns for match in re.finditer(pattern, text, re.I)]
    return normalize_whitespace(" ".join(matches))


def has_measurement(row: Dict[str, str]) -> bool:
    return any(row.get(field) for field in MEASUREMENT_FIELDS)


def catalog_model_rows(product: Dict[str, object], context: ProductContext, fetched_at: str) -> List[Dict[str, str]]:
    comment = model_measurement_text(context)
    if not comment:
        return []
    rows: List[Dict[str, str]] = []
    for image_index, image_url in enumerate(product_image_urls(product), start=1):
        row = build_intake_row(
            context,
            ReviewImage(
                image_url=image_url,
                review_id=f"catalog-model-{context.product_id}-{image_index}",
                review_title="Catalog model image",
                review_body=comment,
                size_raw="",
                extra={
                    "image_source_type": "catalog_model_image",
                    "image_source_detail": "shopify_product_catalog_image_with_product_page_model_measurements",
                },
            ),
            fetched_at,
        )
        if row.get("size_display") and has_measurement(row):
            rows.append(row)
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    global REQUEST_DELAY_SECONDS
    argv = list(argv or sys.argv[1:])
    if "--request-delay-seconds" in argv:
        REQUEST_DELAY_SECONDS = float(argv[argv.index("--request-delay-seconds") + 1])
    limit_products = int(argv[argv.index("--limit-products") + 1]) if "--limit-products" in argv else None
    started_at = utc_now()
    stopped_for_pressure = False
    try:
        products = discover_products()
    except PressureStop as exc:
        products = []
        stopped_for_pressure = True
        print(str(exc), flush=True)
    if limit_products is not None:
        products = products[:limit_products]
    product_by_id = {normalize_whitespace(product.get("id")): product for product in products}
    errors: List[str] = []
    try:
        review_counts = fetch_review_counts([product_id for product_id in product_by_id if product_id]) if products else {}
    except PressureStop as exc:
        stopped_for_pressure = True
        review_counts = {}
        errors.append(str(exc))
    product_summaries: List[Dict[str, object]] = []
    in_scope_count = 0
    out_of_scope_count = 0
    review_pages_scanned = 0
    products_with_reviews = 0
    total_public_reviews = 0
    rows: List[Dict[str, str]] = []
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
            except PressureStop as exc:
                stopped_for_pressure = True
                errors.append(str(exc))
                break
            except Exception as exc:
                errors.append(f"{context.url}: klaviyo media reviews failed: {exc}")
        product_rows = [build_intake_row(context, review, fetched_at) for review in product_reviews if review.image_url]
        if in_scope:
            product_rows.extend(catalog_model_rows(product, context, fetched_at))
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
                "matching_customer_review_images": len(product_reviews),
                "matching_catalog_model_images": sum(1 for row in product_rows if row.get("image_source_type") == "catalog_model_image"),
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
            "distinct_product_urls": payload.get("distinct_products", 0),
            "rows_with_distinct_product_url": payload.get("distinct_products", 0),
            "rows_with_customer_image": payload.get("rows_with_customer_review_image", 0),
            "rows_supabase_qualified": payload.get("rows_with_image_product_size_and_measurement", 0),
            "output_csv": str(standard_csv),
            "legacy_output_csv": str(output_csv),
            "legacy_summary_json": str(summary_json),
            "scrape_scope_status": "full_catalog_attempted",
            "full_catalog_scrape_complete": True,
            "stopped_for_pressure": stopped_for_pressure,
            "seed_scrape_only": False,
            "aggregate_feed_used": True,
            "review_pages_scanned": review_pages_scanned,
            "exhaustive_review_paging": True,
            "warnings": [
                "Liverpool Style uses Klaviyo Reviews; only reviews with public image_uuid media are written as Step 1 rows.",
                "Catalog/model image rows are written only when public product-page/catalog text exposes model size plus measurements.",
            ],
            "access_policy": "public_product_and_review_pages_only; stop_immediately_on_429_captcha_or_waf_like_response",
        }
    )
    summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    standard_summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    json.loads(summary_json.read_text(encoding="utf-8-sig"))
    json.loads(standard_summary_json.read_text(encoding="utf-8-sig"))
    print(
        json.dumps(
            {
                DOMAIN: {
                    "output_csv": str(standard_csv),
                    "summary_json": str(standard_summary_json),
                    "products_discovered": len(products),
                    "products_in_scope": in_scope_count,
                    "products_excluded_from_output": out_of_scope_count,
                    "products_with_public_reviews": products_with_reviews,
                    "total_public_reviews": total_public_reviews,
                    "rows": len(rows),
                    "customer_review_rows": payload.get("rows_with_customer_review_image", 0),
                    "catalog_model_rows": payload.get("rows_with_catalog_model_image", 0),
                    "qualified_rows": payload.get("rows_with_image_product_size_and_measurement", 0),
                    "summary_json_readable_utf8_sig": True,
                }
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
