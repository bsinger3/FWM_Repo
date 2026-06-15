#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import xml.etree.ElementTree as ET
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


SITE_ROOT = "https://ripleyrader.com"
DOMAIN = "ripleyrader.com"
RETAILER = "ripleyrader_com"
CATALOG_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
LEAD_URLS = [f"{SITE_ROOT}/products/black-wide-leg-pant-cropped"]

DATA_ROOT = Path(__file__).resolve().parents[4] / "data-pipelines" / "non-amazon" / "data"
try:
    from step1_intake_utils import STEP1_OUTPUT_ROOT
except ImportError:  # pragma: no cover
    STEP1_OUTPUT_ROOT = DATA_ROOT / "step_1_raw_scraping_data"

OUTPUT_DIR = STEP1_OUTPUT_ROOT / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema_summary.json"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 FWM"
BLOCK_MARKERS = [
    "Just a moment...",
    "challenges.cloudflare.com",
    "cf-chl",
    "Access denied",
    "Attention Required! | Cloudflare",
    "datadome",
    "Please verify you are a human",
    "verify you are human",
]

APPAREL_WORD_RE = re.compile(
    r"\b("
    r"bra|bralette|dress|gown|jumpsuit|romper|set|blazer|suit|top|tee|t-shirt|shirt|"
    r"tank|camisole|sweater|cardigan|jacket|coat|vest|skirt|skort|pant|trouser|jean|"
    r"legging|shorts?|bodysuit|tunic|blouse"
    r")\b",
    re.I,
)
OUT_OF_SCOPE_RE = re.compile(
    r"\b("
    r"fragrance|perfume|returns?|package protection|shipping protection|gift card|earrings?|"
    r"necklace|bracelet|jewelry|jewellery|bag|tote|hat|belt|shoe|sandal|sock"
    r")\b",
    re.I,
)
MODEL_FIELD_RE = re.compile(
    r'<div class="products-metafield-title">\s*MODEL:\s*</div>\s*'
    r'<div class="products-metafield-discription">\s*(?P<value>.*?)\s*</div>',
    re.I | re.S,
)
MODEL_SIZE_RE = re.compile(
    r"\b(?:wears?|wearing)\s+(?:a\s+)?(?:sz|size)\s*"
    r"(?P<size>[A-Za-z0-9+./-]+(?:\s*\([^)]+\))?)",
    re.I,
)
MODEL_HEIGHT_RE = re.compile(r"\b\d\s*(?:ft|feet|foot|['’])\s*\d{1,2}\s*(?:in|inches|[\"”])?", re.I)
MODEL_PROFILE_RE = re.compile(
    r"\b[A-Z][A-Za-z.'-]+\s+is\s+"
    r"\d\s*(?:ft|feet|foot|['’])\s*\d{1,2}\s*(?:in|inches|[\"”])?\s+"
    r"(?:wears?|wearing)\s+(?:a\s+)?(?:sz|size)\s*"
    r"[A-Za-z0-9+./-]+(?:\s*\([^)]+\))?",
    re.I,
)


def request_text(url: str, *, accept: str = "text/html,application/json,application/xml;q=0.9,*/*;q=0.8") -> str:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Referer": SITE_ROOT,
        },
    )
    try:
        with urlopen(req, timeout=45) as response:
            status = getattr(response, "status", 200)
            text = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code in {403, 408, 409, 429, 503}:
            raise RuntimeError(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
        raise
    except URLError as exc:
        raise RuntimeError(f"request_failed: {url}: {exc}") from exc
    if status in {403, 408, 409, 429, 503}:
        raise RuntimeError(f"blocked_or_rate_limited_http_{status}: {url}")
    lower = text.lower()
    if any(marker.lower() in lower for marker in BLOCK_MARKERS):
        raise RuntimeError(f"blocked_or_challenged_response: {url}")
    return text


def product_url(handle: str) -> str:
    return f"{SITE_ROOT}/products/{handle}"


def handle_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path.startswith("products/"):
        return ""
    return path.split("/", 1)[1]


def fetch_catalog(limit: int, max_pages: int, request_delay_seconds: float) -> Tuple[Dict[str, Dict[str, object]], Dict[str, object]]:
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
        if request_delay_seconds:
            time.sleep(request_delay_seconds)
    return products_by_handle, {"endpoint": CATALOG_URL, "page_counts": page_counts, "unique_handles": len(products_by_handle)}


def fetch_sitemap_products(request_delay_seconds: float) -> Tuple[List[str], Dict[str, object]]:
    root_text = request_text(SITEMAP_URL, accept="application/xml,text/xml,*/*")
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(root_text)
    sitemap_urls = [node.text or "" for node in root.findall(".//sm:loc", ns)]
    product_urls: List[str] = []
    product_sitemaps: List[Dict[str, object]] = []
    for sitemap_url in sitemap_urls:
        sitemap_url = html.unescape(normalize_whitespace(sitemap_url))
        if "sitemap_products" not in sitemap_url:
            continue
        text = request_text(sitemap_url, accept="application/xml,text/xml,*/*")
        product_root = ET.fromstring(text)
        urls = [
            html.unescape(normalize_whitespace(node.text or ""))
            for node in product_root.findall(".//sm:loc", ns)
            if "/products/" in normalize_whitespace(node.text or "")
        ]
        product_urls.extend(urls)
        product_sitemaps.append({"url": sitemap_url, "product_urls": len(urls)})
        print(f"[sitemap] {sitemap_url} product_urls={len(urls)}", flush=True)
        if request_delay_seconds:
            time.sleep(request_delay_seconds)
    unique_urls = sorted(set(product_urls))
    return unique_urls, {
        "root": SITEMAP_URL,
        "sitemaps_seen": len(sitemap_urls),
        "product_sitemaps": product_sitemaps,
        "unique_product_urls": len(unique_urls),
    }


def visible_model_text(product_html: str) -> str:
    match = MODEL_FIELD_RE.search(product_html)
    if not match:
        return ""
    value = re.sub(r"<\s*br\s*/?\s*>", " ", match.group("value"), flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return normalize_whitespace(html.unescape(value))


def primary_model_text(model_text: str) -> str:
    match = MODEL_PROFILE_RE.search(model_text)
    if match:
        return normalize_whitespace(match.group(0))
    return model_text


def model_size(model_text: str) -> str:
    match = MODEL_SIZE_RE.search(model_text)
    if not match:
        return ""
    return normalize_whitespace(match.group("size")).strip(" .,:;")


def has_model_height(model_text: str) -> bool:
    return bool(MODEL_HEIGHT_RE.search(model_text))


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


def is_apparel_product(product: Dict[str, object], url: str) -> bool:
    text = product_text(product)
    if OUT_OF_SCOPE_RE.search(text) and not APPAREL_WORD_RE.search(text):
        return False
    context = context_for_product(product, url)
    return bool(classify_clothing_type(context) or APPAREL_WORD_RE.search(text))


def best_catalog_image(product: Dict[str, object]) -> str:
    images = [img for img in product.get("images", []) or [] if normalize_whitespace(img.get("src"))]
    if not images:
        return ""
    ranked = sorted(
        enumerate(images),
        key=lambda item: (
            -5
            if re.search(
                r"\b(detail|flat|swatch|back)\b",
                normalize_whitespace(item[1].get("alt")) + " " + normalize_whitespace(item[1].get("src")),
                re.I,
            )
            else 0,
            -item[0],
        ),
        reverse=True,
    )
    return normalize_whitespace(ranked[0][1].get("src"))


def context_for_product(product: Dict[str, object], url: str) -> ProductContext:
    handle = normalize_whitespace(product.get("handle")) or handle_from_url(url)
    tags = product.get("tags", []) or []
    return ProductContext(
        url=url,
        title=normalize_whitespace(product.get("title")),
        description=strip_tags(product.get("body_html")),
        detail=normalize_whitespace(" ".join(str(tag) for tag in tags)),
        category=normalize_whitespace(product.get("product_type")),
        brand=normalize_whitespace(product.get("vendor")) or "Ripley Rader",
        handle=handle,
        product_id=str(product.get("id") or ""),
        shop_domain=urlparse(SITE_ROOT).netloc,
        provider_hints="shopify_products_json_plus_product_model_metafield",
    )


def fetch_product_from_js(handle: str) -> Optional[Dict[str, object]]:
    try:
        payload = json.loads(request_text(f"{product_url(handle)}.js", accept="application/json,text/plain,*/*"))
    except Exception:
        return None
    return {
        "id": payload.get("id"),
        "title": payload.get("title"),
        "handle": payload.get("handle") or handle,
        "vendor": payload.get("vendor") or "Ripley Rader",
        "product_type": payload.get("type") or "",
        "tags": payload.get("tags") or [],
        "body_html": payload.get("description") or "",
        "images": [{"src": src, "alt": ""} for src in payload.get("images", []) or []],
        "variants": payload.get("variants") or [],
    }


def row_for_product(
    product: Dict[str, object],
    url: str,
    product_html: str,
    fetched_at: str,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    context = context_for_product(product, url)
    raw_model_text = visible_model_text(product_html)
    model_text = primary_model_text(raw_model_text)
    summary: Dict[str, object] = {
        "product_id": context.product_id,
        "product_url": context.url,
        "product_title": context.title,
        "product_type": context.category,
        "clothing_type_id": classify_clothing_type(context),
        "variants": len(product.get("variants", []) or []),
        "images": len(product.get("images", []) or []),
        "model_text": model_text,
        "raw_model_text": raw_model_text,
        "rows": 0,
        "skipped_from_output": False,
        "skip_reason": "",
    }
    if not is_apparel_product(product, url):
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "out_of_scope_non_apparel"
        return [], summary
    if not model_text:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "no_model_metafield_found"
        return [], summary
    if not has_model_height(model_text):
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "model_metafield_without_height"
        return [], summary
    size = model_size(model_text)
    if not size:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "model_metafield_without_ordered_size"
        return [], summary
    image_url = best_catalog_image(product)
    if not image_url:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "no_catalog_model_image_found"
        return [], summary
    review_id = "ripleyrader-model-" + hashlib.md5(f"{url}|{image_url}|{model_text}".encode("utf-8")).hexdigest()[:16]
    review = ReviewImage(
        image_url=image_url,
        review_id=review_id,
        review_title="Catalog model measurements",
        review_body=model_text,
        size_raw=size,
        extra={
            "image_source_type": "catalog_model_image",
            "image_source_detail": "public Shopify catalog/model image with model height/size from product-page MODEL metafield",
        },
    )
    row = build_intake_row(context, review, fetched_at)
    summary["rows"] = 1
    summary["catalog_model_image"] = image_url
    summary["catalog_model_size"] = size
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
    products_by_handle, catalog_summary = fetch_catalog(args.catalog_limit, args.max_catalog_pages, args.request_delay_seconds)
    sitemap_urls, sitemap_summary = fetch_sitemap_products(args.request_delay_seconds)
    lead_urls = [html.unescape(url) for url in LEAD_URLS]

    url_by_handle: Dict[str, str] = {handle: product_url(handle) for handle in products_by_handle}
    for url in sitemap_urls + lead_urls:
        handle = handle_from_url(url)
        if handle:
            url_by_handle.setdefault(handle, url)

    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    scanned = 0
    for index, (handle, url) in enumerate(sorted(url_by_handle.items()), start=1):
        product = products_by_handle.get(handle)
        if product is None:
            product = fetch_product_from_js(handle)
        if product is None:
            product_summaries.append(
                {
                    "product_url": url,
                    "handle": handle,
                    "rows": 0,
                    "skipped_from_output": True,
                    "skip_reason": "product_json_unavailable",
                }
            )
            continue
        try:
            product_html = request_text(url)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            print(f"[stop] {url}: {exc}", flush=True)
            break
        product_rows, summary = row_for_product(product, url, product_html, started_at)
        rows.extend(product_rows)
        product_summaries.append(summary)
        scanned += 1
        print(f"[product {index}/{len(url_by_handle)}] rows={len(product_rows)} total={len(rows)} {handle}", flush=True)
        if args.limit_products and scanned >= args.limit_products:
            break
        if args.request_delay_seconds:
            time.sleep(args.request_delay_seconds)

    rows = dedupe_rows(rows)
    finished_at = utc_now()
    exhaustive = not errors and not args.limit_products and scanned == len(url_by_handle)
    summary = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_sitemap_product_page_model_metafield",
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": {
            "shopify_products_json": catalog_summary,
            "sitemap": sitemap_summary,
            "lead_urls": {"urls": lead_urls, "count": len(lead_urls)},
            "reconciled_unique_product_urls": len(url_by_handle),
        },
        "products_discovered": len(url_by_handle),
        "products_scanned": scanned,
        "product_pages_scanned": scanned,
        "review_pages_scanned": 0,
        "exhaustive_review_paging": True,
        "coverage_exhaustive": exhaustive,
        "scrape_scope_status": "full_public_catalog_complete" if exhaustive else "stopped_or_limited",
        "catalog_model_rows_enabled": True,
        "customer_review_feed_used": False,
        "access_policy": "public Shopify products.json, sitemap, and product pages only; one product-page fetch per product; stop on 429/captcha/WAF",
        "product_summaries": product_summaries,
        "errors": errors,
    }
    return rows, summary


def write_outputs(rows: Sequence[Dict[str, str]], summary: Dict[str, object]) -> None:
    write_intake_csv(rows, OUTPUT_CSV)
    rows_with_product_url = sum(1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display"))
    rows_with_measurements = sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS))
    rows_with_customer_image = sum(
        1
        for row in rows
        if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image"
    )
    rows_with_catalog_image = sum(
        1
        for row in rows
        if row.get("original_url_display") and row.get("image_source_type") == "catalog_model_image"
    )
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
    parser = argparse.ArgumentParser(description="Scrape Ripley Rader public catalog model images and model measurements.")
    parser.add_argument("--catalog-limit", type=int, default=250)
    parser.add_argument("--max-catalog-pages", type=int, default=50)
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
