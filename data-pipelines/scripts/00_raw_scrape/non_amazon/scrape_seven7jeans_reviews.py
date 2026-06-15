#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path
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
    validate_rows,
    write_intake_csv,
    write_summary,
)


SITE_ROOT = "https://seven7jeans.com"
DOMAIN = "seven7jeans.com"
RETAILER = "seven7jeans_com"
TRIAGE_CATEGORY_URL = f"{SITE_ROOT}/shop/women/subcategory_Dress"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
BLOCK_BODY_RE = re.compile(r"\b(?:captcha|access denied|forbidden|too many requests|cloudflare|datadome|akamai)\b", re.I)
BLOCKING_STATUS_CODES = {"401", "403", "407", "429", "503"}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Seven7 Jeans public Merchantly product media/reviews.")
    parser.add_argument("--category-url", default=TRIAGE_CATEGORY_URL)
    parser.add_argument("--max-products", type=int, default=0, help="Debug cap; 0 scans all products in category.")
    parser.add_argument("--max-catalog-images-per-product", type=int, default=4)
    parser.add_argument("--sleep", type=float, default=0.1)
    return parser.parse_args(argv)


def curl_fetch_text(url: str, *, referer: str = SITE_ROOT, accept: str = "text/html,*/*", retries: int = 3) -> str:
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
            "-H",
            "Accept-Language: en-US,en;q=0.9",
        ]
        if referer:
            cmd.extend(["-e", referer])
        cmd.append(url)
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        if result.returncode == 0:
            if BLOCK_BODY_RE.search(stdout[:4000]):
                raise RuntimeError(f"blocked_or_challenged_public_fetch url={url}")
            return stdout
        last_error = normalize_whitespace(stderr or stdout)
        if any(code in last_error for code in BLOCKING_STATUS_CODES):
            raise RuntimeError(f"blocked_or_rate_limited_fetch url={url} detail={last_error}")
        time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"fetch_failed url={url} detail={last_error}")


def next_flight_text(html_text: str) -> str:
    chunks: List[str] = []
    for match in re.finditer(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html_text, re.S):
        try:
            chunks.append(json.loads('"' + match.group(1) + '"'))
        except json.JSONDecodeError:
            continue
    return "\n".join(chunks)


def extract_balanced_json(text: str, marker: str) -> Dict[str, object]:
    idx = text.find(marker)
    if idx == -1:
        return {}
    start = text.find("{", idx)
    if start == -1:
        return {}
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : index + 1])
                    except json.JSONDecodeError:
                        return {}
    return {}


def selected_option(options: Iterable[Dict[str, object]], name: str) -> str:
    for option in options or []:
        if normalize_whitespace(option.get("name")).lower() == name.lower():
            return normalize_whitespace(option.get("value"))
    return ""


def option_values(product: Dict[str, object], name: str) -> List[str]:
    options = product.get("options") if isinstance(product.get("options"), list) else []
    for option in options:
        if not isinstance(option, dict):
            continue
        if normalize_whitespace(option.get("name")).lower() == name.lower():
            values = option.get("values") if isinstance(option.get("values"), list) else []
            return [normalize_whitespace(value) for value in values if normalize_whitespace(value)]
    return []


def discover_product_urls(category_url: str) -> Tuple[List[str], Dict[str, object]]:
    html_text = curl_fetch_text(category_url)
    urls = [
        urljoin(SITE_ROOT, f"/products/{handle}")
        for handle in re.findall(r'href="/products/([^"#?]+)', html_text)
    ]
    flight = next_flight_text(html_text)
    collection = extract_balanced_json(flight, '"collection":')
    products = collection.get("products") if isinstance(collection.get("products"), dict) else {}
    edges = products.get("edges") if isinstance(products.get("edges"), list) else []
    for edge in edges:
        node = edge.get("node") if isinstance(edge, dict) and isinstance(edge.get("node"), dict) else {}
        url = normalize_whitespace(node.get("url"))
        handle = normalize_whitespace(node.get("handle"))
        if url:
            urls.append(url)
        elif handle:
            urls.append(f"{SITE_ROOT}/products/{handle}")
    deduped = list(dict.fromkeys(urls))
    summary = {
        "category_url": category_url,
        "category_products_in_html": len(re.findall(r'href="/products/', html_text)),
        "category_edges": len(edges),
        "category_total_count": int(products.get("totalCount") or 0) if isinstance(products, dict) else 0,
        "category_has_next_page": bool((products.get("pageInfo") or {}).get("hasNextPage")) if isinstance(products, dict) else False,
        "category_end_cursor": normalize_whitespace((products.get("pageInfo") or {}).get("endCursor")) if isinstance(products, dict) else "",
    }
    return deduped, summary


def decode_product(product_url: str) -> Dict[str, object]:
    html_text = curl_fetch_text(product_url, referer=TRIAGE_CATEGORY_URL)
    flight = next_flight_text(html_text)
    product = extract_balanced_json(flight, '"product":')
    if not product:
        raise RuntimeError(f"missing_public_product_payload url={product_url}")
    return product


def review_media_urls(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    for key in ["images", "photos", "media", "imageUrls", "image_urls"]:
        value = review.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.startswith("http"):
                    urls.append(item)
                elif isinstance(item, dict):
                    for image_key in ["url", "src", "image", "main", "full", "thumb"]:
                        url = normalize_whitespace(item.get(image_key))
                        if url.startswith("http"):
                            urls.append(url)
                            break
        elif isinstance(value, str) and value.startswith("http"):
            urls.append(value)
    return list(dict.fromkeys(urls))


def product_context(product: Dict[str, object], product_url: str) -> ProductContext:
    variants = product.get("variants") if isinstance(product.get("variants"), list) else []
    first_variant = variants[0] if variants and isinstance(variants[0], dict) else {}
    color = selected_option(first_variant.get("options") or [], "Color") or (option_values(product, "Color") or [""])[0].title()
    size = selected_option(first_variant.get("options") or [], "Size") or (option_values(product, "Size") or [""])[0]
    description_parts = [
        strip_tags(product.get("description1")),
        strip_tags(product.get("description2")),
        strip_tags(product.get("description3")),
        strip_tags(product.get("description4")),
    ]
    detail_parts = [
        normalize_whitespace(product.get("attribute1")),
        normalize_whitespace(product.get("attribute2")),
        normalize_whitespace(product.get("attribute3")),
        normalize_whitespace(product.get("attribute4")),
        normalize_whitespace(product.get("attribute5")),
        normalize_whitespace(product.get("mpn")),
        normalize_whitespace(product.get("tags")),
    ]
    return ProductContext(
        url=product_url,
        title=normalize_whitespace(product.get("title")),
        description=normalize_whitespace(" ".join(part for part in description_parts if part)),
        detail=normalize_whitespace(" | ".join(part for part in detail_parts if part)),
        category=normalize_whitespace(product.get("attribute2") or product.get("attribute3")),
        brand="Seven7 Jeans",
        color=color,
        variant=normalize_whitespace(" / ".join(part for part in [size, color] if part)),
        product_id=normalize_whitespace(product.get("id")),
        handle=normalize_whitespace(product.get("handle")),
        shop_domain="seven7jeans.com",
        provider_hints="Merchantly-native productReviews in public Next.js flight payload; no review media fields in public review component",
    )


def review_rows(context: ProductContext, product: Dict[str, object], fetched_at: str) -> List[Dict[str, str]]:
    product_reviews = product.get("productReviews") if isinstance(product.get("productReviews"), dict) else {}
    reviews = product_reviews.get("reviews") if isinstance(product_reviews.get("reviews"), list) else []
    rows: List[Dict[str, str]] = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        for index, image_url in enumerate(review_media_urls(review), 1):
            color = normalize_whitespace(review.get("colorBought")) or context.color
            size = normalize_whitespace(review.get("sizeBought"))
            row_context = ProductContext(**{**context.__dict__, "color": color})
            body_parts = [
                normalize_whitespace(review.get("body")),
                f"Color bought: {color}" if color else "",
                f"Size bought: {size}" if size else "",
                f"Height: {normalize_whitespace(review.get('height'))}" if normalize_whitespace(review.get("height")) else "",
            ]
            image = ReviewImage(
                image_url=image_url,
                review_id=f"seven7jeans-review-{normalize_whitespace(review.get('id')) or hashlib.md5(image_url.encode()).hexdigest()[:10]}-{index}",
                review_title=normalize_whitespace(review.get("title")),
                review_body=normalize_whitespace(" ".join(part for part in body_parts if part)),
                reviewer_name=normalize_whitespace(review.get("nickname")),
                date_raw=normalize_whitespace(review.get("createdAt")),
                rating=normalize_whitespace(review.get("rating")),
                size_raw=size,
                extra={
                    "image_source_type": "customer_review_image",
                    "image_source_detail": "public Merchantly productReviews review media field",
                },
            )
            rows.append(build_intake_row(row_context, image, fetched_at))
    return rows


def catalog_rows(
    context: ProductContext,
    product: Dict[str, object],
    fetched_at: str,
    max_images: int,
) -> List[Dict[str, str]]:
    images = product.get("images") if isinstance(product.get("images"), list) else []
    variants = product.get("variants") if isinstance(product.get("variants"), list) else []
    first_variant = variants[0] if variants and isinstance(variants[0], dict) else {}
    size = selected_option(first_variant.get("options") or [], "Size") or (option_values(product, "Size") or [""])[0]
    color = selected_option(first_variant.get("options") or [], "Color") or context.color
    variant_title = normalize_whitespace(" / ".join(part for part in [size, color] if part))
    row_context = ProductContext(**{**context.__dict__, "color": color, "variant": variant_title})
    candidates: List[Tuple[int, str, Dict[str, object]]] = []
    for index, image in enumerate(images):
        if not isinstance(image, dict):
            continue
        url = normalize_whitespace(image.get("full") or image.get("main") or image.get("thumb"))
        if not url:
            continue
        tags = image.get("tags") if isinstance(image.get("tags"), dict) else {}
        score = (100 if tags.get("isProduct") else 0) - index
        candidates.append((score, url, image))
    rows: List[Dict[str, str]] = []
    seen = set()
    for _, image_url, image in sorted(candidates, reverse=True):
        if image_url in seen:
            continue
        seen.add(image_url)
        row_id = "seven7jeans-catalog-" + hashlib.md5(
            f"{context.url}|{image_url}|{variant_title}|{size}".encode("utf-8")
        ).hexdigest()[:16]
        width = ((image.get("fullMeta") or image.get("mainMeta") or {}) or {}).get("width", "")
        height = ((image.get("fullMeta") or image.get("mainMeta") or {}) or {}).get("height", "")
        image_review = ReviewImage(
            image_url=image_url,
            review_id=row_id,
            review_title="Catalog model/variant image",
            review_body=normalize_whitespace(
                f"Public catalog image for {context.title}. Variant: {variant_title}. "
                f"Style: {normalize_whitespace(product.get('mpn'))}. Image dimensions: {width}x{height}."
            ),
            size_raw=size,
            extra={
                "image_source_type": "catalog_model_image",
                "image_source_detail": "public Merchantly/Next.js PDP product images; public reviews had no customer media for this product",
            },
        )
        rows.append(build_intake_row(row_context, image_review, fetched_at))
        if len(rows) >= max_images:
            break
    return rows


def scrape_product(product_url: str, fetched_at: str, max_catalog_images: int) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    product = decode_product(product_url)
    context = product_context(product, product_url)
    rows = review_rows(context, product, fetched_at)
    source_type = "customer_review_image"
    if not rows:
        rows = catalog_rows(context, product, fetched_at, max_catalog_images)
        source_type = "catalog_model_image" if rows else "none"
    product_reviews = product.get("productReviews") if isinstance(product.get("productReviews"), dict) else {}
    reviews = product_reviews.get("reviews") if isinstance(product_reviews.get("reviews"), list) else []
    stats = product_reviews.get("stats") if isinstance(product_reviews.get("stats"), dict) else {}
    reviews_with_media = sum(1 for review in reviews if isinstance(review, dict) and review_media_urls(review))
    return rows, {
        "product_url": product_url,
        "product_id": normalize_whitespace(product.get("id")),
        "handle": normalize_whitespace(product.get("handle")),
        "product_title": context.title,
        "mpn": normalize_whitespace(product.get("mpn")),
        "category": context.category,
        "color": context.color,
        "sizes": option_values(product, "Size"),
        "variants": len(product.get("variants") if isinstance(product.get("variants"), list) else []),
        "images": len(product.get("images") if isinstance(product.get("images"), list) else []),
        "approved_reviews_in_payload": len(reviews),
        "reviews_with_media": reviews_with_media,
        "review_stats_present": bool(stats),
        "row_source_type": source_type,
        "rows": len(rows),
    }


def scrape(args: argparse.Namespace) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    product_urls, category_summary = discover_product_urls(args.category_url)
    if args.max_products:
        product_urls = product_urls[: args.max_products]
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    for index, product_url in enumerate(product_urls, 1):
        try:
            product_rows, product_summary = scrape_product(product_url, started_at, args.max_catalog_images_per_product)
            rows.extend(product_rows)
            product_summaries.append(product_summary)
            print(
                f"[product {index}/{len(product_urls)}] rows={len(product_rows)} "
                f"reviews={product_summary.get('approved_reviews_in_payload')} url={product_url}",
                flush=True,
            )
        except Exception as exc:
            error = f"{product_url}: {exc}"
            errors.append(error)
            print(f"[error] {error}", flush=True)
            if re.search(r"blocked|rate_limited|captcha|429|403|503|auth", str(exc), re.I):
                break
        if args.sleep:
            time.sleep(args.sleep)
    rows = dedupe_rows(rows)
    summary = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "merchantly_next_flight_product_reviews_with_catalog_fallback",
        "started_at": started_at,
        "finished_at": utc_now(),
        "source_triage": {
            "queue_status": "sovrn_first_pass_scrape_candidate",
            "pricing_model": "CPA+CPC",
            "review_provider": "unknown",
            "identified_provider": "Merchantly-native productReviews",
            "photo_reviews": "unknown_sample_too_small",
            "reviews_present": "yes",
            "ships_to_country_codes": "CA|US",
            "payout_fields": "not_populated",
            "category_evidence_url": args.category_url,
        },
        "access_policy": "public category pages and public PDP HTML/Next.js flight payload only; no auth, checkout, captcha/WAF bypass, or review submission endpoints",
        "category_summary": category_summary,
        "products_discovered": len(product_urls),
        "products_scanned": len(product_summaries),
        "approved_reviews_seen": sum(int(item.get("approved_reviews_in_payload") or 0) for item in product_summaries),
        "products_with_review_media": sum(1 for item in product_summaries if int(item.get("reviews_with_media") or 0) > 0),
        "products_with_catalog_fallback_rows": sum(1 for item in product_summaries if item.get("row_source_type") == "catalog_model_image"),
        "stop_reason": "blocked_or_rate_limited" if errors and re.search(r"blocked|rate_limited|captcha|429|403|503|auth", errors[-1], re.I) else "none",
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
    payload["validation"] = validate_rows(rows)
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
