#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

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


SITE_ROOT = "https://www.thirdlove.com"
APP_KEY = "rY9GSntV8qMS3mVnRNBzVIaznqMp8VJiTDyl1Cjr"
BRAND = "ThirdLove"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
REQUEST_DELAY_SECONDS = 0.2
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
CHALLENGE_RE = re.compile(
    r"\b(?:captcha|cloudflare|datadome|access denied|attention required|verify you are human|blocked)\b",
    re.I,
)
NON_OUTPUT_RE = re.compile(
    r"\b(?:gift card|detergent|laundry bag|mesh bag|tape|extender|insert|removable pads?|bundle|pack)\b",
    re.I,
)


class StopScrape(RuntimeError):
    pass


def fetch_text(url: str, *, referer: str = SITE_ROOT, retries: int = 3) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/json,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": referer,
            },
        )
        try:
            with urlopen(req, timeout=45) as resp:
                body = resp.read().decode("utf-8", "replace")
                if CHALLENGE_RE.search(body[:5000]):
                    raise StopScrape(f"Stopping on challenge-like response for {url}")
                return body
        except HTTPError as exc:
            last_error = exc
            if exc.code in {403, 429}:
                raise StopScrape(f"Stopping on HTTP {exc.code} for {url}") from exc
            if exc.code not in {408, 500, 502, 503, 504}:
                raise
        except URLError as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"Failed text request for {url}: {last_error}")


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, *, referer: str = SITE_ROOT) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    return json.loads(fetch_text(query_url, referer=referer))


def product_url_for(product: Dict[str, object]) -> str:
    handle = normalize_whitespace(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def discover_products() -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    by_url: Dict[str, Dict[str, object]] = {}
    product_sources: List[Dict[str, object]] = []

    page = 1
    while True:
        payload = fetch_json(f"{SITE_ROOT}/products.json", {"limit": PRODUCTS_PER_PAGE, "page": page})
        products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        product_sources.append({"source": "products.json", "page": page, "count": len(products)})
        for product in products:
            url = product_url_for(product)
            if url:
                by_url[url] = product
        if len(products) < PRODUCTS_PER_PAGE:
            break
        page += 1
        time.sleep(REQUEST_DELAY_SECONDS)

    sitemap_index = fetch_text(f"{SITE_ROOT}/sitemap.xml")
    sitemap_urls = [
        html.unescape(match)
        for match in re.findall(r"<loc>(https://www\.thirdlove\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index, re.I)
    ]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url)
        urls = sorted(set(re.findall(r"https://www\.thirdlove\.com/products/[^<\s\"']+", text, re.I)))
        urls = [url.split("?", 1)[0].rstrip("/") for url in urls]
        sitemap_product_urls.extend(urls)
        product_sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        time.sleep(REQUEST_DELAY_SECONDS)

    missing = [url for url in sorted(set(sitemap_product_urls)) if url not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {
            "id": "",
            "handle": handle,
            "title": handle.replace("-", " ").title(),
            "vendor": BRAND,
            "product_type": "",
            "body_html": "",
            "variants": [],
        }
    product_sources.append(
        {"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)}
    )
    return list(by_url.values()), product_sources


def variant_detail(product: Dict[str, object]) -> str:
    vals: List[str] = []
    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants[:300]:
            if not isinstance(variant, dict):
                continue
            title = normalize_whitespace(variant.get("title"))
            if title and title.lower() != "default title" and title not in vals:
                vals.append(title)
    return " | ".join(vals)


def context_from_product(product: Dict[str, object]) -> ProductContext:
    return ProductContext(
        url=product_url_for(product),
        title=normalize_whitespace(product.get("title")),
        description=strip_tags(product.get("body_html")),
        detail=variant_detail(product),
        category=normalize_whitespace(product.get("product_type")),
        brand=normalize_whitespace(product.get("vendor")) or BRAND,
        product_id=normalize_whitespace(product.get("id")),
        handle=normalize_whitespace(product.get("handle")),
        shop_domain="thirdlove.myshopify.com",
        provider_hints="Yotpo",
    )


def skip_reason(context: ProductContext) -> str:
    text = f"{context.title} {context.category} {context.url}".lower()
    if NON_OUTPUT_RE.search(text):
        return "out_of_scope_accessory_bundle_or_non_single_clothing_item"
    return ""


def review_image_urls(review: Dict[str, object]) -> List[str]:
    images = review.get("images_data")
    if not isinstance(images, list):
        return []
    urls: List[str] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        url = normalize_whitespace(image.get("original_url") or image.get("thumb_url"))
        if url:
            urls.append(url)
    return list(dict.fromkeys(urls))


def custom_field_lines(review: Dict[str, object]) -> List[str]:
    fields = review.get("custom_fields")
    if not isinstance(fields, dict):
        return []
    lines: List[str] = []
    for field in fields.values():
        if not isinstance(field, dict):
            continue
        title = normalize_whitespace(field.get("title")).rstrip(":")
        value = normalize_whitespace(field.get("value"))
        if not value:
            continue
        lines.append(f"{title}: {value}" if title else value)
    return lines


def reviews_from_payload(payload: Dict[str, object], context: ProductContext) -> List[ReviewImage]:
    response = payload.get("response")
    if not isinstance(response, dict):
        return []
    reviews = response.get("reviews")
    if not isinstance(reviews, list):
        return []
    out: List[ReviewImage] = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        urls = review_image_urls(review)
        if not urls:
            continue
        cf_lines = custom_field_lines(review)
        comment = " | ".join(part for part in [" | ".join(cf_lines), normalize_whitespace(review.get("content"))] if part)
        user = review.get("user") if isinstance(review.get("user"), dict) else {}
        reviewer = normalize_whitespace(user.get("display_name") if isinstance(user, dict) else "")
        extra = {
            "product_url": context.url,
            "product_title": context.title,
            "product_description": context.description,
            "product_detail": context.detail,
            "product_category": context.category,
            "image_source_type": "customer_review_image",
            "image_source_detail": "Yotpo review image",
        }
        for url in urls:
            out.append(
                ReviewImage(
                    image_url=url,
                    review_id=normalize_whitespace(review.get("id")),
                    review_title=normalize_whitespace(review.get("title")),
                    review_body=comment,
                    reviewer_name=reviewer,
                    date_raw=normalize_whitespace(review.get("created_at")),
                    extra=extra,
                )
            )
    return out


def fetch_product_reviews(context: ProductContext) -> Tuple[List[ReviewImage], Dict[str, object]]:
    meta: Dict[str, object] = {
        "product_url": context.url,
        "product_title": context.title,
        "adapter_used": "yotpo_product_widget_images",
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "matching_review_images": 0,
        "errors": [],
    }
    if not context.product_id:
        meta["errors"].append("missing_shopify_product_id")
        return [], meta

    reviews: List[ReviewImage] = []
    seen = set()
    saw_media = False
    for page in range(1, 10000):
        url = f"https://api-cdn.yotpo.com/v1/widget/{APP_KEY}/products/{context.product_id}/reviews.json"
        payload = fetch_json(url, {"per_page": REVIEWS_PER_PAGE, "page": page, "sort": "images"}, referer=context.url)
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"]) + 1
        response = payload.get("response") if isinstance(payload, dict) else {}
        if isinstance(response, dict):
            pagination = response.get("pagination")
            if isinstance(pagination, dict):
                meta["review_count_hint"] = max(int(meta["review_count_hint"] or 0), int(pagination.get("total") or 0))
        page_reviews = []
        for review in reviews_from_payload(payload, context):
            key = (review.review_id, review.image_url)
            if key in seen:
                continue
            seen.add(key)
            page_reviews.append(review)
        if page_reviews:
            saw_media = True
            reviews.extend(page_reviews)
        elif saw_media or page > 1 or int(meta["review_count_hint"] or 0) == 0:
            break
        if page * REVIEWS_PER_PAGE >= int(meta["review_count_hint"] or 0):
            break
        time.sleep(REQUEST_DELAY_SECONDS)
    meta["matching_review_images"] = len(reviews)
    return reviews, meta


def dedupe_yotpo_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        review_id = row.get("id") or ""
        image_url = (row.get("original_url_display") or "").split("?", 1)[0]
        product_url = row.get("product_page_url_display") or ""
        key = (review_id, image_url) if review_id and image_url else (product_url, image_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def has_required_measurement(row: Dict[str, str]) -> bool:
    return any(
        row.get(field)
        for field in [
            "height_in_display",
            "weight_display_display",
            "weight_lbs_display",
            "bust_in_number_display",
            "hips_in_display",
            "waist_in",
            "inseam_inches_display",
        ]
    )


def scrape() -> Dict[str, object]:
    started_at = utc_now()
    products, product_sources = discover_products()
    fetched_at = utc_now()
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    review_pages_scanned = 0
    total_review_count_hint = 0

    for index, product in enumerate(products, start=1):
        context = context_from_product(product)
        reason = skip_reason(context)
        if reason:
            product_summaries.append(
                {
                    "product_index": index,
                    "product_id": context.product_id,
                    "product_title": context.title,
                    "product_url": context.url,
                    "adapter_used": "skipped_from_output",
                    "review_pages_scanned": 0,
                    "review_count_hint": 0,
                    "matching_review_images": 0,
                    "rows": 0,
                    "errors": [],
                    "skipped_from_output": True,
                    "skip_reason": reason,
                }
            )
            print(f"[{index}/{len(products)}] {context.title} skipped={reason}", flush=True)
            continue

        reviews, meta = fetch_product_reviews(context)
        review_pages_scanned += int(meta.get("review_pages_scanned") or 0)
        total_review_count_hint += int(meta.get("review_count_hint") or 0)
        if meta.get("errors"):
            errors.extend(str(error) for error in meta["errors"])
        product_rows = [build_intake_row(context, review, fetched_at) for review in reviews]
        rows.extend(product_rows)
        product_summaries.append(
            {
                "product_index": index,
                "product_id": context.product_id,
                "product_title": context.title,
                "product_url": context.url,
                "adapter_used": meta.get("adapter_used"),
                "review_pages_scanned": meta.get("review_pages_scanned"),
                "review_count_hint": meta.get("review_count_hint"),
                "matching_review_images": meta.get("matching_review_images"),
                "rows": len(product_rows),
                "errors": meta.get("errors"),
                "skipped_from_output": False,
                "skip_reason": "",
            }
        )
        print(
            f"[{index}/{len(products)}] {context.title} reviews={meta.get('review_count_hint')} "
            f"pages={meta.get('review_pages_scanned')} rows={len(product_rows)}",
            flush=True,
        )
        time.sleep(REQUEST_DELAY_SECONDS)

    rows = dedupe_yotpo_rows(dedupe_rows(rows))
    output_csv, summary_json = output_paths("thirdlove.com")
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    write_summary(
        summary_json,
        site=SITE_ROOT,
        retailer="thirdlove.com",
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=finished_at,
        products_scanned=len(products),
        adapter="yotpo_product_widget_images",
        product_summaries=product_summaries,
        errors=errors,
    )
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    summary.update(
        {
            "product_sources": product_sources,
            "products_discovered": len(products),
            "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
            "products_target_scanned": sum(1 for item in product_summaries if not item.get("skipped_from_output")),
            "target_scope": "women's clothing products; accessories, bundles, and non-single-product packs excluded from output",
            "review_pages_scanned": review_pages_scanned,
            "product_review_count_hint": total_review_count_hint,
            "exhaustive_review_paging": False,
            "exhaustive_media_review_paging": True,
            "review_paging_note": "Yotpo product endpoint was paged with sort=images and stopped after media-bearing rows were exhausted for each product.",
            "rows_with_distinct_product_url": len(
                {row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}
            ),
            "rows_with_product_url": sum(
                1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display")
            ),
            "rows_with_customer_image": sum(
                1
                for row in rows
                if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image"
            ),
            "rows_with_any_measurement": sum(1 for row in rows if has_required_measurement(row)),
            "rows_with_image_product_and_measurement": sum(
                1
                for row in rows
                if row.get("original_url_display") and row.get("product_page_url_display") and has_required_measurement(row)
            ),
            "rows_supabase_qualified": summary.get("supabase_qualified_rows", 0),
        }
    )
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    summary = scrape()
    print(json.dumps({"thirdlove_com": summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
