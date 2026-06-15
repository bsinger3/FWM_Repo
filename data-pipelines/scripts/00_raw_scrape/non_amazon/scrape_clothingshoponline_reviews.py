#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import subprocess
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    write_intake_csv,
    write_summary,
)


SITE_ROOT = "https://www.clothingshoponline.com"
DOMAIN = "clothingshoponline.com"
RETAILER = "clothingshoponline_com"
WOMENS_COLLECTION_URL = f"{SITE_ROOT}/collections/womens"
YOTPO_APP_KEY = "EOsjx2qlpqcJrLqUWcKyReElMIp6KdzaIqwvz46k"
YOTPO_PER_PAGE = 100
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
BLOCK_MARKERS = [
    "Just a moment...",
    "challenges.cloudflare.com",
    "cf-chl",
    "captcha",
    "Access denied",
    "Attention Required",
]
BLOCKING_STATUS_CODES = {"401", "403", "407", "429", "503"}
APPAREL_RE = re.compile(
    r"\b("
    r"tee|t-shirt|shirt|tank|top|crop|hoodie|sweatshirt|pullover|zip|jacket|vest|"
    r"shorts?|pants?|joggers?|sweatpants?|leggings?|flannel|polo|dress|skirt|"
    r"sleepwear|activewear|outerwear"
    r")\b",
    re.I,
)
ACCESSORY_ONLY_RE = re.compile(r"\b(hats?|caps?|beanies?|bags?|totes?|blankets?|chairs?|aprons?)\b", re.I)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Clothing Shop Online public reviews and catalog images.")
    parser.add_argument("--max-collection-pages", type=int, default=0, help="Debug cap; 0 scans until collection exhaustion.")
    parser.add_argument("--max-products", type=int, default=0, help="Debug cap; 0 scans all discovered collection products.")
    parser.add_argument("--max-catalog-images-per-product", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=0.15)
    return parser.parse_args(argv)


def curl_fetch_text(url: str, *, referer: str = SITE_ROOT, accept: str = "*/*", retries: int = 3) -> str:
    last_error = ""
    for attempt in range(retries):
        cmd = [
            "curl.exe",
            "-L",
            "-sS",
            "--fail-with-body",
            "--max-time",
            "60",
            "-A",
            USER_AGENT,
            "-H",
            f"Accept: {accept}",
        ]
        if referer:
            cmd.extend(["-e", referer])
        cmd.append(url)
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode == 0:
            text = result.stdout.decode("utf-8", errors="replace")
            if any(marker.lower() in text.lower() for marker in BLOCK_MARKERS):
                raise RuntimeError(f"blocked_or_challenged_public_fetch url={url}")
            return text
        stderr = result.stderr.decode("utf-8", errors="replace")
        stdout = result.stdout.decode("utf-8", errors="replace")
        last_error = normalize_whitespace(stderr or stdout)
        if any(code in last_error for code in BLOCKING_STATUS_CODES):
            raise RuntimeError(f"blocked_or_rate_limited_fetch url={url} detail={last_error}")
        time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"fetch_failed url={url} detail={last_error}")


def curl_fetch_json(url: str, *, referer: str = SITE_ROOT, retries: int = 3) -> Dict[str, object]:
    text = curl_fetch_text(url, referer=referer, accept="application/json,text/plain,*/*", retries=retries)
    return json.loads(text)


def extract_remix_context(html_text: str) -> Dict[str, object]:
    marker = "window.__remixContext = "
    start = html_text.find(marker)
    if start == -1:
        return {}
    start += len(marker)
    end = html_text.find(";__remixContext", start)
    if end == -1:
        end = html_text.find(";</script>", start)
    if end == -1:
        return {}
    try:
        return json.loads(html_text[start:end])
    except json.JSONDecodeError:
        return {}


def route_payload(context: Dict[str, object], route_fragment: str) -> Dict[str, object]:
    state = context.get("state") if isinstance(context, dict) else {}
    loader_data = state.get("loaderData") if isinstance(state, dict) else {}
    if not isinstance(loader_data, dict):
        return {}
    for key, value in loader_data.items():
        if route_fragment in key and isinstance(value, dict):
            return value
    return {}


def collection_urls_from_html(html_text: str) -> Tuple[List[str], int]:
    urls = [
        urljoin(SITE_ROOT, html.unescape(path))
        for path in re.findall(r'href="(/products/[^"#?]+)', html_text)
    ]
    itemlist_urls = re.findall(r'"url":"(https://www\.clothingshoponline\.com/products/[^"]+)"', html_text)
    urls.extend(html.unescape(url) for url in itemlist_urls)
    seen = set()
    deduped = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    total_match = re.search(r'"totalCount"\s*:\s*(\d+)', html_text)
    return deduped, int(total_match.group(1)) if total_match else 0


def discover_womens_product_urls(max_pages: int, sleep: float) -> Tuple[List[str], List[Dict[str, object]], int]:
    product_urls: List[str] = []
    seen = set()
    pages: List[Dict[str, object]] = []
    total_count = 0
    empty_streak = 0
    page = 1
    while True:
        if max_pages and page > max_pages:
            break
        url = WOMENS_COLLECTION_URL if page == 1 else f"{WOMENS_COLLECTION_URL}?page={page}"
        text = curl_fetch_text(url, referer=SITE_ROOT, accept="text/html,*/*")
        urls, page_total = collection_urls_from_html(text)
        total_count = page_total or total_count
        new_urls = [candidate for candidate in urls if candidate not in seen]
        for candidate in new_urls:
            seen.add(candidate)
            product_urls.append(candidate)
        pages.append({"page": page, "url": url, "product_urls": len(urls), "new_product_urls": len(new_urls)})
        print(f"[collection page {page}] urls={len(urls)} new={len(new_urls)} total_seen={len(product_urls)}", flush=True)
        if not urls or not new_urls:
            empty_streak += 1
        else:
            empty_streak = 0
        if total_count and len(product_urls) >= total_count:
            break
        if empty_streak >= 2:
            break
        page += 1
        if sleep:
            time.sleep(sleep)
    return product_urls, pages, total_count


def selected_option(options: Iterable[Dict[str, object]], name: str) -> str:
    for option in options or []:
        if normalize_whitespace(option.get("name")).lower() == name.lower():
            return normalize_whitespace(option.get("value"))
    return ""


def image_url_from_node(node: Dict[str, object]) -> str:
    if not isinstance(node, dict):
        return ""
    image = node.get("image") if isinstance(node.get("image"), dict) else {}
    preview = node.get("previewImage") if isinstance(node.get("previewImage"), dict) else {}
    return normalize_whitespace(image.get("url") or preview.get("url"))


def image_alt_from_node(node: Dict[str, object]) -> str:
    image = node.get("image") if isinstance(node.get("image"), dict) else {}
    preview = node.get("previewImage") if isinstance(node.get("previewImage"), dict) else {}
    return normalize_whitespace(image.get("altText") or preview.get("altText"))


def image_score(url: str, alt: str, index: int) -> Tuple[int, int]:
    value = f"{url} {alt}".lower()
    score = 0
    if "onmodelfront" in value or "styleimage" in value:
        score += 30
    if "onmodel" in value:
        score += 20
    if re.search(r"\bfront\b", value):
        score += 8
    if re.search(r"\b(back|side|swatch|color|flat)\b", value):
        score -= 4
    return score, -index


def product_context(product: Dict[str, object], product_url: str) -> ProductContext:
    variants = product.get("variants") if isinstance(product.get("variants"), dict) else {}
    nodes = variants.get("nodes") if isinstance(variants, dict) and isinstance(variants.get("nodes"), list) else []
    first_variant = nodes[0] if nodes and isinstance(nodes[0], dict) else {}
    color = selected_option(first_variant.get("selectedOptions") or [], "Color")
    size = selected_option(first_variant.get("selectedOptions") or [], "Size")
    return ProductContext(
        url=product_url,
        title=normalize_whitespace(product.get("title")),
        description=strip_tags(product.get("description") or product.get("descriptionHtml")),
        detail=normalize_whitespace(product.get("tags") or ""),
        category=normalize_whitespace(product.get("productType")),
        brand=normalize_whitespace(product.get("vendor")) or "Clothing Shop Online",
        color=color,
        variant=normalize_whitespace(" / ".join(part for part in [size, color] if part)),
        product_id=normalize_whitespace(product.get("id")),
        handle=normalize_whitespace(product.get("handle")),
        shop_domain="clothingshoponline.com",
        provider_hints="Yotpo; Hydrogen product route; public catalog variant images",
    )


def is_apparel_context(context: ProductContext) -> bool:
    text = normalize_whitespace(" ".join([context.title, context.description, context.category, context.detail]))
    if ACCESSORY_ONLY_RE.search(text) and not APPAREL_RE.search(text):
        return False
    return bool(APPAREL_RE.search(text))


def yotpo_product_id(product: Dict[str, object], html_text: str) -> str:
    match = re.search(r'data-yotpo-product-id="([^"]+)"', html_text)
    if match:
        return normalize_whitespace(match.group(1))
    gid = normalize_whitespace(product.get("id"))
    if gid.rsplit("/", 1)[-1].isdigit():
        return gid.rsplit("/", 1)[-1]
    return gid


def yotpo_reviews(yotpo_id: str, product_url: str, sleep: float) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    if not yotpo_id:
        return [], {"yotpo_product_id": "", "review_pages_scanned": 0, "review_total": 0, "error": "missing_yotpo_product_id"}
    reviews: List[Dict[str, object]] = []
    pages_scanned = 0
    review_total = 0
    first_url = (
        f"https://api-cdn.yotpo.com/v1/widget/{YOTPO_APP_KEY}/products/{yotpo_id}/reviews.json"
        f"?per_page={YOTPO_PER_PAGE}&page=1"
    )
    payload = curl_fetch_json(first_url, referer=product_url)
    response = payload.get("response") if isinstance(payload, dict) else {}
    if not isinstance(response, dict):
        return [], {"yotpo_product_id": yotpo_id, "review_pages_scanned": 1, "review_total": 0, "error": "invalid_yotpo_response"}
    pagination = response.get("pagination") if isinstance(response.get("pagination"), dict) else {}
    review_total = int(pagination.get("total") or 0)
    per_page = int(pagination.get("per_page") or YOTPO_PER_PAGE)
    total_pages = max(1, math.ceil(review_total / max(per_page, 1))) if review_total else 1
    for page in range(1, total_pages + 1):
        if page == 1:
            page_response = response
        else:
            page_url = (
                f"https://api-cdn.yotpo.com/v1/widget/{YOTPO_APP_KEY}/products/{yotpo_id}/reviews.json"
                f"?per_page={YOTPO_PER_PAGE}&page={page}"
            )
            page_payload = curl_fetch_json(page_url, referer=product_url)
            page_response = page_payload.get("response") if isinstance(page_payload, dict) else {}
            if not isinstance(page_response, dict):
                break
        pages_scanned += 1
        page_reviews = page_response.get("reviews") if isinstance(page_response.get("reviews"), list) else []
        reviews.extend(review for review in page_reviews if isinstance(review, dict))
        if sleep:
            time.sleep(sleep)
    return reviews, {"yotpo_product_id": yotpo_id, "review_pages_scanned": pages_scanned, "review_total": review_total}


def media_urls(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    images_data = review.get("images_data")
    if isinstance(images_data, list):
        for item in images_data:
            if not isinstance(item, dict):
                continue
            for key in ["original_url", "url", "thumb_url", "image_url"]:
                value = normalize_whitespace(item.get(key))
                if value:
                    urls.append(value)
                    break
    elif isinstance(images_data, dict):
        for value in images_data.values():
            if isinstance(value, dict):
                for key in ["original_url", "url", "thumb_url", "image_url"]:
                    candidate = normalize_whitespace(value.get(key))
                    if candidate:
                        urls.append(candidate)
                        break
            elif isinstance(value, str) and value.startswith("http"):
                urls.append(value)
    return list(dict.fromkeys(urls))


def custom_field_text(review: Dict[str, object]) -> str:
    fields = review.get("custom_fields")
    if not isinstance(fields, dict):
        return ""
    parts = []
    for field in fields.values():
        if not isinstance(field, dict):
            continue
        title = normalize_whitespace(field.get("title"))
        value = normalize_whitespace(field.get("value"))
        if title and value:
            parts.append(f"{title}: {value}")
    return "; ".join(parts)


def review_rows(context: ProductContext, reviews: List[Dict[str, object]], fetched_at: str) -> List[Dict[str, str]]:
    rows = []
    for review in reviews:
        urls = media_urls(review)
        if not urls:
            continue
        user = review.get("user") if isinstance(review.get("user"), dict) else {}
        comment_extra = custom_field_text(review)
        body = normalize_whitespace(review.get("content"))
        if comment_extra:
            body = normalize_whitespace(f"{body} [{comment_extra}]")
        for index, image_url in enumerate(urls, 1):
            review_image = ReviewImage(
                image_url=image_url,
                review_id=f"clothingshoponline-yotpo-{review.get('id')}-{index}",
                review_title=normalize_whitespace(review.get("title")),
                review_body=body,
                reviewer_name=normalize_whitespace(user.get("display_name")),
                date_raw=normalize_whitespace(review.get("created_at")),
                rating=normalize_whitespace(review.get("score")),
                extra={
                    "image_source_type": "customer_review_image",
                    "image_source_detail": "public Yotpo reviews.json images_data",
                },
            )
            rows.append(build_intake_row(context, review_image, fetched_at))
    return rows


def catalog_rows(
    context: ProductContext,
    product: Dict[str, object],
    fetched_at: str,
    max_images: int,
) -> List[Dict[str, str]]:
    if not is_apparel_context(context):
        return []
    media = product.get("media") if isinstance(product.get("media"), dict) else {}
    media_nodes = media.get("nodes") if isinstance(media.get("nodes"), list) else []
    variants = product.get("variants") if isinstance(product.get("variants"), dict) else {}
    variant_nodes = variants.get("nodes") if isinstance(variants.get("nodes"), list) else []
    image_to_variant: Dict[str, Dict[str, object]] = {}
    first_sized_variant: Dict[str, object] = {}
    for variant in variant_nodes:
        if not isinstance(variant, dict):
            continue
        if not first_sized_variant and selected_option(variant.get("selectedOptions") or [], "Size"):
            first_sized_variant = variant
        image = variant.get("image") if isinstance(variant.get("image"), dict) else {}
        url = normalize_whitespace(image.get("url"))
        if url and url not in image_to_variant:
            image_to_variant[url] = variant
    candidates: List[Tuple[Tuple[int, int], str, str]] = []
    for index, node in enumerate(media_nodes):
        url = image_url_from_node(node)
        if not url:
            continue
        alt = image_alt_from_node(node)
        candidates.append((image_score(url, alt, index), url, alt))
    for url, variant in image_to_variant.items():
        alt = normalize_whitespace((variant.get("image") or {}).get("altText") if isinstance(variant.get("image"), dict) else "")
        candidates.append((image_score(url, alt, len(candidates)), url, alt))
    deduped = []
    seen = set()
    for score, url, alt in sorted(candidates, reverse=True):
        if url in seen:
            continue
        seen.add(url)
        deduped.append((score, url, alt))
    rows = []
    for _, image_url, alt in deduped[:max_images]:
        variant = image_to_variant.get(image_url) or first_sized_variant
        size = selected_option(variant.get("selectedOptions") or [], "Size")
        color = selected_option(variant.get("selectedOptions") or [], "Color") or context.color
        variant_title = normalize_whitespace(variant.get("title")) or context.variant
        row_context = ProductContext(**{**context.__dict__, "color": color, "variant": variant_title})
        row_id = "clothingshoponline-catalog-" + hashlib.md5(
            f"{context.url}|{image_url}|{variant_title}|{size}".encode("utf-8")
        ).hexdigest()[:16]
        review = ReviewImage(
            image_url=image_url,
            review_id=row_id,
            review_title="Catalog model/variant image",
            review_body=normalize_whitespace(
                f"Public catalog image for {context.title}. Variant: {variant_title}. Image alt: {alt}."
            ),
            size_raw=size,
            extra={
                "image_source_type": "catalog_model_image",
                "image_source_detail": "public Hydrogen PDP media/variant image; Yotpo reviews had no customer media for this product",
            },
        )
        rows.append(build_intake_row(row_context, review, fetched_at))
    return rows


def scrape_product(product_url: str, fetched_at: str, max_catalog_images: int, sleep: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    html_text = curl_fetch_text(product_url, referer=WOMENS_COLLECTION_URL, accept="text/html,*/*")
    remix = extract_remix_context(html_text)
    payload = route_payload(remix, "products.$handle")
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    if not product:
        return [], {"product_url": product_url, "rows": 0, "error": "missing_product_payload"}
    context = product_context(product, product_url)
    yotpo_id = yotpo_product_id(product, html_text)
    reviews, review_summary = yotpo_reviews(yotpo_id, product_url, sleep)
    rows = review_rows(context, reviews, fetched_at)
    source_type = "customer_review_image"
    if not rows:
        rows = catalog_rows(context, product, fetched_at, max_catalog_images)
        source_type = "catalog_model_image" if rows else "none"
    image_review_count = sum(1 for review in reviews if media_urls(review))
    summary = {
        "product_url": product_url,
        "product_id": normalize_whitespace(product.get("id")),
        "yotpo_product_id": yotpo_id,
        "product_title": context.title,
        "brand": context.brand,
        "is_apparel_context": is_apparel_context(context),
        "review_total": review_summary.get("review_total", 0),
        "review_pages_scanned": review_summary.get("review_pages_scanned", 0),
        "reviews_with_images": image_review_count,
        "variants": len((product.get("variants") or {}).get("nodes") or []) if isinstance(product.get("variants"), dict) else 0,
        "media_nodes": len((product.get("media") or {}).get("nodes") or []) if isinstance(product.get("media"), dict) else 0,
        "rows": len(rows),
        "row_source_type": source_type,
        "error": review_summary.get("error", ""),
    }
    return rows, summary


def scrape(args: argparse.Namespace) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    product_urls, collection_pages, total_count = discover_womens_product_urls(args.max_collection_pages, args.sleep)
    if args.max_products:
        product_urls = product_urls[: args.max_products]
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    for index, product_url in enumerate(product_urls, 1):
        try:
            product_rows, product_summary = scrape_product(
                product_url,
                started_at,
                args.max_catalog_images_per_product,
                args.sleep,
            )
            rows.extend(product_rows)
            product_summaries.append(product_summary)
            print(
                f"[product {index}/{len(product_urls)}] rows={len(product_rows)} "
                f"reviews={product_summary.get('review_total')} url={product_url}",
                flush=True,
            )
        except Exception as exc:
            error = f"{product_url}: {exc}"
            errors.append(error)
            if re.search(r"blocked|rate_limited|captcha|429|403|503", str(exc), re.I):
                break
        if args.sleep:
            time.sleep(args.sleep)
    rows = dedupe_rows(rows)
    summary = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "hydrogen_collection_pdp_yotpo_reviews_with_catalog_fallback",
        "started_at": started_at,
        "finished_at": utc_now(),
        "source_triage": {
            "queue_status": "sovrn_first_pass_scrape_candidate",
            "review_provider": "Yotpo; Loox",
            "photo_reviews": "unknown_sample_too_small",
            "reviews_present": "yes",
            "ships_to_country_codes": "US",
            "estimated_commission_per_click": "$0.14",
            "category_evidence_url": WOMENS_COLLECTION_URL,
        },
        "access_policy": "public collection pages, public PDP HTML, public Yotpo api-cdn reviews.json only; no auth, no checkout, no captcha/WAF bypass",
        "collection_pages_scanned": len(collection_pages),
        "collection_pages": collection_pages,
        "collection_reported_total_count": total_count,
        "products_discovered": len(product_urls),
        "products_scanned": len(product_summaries),
        "review_pages_scanned": sum(int(item.get("review_pages_scanned") or 0) for item in product_summaries),
        "reviews_seen": sum(int(item.get("review_total") or 0) for item in product_summaries),
        "products_with_customer_review_images": sum(1 for item in product_summaries if int(item.get("reviews_with_images") or 0) > 0),
        "products_with_catalog_fallback_rows": sum(1 for item in product_summaries if item.get("row_source_type") == "catalog_model_image"),
        "stop_reason": "blocked_or_rate_limited" if errors and re.search(r"blocked|rate_limited|captcha|429|403|503", errors[-1], re.I) else "none",
        "product_summaries": product_summaries,
        "errors": errors,
    }
    return rows, summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    rows, summary = scrape(args)
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
    payload["rows_supabase_qualified"] = payload.get("rows_with_image_product_and_size", 0)
    summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Rows written: {len(rows)}")
    print(f"Customer image rows: {payload.get('rows_with_customer_review_image', 0)}")
    print(f"Catalog model rows: {payload.get('rows_with_catalog_model_image', 0)}")
    print(f"CSV: {output_csv}")
    print(f"Summary: {summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
