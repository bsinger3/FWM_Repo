#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from step1_intake_utils import (
    INTAKE_HEADERS,
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


SITE_ROOT = "https://saintandsofia.com"
DOMAIN = "saintandsofia.com"
RETAILER = "saintandsofia_com"
CATALOG_URL = f"{SITE_ROOT}/products.json"
LEAD_URLS = [f"{SITE_ROOT}/products/bowie-stretch-flare-jean-black-denim"]

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
    r"\b("
    r"blazer|blouse|bodysuit|camisole|cardigan|coat|dress|gown|jacket|jean|jumpsuit|"
    r"legging|pant|romper|shirt|shorts?|skirt|sweater|tee|t-shirt|top|trouser|vest"
    r")\b",
    re.I,
)
OUT_OF_SCOPE_RE = re.compile(
    r"\b("
    r"bag|belt|bracelet|earrings?|gift card|hat|jewelry|jewellery|necklace|sandal|"
    r"shoe|sneaker|sock|tote|wallet"
    r")\b",
    re.I,
)
MODEL_PROFILE_RE = re.compile(
    r"\bModel\s*:?\s*"
    r"(?P<height>\d\s*(?:ft|feet|foot|['’])\s*\d{1,2}\s*(?:in|inches|[\"”])?)\s*"
    r"(?:wears?|wearing)\s+(?:a\s+)?(?:size\s+)?(?P<size>US\s*\d{1,2}|UK\s*\d{1,2}|[A-Z]{1,3}|\d{1,2})\b",
    re.I,
)
MODEL_TAG_RE = re.compile(r"<p[^>]*>\s*Model\s*:?\s*(?P<value>.*?)</p>", re.I | re.S)
MODAL_MODEL_RE = re.compile(r'<p[^>]+class="[^"]*Modal--model_params[^"]*"[^>]*>\s*(?P<value>.*?)</p>', re.I | re.S)


class PressureStop(RuntimeError):
    pass


def request_text(url: str, *, accept: str = "text/html,application/json,*/*") -> str:
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


def fetch_catalog(limit: int, max_pages: int, delay: float) -> Tuple[Dict[str, Dict[str, object]], List[Dict[str, object]]]:
    products_by_handle: Dict[str, Dict[str, object]] = {}
    page_counts: List[Dict[str, object]] = []
    for page in range(1, max_pages + 1):
        url = f"{CATALOG_URL}?limit={limit}&page={page}"
        payload = json.loads(request_text(url, accept="application/json,text/plain,*/*"))
        products = payload.get("products", []) or []
        page_counts.append({"page": page, "url": url, "products": len(products)})
        if not products:
            break
        for product in products:
            handle = normalize_whitespace(product.get("handle"))
            if handle:
                products_by_handle[handle] = product
        print(f"[catalog page {page}] products={len(products)} total={len(products_by_handle)}", flush=True)
        if len(products) < limit:
            break
        if delay:
            time.sleep(delay)
    return products_by_handle, page_counts


def product_text(product: Dict[str, object]) -> str:
    return normalize_whitespace(
        " ".join(
            str(part or "")
            for part in [
                product.get("title"),
                product.get("product_type"),
                " ".join(str(tag) for tag in product.get("tags", []) or []),
                strip_tags(product.get("body_html")),
            ]
        )
    )


def context_for_product(product: Dict[str, object]) -> ProductContext:
    handle = normalize_whitespace(product.get("handle"))
    first_variant = (product.get("variants") or [{}])[0] if isinstance(product.get("variants"), list) else {}
    tags = product.get("tags", []) or []
    return ProductContext(
        url=product_url(handle),
        title=normalize_whitespace(product.get("title")),
        description=strip_tags(product.get("body_html")),
        detail=normalize_whitespace(" ".join(str(tag) for tag in tags)),
        category=normalize_whitespace(product.get("product_type")),
        brand=normalize_whitespace(product.get("vendor")) or "Saint + Sofia",
        color="",
        variant=normalize_whitespace(first_variant.get("title") if isinstance(first_variant, dict) else ""),
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=urlparse(SITE_ROOT).netloc,
        provider_hints="shopify_products_json_plus_product_page_care_fit_model",
    )


def is_apparel(product: Dict[str, object]) -> bool:
    context = context_for_product(product)
    text = product_text(product)
    if OUT_OF_SCOPE_RE.search(text) and not APPAREL_RE.search(text):
        return False
    return bool(classify_clothing_type(context) or APPAREL_RE.search(text))


def clean_model_value(fragment: str) -> str:
    value = re.sub(r"<\s*br\s*/?\s*>", " ", fragment, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return normalize_whitespace(html.unescape(value))


def model_comment_and_size(product_html: str) -> Tuple[str, str]:
    candidates: List[str] = []
    candidates.extend(f"Model {clean_model_value(match.group('value'))}" for match in MODEL_TAG_RE.finditer(product_html))
    candidates.extend(clean_model_value(match.group("value")) for match in MODAL_MODEL_RE.finditer(product_html))
    for candidate in candidates:
        match = MODEL_PROFILE_RE.search(candidate)
        if match:
            size = normalize_whitespace(match.group("size")).upper().replace("US ", "US ")
            height = normalize_whitespace(match.group("height"))
            comment = f"Model is {height} wearing size {size}."
            return comment, size
    return "", ""


def image_url(product: Dict[str, object]) -> str:
    images = product.get("images") if isinstance(product.get("images"), list) else []
    for image in images:
        if not isinstance(image, dict):
            continue
        src = normalize_whitespace(image.get("src"))
        if src:
            return src if src.startswith("http") else f"https:{src}"
    return ""


def row_for_product(product: Dict[str, object], product_html: str, fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    context = context_for_product(product)
    summary: Dict[str, object] = {
        "product_url": context.url,
        "product_title": context.title,
        "shopify_product_id": context.product_id,
        "product_type": context.category,
        "clothing_type_id": classify_clothing_type(context),
        "variants": len(product.get("variants", []) or []),
        "images": len(product.get("images", []) or []),
        "rows": 0,
        "skipped_from_output": False,
        "skip_reason": "",
    }
    if not is_apparel(product):
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "out_of_scope_non_apparel"
        return [], summary
    comment, size = model_comment_and_size(product_html)
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
        review_id="saintandsofia-model-" + hashlib.md5(f"{context.url}|{src}|{comment}".encode("utf-8")).hexdigest()[:16],
        review_title="Catalog model measurements",
        review_body=comment,
        size_raw=size,
        extra={
            "image_source_type": "catalog_model_image",
            "image_source_detail": "public Shopify catalog image with model height/size from product-page Care & Fit text",
        },
    )
    row = build_intake_row(context, review, fetched_at)
    summary["rows"] = 1
    summary["catalog_model_image"] = src
    summary["catalog_model_size"] = size
    summary["model_text"] = comment
    return [row], summary


def customer_supabase_qualified_rows(rows: Sequence[Dict[str, str]]) -> int:
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
    products_by_handle, page_counts = fetch_catalog(args.catalog_limit, args.max_catalog_pages, args.request_delay_seconds)
    lead_handles = [urlparse(url).path.rstrip("/").split("/")[-1] for url in LEAD_URLS]
    ordered_handles = sorted(products_by_handle)
    for handle in reversed(lead_handles):
        if handle in products_by_handle and handle in ordered_handles:
            ordered_handles.remove(handle)
            ordered_handles.insert(0, handle)

    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    scanned = 0
    for index, handle in enumerate(ordered_handles, start=1):
        product = products_by_handle[handle]
        url = product_url(handle)
        try:
            product_html = request_text(url)
        except PressureStop as exc:
            errors.append(f"{url}: {exc}")
            print(f"[stop] {url}: {exc}", flush=True)
            break
        product_rows, product_summary = row_for_product(product, product_html, started_at)
        rows.extend(product_rows)
        product_summaries.append(product_summary)
        scanned += 1
        print(f"[product {index}/{len(ordered_handles)}] rows={len(product_rows)} total={len(rows)} {handle}", flush=True)
        if args.limit_products and scanned >= args.limit_products:
            break
        if args.request_delay_seconds:
            time.sleep(args.request_delay_seconds)

    rows = dedupe_rows(rows)
    finished_at = utc_now()
    exhaustive = not errors and not args.limit_products and scanned == len(ordered_handles)
    summary = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_product_page_care_fit_catalog_model",
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": {
            "shopify_products_json": {
                "endpoint": CATALOG_URL,
                "page_counts": page_counts,
                "unique_handles": len(products_by_handle),
            },
            "lead_urls": {"urls": LEAD_URLS, "count": len(LEAD_URLS)},
            "reconciled_unique_product_urls": len(ordered_handles),
        },
        "products_discovered": len(ordered_handles),
        "products_scanned": scanned,
        "product_pages_scanned": scanned,
        "review_pages_scanned": 0,
        "exhaustive_review_paging": True,
        "coverage_exhaustive": exhaustive,
        "scrape_scope_status": "full_public_catalog_complete" if exhaustive else "stopped_or_limited",
        "catalog_model_rows_enabled": True,
        "customer_review_feed_used": False,
        "access_policy": "public Shopify products.json and product pages only; stop on 429/captcha/WAF",
        "product_summaries": product_summaries,
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "errors": errors,
    }
    return rows, summary


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
            "rows_supabase_qualified": customer_supabase_qualified_rows(rows),
            "rows_catalog_model_qualified": catalog_model_qualified_rows(rows),
        }
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Saint + Sofia public catalog model image/measurement rows.")
    parser.add_argument("--catalog-limit", type=int, default=250)
    parser.add_argument("--max-catalog-pages", type=int, default=20)
    parser.add_argument("--limit-products", type=int, default=0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.25)
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
