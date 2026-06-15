#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import urljoin, urlparse

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


SITE_ROOT = "https://catchallstore.com"
DOMAIN = "catchallstore.com"
RETAILER = "catchallstore_com"
SAMPLE_URL = f"{SITE_ROOT}/products/astrid-pink-jacquard-floral-mini-dress"

PRODUCT_LINK_RE = re.compile(r"(?:https://catchallstore\.com)?/products/[a-z0-9][a-z0-9-]+", re.I)
META_RE = re.compile(
    r"<meta\s+(?:name|property)=[\"'](?P<name>[^\"']+)[\"']\s+content=[\"'](?P<content>.*?)[\"']\s*/?>",
    re.I | re.S,
)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
MODEL_SIZE_RE = re.compile(
    r"model\s+(?:is|was|height)?[^.]{0,100}?(?:wears?|is wearing|size)\s+(?:a\s+)?(?:size\s+)?([A-Z0-9/ .-]{1,12})\b",
    re.I,
)
MODEL_MEASUREMENT_RE = re.compile(
    r"model\s+(?:is|was|height)?[^.]{0,120}?(?:\d\s*(?:ft|feet|foot|')|\d{2,3}\s*(?:cm|lbs?|pounds?)|\d{2,3}\s*(?:\"|in(?:ches)?))",
    re.I,
)
IMG_RE = re.compile(r"https?://img-[^\"'<>)\\ ]+myshopline\.com/image/store/1694484096840/[^\"'<>)\\ ]+", re.I)


def canonical_product_url(url: str) -> str:
    parsed = urlparse(urljoin(SITE_ROOT, url))
    path = parsed.path.rstrip("/")
    if not path.startswith("/products/") or path == "/products/batch":
        return ""
    return f"{SITE_ROOT}{path}"


def product_links(html_text: str) -> List[str]:
    links = []
    for match in PRODUCT_LINK_RE.finditer(html_text):
        url = canonical_product_url(match.group(0))
        if url:
            links.append(url)
    return sorted(set(links))


def meta_values(html_text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for match in META_RE.finditer(html_text):
        name = normalize_whitespace(match.group("name")).lower()
        content = html.unescape(normalize_whitespace(match.group("content")))
        if name and content and name not in values:
            values[name] = content
    title_match = TITLE_RE.search(html_text)
    if title_match:
        values["title"] = html.unescape(normalize_whitespace(strip_tags(title_match.group(1))))
    return values


def clean_image_url(url: str) -> str:
    url = html.unescape(url).replace("\\u0026", "&")
    return re.sub(r"([?&])q=70&?", r"\1", url).rstrip("?&")


def image_candidates(html_text: str, meta: Dict[str, str]) -> List[str]:
    images = []
    for key in ("og:image", "og:image:secure_url", "twitter:image"):
        if meta.get(key):
            images.append(clean_image_url(meta[key]))
    for match in IMG_RE.finditer(html_text):
        images.append(clean_image_url(match.group(0)))
    deduped = []
    seen = set()
    for image in images:
        base = re.sub(r"([?&])(w|h|q)=[^&]+", "", image)
        if base in seen:
            continue
        seen.add(base)
        deduped.append(image)
    return deduped


def is_accessory(title: str) -> bool:
    return bool(re.search(r"\b(necklace|earrings?|bag|bracelet|ring|jewelry|jewellery)\b", title.lower()))


def is_apparel_context(context: ProductContext) -> bool:
    if classify_clothing_type(context):
        return True
    return bool(
        re.search(
            r"\b(dress|jumpsuit|romper|set|blazer|suit|top|skirt|pant|trouser|jean|shorts?|gown|coat|jacket)\b",
            f"{context.title} {context.description}",
            re.I,
        )
    )


def context_for(url: str, html_text: str, meta: Dict[str, str]) -> ProductContext:
    title = normalize_whitespace(meta.get("og:title") or meta.get("title"))
    title = re.sub(r"\s+[–-]\s+CATCHALL\s*$", "", title, flags=re.I)
    description = normalize_whitespace(meta.get("description") or meta.get("og:description") or meta.get("twitter:description"))
    return ProductContext(
        url=url,
        title=title,
        description=description,
        detail=description,
        category=title,
        brand="CATCHALL",
        raw_html=html_text,
        provider_hints="catalog_model_product_page",
    )


def model_size(text: str) -> str:
    text = re.sub(r"([A-Za-z0-9])Colou?r\b", r"\1 Colour", text)
    match = MODEL_SIZE_RE.search(text)
    if not match:
        return ""
    size = normalize_whitespace(match.group(1))
    size = re.sub(r"\b(colou?r|may|vary|due|to|lighting|on|images|the|product|item|runs).*$", "", size, flags=re.I)
    size = re.sub(r"(XXS|XS|S|M|L|XL|XXL|XXXL|[0-9]{1,2})(?:Colou?r.*)$", r"\1", size, flags=re.I)
    return normalize_whitespace(size.strip(" .,-;:"))


def has_model_measurement(text: str) -> bool:
    return bool(MODEL_MEASUREMENT_RE.search(text))


def row_for_product(url: str, html_text: str, fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    meta = meta_values(html_text)
    context = context_for(url, html_text, meta)
    description = context.description
    summary: Dict[str, object] = {
        "product_url": url,
        "product_title": context.title,
        "clothing_type_id": classify_clothing_type(context),
        "links_discovered": len(product_links(html_text)),
        "catalog_model_images": 0,
        "rows": 0,
        "skipped_from_output": False,
        "skip_reason": "",
    }
    if is_accessory(context.title) or not is_apparel_context(context):
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "out_of_scope_accessory_or_unclear_product_type"
        return [], summary
    if not has_model_measurement(description):
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "no_catalog_model_measurement_found"
        return [], summary
    images = image_candidates(html_text, meta)
    if not images:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "no_catalog_model_image_found"
        return [], summary
    size = model_size(description)
    # Prefer the primary OpenGraph image; Catchall descriptions explicitly say product images without model
    # are closest to color, so the first PDP/OG image is the best model-image candidate available.
    image_url = images[0]
    row_id = "catchall-model-" + hashlib.md5(f"{url}|{image_url}|{description}".encode("utf-8")).hexdigest()[:16]
    review = ReviewImage(
        image_url=image_url,
        review_id=row_id,
        review_title="Catalog model measurements",
        review_body=description,
        size_raw=size,
        extra={
            "image_source_type": "catalog_model_image",
            "image_source_detail": "product page catalog/model image; model measurements from product description",
        },
    )
    row = build_intake_row(context, review, fetched_at)
    summary["catalog_model_images"] = 1
    summary["rows"] = 1
    return [row], summary


def scrape(seed_urls: Sequence[str], max_products: int, request_delay_seconds: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    queue = deque(canonical_product_url(url) for url in seed_urls)
    seen: Set[str] = set()
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    challenged_endpoints = [
        f"{SITE_ROOT}/products.json?limit=5&page=1",
        f"{SITE_ROOT}/sitemap.xml",
        f"{SITE_ROOT}/collections/all",
        f"{SITE_ROOT}/ajax/openapi/recommendations/products?section_id=template--product__recommended-product&product_id=16061095767631798016190975&limit=12",
    ]
    while queue and len(seen) < max_products:
        url = queue.popleft()
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            html_text = fetch_text(url, referer=SITE_ROOT)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue
        if "Just a moment..." in html_text and "challenges.cloudflare.com" in html_text:
            errors.append(f"{url}: cloudflare_challenge")
            continue
        product_rows, summary = row_for_product(url, html_text, started_at)
        product_summaries.append(summary)
        rows.extend(product_rows)
        for link in product_links(html_text):
            if link not in seen and len(seen) + len(queue) < max_products:
                queue.append(link)
        print(f"[catchall {len(seen)}/{max_products}] rows={len(product_rows)} queue={len(queue)} url={url}", flush=True)
        if request_delay_seconds:
            time.sleep(request_delay_seconds)
    rows = dedupe_rows(rows)
    summary = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopline_product_page_catalog_model_crawl",
        "started_at": started_at,
        "finished_at": utc_now(),
        "seed_urls": list(seed_urls),
        "blocked_public_catalog_endpoints": challenged_endpoints,
        "discovery_method": "product_page_link_crawl_from_seed; catalog/listing endpoints returned Cloudflare managed challenge",
        "scrape_scope_status": "partial_product_page_crawl_catalog_blocked",
        "full_catalog_scrape_complete": False,
        "products_discovered": len(seen) + len(queue),
        "products_scanned": len(seen),
        "product_pages_scanned": len(seen),
        "aggregate_feed_used": False,
        "customer_review_feed_used": False,
        "catalog_model_rows_enabled": True,
        "access_policy": "public_product_pages_only; blocked_catalog_endpoints_not_retried; no_auth_bypass; no_captcha_bypass",
        "product_summaries": product_summaries,
        "errors": errors,
    }
    return rows, summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Catchall public product pages for catalog model image+measurement rows.")
    parser.add_argument("--seed-url", action="append", default=[SAMPLE_URL])
    parser.add_argument("--max-products", type=int, default=250)
    parser.add_argument("--request-delay-seconds", type=float, default=0.75)
    args = parser.parse_args(argv)

    rows, summary = scrape(args.seed_url, args.max_products, args.request_delay_seconds)
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
