#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    normalize_bra_size,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    write_intake_csv,
    write_summary,
)


SITE_ROOT = "https://www.wearpepper.com"
SHOP_DOMAIN = "pepper-bra.myshopify.com"
BRAND = "Pepper"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
JUDGEME_WIDGET_URL = "https://api.judge.me/reviews/reviews_for_widget"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
CHALLENGE_RE = re.compile(
    r"\b(?:captcha|cloudflare|datadome|access denied|attention required|verify you are human|blocked)\b",
    re.I,
)
BRA_SIZE_RE = re.compile(r"\b(?:28|30|32|34|36|38|40|42)\s*(?:AAA|AA|A|B|C|D|DD|DDD|E|F)\b", re.I)
ALPHA_SIZE_RE = re.compile(r"\b(?:XXS|XS|S|M|L|XL|XXL|2X|3X|4X)\b", re.I)
NON_OUTPUT_RE = re.compile(
    r"\b(?:gift card|petals?|nippies|nipple|adhesive|tape|adapter|extender|bundle|pack|solution|laundry|bag)\b",
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
        time.sleep(0.25)

    sitemap_index = fetch_text(f"{SITE_ROOT}/sitemap.xml")
    sitemap_urls = [
        html.unescape(match)
        for match in re.findall(r"<loc>(https://www\.wearpepper\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index, re.I)
    ]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url)
        urls = sorted(set(re.findall(r"https://www\.wearpepper\.com/products/[^<\s\"']+", text, re.I)))
        urls = [url.split("?")[0].rstrip("/") for url in urls]
        sitemap_product_urls.extend(urls)
        product_sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})

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
            "options": [],
        }
    product_sources.append(
        {"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)}
    )
    return list(by_url.values()), product_sources


def option_values(product: Dict[str, object], option_name: str) -> List[str]:
    values: List[str] = []
    options = product.get("options")
    if isinstance(options, list):
        for option in options:
            if not isinstance(option, dict):
                continue
            if normalize_whitespace(option.get("name")).lower() != option_name.lower():
                continue
            raw_values = option.get("values")
            if isinstance(raw_values, list):
                values.extend(normalize_whitespace(value) for value in raw_values)
    return [value for value in values if value]


def variant_detail(product: Dict[str, object]) -> str:
    vals: List[str] = []
    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants[:250]:
            if not isinstance(variant, dict):
                continue
            title = normalize_whitespace(variant.get("title"))
            if title and title.lower() != "default title" and title not in vals:
                vals.append(title)
    return " | ".join(vals)


def context_from_product(product: Dict[str, object]) -> ProductContext:
    color_values = option_values(product, "Color")
    return ProductContext(
        url=product_url_for(product),
        title=normalize_whitespace(product.get("title")),
        description=strip_tags(product.get("body_html")),
        detail=variant_detail(product),
        category=normalize_whitespace(product.get("product_type")),
        brand=normalize_whitespace(product.get("vendor")) or BRAND,
        color=color_values[0] if len(color_values) == 1 else "",
        product_id=normalize_whitespace(product.get("id")),
        handle=normalize_whitespace(product.get("handle")),
        shop_domain=SHOP_DOMAIN,
        provider_hints="Judge.me",
    )


def skip_reason(context: ProductContext) -> str:
    text = f"{context.title} {context.category} {context.url}".lower()
    if NON_OUTPUT_RE.search(text):
        return "out_of_scope_accessory_bundle_or_non_single_clothing_item"
    return ""


def unique(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        clean = normalize_whitespace(value)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def clean_product_url(value: str) -> str:
    clean = normalize_whitespace(value)
    if not clean:
        return ""
    if clean.startswith("/"):
        clean = urljoin(SITE_ROOT, clean)
    return clean.split("?", 1)[0].rstrip("/")


def cf_answer_lines(review: Dict[str, object]) -> Tuple[List[str], str]:
    lines: List[str] = []
    size_raw = ""
    answers = review.get("cf_answers")
    if not isinstance(answers, list):
        return lines, size_raw
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        label = normalize_whitespace(
            answer.get("label")
            or answer.get("question")
            or answer.get("title")
            or answer.get("name")
            or answer.get("field")
        ).rstrip(":")
        value = answer.get("value")
        if isinstance(value, list):
            value_text = ", ".join(normalize_whitespace(item) for item in value if normalize_whitespace(item))
        else:
            value_text = normalize_whitespace(value or answer.get("answer") or answer.get("text"))
        if not value_text:
            continue
        if label:
            lines.append(f"{label}: {value_text}")
        else:
            lines.append(value_text)
        if re.search(r"\b(?:size|bra size|purchased|ordered)\b", label, re.I):
            size_raw = value_text
    return lines, size_raw


def normalize_variant_size(value: str) -> str:
    clean = normalize_whitespace(value)
    if not clean:
        return ""
    first = clean.split("/", 1)[0].strip()
    bra = BRA_SIZE_RE.search(first)
    if bra:
        return normalize_bra_size(bra.group(0))
    alpha = ALPHA_SIZE_RE.search(first)
    if alpha:
        return alpha.group(0).upper()
    return ""


def reviews_from_payload(payload: Dict[str, object], context: ProductContext) -> List[ReviewImage]:
    reviews: List[ReviewImage] = []
    raw_reviews = payload.get("reviews")
    if not isinstance(raw_reviews, list):
        return reviews
    for review in raw_reviews:
        if not isinstance(review, dict):
            continue
        image_urls = unique(str(url) for url in review.get("pictures_urls") or [] if url)
        if not image_urls:
            continue
        cf_lines, cf_size = cf_answer_lines(review)
        body = strip_tags(review.get("body_html") or "")
        variant_title = normalize_whitespace(review.get("product_variant_title"))
        size_raw = cf_size or normalize_variant_size(variant_title)
        product_url = clean_product_url(
            normalize_whitespace(review.get("product_url_with_utm")) or normalize_whitespace(review.get("product_url")) or context.url
        )
        product_title = normalize_whitespace(review.get("product_title")) or context.title
        comment = " | ".join(part for part in [" | ".join(cf_lines), body] if part)
        extra = {
            "product_url": product_url,
            "product_title": product_title,
            "product_description": context.description if product_url == context.url else "",
            "product_detail": context.detail if product_url == context.url else "",
            "product_category": context.category,
            "product_variant": variant_title,
            "image_source_type": "customer_review_image",
            "image_source_detail": "Judge.me review image",
        }
        for image_url in image_urls:
            reviews.append(
                ReviewImage(
                    image_url=image_url,
                    review_id=normalize_whitespace(review.get("uuid")),
                    review_title=normalize_whitespace(review.get("title")),
                    review_body=comment,
                    reviewer_name=normalize_whitespace(review.get("reviewer_name")),
                    date_raw=normalize_whitespace(review.get("created_at")),
                    size_raw=size_raw,
                    rating=normalize_whitespace(review.get("rating")),
                    extra=extra,
                )
            )
    return reviews


def fetch_product_reviews(context: ProductContext) -> Tuple[List[ReviewImage], Dict[str, object]]:
    meta: Dict[str, object] = {
        "product_url": context.url,
        "product_title": context.title,
        "adapter_used": "judgeme_product_reviews_json",
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "matching_review_images": 0,
        "errors": [],
        "skipped_from_output": False,
        "skip_reason": "",
    }
    if not context.product_id:
        meta["errors"].append("missing_shopify_product_id")
        return [], meta

    reviews: List[ReviewImage] = []
    seen = set()
    total_pages = 1
    for page in range(1, 10000):
        params = {
            "url": urlparse(SITE_ROOT).netloc,
            "shop_domain": SHOP_DOMAIN,
            "platform": "shopify",
            "per_page": REVIEWS_PER_PAGE,
            "page": page,
            "product_id": context.product_id,
            "sort_by": "with_pictures",
        }
        payload = fetch_json(JUDGEME_WIDGET_URL, params, referer=context.url)
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"]) + 1
        meta["review_count_hint"] = max(int(meta["review_count_hint"] or 0), int(payload.get("number_of_reviews") or 0))
        pagination = payload.get("pagination")
        if isinstance(pagination, dict):
            total_pages = max(1, int(pagination.get("total_pages") or 0))
        for review in reviews_from_payload(payload, context):
            key = (review.review_id, review.image_url)
            if key in seen:
                continue
            seen.add(key)
            reviews.append(review)
        if page >= total_pages:
            break
        time.sleep(0.15)
    meta["matching_review_images"] = len(reviews)
    return reviews, meta


def dedupe_judgeme_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
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
        time.sleep(0.15)

    rows = dedupe_judgeme_rows(dedupe_rows(rows))
    output_csv, summary_json = output_paths("wearpepper.com")
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    write_summary(
        summary_json,
        site=SITE_ROOT,
        retailer="wearpepper.com",
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=finished_at,
        products_scanned=len(products),
        adapter="judgeme_product_reviews_json",
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
            "review_paging_note": "Judge.me product endpoint was paged with sort_by=with_pictures to exhaust public media-bearing review pages without crawling text-only grouped review history.",
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
    print(json.dumps({"wearpepper_com": summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
