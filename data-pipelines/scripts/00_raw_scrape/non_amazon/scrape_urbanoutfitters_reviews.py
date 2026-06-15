#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError
from urllib.parse import urlparse, urlunparse

import openpyxl

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    fetch_text,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    write_intake_csv,
    write_summary,
)


SITE_ROOT = "https://www.urbanoutfitters.com"
DOMAIN = "urbanoutfitters.com"
RETAILER = "urbanoutfitters_com"
OUTPUT_RETAILER = "urban_outfitters"
DATA_ROOT = Path(os.environ["FWM_DATA_DIR"]).expanduser() if os.environ.get("FWM_DATA_DIR") else Path(__file__).resolve().parents[4].parent / "FWM_Data"
DEFAULT_WORKBOOK = (
    DATA_ROOT
    / "non-amazon"
    / "data"
    / "step_1_raw_scraping_data"
    / "urban_outfitters"
    / "UO_BigImages.xlsx"
)
PRODUCT_LINK_SHEET = "prodLinks"
IMAGE_ROOT = "https://images.urbndata.com/is/image/UrbanOutfitters"

BLOCKED_MARKERS = (
    "captcha-delivery.com/interstitial",
    "geo.captcha-delivery.com",
    '"url":"https://geo.captcha-delivery.com',
    "Pardon Our Interruption",
)

MODEL_MEASUREMENT_RE = re.compile(
    r"\b(model|measurements?|waist|rise|inseam|bust|chest|hips?|wearing size|wears size|taken from size)\b",
    re.I,
)
WEARING_SIZE_RE = re.compile(r"\bwear(?:ing|s)\s+(?:a\s+)?(?:size\s+)?([A-Z]{1,4}|\d{1,2}(?:\s*[A-Z]+)?)\b", re.I)


def clean(value: object) -> str:
    return normalize_whitespace(value)


def canonical_product_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme or "https", parsed.netloc or "www.urbanoutfitters.com", path, "", "", ""))


def product_urls_from_workbook(path: Path) -> List[str]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook[PRODUCT_LINK_SHEET]
    urls: List[str] = []
    seen = set()
    for row in worksheet.iter_rows(min_row=2, values_only=True):
        values = [clean(value) for value in row]
        url = next((value for value in values if value.startswith("https://www.urbanoutfitters.com/shop/")), "")
        if not url:
            continue
        url = canonical_product_url(url)
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def extract_script_json(html: str, script_id: str) -> Optional[Dict[str, object]]:
    match = re.search(
        rf"<script[^>]*id=[\"']{re.escape(script_id)}[\"'][^>]*>([\s\S]*?)</script>",
        html,
        re.I,
    )
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        return json.loads(json.loads(raw))
    except json.JSONDecodeError:
        return None


def product_payloads(pinia_state: Dict[str, object]) -> Iterable[Tuple[str, Dict[str, object]]]:
    catalog = pinia_state.get("catalog")
    if not isinstance(catalog, dict):
        return []
    products = catalog.get("products")
    if not isinstance(products, dict):
        return []
    return [(str(slug), payload) for slug, payload in products.items() if isinstance(payload, dict)]


def markdownish_text(value: object) -> str:
    text = strip_tags(value)
    text = re.sub(r"\\-", " - ", text)
    text = re.sub(r"\*\*", " ", text)
    return normalize_whitespace(text)


def product_context(url: str, slug: str, payload: Dict[str, object]) -> ProductContext:
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    category = ""
    parent_category = product.get("parentCategory")
    if isinstance(parent_category, dict):
        category = clean(parent_category.get("displayName"))
    description = markdownish_text(product.get("longDescription"))
    size_fit = size_fit_text(product)
    detail = normalize_whitespace(" ".join(part for part in [clean(product.get("modelNotes")), size_fit] if part))
    return ProductContext(
        url=url,
        title=clean(product.get("displayName")),
        description=description,
        detail=detail,
        category=category,
        brand=clean(product.get("brand")),
        product_id=clean(product.get("styleNumber") or product.get("productId")),
        handle=slug,
        provider_hints="urban_outfitters_ssr_pinia_product_state; review_api_datadome_blocked",
    )


def size_fit_text(product: Dict[str, object]) -> str:
    parts: List[str] = []
    for item in product.get("sizeAndFit") or []:
        if not isinstance(item, dict):
            continue
        for key in ("sizeType", "dimensions", "specifications"):
            value = markdownish_text(item.get(key))
            if value:
                parts.append(value)
    return normalize_whitespace(" ".join(parts))


def model_size(product: Dict[str, object]) -> str:
    for value in [clean(product.get("modelNotes")), size_fit_text(product)]:
        match = WEARING_SIZE_RE.search(value)
        if match:
            return clean(match.group(1))
    return ""


def has_catalog_measurement(product: Dict[str, object]) -> bool:
    return bool(MODEL_MEASUREMENT_RE.search(" ".join([clean(product.get("modelNotes")), size_fit_text(product)])))


def color_items(payload: Dict[str, object]) -> List[Dict[str, object]]:
    sku_info = payload.get("skuInfo") if isinstance(payload.get("skuInfo"), dict) else {}
    primary_slice = sku_info.get("primarySlice") if isinstance(sku_info.get("primarySlice"), dict) else {}
    items = primary_slice.get("sliceItems")
    return [item for item in items or [] if isinstance(item, dict)]


def image_urls_for_color(item: Dict[str, object]) -> List[str]:
    image_id = clean(item.get("id"))
    if not image_id:
        return []
    suffixes = item.get("images") if isinstance(item.get("images"), list) else []
    urls: List[str] = []
    for suffix in suffixes:
        suffix = clean(suffix)
        if not suffix:
            continue
        urls.append(f"{IMAGE_ROOT}/{image_id}_{suffix}")
    return urls


def media_urls_from_review(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    stack: List[object] = [review]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, str) and re.search(r"https?://", child) and re.search(r"image|photo|media|url", key, re.I):
                    urls.append(child)
                elif isinstance(child, (dict, list)):
                    stack.append(child)
        elif isinstance(value, list):
            stack.extend(value)
    return sorted(set(urls))


def review_rows(context: ProductContext, payload: Dict[str, object], fetched_at: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    reviews = payload.get("reviews") if isinstance(payload.get("reviews"), dict) else {}
    latest = reviews.get("latestReviews") if isinstance(reviews.get("latestReviews"), list) else []
    for review in latest:
        if not isinstance(review, dict):
            continue
        media_urls = media_urls_from_review(review)
        for index, image_url in enumerate(media_urls):
            review_id = clean(review.get("id")) or hashlib.md5(f"{context.url}|{image_url}".encode("utf-8")).hexdigest()[:16]
            item = ReviewImage(
                image_url=image_url,
                review_id=f"uo-review-{review_id}-{index}",
                review_title=clean(review.get("title")),
                review_body=clean(review.get("reviewText")),
                reviewer_name=clean(review.get("userNickname") or review.get("authorId")),
                date_raw=clean(review.get("submissionTime")),
                rating=clean(review.get("rating")),
                extra={
                    "image_source_type": "customer_review_image",
                    "image_source_detail": "Urban Outfitters SSR latestReviews review media",
                },
            )
            rows.append(build_intake_row(context, item, fetched_at))
    return rows


def catalog_rows(context: ProductContext, payload: Dict[str, object], fetched_at: str) -> List[Dict[str, str]]:
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    if not has_catalog_measurement(product):
        return []
    body = normalize_whitespace(
        " ".join(
            part
            for part in [
                "Catalog model measurements.",
                clean(product.get("modelNotes")),
                size_fit_text(product),
            ]
            if part
        )
    )
    rows: List[Dict[str, str]] = []
    size = model_size(product)
    for item in color_items(payload):
        color = clean(item.get("displayName"))
        for image_url in image_urls_for_color(item):
            row_context = ProductContext(**{**context.__dict__, "color": color, "variant": color})
            row_id = "uo-model-" + hashlib.md5(f"{context.url}|{image_url}|{body}".encode("utf-8")).hexdigest()[:18]
            review = ReviewImage(
                image_url=image_url,
                review_id=row_id,
                review_title="Catalog model measurements",
                review_body=body,
                size_raw=size,
                extra={
                    "image_source_type": "catalog_model_image",
                    "image_source_detail": "Urban Outfitters public product page catalog/model image; model and size/fit measurements from SSR product state",
                },
            )
            rows.append(build_intake_row(row_context, review, fetched_at))
    return rows


def scrape_product(url: str, fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object], bool]:
    html = fetch_text(url, referer=SITE_ROOT, retries=2, timeout=30)
    if any(marker in html for marker in BLOCKED_MARKERS):
        return [], {"url": url, "blocked": True, "rows": 0, "skip_reason": "datadome_or_captcha_interstitial"}, True
    pinia = extract_script_json(html, "urbnInitialPiniaState")
    if not pinia:
        return [], {"url": url, "rows": 0, "skip_reason": "missing_or_unparseable_urbnInitialPiniaState"}, False
    product_rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    for slug, payload in product_payloads(pinia):
        context = product_context(url, slug, payload)
        rows = review_rows(context, payload, fetched_at)
        rows.extend(catalog_rows(context, payload, fetched_at))
        product_rows.extend(rows)
        product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
        product_summaries.append(
            {
                "slug": slug,
                "title": context.title,
                "style_number": clean(product.get("styleNumber")),
                "merchandise_class": clean(product.get("merchandiseClass")),
                "review_count_embedded": (payload.get("reviews") or {}).get("count") if isinstance(payload.get("reviews"), dict) else None,
                "catalog_measurement_found": has_catalog_measurement(product),
                "colors": len(color_items(payload)),
                "rows": len(rows),
            }
        )
    return product_rows, {"url": url, "rows": len(product_rows), "products": product_summaries}, False


def scrape(workbook: Path, limit: Optional[int], request_delay_seconds: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    urls = product_urls_from_workbook(workbook)
    if limit:
        urls = urls[:limit]
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    stopped_by_access_guardrail = False
    for index, url in enumerate(urls, 1):
        try:
            product_rows, summary, blocked = scrape_product(url, started_at)
            rows.extend(product_rows)
            product_summaries.append(summary)
            if blocked:
                stopped_by_access_guardrail = True
                errors.append(f"{url}: stopped after bot-protection/captcha interstitial marker")
        except Exception as exc:
            if isinstance(exc, HTTPError) and exc.code in {403, 429}:
                stopped_by_access_guardrail = True
                errors.append(f"{url}: stopped after HTTP {exc.code} from public product page")
                print(f"[uo {index}/{len(urls)}] stopped_on_http_{exc.code} url={url}", flush=True)
                break
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
        print(f"[uo {index}/{len(urls)}] rows_total={len(rows)} url={url}", flush=True)
        if stopped_by_access_guardrail:
            break
        if request_delay_seconds:
            time.sleep(request_delay_seconds)
    rows = dedupe_rows(rows)
    summary = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "urbanoutfitters_product_page_ssr_pinia_catalog_model",
        "started_at": started_at,
        "finished_at": utc_now(),
        "workbook": str(workbook),
        "source_catalog_sheet": PRODUCT_LINK_SHEET,
        "discovery_method": "local workbook prodLinks sheet; every listed Urban Outfitters product page fetched directly",
        "scrape_scope_status": (
            "all_workbook_product_pages_complete"
            if not stopped_by_access_guardrail and not errors
            else "stopped_after_public_endpoint_restriction_or_error"
        ),
        "full_catalog_scrape_complete": False,
        "full_catalog_scrape_note": "Covered all product pages in the local UO prodLinks catalog, not independently discovered sitewide inventory.",
        "products_discovered": len(urls),
        "products_scanned": len(product_summaries),
        "product_pages_scanned": len(product_summaries),
        "aggregate_feed_used": False,
        "customer_review_feed_used": False,
        "customer_review_api_status": "not_used_datadome_interstitial_on_public_probe",
        "catalog_model_rows_enabled": True,
        "access_policy": "public_product_pages_only; no_auth_bypass; no_captcha_bypass; stopped if interstitial markers appear",
        "product_summaries": product_summaries,
        "errors": errors,
    }
    return rows, summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Urban Outfitters public product pages for catalog model rows.")
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--limit-products", type=int, default=None)
    parser.add_argument("--request-delay-seconds", type=float, default=0.35)
    args = parser.parse_args(argv)

    rows, summary = scrape(args.workbook, args.limit_products, args.request_delay_seconds)
    output_csv, summary_json = output_paths(OUTPUT_RETAILER)
    write_intake_csv(rows, output_csv)
    write_summary(
        summary_json,
        site=SITE_ROOT,
        retailer=OUTPUT_RETAILER,
        rows=rows,
        output_csv=output_csv,
        started_at=summary["started_at"],
        finished_at=summary["finished_at"],
        products_scanned=int(summary["products_scanned"]),
        adapter=str(summary["adapter"]),
        product_summaries=summary["product_summaries"],
        errors=summary["errors"],
    )
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    payload.update(summary)
    payload["output_csv"] = str(output_csv)
    payload["summary_json"] = str(summary_json)
    payload["rows_supabase_qualified"] = payload.get("rows_with_image_product_size_and_measurement", 0)
    summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Rows written: {len(rows)}")
    print(f"Catalog model rows: {payload.get('rows_with_catalog_model_image', 0)}")
    print(f"Customer review image rows: {payload.get('rows_with_customer_review_image', 0)}")
    print(f"CSV: {output_csv}")
    print(f"Summary: {summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
