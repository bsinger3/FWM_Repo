#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
    ProductContext,
    ReviewImage,
    build_intake_row,
    classify_clothing_type,
    dedupe_rows,
    normalize_whitespace,
    strip_tags,
    utc_now,
    write_intake_csv,
)


SITE_ROOT = "https://svahausa.com"
DOMAIN = "svahausa.com"
RETAILER = "svahausa_com"
CATALOG_URL = f"{SITE_ROOT}/products.json"

try:
    from step1_intake_utils import STEP1_OUTPUT_ROOT
except ImportError:  # pragma: no cover
    STEP1_OUTPUT_ROOT = Path(__file__).resolve().parents[4] / "data-pipelines" / "non-amazon" / "data" / "step_1_raw_scraping_data"

OUTPUT_DIR = STEP1_OUTPUT_ROOT / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema_summary.json"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 FWM"
PRESSURE_STATUS_CODES = {401, 403, 407, 408, 409, 423, 429, 430, 503}
BLOCK_MARKERS = [
    "Just a moment...",
    "challenges.cloudflare.com",
    "cf-chl",
    "Attention Required! | Cloudflare",
    "datadome",
    "Please verify you are a human",
    "verify you are human",
    "Access denied",
]

APPAREL_RE = re.compile(
    r"\b(a-line|blouse|cardigan|dress|jumpsuit|leggings?|skirt|sweater|tee|top|tunic|pants?)\b",
    re.I,
)
OUT_OF_SCOPE_RE = re.compile(
    r"\b(earrings?|necklace|bracelet|jewelry|stainless steel|kids?|youth|toddler|gift card|mask|pin|sticker|belt)\b",
    re.I,
)
ADULT_RE = re.compile(r"\b(adults?|women|womens?|dress|skirt|top|blouse|tunic|cardigan|leggings?)\b", re.I)
SIZE_TOKEN = r"(?:XXS|XS|S/M|M/L|S|M|L|XL|[2-5]XL|petite\s+(?:XXS|XS|S|M|L|XL|[2-5]XL))"
MODEL_RE = re.compile(
    r"\b(?:1st\s+)?(?:The\s+)?Model\s+is\s+"
    r"(?P<height>\d\s*(?:ft|feet|foot|['’])\s*\d{1,2}\s*(?:in|inches|[\"”])?)"
    rf"(?:\s+and)?\s+(?:is\s+)?(?:wearing|wears)\s+(?:(?:a|an|the)\s+)?(?:size\s+)?(?P<size>{SIZE_TOKEN})\b",
    re.I,
)
MODEL_REVERSED_RE = re.compile(
    rf"\b(?:The\s+)?Model\s+is\s+wearing\s+(?:(?:a|an|the)\s+)?(?:size\s+)?(?P<size>{SIZE_TOKEN})\b"
    r".{0,80}?\b(?:height\s+is\s+)?(?P<height>\d\s*(?:ft|feet|foot|['’])\s*\d{1,2}\s*(?:in|inches|[\"”])?)",
    re.I,
)
SIZE_CLEAN_RE = re.compile(r"\b(?:and|with|the|length|measures|waist|hips|no|tagless|care|machine|imported).*$", re.I)


class PressureStop(RuntimeError):
    pass


def request_text(url: str, *, accept: str = "application/json,text/plain,*/*") -> str:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": SITE_ROOT,
        },
    )
    try:
        with urlopen(req, timeout=45) as response:
            status = getattr(response, "status", 200)
            text = response.read().decode("utf-8-sig", "replace")
    except HTTPError as exc:
        if exc.code in PRESSURE_STATUS_CODES:
            raise PressureStop(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
        raise
    except URLError as exc:
        raise PressureStop(f"request_failed: {url}: {exc}") from exc
    if status in PRESSURE_STATUS_CODES:
        raise PressureStop(f"blocked_or_rate_limited_http_{status}: {url}")
    lower = text.lower()
    if any(marker.lower() in lower for marker in BLOCK_MARKERS):
        raise PressureStop(f"blocked_or_challenged_response: {url}")
    return text


def product_url(handle: str) -> str:
    return f"{SITE_ROOT}/products/{handle}"


def fetch_catalog(limit: int, max_pages: int, delay: float) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    page_counts: List[Dict[str, object]] = []
    seen = set()
    for page in range(1, max_pages + 1):
        url = f"{CATALOG_URL}?limit={limit}&page={page}"
        payload = json.loads(request_text(url))
        page_products = payload.get("products", []) or []
        page_counts.append({"page": page, "url": url, "products": len(page_products)})
        if not page_products:
            break
        for product in page_products:
            if not isinstance(product, dict):
                continue
            handle = normalize_whitespace(product.get("handle"))
            if not handle or handle in seen:
                continue
            seen.add(handle)
            products.append(product)
        print(f"[catalog page {page}] products={len(page_products)} total={len(products)}", flush=True)
        if len(page_products) < limit:
            break
        if delay:
            time.sleep(delay)
    return products, page_counts


def context_for_product(product: Dict[str, object]) -> ProductContext:
    handle = normalize_whitespace(product.get("handle"))
    variants = product.get("variants") if isinstance(product.get("variants"), list) else []
    variant_titles: List[str] = []
    for variant in variants[:200]:
        if not isinstance(variant, dict):
            continue
        title = normalize_whitespace(variant.get("title"))
        if title and title.lower() != "default title" and title not in variant_titles:
            variant_titles.append(title)
    return ProductContext(
        url=product_url(handle),
        title=normalize_whitespace(product.get("title")),
        description=strip_tags(product.get("body_html")),
        detail=" | ".join(variant_titles),
        category=normalize_whitespace(product.get("product_type")),
        brand=normalize_whitespace(product.get("vendor")) or "Svaha USA",
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=urlparse(SITE_ROOT).netloc,
        provider_hints="shopify_products_json_catalog_model",
    )


def is_adult_apparel(product: Dict[str, object], context: ProductContext) -> Tuple[bool, str]:
    text = normalize_whitespace(
        " ".join(
            [
                context.title,
                context.category,
                context.description,
                context.detail,
                " ".join(str(tag) for tag in product.get("tags", []) or []),
            ]
        )
    )
    lowered = text.lower()
    if re.search(r"\b(kids?|youth|toddler|baby|children|girls?)\b", lowered):
        return False, "out_of_scope_kids"
    if re.search(r"\bunisex\b", lowered):
        return False, "out_of_scope_unisex"
    if OUT_OF_SCOPE_RE.search(text) and not APPAREL_RE.search(text):
        return False, "out_of_scope_non_apparel"
    if not (classify_clothing_type(context) or APPAREL_RE.search(text)):
        return False, "out_of_scope_no_womens_clothing_signal"
    if not ADULT_RE.search(text):
        return False, "out_of_scope_no_adult_signal"
    return True, ""


def clean_size(value: str) -> str:
    size = normalize_whitespace(value)
    size = SIZE_CLEAN_RE.sub("", size)
    size = re.sub(r"[\s.,;:()\"”]+$", "", size)
    size = normalize_whitespace(size)
    if size.lower().startswith("petite "):
        prefix, _, suffix = size.partition(" ")
        return f"{prefix.lower()} {suffix.upper()}"
    return size.upper()


def model_comment_and_size(product: Dict[str, object]) -> Tuple[str, str]:
    text = strip_tags(product.get("body_html"))
    match = MODEL_RE.search(text) or MODEL_REVERSED_RE.search(text)
    if not match:
        return "", ""
    height = normalize_whitespace(match.group("height"))
    size = clean_size(match.group("size"))
    if not size:
        return "", ""
    return f"Model is {height} wearing size {size}.", size


def image_url(product: Dict[str, object]) -> str:
    images = product.get("images") if isinstance(product.get("images"), list) else []
    for image in images:
        if not isinstance(image, dict):
            continue
        src = normalize_whitespace(image.get("src"))
        if src:
            return src if src.startswith("http") else f"https:{src}"
    return ""


def row_for_product(product: Dict[str, object], fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    context = context_for_product(product)
    in_scope, reason = is_adult_apparel(product, context)
    summary: Dict[str, object] = {
        "product_id": context.product_id,
        "product_url": context.url,
        "product_title": context.title,
        "product_type": context.category,
        "clothing_type_id": classify_clothing_type(context),
        "variants": len(product.get("variants", []) or []),
        "images": len(product.get("images", []) or []),
        "rows": 0,
        "skipped_from_output": False,
        "skip_reason": "",
    }
    if not in_scope:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = reason
        return [], summary
    comment, size = model_comment_and_size(product)
    if not comment:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "no_model_height_size_text"
        return [], summary
    src = image_url(product)
    if not src:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "no_catalog_model_image"
        return [], summary
    review = ReviewImage(
        image_url=src,
        review_id="svaha-model-" + hashlib.md5(f"{context.url}|{src}|{comment}".encode("utf-8")).hexdigest()[:16],
        review_title="Catalog model measurements",
        review_body=comment,
        size_raw=size,
        extra={
            "image_source_type": "catalog_model_image",
            "image_source_detail": "public Shopify products.json catalog image with product-description model height/size",
        },
    )
    row = build_intake_row(context, review, fetched_at)
    summary["rows"] = 1
    summary["catalog_model_image"] = src
    summary["catalog_model_size"] = size
    summary["model_text"] = comment
    return [row], summary


def strict_customer_qualified_rows(rows: Sequence[Dict[str, str]]) -> int:
    return sum(
        1
        for row in rows
        if row.get("original_url_display")
        and row.get("image_source_type") == "customer_review_image"
        and row.get("product_page_url_display")
        and row.get("size_display")
        and any(row.get(field) for field in MEASUREMENT_FIELDS)
    )


def catalog_model_qualified_rows(rows: Sequence[Dict[str, str]]) -> int:
    return sum(
        1
        for row in rows
        if row.get("original_url_display")
        and row.get("image_source_type") == "catalog_model_image"
        and row.get("product_page_url_display")
        and row.get("size_display")
        and any(row.get(field) for field in MEASUREMENT_FIELDS)
    )


def scrape(args: argparse.Namespace) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    products, page_counts = fetch_catalog(args.catalog_limit, args.max_catalog_pages, args.request_delay_seconds)
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    scanned = 0
    for index, product in enumerate(products, start=1):
        product_rows, product_summary = row_for_product(product, started_at)
        rows.extend(product_rows)
        product_summaries.append(product_summary)
        scanned += 1
        print(f"[product {index}/{len(products)}] rows={len(product_rows)} total={len(rows)} {product.get('handle')}", flush=True)
        if args.limit_products and scanned >= args.limit_products:
            break
    rows = dedupe_rows(rows)
    finished_at = utc_now()
    exhaustive = not errors and not args.limit_products and scanned == len(products)
    return rows, {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_catalog_model_sitewide",
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": {
            "shopify_products_json": {
                "endpoint": CATALOG_URL,
                "page_counts": page_counts,
                "unique_handles": len(products),
            }
        },
        "products_discovered": len(products),
        "products_scanned": scanned,
        "product_pages_scanned": 0,
        "review_pages_scanned": 0,
        "exhaustive_review_paging": True,
        "coverage_exhaustive": exhaustive,
        "scrape_scope_status": "full_public_catalog_products_json_complete" if exhaustive else "stopped_or_limited",
        "catalog_model_rows_enabled": True,
        "customer_review_feed_used": False,
        "access_policy": "public Shopify products.json only; no auth bypass; stop on 429/captcha/WAF",
        "product_summaries": product_summaries,
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "errors": errors,
    }


def write_outputs(rows: Sequence[Dict[str, str]], summary: Dict[str, object]) -> None:
    write_intake_csv(rows, OUTPUT_CSV)
    rows_with_product_url = sum(1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display"))
    rows_with_measurements = sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS))
    rows_with_customer_image = sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image")
    rows_with_catalog_image = sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "catalog_model_image")
    rows_with_ordered_size = sum(1 for row in rows if row.get("size_display") and row.get("size_display") != "unknown")
    payload = dict(summary)
    payload.update(
        {
            "output_csv": str(OUTPUT_CSV),
            "summary_json": str(SUMMARY_JSON),
            "rows_written": len(rows),
            "distinct_reviews": len({row.get("id", "") for row in rows if row.get("id")}),
            "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
            "distinct_product_urls": len({row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}),
            "rows_with_distinct_product_url": rows_with_product_url,
            "rows_with_any_measurement": rows_with_measurements,
            "rows_with_customer_image": rows_with_customer_image,
            "rows_with_customer_review_image": rows_with_customer_image,
            "rows_with_catalog_model_image": rows_with_catalog_image,
            "rows_with_customer_ordered_size": rows_with_ordered_size,
            "rows_with_size": rows_with_ordered_size,
            "rows_supabase_qualified": strict_customer_qualified_rows(rows),
            "rows_catalog_model_qualified": catalog_model_qualified_rows(rows),
        }
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Svaha USA public catalog model image/measurement rows.")
    parser.add_argument("--catalog-limit", type=int, default=250)
    parser.add_argument("--max-catalog-pages", type=int, default=20)
    parser.add_argument("--limit-products", type=int, default=0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.2)
    args = parser.parse_args(argv)
    rows, summary = scrape(args)
    write_outputs(rows, summary)
    print(f"Rows written: {len(rows)}")
    print(f"Products discovered: {summary['products_discovered']}")
    print(f"Products scanned: {summary['products_scanned']}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
