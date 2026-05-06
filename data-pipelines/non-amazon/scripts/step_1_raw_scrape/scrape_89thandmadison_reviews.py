#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    classify_clothing_type,
    dedupe_rows,
    fetch_text,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    write_intake_csv,
    write_summary,
)


SITE_ROOT = "https://89thandmadison.com"
DOMAIN = "89thandmadison.com"
RETAILER = "89thandmadison_com"
CATALOG_URL = f"{SITE_ROOT}/products.json"

BLOCK_MARKERS = [
    "Just a moment...",
    "challenges.cloudflare.com",
    "cf-chl",
    "captcha",
    "Access denied",
]

APPAREL_WORD_RE = re.compile(
    r"\b("
    r"bra|bralette|dress|gown|jumpsuit|romper|pajamas?|pyjamas?|set|blazer|suit|top|tee|t-shirt|shirt|"
    r"tank|camisole|sweater|cardigan|jacket|coat|vest|skirt|skort|pant|trouser|jean|legging|shorts?|"
    r"bodysuit|tunic|blouse"
    r")\b",
    re.I,
)
ACCESSORY_WORD_RE = re.compile(
    r"\b("
    r"slipper|shoe|boot|sandal|sock|hat|cap|belt|bag|purse|wallet|scarf|necklace|earrings?|bracelet|"
    r"jewelry|jewellery|ring|glove|mittens?|blanket|tote|keychain|gift\s*card"
    r")\b",
    re.I,
)
MODEL_TEXT_RE = re.compile(
    r"\bmodel\b[^.]{0,180}?\b("
    r"\d\s*(?:ft|feet|foot|')\s*\d{0,2}|height|chest|bust|waist|hips?|wears?|wearing|size"
    r")\b",
    re.I,
)
MODEL_SIZE_RE = re.compile(
    r"\b(?:wears?|wearing)\s+(?:a\s+)?(?:size\s+)?([A-Z0-9/ .-]{1,16})\b",
    re.I,
)
MODEL_PROFILE_RE = re.compile(
    r"\bmodel\s+height\s+is\s+"
    r"(?P<height>\d\s*(?:ft|feet|foot|')\s*\d{0,2}\s*(?:in|inches|\"|”)?)[\s,;]*"
    r"(?:(?:chest|bust)\s*(?:is\s*)?(?P<chest>\d{2,3}(?:\.\d+)?)\s*(?:\"|in|inches)?[\s,;]*)?"
    r"(?:wears?|wearing)\s+(?:a\s+)?(?:size\s+)?(?P<size>[A-Z0-9/.-]+)\b",
    re.I,
)


def catalog_url(page: int, limit: int) -> str:
    return f"{CATALOG_URL}?limit={limit}&page={page}"


def product_url(handle: str) -> str:
    return f"{SITE_ROOT}/products/{handle}"


def fetch_catalog_page(page: int, limit: int) -> Dict[str, object]:
    url = catalog_url(page, limit)
    text = fetch_text(url, accept="application/json,text/plain,*/*", referer=SITE_ROOT)
    if any(marker.lower() in text.lower() for marker in BLOCK_MARKERS):
        raise RuntimeError(f"blocked_or_challenged_public_catalog_endpoint: {url}")
    return json.loads(text)


def product_text(product: Dict[str, object]) -> str:
    body = strip_tags(product.get("body_html"))
    parts = [
        product.get("title"),
        product.get("product_type"),
        " ".join(str(tag) for tag in product.get("tags", []) or []),
        body,
    ]
    return normalize_whitespace(" ".join(str(part or "") for part in parts))


def is_apparel_product(product: Dict[str, object]) -> bool:
    text = product_text(product)
    if ACCESSORY_WORD_RE.search(text) and not APPAREL_WORD_RE.search(text):
        return False
    context = ProductContext(
        url=product_url(str(product.get("handle") or "")),
        title=normalize_whitespace(product.get("title")),
        description=strip_tags(product.get("body_html")),
        category=normalize_whitespace(product.get("product_type")),
        brand="89th & Madison",
    )
    return bool(classify_clothing_type(context) or APPAREL_WORD_RE.search(text))


def has_model_measurements(product: Dict[str, object]) -> bool:
    return bool(MODEL_TEXT_RE.search(product_text(product)))


def model_size(product: Dict[str, object]) -> str:
    text = product_text(product)
    profile_match = MODEL_PROFILE_RE.search(text)
    if profile_match:
        return normalize_whitespace(profile_match.group("size"))
    match = MODEL_SIZE_RE.search(text)
    if not match:
        return ""
    size = normalize_whitespace(match.group(1))
    size = re.sub(r"\b(?:and|in|the|photo|image|shown|for|reference|materials?).*$", "", size, flags=re.I)
    return normalize_whitespace(size.strip(" .,-;:"))


def model_profile_comment(product: Dict[str, object]) -> str:
    text = product_text(product)
    match = MODEL_PROFILE_RE.search(text)
    if not match:
        return strip_tags(product.get("body_html"))
    height = normalize_whitespace(match.group("height"))
    height = height.replace("'", " ft ").replace('"', " in")
    height = normalize_whitespace(height)
    if not re.search(r"\bin\b", height, re.I):
        height = normalize_whitespace(f"{height} in")
    parts = [f"Model height is {height}."]
    chest = normalize_whitespace(match.group("chest"))
    if chest:
        parts.append(f"Chest is {chest} in.")
    parts.append(f"Wearing size {normalize_whitespace(match.group('size'))}.")
    return " ".join(parts)


def image_score(image: Dict[str, object], index: int) -> Tuple[int, int]:
    alt = normalize_whitespace(image.get("alt")).lower()
    src = normalize_whitespace(image.get("src")).lower()
    score = 0
    if "model" in alt or "model" in src:
        score += 20
    if re.search(r"\b(wearing|wears|shown|front|look)\b", alt):
        score += 8
    if re.search(r"\b(flat|swatch|detail|back|color)\b", alt):
        score -= 5
    return score, -index


def catalog_model_image(product: Dict[str, object]) -> str:
    images = [img for img in product.get("images", []) or [] if normalize_whitespace(img.get("src"))]
    if not images:
        return ""
    ranked = sorted(enumerate(images), key=lambda item: image_score(item[1], item[0]), reverse=True)
    return normalize_whitespace(ranked[0][1].get("src"))


def context_for_product(product: Dict[str, object]) -> ProductContext:
    handle = normalize_whitespace(product.get("handle"))
    title = normalize_whitespace(product.get("title"))
    description = strip_tags(product.get("body_html"))
    category = normalize_whitespace(product.get("product_type"))
    tags = product.get("tags", []) or []
    return ProductContext(
        url=product_url(handle),
        title=title,
        description=description,
        detail=normalize_whitespace(" ".join(str(tag) for tag in tags)),
        category=category,
        brand=normalize_whitespace(product.get("vendor")) or "89th & Madison",
        handle=handle,
        product_id=str(product.get("id") or ""),
        shop_domain=urlparse(SITE_ROOT).netloc,
        provider_hints="shopify_products_json_catalog_model",
    )


def row_for_product(product: Dict[str, object], fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    context = context_for_product(product)
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
    if not is_apparel_product(product):
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "out_of_scope_non_apparel"
        return [], summary
    if not has_model_measurements(product):
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "no_catalog_model_measurement_found"
        return [], summary
    image_url = catalog_model_image(product)
    if not image_url:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "no_catalog_model_image_found"
        return [], summary
    size = model_size(product)
    row_id = "89th-model-" + hashlib.md5(f"{context.url}|{image_url}|{context.description}".encode("utf-8")).hexdigest()[:16]
    review = ReviewImage(
        image_url=image_url,
        review_id=row_id,
        review_title="Catalog model measurements",
        review_body=model_profile_comment(product),
        size_raw=size,
        extra={
            "image_source_type": "catalog_model_image",
            "image_source_detail": "public Shopify products.json catalog/model image; model measurements from product description",
        },
    )
    row = build_intake_row(context, review, fetched_at)
    summary["rows"] = 1
    summary["catalog_model_image"] = image_url
    summary["catalog_model_size"] = size
    return [row], summary


def scrape(limit: int, max_pages: int, request_delay_seconds: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    products_discovered = 0
    pages_scanned = 0
    for page in range(1, max_pages + 1):
        url = catalog_url(page, limit)
        try:
            payload = fetch_catalog_page(page, limit)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            break
        products = payload.get("products", []) or []
        if not products:
            break
        pages_scanned += 1
        products_discovered += len(products)
        for product in products:
            product_rows, product_summary = row_for_product(product, started_at)
            product_summaries.append(product_summary)
            rows.extend(product_rows)
        print(
            f"[89th page {page}] products={len(products)} rows_total={len(rows)} url={url}",
            flush=True,
        )
        if len(products) < limit:
            break
        if request_delay_seconds:
            time.sleep(request_delay_seconds)
    rows = dedupe_rows(rows)
    summary = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_catalog_model_sitewide",
        "started_at": started_at,
        "finished_at": utc_now(),
        "catalog_endpoint": CATALOG_URL,
        "discovery_method": "public Shopify products.json full catalog pagination",
        "scrape_scope_status": "full_public_catalog_products_json_complete" if not errors else "stopped_after_public_endpoint_error",
        "full_catalog_scrape_complete": not errors,
        "products_discovered": products_discovered,
        "products_scanned": products_discovered,
        "product_pages_scanned": products_discovered,
        "catalog_pages_scanned": pages_scanned,
        "aggregate_feed_used": False,
        "customer_review_feed_used": False,
        "catalog_model_rows_enabled": True,
        "access_policy": "public_shopify_products_json_only; no_auth_bypass; no_captcha_bypass",
        "product_summaries": product_summaries,
        "errors": errors,
    }
    return rows, summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape 89th & Madison public catalog model images and measurements.")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--request-delay-seconds", type=float, default=0.5)
    args = parser.parse_args(argv)

    rows, summary = scrape(args.limit, args.max_pages, args.request_delay_seconds)
    output_csv, summary_json = output_paths(DOMAIN)
    write_intake_csv(rows, output_csv)
    write_summary(
        summary_json,
        site=SITE_ROOT,
        retailer=DOMAIN,
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
    print(f"CSV: {output_csv}")
    print(f"Summary: {summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
