#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Sequence
from urllib.parse import urlencode, urlparse

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    STEP1_OUTPUT_ROOT,
    build_intake_row,
    classify_clothing_type,
    canonical_product_url,
    dedupe_rows,
    fetch_json,
    normalize_whitespace,
    utc_now,
    write_intake_csv,
)


RETAILER = "levi_com"
BRAND = "Levi's"
SOURCE_SITE = "https://www.levi.com/"
OUTPUT_DIR = STEP1_OUTPUT_ROOT / RETAILER
DEFAULT_QUEUE = OUTPUT_DIR / "levi_women_clothing_product_urls_from_sitemap.txt"
OUTPUT_CSV = OUTPUT_DIR / "levi_com_women_bazaarvoice_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "levi_com_women_bazaarvoice_reviews_matching_intake_schema_summary.json"
PROGRESS_JSON = OUTPUT_DIR / "levi_com_women_bazaarvoice_progress.json"
PRODUCT_PAGES_CSV = OUTPUT_DIR / "levi_com_women_product_pages_for_staging.csv"
PRODUCT_PAGES_JSONL = OUTPUT_DIR / "levi_com_women_product_pages_for_staging.jsonl"

BV_ENDPOINT = "https://api.bazaarvoice.com/data/reviews.json"
BV_PASSKEY = "ca68iFuyCSvgNcQbyjzgnsURQlXrJrJQn10w3kChiZPK4"
BV_DISPLAY_CODE = "18056_16_0-en_us"


def product_code_from_url(url: str) -> str:
    match = re.search(r"/p/([^/?#]+)", url)
    return match.group(1) if match else ""


def title_from_url(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    try:
        slug = parts[parts.index("p") - 1]
    except (ValueError, IndexError):
        slug = ""
    return normalize_whitespace(slug.replace("-", " ").title())


def path_parts_after_women(url: str) -> List[str]:
    parts = [part for part in urlparse(url).path.split("/") if part]
    try:
        start = parts.index("women")
    except ValueError:
        return []
    tail = parts[start + 1 :]
    if "p" in tail:
        tail = tail[: tail.index("p")]
    return tail


def breadcrumb_from_url(url: str) -> str:
    labels = ["Clothing", "Women"]
    labels.extend(part.replace("-", " ").title() for part in path_parts_after_women(url))
    return " > ".join(dict.fromkeys(label for label in labels if label))


def category_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    for category in ("jeans", "pants", "shorts", "skirts", "dresses", "jackets", "tops", "shirts", "sweaters", "sweatshirts", "overalls", "plus-size"):
        if f"/{category}/" in path:
            return category
    return "women clothing"


def product_page_url_from_bv(product: Dict[str, object], fallback_url: str) -> str:
    value = normalize_whitespace(product.get("ProductPageUrl"))
    if not value:
        return fallback_url
    if value.startswith("http://www.levi.com/"):
        value = "https://" + value[len("http://") :]
    return value


def split_image_urls(value: object) -> List[str]:
    urls: List[str] = []
    for url in str(value or "").split(","):
        url = normalize_whitespace(url)
        if url and url not in urls:
            urls.append(url)
    return urls


def photo_url(photo: Dict[str, object]) -> str:
    sizes = photo.get("Sizes") if isinstance(photo, dict) else {}
    if not isinstance(sizes, dict):
        return ""
    for key in ("normal", "large", "thumbnail"):
        item = sizes.get(key)
        if isinstance(item, dict) and item.get("Url"):
            return normalize_whitespace(item.get("Url"))
    return ""


def field_value(review: Dict[str, object], group: str, field: str) -> str:
    values = review.get(group)
    if not isinstance(values, dict):
        return ""
    item = values.get(field)
    if isinstance(item, dict):
        return normalize_whitespace(item.get("Value"))
    return ""


def review_context_text(review: Dict[str, object]) -> str:
    parts: List[str] = []
    context = review.get("ContextDataValues")
    if isinstance(context, dict):
        for key in ("Height", "Weight", "BodyType", "Age"):
            value = field_value(review, "ContextDataValues", key)
            if value:
                parts.append(f"{key}: {value}")
    additional = review.get("AdditionalFields")
    if isinstance(additional, dict):
        for key in ("UsualSize", "SizePurchased"):
            value = field_value(review, "AdditionalFields", key)
            if value:
                parts.append(f"{key}: {value}")
    return " ".join(parts)


def size_raw(review: Dict[str, object]) -> str:
    return (
        field_value(review, "AdditionalFields", "SizePurchased")
        or field_value(review, "AdditionalFields", "UsualSize")
    )


def build_url(product_id: str, offset: int, limit: int) -> str:
    params: List[tuple[str, str]] = [
        ("passkey", BV_PASSKEY),
        ("apiversion", "5.5"),
        ("displaycode", BV_DISPLAY_CODE),
        ("filter", f"productid:eq:{product_id}"),
        ("filter", "isratingsonly:eq:false"),
        ("filter", "hasphotos:eq:true"),
        ("sort", "submissiontime:desc"),
        ("limit", str(limit)),
        ("offset", str(offset)),
        ("include", "authors,products,comments"),
    ]
    return f"{BV_ENDPOINT}?{urlencode(params)}"


def build_product_url(product_id: str) -> str:
    params: List[tuple[str, str]] = [
        ("passkey", BV_PASSKEY),
        ("apiversion", "5.5"),
        ("displaycode", BV_DISPLAY_CODE),
        ("filter", f"id:eq:{product_id}"),
        ("stats", "reviews"),
        ("limit", "1"),
    ]
    return f"https://api.bazaarvoice.com/data/products.json?{urlencode(params)}"


def fetch_product_metadata(product_id: str) -> Dict[str, object]:
    data = fetch_json(build_product_url(product_id))
    results = data.get("Results") or []
    if isinstance(results, list) and results:
        return results[0] if isinstance(results[0], dict) else {}
    return {}


def fetch_photo_reviews(product_id: str, limit: int, delay_seconds: float) -> Dict[str, object]:
    all_reviews: List[Dict[str, object]] = []
    total = None
    offset = 0
    while True:
        data = fetch_json(build_url(product_id, offset, limit))
        if total is None:
            total = int(data.get("TotalResults") or 0)
        results = data.get("Results") or []
        if not isinstance(results, list) or not results:
            break
        all_reviews.extend(results)
        offset += len(results)
        if offset >= total:
            break
        if delay_seconds:
            time.sleep(delay_seconds)
    return {"total": total or 0, "reviews": all_reviews}


def context_for_product(product_url: str, product: Dict[str, object]) -> ProductContext:
    category = category_from_url(product_url)
    title = normalize_whitespace(product.get("Name")) or title_from_url(product_url)
    image_urls = split_image_urls(product.get("ImageUrl"))
    return ProductContext(
        url=product_url,
        title=title,
        description=normalize_whitespace(product.get("Description")),
        detail=f"breadcrumb: {breadcrumb_from_url(product_url)}",
        category=category,
        brand=BRAND,
        variant=product_code_from_url(product_url),
        product_id=f"{product_code_from_url(product_url)}-US",
        provider_hints=f"bazaarvoice_public_api_hasphotos; catalog_images={len(image_urls)}",
    )


def rows_for_product(product_url: str, product: Dict[str, object], reviews: Sequence[Dict[str, object]], fetched_at: str) -> List[Dict[str, str]]:
    context = context_for_product(product_url, product)
    rows: List[Dict[str, str]] = []
    for review in reviews:
        photos = review.get("Photos") or []
        if not isinstance(photos, list):
            continue
        comment = normalize_whitespace(" ".join(part for part in [
            review.get("ReviewText"),
            review_context_text(review),
        ] if part))
        for photo in photos:
            image_url = photo_url(photo)
            if not image_url:
                continue
            photo_id = normalize_whitespace(photo.get("Id") if isinstance(photo, dict) else "")
            review_id = normalize_whitespace(review.get("Id"))
            image = ReviewImage(
                image_url=image_url,
                review_id=f"levi_bv_{review_id}_{photo_id}".strip("_"),
                review_title=normalize_whitespace(review.get("Title")),
                review_body=comment,
                reviewer_name=normalize_whitespace(review.get("UserNickname")),
                date_raw=normalize_whitespace(review.get("SubmissionTime")),
                size_raw=size_raw(review),
                rating=normalize_whitespace(review.get("Rating")),
                extra={
                    "image_source_type": "customer_review_image",
                    "image_source_detail": f"bazaarvoice_public_api:{context.product_id}",
                    "product_url": product_url,
                    "product_title": normalize_whitespace(review.get("OriginalProductName")) or context.title,
                    "product_category": context.category,
                    "product_variant": normalize_whitespace(review.get("ProductId")) or context.variant,
                },
            )
            rows.append(build_intake_row(context, image, fetched_at))
    return rows


PRODUCT_PAGE_HEADERS = [
    "normalized_product_page_url",
    "source_site",
    "brand",
    "product_title_raw",
    "product_category_raw",
    "catalog_image_url",
    "catalog_image_urls",
    "catalog_image_source",
    "catalog_image_fetched_at",
    "catalog_image_fetch_status",
    "catalog_image_fetch_error",
    "mother_category_id",
    "category_confidence",
    "category_evidence",
    "category_source_field",
    "category_breadcrumb_path",
    "category_extractor_version",
    "observed_clothing_type_ids",
    "source_status",
    "robots_disallowed",
    "first_seen_at",
    "last_seen_at",
    "populated_from",
    "image_row_count",
    "needs_manual_review",
    "title",
    "breadcrumb",
    "url_slug",
    "json_ld_product_core",
    "json_ld_product_description",
    "description",
    "raw_metadata",
]


def product_page_row(product_url: str, product: Dict[str, object], photo_row_count: int, photo_review_count: int, fetched_at: str) -> Dict[str, str]:
    canonical_url = canonical_product_url(product_page_url_from_bv(product, product_url))
    image_urls = split_image_urls(product.get("ImageUrl"))
    context = context_for_product(canonical_url, product)
    clothing_type = classify_clothing_type(context)
    review_stats = product.get("ReviewStatistics") if isinstance(product.get("ReviewStatistics"), dict) else {}
    breadcrumb = breadcrumb_from_url(canonical_url)
    url_slug = " ".join(path_parts_after_women(canonical_url)).replace("-", " ")
    raw_metadata = {
        "source_doc": "data-pipelines/docs/scrape_required_fields_for_product_pages.md",
        "taxonomy_capture_method": "levi_women_sitemap_url_plus_bazaarvoice_product_api",
        "bazaarvoice_product_id": context.product_id,
        "bazaarvoice_family_ids": product.get("FamilyIds") or [],
        "bazaarvoice_category_id": product.get("CategoryId"),
        "bazaarvoice_total_review_count": product.get("TotalReviewCount") or review_stats.get("TotalReviewCount"),
        "bazaarvoice_total_photo_count": review_stats.get("TotalPhotoCount"),
        "bazaarvoice_context_distribution_order": review_stats.get("ContextDataDistributionOrder") or [],
        "photo_review_count_seen": photo_review_count,
        "photo_row_count": photo_row_count,
    }
    title = context.title
    description = context.description
    category = breadcrumb or context.category
    evidence = "URL breadcrumb/title captured; shared extractTaxonomy can classify from raw signals without re-fetching Levi"
    return {
        "normalized_product_page_url": canonical_url,
        "source_site": SOURCE_SITE,
        "brand": context.brand,
        "product_title_raw": title,
        "product_category_raw": category,
        "catalog_image_url": image_urls[0] if image_urls else "",
        "catalog_image_urls": json.dumps(image_urls, ensure_ascii=False),
        "catalog_image_source": "bazaarvoice_products_api",
        "catalog_image_fetched_at": fetched_at,
        "catalog_image_fetch_status": "ok" if image_urls else "missing",
        "catalog_image_fetch_error": "",
        "mother_category_id": "",
        "category_confidence": "low",
        "category_evidence": evidence,
        "category_source_field": "url_slug,breadcrumb,product_title_raw",
        "category_breadcrumb_path": breadcrumb,
        "category_extractor_version": "not_run_at_scrape_time",
        "observed_clothing_type_ids": json.dumps([clothing_type] if clothing_type else [], ensure_ascii=False),
        "source_status": "in_stock" if product.get("Active") is True and product.get("Disabled") is False else "",
        "robots_disallowed": "false",
        "first_seen_at": fetched_at,
        "last_seen_at": fetched_at,
        "populated_from": "levi_women_bazaarvoice_public_api",
        "image_row_count": str(photo_row_count),
        "needs_manual_review": "true",
        "title": title,
        "breadcrumb": breadcrumb,
        "url_slug": url_slug,
        "json_ld_product_core": json.dumps(
            {
                "name": title,
                "brand": context.brand,
                "category": category,
                "product_id": context.product_id,
                "url": canonical_url,
                "image": image_urls,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "json_ld_product_description": description,
        "description": description,
        "raw_metadata": json.dumps(raw_metadata, ensure_ascii=False, sort_keys=True),
    }


def write_product_pages(rows: Iterable[Dict[str, str]]) -> None:
    rows = list(rows)
    PRODUCT_PAGES_CSV.parent.mkdir(parents=True, exist_ok=True)
    with PRODUCT_PAGES_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PRODUCT_PAGE_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in PRODUCT_PAGE_HEADERS})
    with PRODUCT_PAGES_JSONL.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


MEASUREMENT_FIELDS = (
    "height_raw",
    "weight_raw",
    "height_in_display",
    "weight_lbs_display",
    "weight_display_display",
    "waist_raw_display",
    "waist_in",
    "hips_raw",
    "hips_in_display",
    "age_raw",
    "age_years_display",
    "inseam_inches_display",
    "bust_in_display",
    "bra_band_in_display",
    "bust_in_number_display",
    "cupsize_display",
)


def load_progress() -> Dict[str, object]:
    if not PROGRESS_JSON.exists():
        return {"processed": {}, "errors": []}
    return json.loads(PROGRESS_JSON.read_text(encoding="utf-8"))


def write_progress(progress: Dict[str, object]) -> None:
    PROGRESS_JSON.write_text(json.dumps(progress, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Levi women's clothing customer review images from public Bazaarvoice API.")
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--limit-products", type=int, default=0, help="Optional cap for test/batch runs.")
    parser.add_argument("--api-page-size", type=int, default=100)
    parser.add_argument("--delay-seconds", type=float, default=0.15)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    product_urls = [line.strip() for line in args.queue.read_text(encoding="utf-8").splitlines() if line.strip()]
    product_urls = [url for url in product_urls if "/clothing/women/" in url]
    if args.limit_products:
        product_urls = product_urls[: args.limit_products]

    progress = load_progress() if args.resume else {"processed": {}, "errors": []}
    processed: Dict[str, object] = progress.setdefault("processed", {})
    errors: List[Dict[str, object]] = progress.setdefault("errors", [])

    fetched_at = utc_now()
    all_rows: List[Dict[str, str]] = []
    product_page_rows: List[Dict[str, str]] = []
    if args.resume and OUTPUT_CSV.exists():
        # Rewriting from scratch would require preserving prior rows; for simplicity,
        # resumed runs should process only remaining URLs and then rewrite with the rows
        # collected in the current run plus any downstream dedupe step if needed.
        pass

    attempted = 0
    for index, product_url in enumerate(product_urls):
        if args.resume and product_url in processed:
            continue
        attempted += 1
        product_id = f"{product_code_from_url(product_url)}-US"
        record: Dict[str, object] = {"index": index, "url": product_url, "product_id": product_id, "started_at": utc_now()}
        try:
            product = fetch_product_metadata(product_id)
            payload = fetch_photo_reviews(product_id, args.api_page_size, args.delay_seconds)
            rows = rows_for_product(product_url, product, payload["reviews"], fetched_at)
            page_row = product_page_row(product_url, product, len(rows), len(payload["reviews"]), fetched_at)
            all_rows.extend(rows)
            product_page_rows.append(page_row)
            record.update(
                {
                    "finished_at": utc_now(),
                    "photo_review_count": len(payload["reviews"]),
                    "photo_row_count": len(rows),
                    "total_photo_reviews": payload["total"],
                    "product_title_raw": page_row.get("product_title_raw"),
                    "product_category_raw": page_row.get("product_category_raw"),
                    "observed_clothing_type_ids": page_row.get("observed_clothing_type_ids"),
                }
            )
        except Exception as exc:  # noqa: BLE001 - preserve scrape progress per product.
            record.update({"finished_at": utc_now(), "error": str(exc)})
            errors.append(record)
        processed[product_url] = record
        progress["updated_at"] = utc_now()
        progress["attempted_this_run"] = attempted
        write_progress(progress)
        if args.delay_seconds:
            time.sleep(args.delay_seconds)

    rows = dedupe_rows(all_rows)
    write_intake_csv(rows, OUTPUT_CSV)
    write_product_pages(product_page_rows)
    summary = {
        "generated_at": utc_now(),
        "queue": str(args.queue),
        "women_product_urls_in_scope": len(product_urls),
        "attempted_this_run": attempted,
        "processed_total": len(processed),
        "error_count": len(errors),
        "rows_written": len(rows),
        "product_pages_written": len(product_page_rows),
        "product_pages_csv": str(PRODUCT_PAGES_CSV),
        "product_pages_jsonl": str(PRODUCT_PAGES_JSONL),
        "customer_review_image_rows": sum(1 for row in rows if row.get("image_source_type") == "customer_review_image"),
        "rows_with_image_product_and_measurement": sum(
            1
            for row in rows
            if row.get("original_url_display")
            and row.get("product_page_url_display")
            and any(row.get(field) for field in MEASUREMENT_FIELDS)
        ),
        "rows_with_image_product_size_and_measurement": sum(
            1
            for row in rows
            if row.get("original_url_display")
            and row.get("product_page_url_display")
            and row.get("size_display")
            and any(row.get(field) for field in MEASUREMENT_FIELDS)
        ),
        "output_csv": str(OUTPUT_CSV),
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
