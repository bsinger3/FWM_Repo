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
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

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


SITE = "https://nojeans.co"
RETAILER = "nojeans_co"
TRIAGE_CATEGORY_URL = "https://nojeans.co/#main-content"
TRIAGE_SAMPLE_PDPS = [
    "https://nojeans.co/products/nj-20s01-knit-cardigan",
    "https://nojeans.co/products/nj-25s06-surfing",
]
BLOCKING_STATUS_CODES = {401, 403, 407, 429, 503}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
BLOCK_BODY_RE = re.compile(r"\b(?:captcha|access denied|forbidden|too many requests|datadome|akamai)\b", re.I)
NEXT_DATA_RE = re.compile(
    r"<script[^>]+id=['\"]__NEXT_DATA__['\"][^>]*>(.*?)</script>",
    re.I | re.S,
)
PRODUCT_URL_RE = re.compile(r"https://nojeans\.co/products/[^<\s\"']+", re.I)


@dataclass
class EmbeddedReview:
    review_id: str
    title: str = ""
    body: str = ""
    nickname: str = ""
    location: str = ""
    rating: str = ""
    size_bought: str = ""
    color_bought: str = ""
    height: str = ""
    created_at: str = ""
    media_fields: Dict[str, object] = field(default_factory=dict)


@dataclass
class ProductRecord:
    product_id: str
    url: str
    title: str
    description: str = ""
    detail: str = ""
    category: str = ""
    color: str = ""
    variant: str = ""
    handle: str = ""
    tags: Dict[str, str] = field(default_factory=dict)
    images: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class PageExtraction:
    page_url: str
    product_records: List[ProductRecord] = field(default_factory=list)
    reviews: List[EmbeddedReview] = field(default_factory=list)
    overall_rating: str = ""
    review_count: int = 0
    provider_hints: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Focused No! Jeans Next/Apollo catalog-image scrape.")
    parser.add_argument("--max-products", type=int, default=0, help="Debug cap on unique product URLs; 0 scans all discovered URLs.")
    parser.add_argument("--sleep", type=float, default=0.05, help="Sleep between public requests.")
    parser.add_argument("--sitemap-limit", type=int, default=0, help="Optional debug cap on product URLs read from sitemap.")
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
            if BLOCK_BODY_RE.search(body[:2500]):
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


def normalize_url(url: str) -> str:
    clean = normalize_whitespace(html.unescape(url)).rstrip("/)")
    if clean.startswith("//"):
        return "https:" + clean
    return urljoin(SITE, clean)


def extract_next_data(html_text: str) -> Dict[str, object]:
    match = NEXT_DATA_RE.search(html_text)
    if not match:
        return {}
    try:
        return json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError:
        return {}


def apollo_state(next_data: Dict[str, object]) -> Dict[str, object]:
    props = next_data.get("props")
    if not isinstance(props, dict):
        return {}
    page_props = props.get("pageProps")
    if not isinstance(page_props, dict):
        return {}
    state = page_props.get("apolloState")
    return state if isinstance(state, dict) else {}


def coerce_tags(value: object) -> Dict[str, str]:
    if isinstance(value, dict):
        if isinstance(value.get("json"), list):
            tags: Dict[str, str] = {}
            for item in value["json"]:
                clean = normalize_whitespace(item)
                if "_" in clean:
                    key, tag_value = clean.split("_", 1)
                    tags[normalize_whitespace(key)] = normalize_whitespace(tag_value)
                elif clean:
                    tags[clean] = "true"
            return tags
        return {normalize_whitespace(k): normalize_whitespace(v) for k, v in value.items()}
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return {normalize_whitespace(k): normalize_whitespace(v) for k, v in parsed.items()}
    return {}


def json_values(value: object) -> List[str]:
    if isinstance(value, dict) and isinstance(value.get("json"), list):
        return [normalize_whitespace(item) for item in value["json"] if normalize_whitespace(item)]
    if isinstance(value, list):
        return [normalize_whitespace(item) for item in value if normalize_whitespace(item)]
    clean = normalize_whitespace(value)
    return [clean] if clean else []


def record_id_from_key(key: str) -> str:
    return key.split(":", 1)[1].split(".", 1)[0] if ":" in key else key


def linked_refs(value: object) -> List[str]:
    if isinstance(value, dict):
        ref = value.get("__ref")
        return [str(ref)] if ref else []
    if isinstance(value, list):
        refs: List[str] = []
        for item in value:
            refs.extend(linked_refs(item))
        return refs
    return []


def image_url_from_record(record: Dict[str, object]) -> str:
    candidates = [
        record.get('url({"size":"venti"})'),
        record.get('url({"size":"grande"})'),
        record.get('url({"size":"optimized"})'),
        record.get("url"),
        record.get("src"),
    ]
    for candidate in candidates:
        clean = normalize_whitespace(candidate)
        if clean:
            return normalize_url(clean)
    return ""


def product_images(product_key: str, state: Dict[str, object]) -> List[Dict[str, str]]:
    image_records: List[Tuple[str, Dict[str, object]]] = []
    prefix = f"{product_key}.images."
    for key, value in state.items():
        if key.startswith(prefix) and isinstance(value, dict):
            image_records.append((key, value))
    image_records.sort(key=lambda item: item[0])

    images: List[Dict[str, str]] = []
    for index, (key, record) in enumerate(image_records, start=1):
        image_url = image_url_from_record(record)
        if not image_url:
            continue
        tags = []
        is_product = ""
        is_swatch = ""
        for ref in linked_refs(record.get("tags")):
            tag_record = state.get(ref)
            if not isinstance(tag_record, dict):
                continue
            tags.append(normalize_whitespace(tag_record.get("name") or tag_record.get("slug") or ref))
            is_product = is_product or normalize_whitespace(tag_record.get("isProduct"))
            is_swatch = is_swatch or normalize_whitespace(tag_record.get("isSwatch"))
        if is_swatch.lower() == "true":
            continue
        images.append(
            {
                "url": image_url,
                "image_key": key,
                "position": str(index),
                "tags": "; ".join(tag for tag in tags if tag),
                "is_product": is_product,
            }
        )
    return images


def product_options(product_key: str, state: Dict[str, object]) -> Dict[str, List[str]]:
    options: Dict[str, List[str]] = {}
    for key, value in state.items():
        if not key.startswith(f"{product_key}.options.") or not isinstance(value, dict):
            continue
        name = normalize_whitespace(value.get("name"))
        values = json_values(value.get("values"))
        if name and values:
            options[name] = values
    return options


def product_detail(product_key: str, record: Dict[str, object], state: Dict[str, object]) -> Tuple[str, str, str, Dict[str, str]]:
    tags = coerce_tags(record.get("tags"))
    description = " ".join(
        part
        for part in [
            strip_tags(record.get("description1") or ""),
            strip_tags(record.get("description2") or ""),
            strip_tags(record.get("description3") or ""),
            strip_tags(record.get("description4") or ""),
        ]
        if part
    )
    category = " > ".join(
        part
        for part in [
            normalize_whitespace(record.get("attribute1")),
            normalize_whitespace(record.get("attribute2")),
            normalize_whitespace(record.get("attribute3")),
        ]
        if part
    )
    options = product_options(product_key, state)
    size_values = options.get("Size") or [value for key, value in tags.items() if key.lower().startswith("size") and value]
    fabric_values = [value for value in [strip_tags(record.get("description3") or "")] if value] or [
        value for key, value in tags.items() if key.lower() in {"fabric", "materials", "material"} and value
    ]
    detail_parts = []
    if size_values:
        detail_parts.append("available sizes: " + ", ".join(dict.fromkeys(size_values)))
    for option_name, option_values in options.items():
        if option_name == "Size":
            continue
        detail_parts.append(f"{option_name.lower()}: " + ", ".join(dict.fromkeys(option_values)))
    if fabric_values:
        detail_parts.append("fabric: " + ", ".join(dict.fromkeys(fabric_values)))
    color = normalize_whitespace(tags.get("color") or tags.get("colour") or record.get("color") or "")
    if color and not any(part.lower().startswith("color:") for part in detail_parts):
        detail_parts.append(f"color: {color}")
    return description, " | ".join(detail_parts), category, tags


def product_records_from_state(state: Dict[str, object]) -> List[ProductRecord]:
    products: List[ProductRecord] = []
    for key, record in state.items():
        if not key.startswith("Product:") or "." in key or not isinstance(record, dict):
            continue
        url = normalize_whitespace(record.get("url"))
        handle = normalize_whitespace(record.get("handle"))
        if not url and handle:
            url = f"{SITE}/products/{handle}"
        if not url or "/products/" not in url:
            continue
        description, detail, category, tags = product_detail(key, record, state)
        color = normalize_whitespace(tags.get("color") or tags.get("colour") or "")
        title = normalize_whitespace(record.get("title") or tags.get("name") or handle)
        products.append(
            ProductRecord(
                product_id=record_id_from_key(key),
                url=normalize_url(url),
                title=title,
                description=description,
                detail=detail,
                category=category,
                color=color,
                variant=color,
                handle=handle,
                tags=tags,
                images=product_images(key, state),
            )
        )
    products.sort(key=lambda product: (product.url, product.product_id))
    return products


def embedded_reviews_from_state(state: Dict[str, object]) -> List[EmbeddedReview]:
    reviews: List[EmbeddedReview] = []
    media_field_names = {"images", "image", "media", "photos", "photo", "attachments", "videos"}
    for key, record in state.items():
        if not isinstance(record, dict):
            continue
        if record.get("__typename") != "ProductReview":
            continue
        media_fields = {
            name: value
            for name, value in record.items()
            if any(token in name.lower() for token in media_field_names) and value not in (None, "", [])
        }
        reviews.append(
            EmbeddedReview(
                review_id=record_id_from_key(key),
                title=normalize_whitespace(record.get("title")),
                body=strip_tags(record.get("body") or ""),
                nickname=normalize_whitespace(record.get("nickname")),
                location=normalize_whitespace(record.get("location")),
                rating=normalize_whitespace(record.get("rating")),
                size_bought=normalize_whitespace(record.get("sizeBought")),
                color_bought=normalize_whitespace(record.get("colorBought")),
                height=normalize_whitespace(record.get("height")),
                created_at=normalize_whitespace(record.get("createdAt")),
                media_fields=media_fields,
            )
        )
    reviews.sort(key=lambda review: review.review_id)
    return reviews


def review_stats_from_state(state: Dict[str, object]) -> Tuple[str, int]:
    overall = ""
    count = 0
    for record in state.values():
        if not isinstance(record, dict):
            continue
        if "overallRating" in record:
            overall = overall or normalize_whitespace(record.get("overallRating"))
        for field in ("totalReviewCount", "reviewCount", "count"):
            value = record.get(field)
            if isinstance(value, int):
                count = max(count, value)
    return overall, count


def extract_page(page_url: str, html_text: str) -> PageExtraction:
    next_payload = extract_next_data(html_text)
    state = apollo_state(next_payload)
    products = product_records_from_state(state)
    reviews = embedded_reviews_from_state(state)
    overall, review_count = review_stats_from_state(state)
    provider_hints = "custom Next.js/Apollo ProductReview objects embedded in __NEXT_DATA__; no third-party review widget detected"
    return PageExtraction(
        page_url=page_url,
        product_records=products,
        reviews=reviews,
        overall_rating=overall,
        review_count=max(review_count, len(reviews)),
        provider_hints=provider_hints,
    )


def discover_product_urls(args: argparse.Namespace) -> Tuple[List[str], List[Dict[str, object]]]:
    urls = list(TRIAGE_SAMPLE_PDPS)
    source_pages: List[Dict[str, object]] = []
    sitemap_url = f"{SITE}/sitemap.xml"
    sitemap_text, headers = curl_fetch_text(sitemap_url, accept="application/xml,text/xml,*/*")
    sitemap_urls = [normalize_url(match) for match in PRODUCT_URL_RE.findall(sitemap_text)]
    if not sitemap_urls:
        sitemap_urls = [normalize_url(item) for item in re.findall(r"<loc>(.*?)</loc>", sitemap_text, re.I | re.S) if "/products/" in item]
    if args.sitemap_limit:
        sitemap_urls = sitemap_urls[: args.sitemap_limit]
    source_pages.append(
        {
            "url": sitemap_url,
            "content_type": headers.get("content-type", ""),
            "product_urls": len(sitemap_urls),
        }
    )
    urls.extend(sitemap_urls)
    unique_urls = []
    seen = set()
    for url in urls:
        canonical = normalize_url(url).split("?", 1)[0].rstrip("/")
        if "/products/" not in canonical or canonical in seen:
            continue
        seen.add(canonical)
        unique_urls.append(canonical)
    if args.max_products:
        unique_urls = unique_urls[: args.max_products]
    return unique_urls, source_pages


def context_for_product(product: ProductRecord) -> ProductContext:
    return ProductContext(
        url=product.url,
        title=product.title,
        description=product.description,
        detail=product.detail,
        category=product.category,
        brand="No! Jeans",
        color=product.color,
        variant=product.variant,
        product_id=product.product_id,
        handle=product.handle,
        shop_domain="nojeans.co",
        provider_hints="custom Next.js/Apollo product records; catalog/model image fallback",
    )


def rows_from_product(product: ProductRecord, page_url: str, fetched_at: str) -> List[Dict[str, str]]:
    context = context_for_product(product)
    rows = []
    for index, image in enumerate(product.images, start=1):
        detail = normalize_whitespace(
            "catalog/model product image from public Next.js Apollo state; "
            f"source_page={page_url}; product_id={product.product_id}; image_position={image.get('position')}; "
            f"image_tags={image.get('tags')}; no review image/media field found on embedded ProductReview objects"
        )
        review = ReviewImage(
            image_url=image["url"],
            review_id=f"nojeans-catalog-{product.product_id}-{index}",
            review_title="Catalog/model product image",
            review_body=(
                "Catalog/model product image. Public embedded ProductReview objects were present, "
                "but customer review media fields were not exposed in the sampled page state."
            ),
            reviewer_name="No! Jeans",
            extra={
                "product_url": product.url,
                "product_title": product.title,
                "product_description": product.description,
                "product_detail": product.detail,
                "product_category": product.category,
                "product_variant": product.variant,
                "image_source_type": "catalog_model_image",
                "image_source_detail": detail,
            },
        )
        rows.append(build_intake_row(context, review, fetched_at))
    return rows


def dedupe_nojeans_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped = []
    seen = set()
    for row in rows:
        key = (row.get("product_page_url_display", ""), row.get("original_url_display", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def review_summary(reviews: Sequence[EmbeddedReview]) -> Dict[str, object]:
    return {
        "embedded_reviews_seen": len(reviews),
        "embedded_reviews_with_media_fields": sum(1 for review in reviews if review.media_fields),
        "embedded_reviews_with_size_bought": sum(1 for review in reviews if review.size_bought),
        "embedded_reviews_with_height": sum(1 for review in reviews if review.height),
        "sample_review_fields": [
            {
                "review_id": review.review_id,
                "rating": review.rating,
                "size_bought": review.size_bought,
                "height": review.height,
                "created_at": review.created_at,
                "media_field_names": sorted(review.media_fields.keys()),
            }
            for review in reviews[:5]
        ],
    }


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
    product_urls: Sequence[str],
    source_pages: Sequence[Dict[str, object]],
    page_summaries: Sequence[Dict[str, object]],
    products: Sequence[ProductRecord],
    reviews: Sequence[EmbeddedReview],
    errors: Sequence[str],
) -> None:
    summary = {
        "site": SITE,
        "retailer": RETAILER,
        "adapter": "next_apollo_catalog_model_images",
        "provider_identified": (
            "custom Next.js/Apollo product review implementation with ProductReview objects embedded in __NEXT_DATA__; "
            "no review media fields found, so output uses catalog_model_image rows from public product image state"
        ),
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": {
            "triage_category_url": TRIAGE_CATEGORY_URL,
            "triage_sample_pdps": TRIAGE_SAMPLE_PDPS,
            "sitemap_sources": list(source_pages),
            "product_urls_scanned": list(product_urls),
            "scope_note": "Focused public sitemap plus Sovrn sample PDPs; no authenticated/private endpoints used.",
        },
        "products_discovered_from_page_state": len(products),
        "products_scanned": len(product_urls),
        "review_pages_scanned": 0,
        "exhaustive_review_paging": False,
        "embedded_review_summary": review_summary(reviews),
        "page_summaries": list(page_summaries),
        "errors": list(errors),
        "access_policy": "public No! Jeans sitemap/PDP pages and embedded Next.js state only; stop on 429/captcha/WAF/auth behavior.",
        "sovrn_triage_source": {
            "source_file": "data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv",
            "status": "first-pass candidate",
            "payout_model": "CPA+CPC",
            "provider": "unknown",
            "reviews_present": "yes",
            "photo_reviews": "unknown_sample_too_small",
            "shipping": "AU|CA|DE|ES|FR|GB|IT|NZ|US",
            "payout_note": "payout fields not populated",
            "category_evidence_url": TRIAGE_CATEGORY_URL,
            "sample_pdps": TRIAGE_SAMPLE_PDPS,
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
    all_products: List[ProductRecord] = []
    all_reviews: List[EmbeddedReview] = []
    page_summaries: List[Dict[str, object]] = []
    product_urls: List[str] = []
    source_pages: List[Dict[str, object]] = []

    try:
        product_urls, source_pages = discover_product_urls(args)
        seen_product_images = set()
        seen_reviews = set()
        for index, product_url in enumerate(product_urls, start=1):
            html_text, headers = curl_fetch_text(product_url, referer=TRIAGE_CATEGORY_URL)
            extraction = extract_page(product_url, html_text)
            page_rows = 0
            for review in extraction.reviews:
                if review.review_id not in seen_reviews:
                    all_reviews.append(review)
                    seen_reviews.add(review.review_id)
            for product in extraction.product_records:
                filtered_images = []
                for image in product.images:
                    key = (product.url, image["url"])
                    if key in seen_product_images:
                        continue
                    seen_product_images.add(key)
                    filtered_images.append(image)
                product.images = filtered_images
                if product.images:
                    all_products.append(product)
                    product_rows = rows_from_product(product, product_url, fetched_at)
                    rows.extend(product_rows)
                    page_rows += len(product_rows)
            page_summaries.append(
                {
                    "page_index": index,
                    "page_url": product_url,
                    "content_type": headers.get("content-type", ""),
                    "apollo_products": len(extraction.product_records),
                    "catalog_model_image_rows": page_rows,
                    "embedded_reviews_seen_on_page": len(extraction.reviews),
                    "embedded_review_count_stat": extraction.review_count,
                    "overall_rating": extraction.overall_rating,
                    "provider_hints": extraction.provider_hints,
                }
            )
            if index % 25 == 0:
                print(f"scanned {index}/{len(product_urls)} PDPs; rows={len(rows)}", file=sys.stderr, flush=True)
            if args.sleep:
                time.sleep(args.sleep)
    except RuntimeError as exc:
        errors.append(str(exc))
    except Exception as exc:
        errors.append(f"scrape_failed: {exc}")

    rows = dedupe_nojeans_rows(dedupe_rows(rows))
    write_intake_csv(rows, output_csv)
    write_summary(
        summary_json,
        output_csv=output_csv,
        rows=rows,
        started_at=started_at,
        finished_at=utc_now(),
        product_urls=product_urls,
        source_pages=source_pages,
        page_summaries=page_summaries,
        products=all_products,
        reviews=all_reviews,
        errors=errors,
    )
    print(str(output_csv))
    print(str(summary_json))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
