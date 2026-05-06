#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from step1_intake_utils import (
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


SITE_ROOT = "https://aliava.com"
DOMAIN = "aliava.com"
RETAILER = "aliava_com"
CATALOG_URL = f"{SITE_ROOT}/products.json"
BLOCK_RE = re.compile(r"(captcha|cloudflare|access denied|temporarily blocked|suspicious request|bot detection|waf)", re.I)
MODEL_RE = re.compile(
    r"\bModel(?:\s+Measurement)?\s*:\s*Model\s+is\s+"
    r"(?P<feet>\d)\s*(?:ft|feet|foot|')\s*(?P<inches>\d{0,2})"
    r"(?:\s*(?:in|inches|\"))?\s+and\s+wears?\s+size\s+(?P<size>[A-Z0-9/.-]+)\b",
    re.I,
)
APPAREL_RE = re.compile(r"\b(dress|gown|skirt|top|corset|bodysuit|jumpsuit|romper|pant|trouser|jean|short)\b", re.I)


class PressureStop(RuntimeError):
    pass


def catalog_url(page: int, limit: int) -> str:
    return f"{CATALOG_URL}?limit={limit}&page={page}"


def product_url(handle: str) -> str:
    return f"{SITE_ROOT}/products/{handle}"


def fetch_json_public(url: str, referer: str = SITE_ROOT, timeout: int = 45) -> Dict[str, object]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            text = response.read().decode("utf-8-sig", errors="replace")
    except HTTPError as exc:
        if exc.code in {401, 403, 407, 408, 423, 429, 430, 503}:
            raise PressureStop(f"stopping on HTTP {exc.code} for {url}") from exc
        raise
    except URLError as exc:
        raise PressureStop(f"stopping on URL error for {url}: {exc}") from exc
    if BLOCK_RE.search(text[:5000]):
        raise PressureStop(f"stopping on challenge marker for {url}")
    return json.loads(text)


def is_apparel(product: Dict[str, object]) -> bool:
    text = " ".join(
        [
            normalize_whitespace(product.get("title")),
            normalize_whitespace(product.get("product_type")),
            normalize_whitespace(" ".join(str(tag) for tag in product.get("tags", []) or [])),
            strip_tags(product.get("body_html")),
        ]
    )
    context = context_for_product(product)
    return bool(classify_clothing_type(context) or APPAREL_RE.search(text))


def context_for_product(product: Dict[str, object]) -> ProductContext:
    handle = normalize_whitespace(product.get("handle"))
    title = normalize_whitespace(product.get("title"))
    body = strip_tags(product.get("body_html"))
    tags = product.get("tags", []) or []
    first_variant = (product.get("variants") or [{}])[0] if isinstance(product.get("variants"), list) else {}
    return ProductContext(
        url=product_url(handle),
        title=title,
        description=body,
        detail=normalize_whitespace(" ".join(str(tag) for tag in tags)),
        category=normalize_whitespace(product.get("product_type")),
        brand=normalize_whitespace(product.get("vendor")) or "Aliava",
        color=normalize_whitespace(first_variant.get("option1") if isinstance(first_variant, dict) else ""),
        variant=normalize_whitespace(first_variant.get("title") if isinstance(first_variant, dict) else ""),
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=urlparse(SITE_ROOT).netloc,
        provider_hints="shopify_products_json_catalog_model",
    )


def model_comment_and_size(product: Dict[str, object]) -> Tuple[str, str]:
    text = strip_tags(product.get("body_html"))
    match = MODEL_RE.search(text)
    if not match:
        return "", ""
    feet = int(match.group("feet"))
    inches = int(match.group("inches") or 0)
    size = normalize_whitespace(match.group("size"))
    return f"Model is {feet} ft {inches} in and wears size {size}.", size


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
    summary: Dict[str, object] = {
        "product_url": context.url,
        "product_title": context.title,
        "shopify_product_id": context.product_id,
        "product_type": context.category,
        "clothing_type_id": classify_clothing_type(context),
        "skipped_from_output": False,
        "skip_reason": "",
        "matching_catalog_model_images": 0,
        "matching_review_images": 0,
    }
    if not is_apparel(product):
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "out_of_scope_non_apparel"
        return [], summary
    comment, size = model_comment_and_size(product)
    if not comment:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "no_model_measurement_text"
        return [], summary
    src = image_url(product)
    if not src:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "no_product_image"
        return [], summary
    review = ReviewImage(
        image_url=src,
        review_id="aliava-model-" + hashlib.md5(f"{context.url}|{src}|{comment}".encode("utf-8")).hexdigest()[:16],
        review_title="Catalog model measurements",
        review_body=comment,
        size_raw=size,
        extra={
            "image_source_type": "catalog_model_image",
            "image_source_detail": "public Shopify products.json catalog image with product-description model measurements",
        },
    )
    row = build_intake_row(context, review, fetched_at)
    summary["matching_catalog_model_images"] = 1
    summary["matching_review_images"] = 1
    return [row], summary


def scrape(limit: int, request_delay_seconds: float, max_pages: int) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    products_discovered = 0
    pages_scanned = 0
    errors: List[str] = []
    stopped_for_pressure = False
    for page in range(1, max_pages + 1):
        url = catalog_url(page, limit)
        try:
            payload = fetch_json_public(url)
        except PressureStop as exc:
            errors.append(str(exc))
            stopped_for_pressure = True
            break
        products = payload.get("products") if isinstance(payload, dict) else []
        if not isinstance(products, list) or not products:
            break
        pages_scanned += 1
        products_discovered += len(products)
        for product in products:
            if isinstance(product, dict):
                product_rows, summary = row_for_product(product, started_at)
                rows.extend(product_rows)
                product_summaries.append(summary)
        print(f"[aliava page {page}] products={len(products)} rows={len(rows)}", flush=True)
        if len(products) < limit:
            break
        if request_delay_seconds:
            time.sleep(request_delay_seconds)
    rows = dedupe_rows(rows)
    return rows, {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_catalog_model_sitewide",
        "started_at": started_at,
        "finished_at": utc_now(),
        "products_discovered": products_discovered,
        "products_scanned": products_discovered,
        "product_pages_scanned": products_discovered,
        "catalog_pages_scanned": pages_scanned,
        "scrape_scope_status": "stopped_for_pressure" if stopped_for_pressure else "full_public_catalog_products_json_complete",
        "full_catalog_scrape_complete": not stopped_for_pressure,
        "stopped_for_pressure": stopped_for_pressure,
        "catalog_model_rows_enabled": True,
        "aggregate_feed_used": False,
        "customer_review_feed_used": False,
        "access_policy": "public_shopify_products_json_only; no_auth_bypass; no_captcha_bypass; stop_on_429_or_challenge",
        "product_summaries": product_summaries,
        "errors": errors,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Aliava public catalog model image/measurement rows.")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--request-delay-seconds", type=float, default=1.0)
    parser.add_argument("--max-pages", type=int, default=100)
    args = parser.parse_args(argv)
    rows, summary = scrape(args.limit, args.request_delay_seconds, args.max_pages)
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
    print(json.dumps({
        RETAILER: {
            "rows": len(rows),
            "catalog_model_rows": payload.get("rows_with_catalog_model_image", 0),
            "qualified_rows": payload.get("rows_with_image_product_size_and_measurement", 0),
            "products_discovered": summary["products_discovered"],
            "stopped_for_pressure": summary["stopped_for_pressure"],
            "output_csv": str(output_csv),
        }
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
