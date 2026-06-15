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
from typing import Dict, Iterable, List, Sequence, Tuple
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


SITE = "https://www.foxylingerie.com"
RETAILER = "foxylingerie_com"
TRIAGE_CATEGORY_URL = f"{SITE}/collections/swimsuit-tops"
SCRAPE_CATEGORY_URL = f"{SITE}/collections/sexy-swimsuits"
TRIAGE_SAMPLE_PDPS = [
    f"{SITE}/products/sunset-gradient-ring-bikini-set",
    f"{SITE}/products/starfish-charm-scallop-bikini-set",
]
BLOCKING_STATUS_CODES = {401, 403, 407, 429, 503}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
BLOCK_BODY_RE = re.compile(r"\b(?:captcha|access denied|forbidden|too many requests|datadome|akamai)\b", re.I)
PRODUCT_LINK_RE = re.compile(r'href=["\'](/products/[^"\']+)["\']', re.I)
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I | re.S)
ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*(["\'])(.*?)\2', re.I | re.S)
REVIEWS_URL_RE = re.compile(r'data-reviews-url=["\']([^"\']+)["\']', re.I)
JSON_LD_RE = re.compile(r"<script[^>]+type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", re.I | re.S)


@dataclass
class ProductRecord:
    url: str
    title: str = ""
    description: str = ""
    detail: str = ""
    category: str = "Swimsuits"
    brand: str = "Foxy Lingerie"
    product_id: str = ""
    handle: str = ""
    color: str = ""
    variant: str = ""
    images: List[Dict[str, str]] = field(default_factory=list)
    reviews_url: str = ""
    review_html_length: int = 0
    review_has_more: bool = False
    review_count_label: str = ""
    customer_review_images: List[Dict[str, str]] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Focused Foxy Lingerie public swimsuit scrape.")
    parser.add_argument("--max-products", type=int, default=0, help="Debug cap on products; 0 scans all discovered products.")
    parser.add_argument("--max-pages", type=int, default=10, help="Max collection pages to inspect.")
    parser.add_argument("--sleep", type=float, default=0.05, help="Sleep between public requests.")
    return parser.parse_args()


def parse_attrs(tag: str) -> Dict[str, str]:
    return {match.group(1).lower(): html.unescape(match.group(3)) for match in ATTR_RE.finditer(tag)}


def curl_fetch_text(
    url: str,
    *,
    referer: str = SITE,
    accept: str = "text/html,application/json,*/*",
    xhr: bool = False,
    retries: int = 3,
) -> Tuple[str, Dict[str, str]]:
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
        if xhr:
            cmd.extend(["-H", "X-Requested-With: XMLHttpRequest"])
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


def normalize_url(value: str) -> str:
    clean = normalize_whitespace(html.unescape(value))
    if not clean:
        return ""
    clean = clean.split("?", 1)[0]
    return urljoin(SITE, clean)


def first_match(patterns: Sequence[str], text: str, flags: int = re.I | re.S) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return normalize_whitespace(html.unescape(match.group(1)))
    return ""


def json_ld_product(html_text: str) -> Dict[str, object]:
    for block in JSON_LD_RE.findall(html_text):
        try:
            payload = json.loads(html.unescape(block.strip()))
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            item_type = candidate.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(item).lower() == "product" for item in types):
                return candidate
    return {}


def discover_product_urls(args: argparse.Namespace) -> Tuple[List[str], List[Dict[str, object]]]:
    urls = list(TRIAGE_SAMPLE_PDPS)
    page_summaries: List[Dict[str, object]] = []
    previous_signature = None
    for page in range(1, args.max_pages + 1):
        page_url = SCRAPE_CATEGORY_URL if page == 1 else f"{SCRAPE_CATEGORY_URL}?page={page}"
        html_text, headers = curl_fetch_text(page_url, referer=TRIAGE_CATEGORY_URL)
        links = sorted({normalize_url(match.group(1)) for match in PRODUCT_LINK_RE.finditer(html_text)})
        signature = tuple(links)
        repeated = bool(previous_signature and signature == previous_signature)
        page_summaries.append(
            {
                "page": page,
                "url": page_url,
                "content_type": headers.get("content-type", ""),
                "product_links": len(links),
                "repeated_previous_page": repeated,
            }
        )
        if repeated or not links:
            break
        urls.extend(links)
        previous_signature = signature
        time.sleep(args.sleep)

    deduped = []
    seen = set()
    for url in urls:
        canonical = normalize_url(url).rstrip("/")
        if "/products/" not in canonical or canonical in seen:
            continue
        seen.add(canonical)
        deduped.append(canonical)
    if args.max_products:
        deduped = deduped[: args.max_products]
    return deduped, page_summaries


def extract_json_images(product_json: Dict[str, object]) -> List[Dict[str, str]]:
    images: List[Dict[str, str]] = []
    value = product_json.get("image")
    items = value if isinstance(value, list) else [value]
    for index, item in enumerate(items, start=1):
        url = normalize_url(str(item or ""))
        if url:
            images.append({"url": url, "alt": "", "title": "", "source": "json_ld_image", "position": str(index)})
    return images


def extract_product_images(html_text: str, product_json: Dict[str, object]) -> List[Dict[str, str]]:
    images = extract_json_images(product_json)
    for match in re.finditer(r'<li[^>]+class=["\'][^"\']*alternate-image[^"\']*["\'][^>]*>', html_text, re.I | re.S):
        attrs = parse_attrs(match.group(0))
        image_url = normalize_url(attrs.get("data-large-image", ""))
        if image_url:
            images.append({"url": image_url, "alt": "", "title": "", "source": "alternate_image", "position": str(len(images) + 1)})
    for tag_match in IMG_TAG_RE.finditer(html_text):
        tag = tag_match.group(0)
        attrs = parse_attrs(tag)
        image_url = normalize_url(attrs.get("data-zoom-image") or attrs.get("src") or "")
        if not image_url or "images.foxylingerie.com/images/" not in image_url:
            continue
        classes = attrs.get("class", "")
        if "product-thumb__image" in classes:
            continue
        images.append(
            {
                "url": image_url,
                "alt": normalize_whitespace(attrs.get("alt")),
                "title": normalize_whitespace(attrs.get("title")),
                "source": "pdp_product_img",
                "position": str(len(images) + 1),
            }
        )
    deduped = []
    seen = set()
    for image in images:
        key = image["url"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(image)
    return deduped


def extract_options(html_text: str, field_name: str) -> List[str]:
    pattern = re.compile(
        rf'<input\b[^>]+name=["\']cart_item\[{re.escape(field_name)}\]["\'][^>]*>',
        re.I | re.S,
    )
    values = []
    for match in pattern.finditer(html_text):
        attrs = parse_attrs(match.group(0))
        value = normalize_whitespace(attrs.get("value"))
        if value and attrs.get("type", "").lower() == "radio":
            disabled = "disabled" in match.group(0).lower()
            values.append(value + (" (disabled)" if disabled else ""))
    return values


def extract_review_count_label(html_text: str) -> str:
    return first_match(
        [
            r'<div[^>]+class=["\'][^"\']*aggregate-review-count[^"\']*["\'][^>]*>(.*?)</div>',
            r'<span[^>]+class=["\'][^"\']*review-count[^"\']*["\'][^>]*>(.*?)</span>',
        ],
        html_text,
    )


def product_from_html(product_url: str, html_text: str) -> ProductRecord:
    product_json = json_ld_product(html_text)
    title = normalize_whitespace(product_json.get("name")) if product_json else ""
    title = title or first_match(
        [
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            r"<title[^>]*>(.*?)</title>",
        ],
        html_text,
    )
    description = normalize_whitespace(product_json.get("description")) if product_json else ""
    description = description or first_match(
        [
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        ],
        html_text,
    )
    sizes = extract_options(html_text, "size")
    colors = extract_options(html_text, "color")
    detail_parts = []
    if sizes:
        detail_parts.append("available sizes: " + ", ".join(dict.fromkeys(sizes)))
    if colors:
        detail_parts.append("available color codes: " + ", ".join(dict.fromkeys(colors)))
    product_id = first_match(
        [
            r'name=["\']cart_item\[product_id\]["\'][^>]+value=["\']([^"\']+)["\']',
            r'value=["\']([^"\']+)["\'][^>]+name=["\']cart_item\[product_id\]["\']',
        ],
        html_text,
    )
    reviews_url = ""
    reviews_match = REVIEWS_URL_RE.search(html_text)
    if reviews_match:
        reviews_url = urljoin(SITE, reviews_match.group(1))
    return ProductRecord(
        url=product_url,
        title=title,
        description=description,
        detail=" | ".join(detail_parts),
        product_id=product_id,
        handle=urlparse(product_url).path.rstrip("/").split("/")[-1],
        color=", ".join(dict.fromkeys(colors)),
        variant=", ".join(dict.fromkeys(sizes)),
        images=extract_product_images(html_text, product_json),
        reviews_url=reviews_url,
        review_count_label=extract_review_count_label(html_text),
    )


def extract_customer_images_from_review_html(review_html: str, product: ProductRecord) -> List[Dict[str, str]]:
    images: List[Dict[str, str]] = []
    for index, tag_match in enumerate(IMG_TAG_RE.finditer(review_html), start=1):
        attrs = parse_attrs(tag_match.group(0))
        image_url = normalize_url(attrs.get("src") or attrs.get("data-src") or "")
        if not image_url:
            continue
        images.append(
            {
                "url": image_url,
                "alt": normalize_whitespace(attrs.get("alt")),
                "title": normalize_whitespace(attrs.get("title")),
                "review_id": f"foxylingerie-review-{product.product_id or product.handle}-{index}",
            }
        )
    return images


def fetch_reviews(product: ProductRecord) -> Dict[str, object]:
    if not product.reviews_url:
        return {"url": "", "html_length": 0, "has_more": False, "customer_review_images": 0}
    text, _headers = curl_fetch_text(
        product.reviews_url,
        referer=product.url,
        accept="application/json,text/html,*/*",
        xhr=True,
        retries=2,
    )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        review_html = text
        has_more = False
    else:
        review_html = str(payload.get("html") or "")
        has_more = bool(payload.get("has_more"))
    product.review_html_length = len(review_html.strip())
    product.review_has_more = has_more
    product.customer_review_images = extract_customer_images_from_review_html(review_html, product)
    return {
        "url": product.reviews_url,
        "html_length": product.review_html_length,
        "has_more": product.review_has_more,
        "customer_review_images": len(product.customer_review_images),
    }


def context_for_product(product: ProductRecord) -> ProductContext:
    return ProductContext(
        url=product.url,
        title=product.title,
        description=product.description,
        detail=product.detail,
        category=product.category,
        brand=product.brand,
        color=product.color,
        variant=product.variant,
        product_id=product.product_id,
        handle=product.handle,
        shop_domain="www.foxylingerie.com",
        provider_hints="custom Foxy Lingerie product reviews endpoint; catalog/model image fallback",
    )


def rows_from_product(product: ProductRecord, fetched_at: str) -> List[Dict[str, str]]:
    context = context_for_product(product)
    rows = []
    for index, image in enumerate(product.customer_review_images, start=1):
        review = ReviewImage(
            image_url=image["url"],
            review_id=image.get("review_id") or f"foxylingerie-review-{product.product_id or product.handle}-{index}",
            review_title="Customer review image",
            review_body=normalize_whitespace(image.get("alt") or image.get("title")),
            reviewer_name="",
            extra={
                "product_url": product.url,
                "product_title": product.title,
                "product_description": product.description,
                "product_detail": product.detail,
                "product_category": product.category,
                "product_variant": product.variant,
                "image_source_type": "customer_review_image",
                "image_source_detail": f"public product review endpoint {product.reviews_url}",
            },
        )
        rows.append(build_intake_row(context, review, fetched_at))
    if rows:
        return rows
    for index, image in enumerate(product.images, start=1):
        review = ReviewImage(
            image_url=image["url"],
            review_id=f"foxylingerie-catalog-{product.product_id or product.handle}-{index}",
            review_title="Catalog/model product image",
            review_body=(
                "Catalog/model product image. Public product review endpoint returned no customer review media "
                "for this swimsuit product."
            ),
            reviewer_name="Foxy Lingerie",
            extra={
                "product_url": product.url,
                "product_title": product.title,
                "product_description": product.description,
                "product_detail": product.detail,
                "product_category": product.category,
                "product_variant": product.variant,
                "image_source_type": "catalog_model_image",
                "image_source_detail": normalize_whitespace(
                    "catalog/model image from public PDP; "
                    f"source={image.get('source')}; position={image.get('position')}; "
                    f"alt={image.get('alt')}; review_html_length={product.review_html_length}; "
                    f"review_count_label={product.review_count_label}"
                ),
            },
        )
        rows.append(build_intake_row(context, review, fetched_at))
    return rows


def dedupe_foxy_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped = []
    seen = set()
    for row in rows:
        key = (row.get("image_source_type", ""), row.get("product_page_url_display", ""), row.get("original_url_display", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


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
    collection_pages: Sequence[Dict[str, object]],
    product_summaries: Sequence[Dict[str, object]],
    review_endpoint_summaries: Sequence[Dict[str, object]],
    errors: Sequence[str],
) -> None:
    summary = {
        "site": SITE,
        "retailer": RETAILER,
        "adapter": "custom_reviews_endpoint_catalog_model_images",
        "provider_identified": (
            "custom Foxy Lingerie review block with public per-product /reviews JSON endpoint; "
            "swimsuit products returned empty review HTML, so output uses catalog_model_image rows from public PDP media"
        ),
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": {
            "triage_category_url": TRIAGE_CATEGORY_URL,
            "scrape_category_url": SCRAPE_CATEGORY_URL,
            "triage_sample_pdps": TRIAGE_SAMPLE_PDPS,
            "collection_pages": list(collection_pages),
            "product_urls_scanned": list(product_urls),
            "scope_note": "Started with Sovrn swimsuit tops samples; expanded to the public swimsuit collection after sample PDP review endpoints were empty.",
        },
        "products_scanned": len(product_urls),
        "review_pages_scanned": len(review_endpoint_summaries),
        "exhaustive_review_paging": False,
        "review_endpoint_summaries": list(review_endpoint_summaries),
        "product_summaries": list(product_summaries),
        "errors": list(errors),
        "access_policy": "public Foxy Lingerie collection/PDP pages and public XHR review endpoints only; stop on 429/captcha/WAF/auth behavior.",
        "sovrn_triage_source": {
            "source_file": "data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv",
            "status": "first-pass candidate",
            "payout_model": "CPC",
            "provider": "unknown",
            "reviews_present": "yes",
            "photo_reviews": "yes",
            "shipping": "US",
            "payout_note": "CPC amount not populated",
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
    collection_pages: List[Dict[str, object]] = []
    product_summaries: List[Dict[str, object]] = []
    review_endpoint_summaries: List[Dict[str, object]] = []
    product_urls: List[str] = []

    try:
        product_urls, collection_pages = discover_product_urls(args)
        for index, product_url in enumerate(product_urls, start=1):
            html_text, headers = curl_fetch_text(product_url, referer=SCRAPE_CATEGORY_URL)
            product = product_from_html(product_url, html_text)
            review_summary = fetch_reviews(product)
            review_endpoint_summaries.append({"product_url": product_url, **review_summary})
            product_rows = rows_from_product(product, fetched_at)
            rows.extend(product_rows)
            product_summaries.append(
                {
                    "product_index": index,
                    "product_url": product_url,
                    "product_id": product.product_id,
                    "product_title": product.title,
                    "content_type": headers.get("content-type", ""),
                    "catalog_model_images": len(product.images),
                    "customer_review_images": len(product.customer_review_images),
                    "review_html_length": product.review_html_length,
                    "review_count_label": product.review_count_label,
                    "sizes_or_fit_detail": product.detail,
                }
            )
            if index % 25 == 0:
                print(f"scanned {index}/{len(product_urls)} products; rows={len(rows)}", file=sys.stderr, flush=True)
            if args.sleep:
                time.sleep(args.sleep)
    except RuntimeError as exc:
        errors.append(str(exc))
    except Exception as exc:
        errors.append(f"scrape_failed: {exc}")

    rows = dedupe_foxy_rows(dedupe_rows(rows))
    write_intake_csv(rows, output_csv)
    write_summary(
        summary_json,
        output_csv=output_csv,
        rows=rows,
        started_at=started_at,
        finished_at=utc_now(),
        product_urls=product_urls,
        collection_pages=collection_pages,
        product_summaries=product_summaries,
        review_endpoint_summaries=review_endpoint_summaries,
        errors=errors,
    )
    print(str(output_csv))
    print(str(summary_json))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
