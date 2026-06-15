#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import math
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
    normalize_ordered_size,
    normalize_whitespace,
    output_paths,
    review_date_from_raw,
    strip_tags,
    utc_now,
    validate_rows,
    write_intake_csv,
)


SITE = "https://www.yogademocracy.com"
RETAILER = "yogademocracy_com"
YOTPO_APP_KEY = "YVXTEHoqp4n0JhHEBNigfesPIxNLjbyOSszJl7nI"
YOTPO_PER_PAGE = 100
BLOCKING_STATUS_CODES = {401, 403, 407, 429, 503}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
BLOCK_BODY_RE = re.compile(r"\b(?:captcha|access denied|forbidden|too many requests|akamai|datadome|cloudflare)\b", re.I)
CATEGORY_SEEDS = [
    ("tops", f"{SITE}/shop/tops/"),
    ("bottoms", f"{SITE}/shop/bottoms/"),
    ("shorts", f"{SITE}/shop/shorts/"),
    ("tanks", f"{SITE}/shop/tanks/"),
    ("bras", f"{SITE}/shop/sports-bras/"),
    ("inseam-update", f"{SITE}/shop/inseam-update/"),
]
PDP_CATEGORY_GUESSES = ["tops", "bottoms", "shorts", "tanks", "sports-bras", "inseam-update"]


@dataclass
class ProductRecord:
    product_key: str
    url: str = ""
    title: str = ""
    description: str = ""
    category: str = ""
    source_names: set[str] = field(default_factory=set)
    page_error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Focused Yoga Democracy public Yotpo photo-review scrape.")
    parser.add_argument("--max-review-pages", type=int, default=0, help="Debug cap; 0 scans all public Yotpo pages.")
    parser.add_argument("--max-category-pages", type=int, default=0, help="Debug cap per category; 0 scans until empty/repeat.")
    parser.add_argument("--sleep", type=float, default=0.05, help="Sleep between public requests.")
    return parser.parse_args()


def curl_fetch_text(url: str, *, referer: str = SITE, accept: str = "*/*", retries: int = 3) -> str:
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
            if BLOCK_BODY_RE.search(result.stdout[:2000]):
                raise RuntimeError(f"blocked_or_challenge_body url={url}")
            return result.stdout
        last_error = normalize_whitespace(result.stderr or result.stdout)
        if any(f" {code}" in last_error or f"error: {code}" in last_error.lower() for code in BLOCKING_STATUS_CODES):
            raise RuntimeError(f"blocked_or_rate_limited_fetch url={url} detail={last_error}")
        time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"fetch_failed url={url} detail={last_error}")


def curl_fetch_json(url: str, *, referer: str = SITE, retries: int = 3) -> Dict[str, object]:
    return json.loads(curl_fetch_text(url, referer=referer, accept="application/json,text/plain,*/*", retries=retries))


def product_key_from_url(url: str) -> str:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1]
    return name.removesuffix(".html")


def absolute_url(value: str) -> str:
    return urljoin(SITE, html.unescape(value))


def parse_category_products(page_html: str, category: str) -> Dict[str, ProductRecord]:
    products: Dict[str, ProductRecord] = {}
    for match in re.finditer(r"href=\"([^\"]+\.html)\"", page_html, re.I):
        url = absolute_url(match.group(1))
        if "/shop/" not in url:
            continue
        key = product_key_from_url(url)
        if not key:
            continue
        products.setdefault(
            key,
            ProductRecord(product_key=key, url=url, category=category, source_names={f"category:{category}"}),
        )
    for match in re.finditer(r"data-pid=\"([^\"]+)\"", page_html, re.I):
        key = normalize_whitespace(match.group(1))
        if not key:
            continue
        record = products.setdefault(
            key,
            ProductRecord(
                product_key=key,
                url=f"{SITE}/shop/{'sports-bras' if category == 'bras' else category}/{key}.html",
                category=category,
                source_names={f"category:{category}"},
            ),
        )
        record.source_names.add(f"category:{category}")
    return products


def discover_category_products(args: argparse.Namespace) -> Tuple[Dict[str, ProductRecord], List[Dict[str, object]]]:
    products: Dict[str, ProductRecord] = {}
    pages: List[Dict[str, object]] = []
    for category, category_url in CATEGORY_SEEDS:
        start = 0
        page_number = 0
        seen_page_keys: set[Tuple[str, ...]] = set()
        while True:
            if args.max_category_pages and page_number >= args.max_category_pages:
                break
            page_url = category_url if start == 0 else (
                f"{SITE}/on/demandware.store/Sites-yoga-democracy-b2c-Site/en_US/"
                f"Search-UpdateGrid?cgid={category}&start={start}&sz=12"
            )
            page_html = curl_fetch_text(page_url, referer=category_url, accept="text/html,*/*")
            page_products = parse_category_products(page_html, category)
            keys_tuple = tuple(sorted(page_products))
            pages.append({"category": category, "url": page_url, "products": len(page_products), "start": start})
            if not page_products or keys_tuple in seen_page_keys:
                break
            seen_page_keys.add(keys_tuple)
            for key, incoming in page_products.items():
                if key in products:
                    products[key].source_names.update(incoming.source_names)
                    if not products[key].url and incoming.url:
                        products[key].url = incoming.url
                    if not products[key].category:
                        products[key].category = incoming.category
                else:
                    products[key] = incoming
            if len(page_products) < 12:
                break
            start += 12
            page_number += 1
            if args.sleep:
                time.sleep(args.sleep)
    return products, pages


def first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.I | re.S)
    return normalize_whitespace(html.unescape(match.group(1))) if match else ""


def hydrate_product(product: ProductRecord) -> None:
    if not product.url:
        return
    page_html = curl_fetch_text(product.url, referer=SITE, accept="text/html,*/*")
    product.title = (
        first_match(r"<meta[^>]+property=['\"]og:title['\"][^>]+content=['\"]([^'\"]+)['\"]", page_html)
        or first_match(r"<h1[^>]*>(.*?)</h1>", page_html)
        or product.title
    )
    product.description = (
        first_match(r"<meta[^>]+name=['\"]description['\"][^>]+content=['\"]([^'\"]+)['\"]", page_html)
        or strip_tags(first_match(r"<div[^>]+class=['\"][^'\"]*description[^'\"]*['\"][^>]*>(.*?)</div>", page_html))
        or product.description
    )
    if YOTPO_APP_KEY not in page_html:
        product.page_error = "public_yotpo_key_not_seen_on_pdp"


def yotpo_reviews_url(page: int) -> str:
    return f"https://api-cdn.yotpo.com/v1/widget/{YOTPO_APP_KEY}/reviews.json?page={page}&per_page={YOTPO_PER_PAGE}&sort=images"


def response_from_payload(payload: Dict[str, object]) -> Dict[str, object]:
    response = payload.get("response")
    return response if isinstance(response, dict) else {}


def image_urls_from_review(review: Dict[str, object]) -> List[str]:
    urls = []
    images = review.get("images_data") or review.get("images") or []
    if not isinstance(images, list):
        return urls
    for image in images:
        if not isinstance(image, dict):
            continue
        url = normalize_whitespace(image.get("original_url") or image.get("originalUrl") or image.get("url"))
        if url:
            urls.append(url)
    return list(dict.fromkeys(urls))


def custom_field_map(review: Dict[str, object]) -> Dict[str, str]:
    mapped: Dict[str, str] = {}
    fields = review.get("custom_fields")
    if not isinstance(fields, dict):
        return mapped
    for field in fields.values():
        if not isinstance(field, dict):
            continue
        title = normalize_whitespace(field.get("title"))
        value = normalize_whitespace(html.unescape(str(field.get("value") or "")))
        if title and value:
            mapped[title] = value
    return mapped


def comment_with_fields(review: Dict[str, object], fields: Dict[str, str]) -> Tuple[str, str]:
    title = normalize_whitespace(html.unescape(str(review.get("title") or "")))
    body = normalize_whitespace(html.unescape(str(review.get("content") or "")))
    additions = []
    for label in ["Size", "Height", "Weight", "Fit", "Body Type", "Waist", "Hips", "Bust"]:
        if fields.get(label):
            additions.append(f"{label}: {fields[label]}")
    return title, normalize_whitespace(" ".join([body, " ".join(additions)]))


def size_from_fields(fields: Dict[str, str], comment: str) -> str:
    for label in ["Size", "Size Purchased", "Purchased Size"]:
        if fields.get(label):
            return normalize_ordered_size(fields[label])
    for pattern in [
        r"\b(?:ordered|bought|purchased|wear(?:ing)?|got)\s+(?:a\s+|an\s+)?(?:size\s+)?(2xs|xs|s|m|l|xl|2xl|3xl|xxs|small|medium|large)\b",
        r"\bsize\s+(2xs|xs|s|m|l|xl|2xl|3xl|xxs|small|medium|large)\b",
    ]:
        match = re.search(pattern, comment, re.I)
        if match:
            return normalize_ordered_size(match.group(1))
    return ""


def product_url_guess(product_key: str, product_name: str = "") -> str:
    lowered = f"{product_key} {product_name}".lower()
    if re.search(r"\b(?:bra|sports?-bra|bralette)\b", lowered):
        category_order = ["sports-bras", "tops", "tanks", "bottoms", "shorts"]
    elif re.search(r"\b(?:shorts?|skort)\b", lowered):
        category_order = ["shorts", "bottoms", "tops", "tanks", "sports-bras"]
    elif re.search(r"\b(?:legging|bell|bottom|flare|tight)\b", lowered):
        category_order = ["bottoms", "inseam-update", "shorts", "tops", "tanks"]
    elif re.search(r"\b(?:tank|top|tee|shirt)\b", lowered):
        category_order = ["tops", "tanks", "sports-bras", "bottoms", "shorts"]
    else:
        category_order = PDP_CATEGORY_GUESSES
    return f"{SITE}/shop/{category_order[0]}/{product_key}.html"


def context_for_product(product: ProductRecord) -> ProductContext:
    return ProductContext(
        url=product.url,
        title=product.title,
        description=product.description,
        category=product.category,
        brand="Yoga Democracy",
        product_id=product.product_key,
        handle=product.product_key,
        shop_domain="www.yogademocracy.com",
        provider_hints="Yotpo aggregate photo reviews",
    )


def scrape_yotpo_aggregate(args: argparse.Namespace) -> Tuple[List[Dict[str, object]], Dict[str, ProductRecord], List[Dict[str, object]]]:
    reviews: List[Dict[str, object]] = []
    yotpo_products: Dict[str, ProductRecord] = {}
    review_pages: List[Dict[str, object]] = []
    first_payload = curl_fetch_json(yotpo_reviews_url(1), referer=f"{SITE}/shop/tops/")
    first_response = response_from_payload(first_payload)
    pagination = first_response.get("pagination") if isinstance(first_response.get("pagination"), dict) else {}
    total = int(pagination.get("total") or 0)
    total_pages = math.ceil(total / YOTPO_PER_PAGE) if total else 1
    if args.max_review_pages:
        total_pages = min(total_pages, args.max_review_pages)
    for page in range(1, total_pages + 1):
        payload = first_payload if page == 1 else curl_fetch_json(yotpo_reviews_url(page), referer=f"{SITE}/shop/tops/")
        response = response_from_payload(payload)
        products = response.get("products") if isinstance(response.get("products"), list) else []
        for product in products:
            if not isinstance(product, dict):
                continue
            product_id = normalize_whitespace(product.get("id"))
            key = normalize_whitespace(product.get("domain_key"))
            if not product_id or not key:
                continue
            yotpo_products[product_id] = ProductRecord(
                product_key=key,
                title=normalize_whitespace(product.get("name")),
                url=product_url_guess(key, normalize_whitespace(product.get("name"))),
                source_names={"yotpo_aggregate_product"},
            )
        page_reviews = response.get("reviews") if isinstance(response.get("reviews"), list) else []
        image_reviews = [review for review in page_reviews if isinstance(review, dict) and image_urls_from_review(review)]
        reviews.extend([review for review in page_reviews if isinstance(review, dict)])
        review_pages.append(
            {"page": page, "url": yotpo_reviews_url(page), "reviews": len(page_reviews), "image_reviews": len(image_reviews)}
        )
        print(f"yogademocracy yotpo aggregate page {page}/{total_pages}: reviews={len(page_reviews)} image_reviews={len(image_reviews)}", file=sys.stderr, flush=True)
        if args.sleep:
            time.sleep(args.sleep)
    return reviews, yotpo_products, review_pages


def rows_from_reviews(
    reviews: Sequence[Dict[str, object]],
    product_by_yotpo_id: Dict[str, ProductRecord],
    product_by_key: Dict[str, ProductRecord],
    fetched_at: str,
) -> Tuple[List[Dict[str, str]], Dict[str, int], int]:
    rows: List[Dict[str, str]] = []
    product_counts: Dict[str, int] = {}
    missing_product_url_reviews = 0
    seen = set()
    for review in reviews:
        image_urls = image_urls_from_review(review)
        if not image_urls:
            continue
        yotpo_product_id = normalize_whitespace(review.get("product_id"))
        product = product_by_yotpo_id.get(yotpo_product_id)
        if not product:
            missing_product_url_reviews += 1
            continue
        if product.product_key in product_by_key:
            discovered = product_by_key[product.product_key]
            product.url = discovered.url or product.url
            product.category = discovered.category or product.category
            product.source_names.update(discovered.source_names)
        if not product.url:
            missing_product_url_reviews += 1
            continue
        fields = custom_field_map(review)
        title, body = comment_with_fields(review, fields)
        comment = normalize_whitespace(" ".join([title, body]))
        size = size_from_fields(fields, comment)
        reviewer = review.get("user") if isinstance(review.get("user"), dict) else {}
        date_raw = normalize_whitespace(review.get("created_at"))
        context = context_for_product(product)
        for image_index, image_url in enumerate(image_urls, start=1):
            review_id = normalize_whitespace(review.get("id"))
            stable_key = (review_id, image_url)
            if stable_key in seen:
                continue
            seen.add(stable_key)
            review_image = ReviewImage(
                image_url=image_url,
                review_id=f"yogademocracy-yotpo-{review_id}-{image_index}" if review_id else "",
                review_title=title,
                review_body=body,
                reviewer_name=normalize_whitespace(reviewer.get("display_name") or reviewer.get("displayName")),
                date_raw=date_raw,
                review_date=review_date_from_raw(date_raw),
                size_raw=size,
                rating=normalize_whitespace(review.get("score")),
                extra={
                    "product_url": product.url,
                    "product_title": product.title,
                    "product_description": product.description,
                    "product_category": product.category,
                    "image_source_type": "customer_review_image",
                    "image_source_detail": normalize_whitespace(
                        f"public Yotpo aggregate photo review; yotpo_product_id={yotpo_product_id}; rating={normalize_whitespace(review.get('score'))}"
                    ),
                },
            )
            rows.append(build_intake_row(context, review_image, fetched_at))
            product_counts[product.product_key] = product_counts.get(product.product_key, 0) + 1
    return rows, product_counts, missing_product_url_reviews


def dedupe_yogademocracy_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped = []
    seen = set()
    for row in rows:
        key = (row.get("id", ""), row.get("original_url_display", ""))
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
    product_sources: Dict[str, object],
    category_pages: Sequence[Dict[str, object]],
    products_discovered: int,
    products_scanned: int,
    review_pages: Sequence[Dict[str, object]],
    product_summaries: Sequence[Dict[str, object]],
    missing_product_url_reviews: int,
    exhaustive_review_paging: bool,
    errors: Sequence[str],
) -> None:
    summary = {
        "site": SITE,
        "retailer": RETAILER,
        "adapter": "demandware_category_pages_yotpo_aggregate_photo_reviews",
        "yotpo_app_key": YOTPO_APP_KEY,
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": product_sources,
        "category_pages": list(category_pages),
        "products_discovered": products_discovered,
        "products_scanned": products_scanned,
        "products_excluded_from_output": 0,
        "review_pages_scanned": len(review_pages),
        "review_pages": list(review_pages),
        "exhaustive_review_paging": exhaustive_review_paging,
        "product_summaries": list(product_summaries),
        "missing_product_url_reviews": missing_product_url_reviews,
        "errors": list(errors),
        "access_policy": "public Yoga Democracy category/PDP pages and public Yotpo aggregate photo-review JSON only; stop on 429/captcha/WAF/auth behavior.",
        "sovrn_triage_source": {
            "source_file": "data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv",
            "status": "first-pass candidate",
            "provider": "Yotpo",
            "photo_reviews": "yes",
            "reviews_present": "yes",
            "shipping": "US",
            "payout_note": "payout fields not populated; focused safe scrape/probe before broad crawling",
            "category_evidence_url": "https://www.yogademocracy.com/shop/tops/",
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
    errors: List[str] = []
    rows: List[Dict[str, str]] = []
    category_products: Dict[str, ProductRecord] = {}
    category_pages: List[Dict[str, object]] = []
    yotpo_reviews: List[Dict[str, object]] = []
    yotpo_products: Dict[str, ProductRecord] = {}
    review_pages: List[Dict[str, object]] = []

    try:
        category_products, category_pages = discover_category_products(args)
        yotpo_reviews, yotpo_products, review_pages = scrape_yotpo_aggregate(args)
        for product in yotpo_products.values():
            if product.product_key in category_products:
                product.url = category_products[product.product_key].url or product.url
                product.category = category_products[product.product_key].category or product.category
                product.source_names.update(category_products[product.product_key].source_names)
        products_to_hydrate = {product.product_key: product for product in yotpo_products.values() if product.url}
        for index, product in enumerate(products_to_hydrate.values(), start=1):
            try:
                hydrate_product(product)
            except Exception as exc:
                product.page_error = f"hydrate_failed: {exc}"
            if index % 50 == 0:
                print(f"hydrated {index}/{len(products_to_hydrate)} yotpo products", file=sys.stderr, flush=True)
            if args.sleep:
                time.sleep(args.sleep)
        rows, product_counts, missing_product_url_reviews = rows_from_reviews(
            yotpo_reviews, yotpo_products, category_products, fetched_at
        )
    except RuntimeError as exc:
        errors.append(str(exc))
        missing_product_url_reviews = 0
        product_counts = {}
    except Exception as exc:
        errors.append(f"scrape_failed: {exc}")
        missing_product_url_reviews = 0
        product_counts = {}

    rows = dedupe_yogademocracy_rows(dedupe_rows(rows))
    write_intake_csv(rows, output_csv)
    product_summaries = [
        {
            "product_key": product.product_key,
            "product_url": product.url,
            "product_title": product.title,
            "category": product.category,
            "source_names": sorted(product.source_names),
            "customer_review_image_rows": product_counts.get(product.product_key, 0),
            "page_error": product.page_error,
        }
        for product in sorted(yotpo_products.values(), key=lambda item: item.product_key)
    ]
    product_sources = {
        "category_seed_urls": [{"category": category, "url": url} for category, url in CATEGORY_SEEDS],
        "category_products_discovered": len(category_products),
        "yotpo_products_seen": len(yotpo_products),
        "focused_scrape_note": "Category discovery started from Sovrn tops evidence and adjacent public nav categories; review rows come from the small public Yotpo aggregate photo feed.",
    }
    write_summary(
        summary_json,
        output_csv=output_csv,
        rows=rows,
        started_at=started_at,
        finished_at=utc_now(),
        product_sources=product_sources,
        category_pages=category_pages,
        products_discovered=len(category_products),
        products_scanned=len(yotpo_products),
        review_pages=review_pages,
        product_summaries=product_summaries,
        missing_product_url_reviews=missing_product_url_reviews,
        exhaustive_review_paging=args.max_review_pages == 0 and not errors,
        errors=errors,
    )
    print(str(output_csv))
    print(str(summary_json))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
