#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    output_paths,
    normalize_whitespace,
    strip_tags,
    utc_now,
    validate_rows,
    write_intake_csv,
)


SITE_ROOT = "https://rollasjeans.com"
RETAILER = "rollasjeans_com"
SAMPLE_CATEGORY_URL = f"{SITE_ROOT}/collections/womens/clothing/tops"
SAMPLE_PDP_URLS = [
    f"{SITE_ROOT}/products/petal-bloom-blouse",
    f"{SITE_ROOT}/products/script-ringer-tee",
    f"{SITE_ROOT}/products/classic-ringer-tee-petite-logo-cream",
]
OUTPUT_CSV, SUMMARY_JSON = output_paths(RETAILER)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
PRESSURE_STATUS_CODES = {401, 403, 407, 423, 429, 430, 503}
BLOCK_RE = re.compile(
    r"\b(?:captcha|cloudflare challenge|cf-chl|datadome|perimeterx|awswaf|access denied|"
    r"attention required|verify you are human|temporarily blocked)\b",
    re.I,
)
PROVIDER_RE = re.compile(r"\b(okendo|judge\.me|judgeme|loox|stamped|yotpo|bazaarvoice|powerreviews)\b", re.I)


class StopScrape(RuntimeError):
    pass


def fetch_text(url: str, *, referer: str = SITE_ROOT, delay: float = 0.35) -> str:
    time.sleep(delay)
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        },
    )
    try:
        with urlopen(request, timeout=45) as response:
            status = int(getattr(response, "status", 200))
            text = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code in PRESSURE_STATUS_CODES:
            raise StopScrape(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
        raise
    except URLError as exc:
        raise StopScrape(f"network_error: {url}: {exc}") from exc
    if status in PRESSURE_STATUS_CODES:
        raise StopScrape(f"blocked_or_rate_limited_http_{status}: {url}")
    if BLOCK_RE.search(text[:120_000]):
        raise StopScrape(f"blocked_or_challenged_response: {url}")
    return text


def next_data_from_html(html_text: str, url: str) -> Dict[str, object]:
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_text, re.S)
    if not match:
        raise StopScrape(f"missing_next_data: {url}")
    payload = json.loads(html.unescape(match.group(1)))
    if not isinstance(payload, dict):
        raise StopScrape(f"unexpected_next_data: {url}")
    return payload


def get_page_props(payload: Dict[str, object]) -> Dict[str, object]:
    props = payload.get("props")
    if isinstance(props, dict) and isinstance(props.get("pageProps"), dict):
        return props["pageProps"]  # type: ignore[return-value]
    return {}


def plain_rich_text(value: object) -> str:
    if isinstance(value, str):
        return normalize_whitespace(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(normalize_whitespace(item.get("text")))
            else:
                parts.append(normalize_whitespace(item))
        return normalize_whitespace(" ".join(part for part in parts if part))
    return normalize_whitespace(value)


def nested_value(payload: object, *keys: str) -> object:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def category_product_urls(category_url: str, html_text: str) -> List[str]:
    payload = next_data_from_html(html_text, category_url)
    page_props = get_page_props(payload)
    urls: List[str] = []
    edges = nested_value(page_props, "collection", "products", "edges")
    if isinstance(edges, list):
        for edge in edges:
            handle = nested_value(edge, "node", "handle")
            if handle:
                urls.append(f"{SITE_ROOT}/products/{normalize_whitespace(handle)}")
    if not urls:
        for match in re.findall(r"href=['\"]([^'\"]*/products/[^'\"#?]+)", html_text, re.I):
            urls.append(urljoin(SITE_ROOT, html.unescape(match)))
    return list(dict.fromkeys(urls))


def media_images(product: Dict[str, object], limit: int) -> List[Dict[str, str]]:
    candidates: List[Dict[str, str]] = []
    edges = nested_value(product, "media", "edges")
    if isinstance(edges, list):
        for edge in edges:
            node = edge.get("node") if isinstance(edge, dict) else None
            if not isinstance(node, dict):
                continue
            image = node.get("image") or node.get("previewImage")
            if not isinstance(image, dict):
                continue
            url = normalize_whitespace(image.get("url"))
            if not url:
                continue
            candidates.append(
                {
                    "url": url,
                    "id": normalize_whitespace(node.get("id") or image.get("id")),
                    "alt": normalize_whitespace(image.get("altText") or node.get("alt")),
                }
            )
    image_edges = nested_value(product, "images", "edges")
    if isinstance(image_edges, list):
        for edge in image_edges:
            node = edge.get("node") if isinstance(edge, dict) else None
            if not isinstance(node, dict):
                continue
            url = normalize_whitespace(node.get("url"))
            if url:
                candidates.append(
                    {
                        "url": url,
                        "id": normalize_whitespace(node.get("id")),
                        "alt": normalize_whitespace(node.get("altText")),
                    }
                )
    seen = set()
    unique: List[Dict[str, str]] = []
    for item in candidates:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def variant_summary(product: Dict[str, object]) -> Tuple[str, str]:
    values: List[str] = []
    variants = nested_value(product, "variants", "edges")
    if isinstance(variants, list):
        for edge in variants:
            node = edge.get("node") if isinstance(edge, dict) else None
            if not isinstance(node, dict):
                continue
            label = normalize_whitespace(node.get("title"))
            if label:
                values.append(label)
            selected = node.get("selectedOptions")
            if isinstance(selected, list):
                values.extend(
                    normalize_whitespace(option.get("value"))
                    for option in selected
                    if isinstance(option, dict) and option.get("value")
                )
    sizes = []
    for option in product.get("options", []) if isinstance(product.get("options"), list) else []:
        if not isinstance(option, dict):
            continue
        if normalize_whitespace(option.get("name")).lower() == "size":
            option_values = option.get("values")
            if isinstance(option_values, list):
                sizes.extend(normalize_whitespace(value) for value in option_values)
    return " | ".join(dict.fromkeys(values[:60])), " / ".join(dict.fromkeys(sizes))


def model_details(model: object) -> Tuple[str, str, str]:
    if not isinstance(model, dict):
        return "", "", ""
    data = model.get("data")
    if not isinstance(data, dict):
        return "", "", ""
    model_name = plain_rich_text(data.get("model_name"))
    model_blurb = plain_rich_text(data.get("model_blurb"))
    detail_parts: List[str] = []
    size_by_label: Dict[str, str] = {}
    details = data.get("details")
    if isinstance(details, list):
        for detail in details:
            if not isinstance(detail, dict):
                continue
            label = plain_rich_text(detail.get("detail_label"))
            value = plain_rich_text(detail.get("detail_value"))
            if label and value:
                detail_parts.append(f"{label}: {value}")
                if label.lower() in {"apparel size", "denim size", "size"}:
                    size_by_label[label.lower()] = value
    size = size_by_label.get("apparel size") or size_by_label.get("size") or size_by_label.get("denim size") or ""
    return model_name, size, normalize_whitespace("; ".join(detail_parts + ([model_blurb] if model_blurb else [])))


def product_context(product_url: str, page_props: Dict[str, object]) -> Tuple[ProductContext, str, str]:
    product = page_props.get("product")
    if not isinstance(product, dict):
        raise StopScrape(f"missing_product_payload: {product_url}")
    model_name, model_size, model_detail = model_details(page_props.get("model"))
    variant_detail, size_values = variant_summary(product)
    category_titles = []
    collections = nested_value(product, "collections", "edges")
    if isinstance(collections, list):
        for edge in collections:
            title = nested_value(edge, "node", "title")
            if title:
                category_titles.append(normalize_whitespace(title))
    color = normalize_whitespace(nested_value(product, "colourName", "value"))
    description = strip_tags(product.get("descriptionHtml")) or normalize_whitespace(product.get("description"))
    detail_bits = [
        model_detail,
        f"Available sizes: {size_values}" if size_values else "",
        f"Variants: {variant_detail}" if variant_detail else "",
        f"Fit: {normalize_whitespace(nested_value(product, 'fitSize', 'value'))}" if nested_value(product, "fitSize", "value") else "",
        f"Stretch: {normalize_whitespace(nested_value(product, 'fitStretch', 'value'))}" if nested_value(product, "fitStretch", "value") else "",
    ]
    product_id = normalize_whitespace(product.get("id")).replace("gid://shopify/Product/", "")
    handle = normalize_whitespace(product.get("handle")) or product_url.rstrip("/").rsplit("/", 1)[-1]
    context = ProductContext(
        url=product_url,
        title=normalize_whitespace(product.get("title")),
        description=description,
        detail=" | ".join(part for part in detail_bits if part),
        category=" > ".join(dict.fromkeys(category_titles[:8])) or "Women's Tops",
        brand=normalize_whitespace(product.get("vendor")) or "Rolla's Jeans",
        color=color,
        product_id=product_id,
        handle=handle,
        shop_domain="rollasjeans.com",
        provider_hints="review provider unresolved/custom Next.js copy; no public review payload found in PDP data",
    )
    return context, model_name, model_size


def probe_provider(html_text: str) -> List[str]:
    return sorted({match.group(1).lower() for match in PROVIDER_RE.finditer(html_text)})


def scrape_product(product_url: str, *, image_limit: int, delay: float) -> Tuple[List[Dict[str, str]], Dict[str, object], List[str]]:
    html_text = fetch_text(product_url, delay=delay)
    provider_hits = probe_provider(html_text)
    payload = next_data_from_html(html_text, product_url)
    page_props = get_page_props(payload)
    product = page_props.get("product")
    if not isinstance(product, dict):
        return [], {"url": product_url, "skip_reason": "missing_product_payload"}, provider_hits
    context, model_name, model_size = product_context(product_url, page_props)
    images = media_images(product, image_limit)
    fetched_at = utc_now()
    rows = []
    for index, image in enumerate(images, start=1):
        review = ReviewImage(
            image_url=image["url"],
            review_id=f"rollasjeans_catalog_{context.handle}_{index}",
            review_body=context.detail,
            reviewer_name=model_name,
            size_raw=model_size,
            extra={
                "image_source_type": "catalog_model_image",
                "image_source_detail": "public PDP Shopify/Next catalog model image; customer review media feed not exposed",
                "product_detail": context.detail,
                "product_category": context.category,
                "product_title": context.title,
                "product_description": context.description,
            },
        )
        rows.append(build_intake_row(context, review, fetched_at))
    return rows, {
        "url": product_url,
        "title": context.title,
        "product_id": context.product_id,
        "handle": context.handle,
        "rows": len(rows),
        "image_source_type": "catalog_model_image",
        "model_name": model_name,
        "model_size": model_size,
        "provider_hits": provider_hits,
        "skip_reason": "" if rows else "no_catalog_images",
    }, provider_hits


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Rolla's Jeans public women tops PDP catalog/model fit media.")
    parser.add_argument("--max-products", type=int, default=0, help="Limit products after category+sample discovery; 0 means all.")
    parser.add_argument("--image-limit-per-product", type=int, default=2, help="Catalog images to emit per product.")
    parser.add_argument("--request-delay-seconds", type=float, default=0.4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started_at = utc_now()
    errors: List[str] = []
    category_html = fetch_text(SAMPLE_CATEGORY_URL, delay=args.request_delay_seconds)
    product_urls = category_product_urls(SAMPLE_CATEGORY_URL, category_html)
    for sample_url in SAMPLE_PDP_URLS:
        if sample_url not in product_urls:
            product_urls.append(sample_url)
    if args.max_products and args.max_products > 0:
        product_urls = product_urls[: args.max_products]

    all_rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    provider_hits_seen = set(probe_provider(category_html))
    for product_url in product_urls:
        try:
            rows, summary, provider_hits = scrape_product(
                product_url,
                image_limit=args.image_limit_per_product,
                delay=args.request_delay_seconds,
            )
        except StopScrape:
            raise
        except Exception as exc:
            errors.append(f"{product_url}: {type(exc).__name__}: {exc}")
            product_summaries.append({"url": product_url, "skip_reason": f"error: {type(exc).__name__}"})
            continue
        provider_hits_seen.update(provider_hits)
        all_rows.extend(rows)
        product_summaries.append(summary)

    rows = dedupe_rows(all_rows)
    write_intake_csv(rows, OUTPUT_CSV)
    finished_at = utc_now()
    summary = {
        "site": "rollasjeans.com",
        "retailer": RETAILER,
        "merchant": "Rolla's Jeans",
        "adapter": "nextjs_shopify_category_catalog_model_fallback",
        "access_policy": "public category/product pages only; stop_on_429_captcha_waf_auth",
        "triage_source": "data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv",
        "triage_bucket": "sovrn_first_pass_scrape_candidate",
        "commission_model": "CPC",
        "cpc_amount": "not populated in triage",
        "shipping_geos": "US",
        "review_platform_provider": "unknown_unresolved_custom_nextjs",
        "reviews_present_triage": True,
        "photo_reviews_present_triage": True,
        "customer_review_media_source_found": False,
        "catalog_model_fallback_used": True,
        "sample_category_url": SAMPLE_CATEGORY_URL,
        "sample_pdp_urls": SAMPLE_PDP_URLS,
        "category_product_links_found": len(category_product_urls(SAMPLE_CATEGORY_URL, category_html)),
        "products_discovered": len(product_urls),
        "products_scanned": len(product_summaries),
        "output_csv": str(OUTPUT_CSV),
        "started_at": started_at,
        "finished_at": finished_at,
        "stop_reason": "completed_public_catalog_model_fallback_scan",
        "blocked": False,
        "provider_hits_seen": sorted(provider_hits_seen),
        "product_summaries": product_summaries,
        "errors": errors,
    }
    summary.update(validate_rows(rows))
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
