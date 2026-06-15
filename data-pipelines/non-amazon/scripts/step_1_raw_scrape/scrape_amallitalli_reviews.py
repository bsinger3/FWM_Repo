#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple
from urllib.parse import urlencode, urlparse

from scrape_p0_lead_reviews import LooxAdapter
from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    canonical_product_url,
    dedupe_rows,
    fetch_json,
    fetch_text,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    validate_rows,
    write_intake_csv,
)


SITE_ROOT = "https://amallitalli.com"
RETAILER = "amallitalli_com"
LOOX_APP_ID = "dhtRTz2ihe"
SEED_PRODUCT_ID = "10249148530971"
SEED_PRODUCT_URL = f"{SITE_ROOT}/products/mercer-tall-jacket-ecru"
OUTPUT_CSV, SUMMARY_JSON = output_paths(RETAILER)


def norm(value: object) -> str:
    return normalize_whitespace(value)


def title_key(value: str) -> str:
    value = norm(value).lower()
    value = re.sub(r"\s+", " ", value)
    return value


def discover_products(max_pages: int = 20) -> Tuple[Dict[str, ProductContext], Dict[str, ProductContext], List[Dict[str, object]], List[str]]:
    by_title: Dict[str, ProductContext] = {}
    by_id: Dict[str, ProductContext] = {}
    summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    for page in range(1, max_pages + 1):
        api_url = f"{SITE_ROOT}/products.json?limit=250&page={page}"
        try:
            payload = fetch_json(api_url, referer=SITE_ROOT, retries=2)
        except Exception as exc:
            if page == 1:
                errors.append(f"products_json_failed: {type(exc).__name__}: {exc}")
            break
        products = payload.get("products")
        if not isinstance(products, list) or not products:
            break
        for product in products:
            if not isinstance(product, dict):
                continue
            handle = norm(product.get("handle"))
            product_id = norm(product.get("id"))
            title = norm(product.get("title"))
            if not handle or not product_id or not title:
                continue
            variants = product.get("variants")
            variant = ""
            color = ""
            if isinstance(variants, list) and variants and isinstance(variants[0], dict):
                variant = norm(variants[0].get("title"))
                color = norm(variants[0].get("option1") or variants[0].get("option2"))
            context = ProductContext(
                url=canonical_product_url(f"{SITE_ROOT}/products/{handle}"),
                title=title,
                description=strip_tags(product.get("body_html")),
                category=norm(product.get("product_type")) or "Tall women's apparel",
                brand=norm(product.get("vendor")) or "Amalli Talli",
                color=color,
                variant=variant,
                product_id=product_id,
                handle=handle,
                shop_domain="amallitalli.com",
                provider_hints="Loox public photo reviews",
                raw_html="",
            )
            by_title[title_key(title)] = context
            by_id[product_id] = context
        summaries.append({"page": page, "products": len(products)})
        if len(products) < 250:
            break
    return by_title, by_id, summaries, errors


def loox_url(page: int, limit: int) -> str:
    return f"https://loox.io/widget/{LOOX_APP_ID}/reviews?{urlencode({'productId': SEED_PRODUCT_ID, 'page': page, 'limit': limit, 'sort_by': 'photo'})}"


def scrape_loox_pages(max_pages: int, limit: int, delay: float) -> Tuple[List[ReviewImage], List[Dict[str, object]], List[str]]:
    adapter = LooxAdapter()
    reviews: List[ReviewImage] = []
    summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    seen = set()
    for page in range(1, max_pages + 1):
        url = loox_url(page, limit)
        time.sleep(delay)
        try:
            html_text = fetch_text(url, referer=SEED_PRODUCT_URL, retries=2)
        except Exception as exc:
            errors.append(f"loox_page_fetch_failed_page_{page}: {type(exc).__name__}: {exc}")
            break
        parsed = adapter._parse_embedded(html_text)
        page_reviews = []
        for review in parsed:
            key = (review.review_id, review.image_url)
            if not review.image_url or key in seen:
                continue
            seen.add(key)
            page_reviews.append(review)
        summaries.append(
            {
                "page": page,
                "reviews_with_images": len(page_reviews),
                "raw_reviews_with_images": len(parsed),
                "height_terms": html_text.lower().count("height"),
                "weight_terms": html_text.lower().count("weight"),
            }
        )
        reviews.extend(page_reviews)
        print(f"[loox page {page}] rows={len(page_reviews)}", flush=True)
        if not page_reviews:
            break
    return reviews, summaries, errors


def context_for_review(review: ReviewImage, by_title: Dict[str, ProductContext]) -> ProductContext:
    product_title = norm(review.extra.get("product_title"))
    context = by_title.get(title_key(product_title))
    if context:
        return context
    return ProductContext(
        url=SEED_PRODUCT_URL,
        title=product_title or "Amalli Talli tall apparel",
        category="Tall women's apparel",
        brand="Amalli Talli",
        shop_domain="amallitalli.com",
        provider_hints="Loox public photo reviews",
    )


def rows_from_reviews(reviews: Iterable[ReviewImage], by_title: Dict[str, ProductContext], fetched_at: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for review in reviews:
        context = context_for_review(review, by_title)
        product_title = norm(review.extra.get("product_title")) or context.title
        rows.append(
            build_intake_row(
                context,
                ReviewImage(
                    image_url=review.image_url,
                    review_id=f"amallitalli-loox-{review.review_id}",
                    review_title=review.review_title,
                    review_body=review.review_body,
                    reviewer_name=review.reviewer_name,
                    date_raw=review.date_raw,
                    size_raw=review.size_raw,
                    rating=review.rating,
                    extra={
                        "product_url": context.url,
                        "product_title": product_title,
                        "image_source_type": "customer_review_image",
                        "image_source_detail": "loox_public_photo_review",
                    },
                ),
                fetched_at,
            )
        )
    return rows


def clear_implausible_measurements(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    cleaned: List[Dict[str, str]] = []
    for row in rows:
        height = row.get("height_in_display")
        if height:
            try:
                height_value = float(height)
            except ValueError:
                height_value = 0
            if height_value < 48 or height_value > 84:
                row["height_in_display"] = ""
                row["height_raw"] = ""
        cleaned.append(row)
    return cleaned


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Amalli Talli public Loox photo reviews for tall-gap coverage.")
    parser.add_argument("--max-pages", type=int, default=25)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--request-delay-seconds", type=float, default=0.25)
    args = parser.parse_args(argv)

    started_at = utc_now()
    by_title, by_id, product_page_summaries, product_errors = discover_products()
    reviews, loox_page_summaries, loox_errors = scrape_loox_pages(
        max_pages=args.max_pages,
        limit=args.limit,
        delay=args.request_delay_seconds,
    )
    rows = clear_implausible_measurements(dedupe_rows(rows_from_reviews(reviews, by_title, started_at)))
    write_intake_csv(rows, OUTPUT_CSV)
    finished_at = utc_now()
    validation = validate_rows(rows)
    summary = {
        "site": "amallitalli.com",
        "retailer": RETAILER,
        "adapter": "shopify_products_json_loox_public_photo_reviews",
        "candidate_source": "outputs/measurement_coverage/20260609_human_labeled_approved_only/net_new_site_research_candidates.csv",
        "candidate_target_gap_tags": "height_6ft_plus,inseam_34_plus,tall_women",
        "review_platform_provider": "Loox",
        "loox_app_id": LOOX_APP_ID,
        "seed_product_id": SEED_PRODUCT_ID,
        "seed_product_url": SEED_PRODUCT_URL,
        "products_discovered": len(by_id),
        "products_scanned": 1,
        "review_pages_scanned": len(loox_page_summaries),
        "output_csv": str(OUTPUT_CSV),
        "started_at": started_at,
        "finished_at": finished_at,
        "access_policy": "public Shopify products.json and public Loox widget photo reviews only; stop_on_429_captcha_waf_auth",
        "product_page_summaries": product_page_summaries,
        "loox_page_summaries": loox_page_summaries,
        "errors": product_errors + loox_errors,
    }
    summary.update(validation)
    summary["rows_with_distinct_product_url"] = validation.get("distinct_products", 0)
    summary["rows_with_customer_image"] = validation.get("rows_with_customer_review_image", 0)
    summary["rows_with_customer_ordered_size"] = validation.get("rows_with_customer_ordered_size", 0)
    summary["rows_supabase_qualified"] = validation.get("supabase_qualified_rows", 0)
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {SUMMARY_JSON}")
    print(
        f"Rows={summary['rows_written']} measurements={summary['rows_with_any_measurement']} "
        f"qualified={summary['rows_supabase_qualified']} products={summary['distinct_products']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
