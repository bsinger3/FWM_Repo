#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

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
    write_intake_csv,
)


SITE_ROOT = "https://www.hollisterco.com"
DOMAIN = "hollisterco.com"
SITEMAP_URL = f"{SITE_ROOT}/api/ecomm/util/sitemap/product?targetStoreId=10251&targetLangId=-1"
BAZAARVOICE_BASE = "https://apps.bazaarvoice.com/bfd/v1/clients/hollister/api-products/cv2/resources/data/reviews.json"
DISPLAY_CODE = "17450-en_us"
BV_BFD_TOKEN = "17450,main_site,en_US"
REQUEST_DELAY_SECONDS = 0.05
REVIEW_PAGE_SIZE = 100

PRODUCT_UA = "Googlebot/2.1 (+http://www.google.com/bot.html)"
DEFAULT_UA = "Mozilla/5.0 (compatible; FWM non-Amazon raw scrape; +https://friendswithmeasurements.com)"

BLOCK_MARKERS = [
    "verify you are human",
    "access denied",
    "attention required",
    "cf-chl",
]


class StopScrape(RuntimeError):
    pass


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


def fetch_text(
    url: str,
    *,
    user_agent: str = DEFAULT_UA,
    accept: str = "text/html,application/xml,application/json;q=0.9,*/*;q=0.8",
    referer: str = "",
    retries: int = 4,
    timeout: int = 60,
    headers: Optional[Dict[str, str]] = None,
) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        request_headers = {
            "User-Agent": user_agent,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        }
        if referer:
            request_headers["Referer"] = referer
        if headers:
            request_headers.update(headers)
        try:
            req = Request(url, headers=request_headers)
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            lower_body = body.lower()
            if any(marker in lower_body for marker in BLOCK_MARKERS):
                raise StopScrape(f"challenge_marker_in_response: {url}")
            return body
        except HTTPError as exc:
            last_error = exc
            if exc.code in {403, 409, 429, 503}:
                raise StopScrape(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
            if exc.code not in {408, 500, 502, 504}:
                raise
        except StopScrape:
            raise
        except (URLError, TimeoutError) as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 12))
    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def fetch_json(url: str, *, headers: Optional[Dict[str, str]] = None, retries: int = 4) -> Dict[str, object]:
    return json.loads(fetch_text(url, accept="application/json,text/plain,*/*", headers=headers, retries=retries))


def discover_product_urls() -> List[str]:
    text = fetch_text(SITEMAP_URL, accept="application/xml,text/xml,*/*", referer=SITE_ROOT)
    urls = [html.unescape(match) for match in re.findall(r"<loc>(.*?)</loc>", text, re.I | re.S)]
    urls = [
        url
        for url in urls
        if url.startswith(f"{SITE_ROOT}/shop/us/p/") and re.search(r"-\d+(?:[?#].*)?$", urlparse(url).path)
    ]
    return unique(urls)


def title_from_url(product_url: str) -> str:
    slug = urlparse(product_url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"-\d+$", "", slug)
    return normalize_whitespace(slug.replace("-", " ").title())


def json_ld_products(html_text: str) -> List[Dict[str, object]]:
    products: List[Dict[str, object]] = []
    for raw in re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html_text,
        flags=re.I | re.S,
    ):
        try:
            data = json.loads(html.unescape(raw.strip()))
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if isinstance(item, dict) and str(item.get("@type", "")).lower() == "product":
                products.append(item)
    return products


def first_json_ld_product(html_text: str) -> Dict[str, object]:
    products = json_ld_products(html_text)
    return products[0] if products else {}


def apollo_cache_text(html_text: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', html_text)
    if not match:
        return ""
    return normalize_whitespace(match.group(1).encode("utf-8").decode("unicode_escape", errors="ignore"))


def parse_product_context(product_url: str, html_text: str, bv_product_id: str) -> ProductContext:
    product_ld = first_json_ld_product(html_text)
    title = normalize_whitespace(product_ld.get("name")) or apollo_cache_text(html_text, "productName") or title_from_url(product_url)
    description = strip_tags(product_ld.get("description")) or apollo_cache_text(html_text, "description")
    color = apollo_cache_text(html_text, "colorFamily")
    breadcrumbs = re.search(r'"breadcrumbs"\s*:\s*\[(.*?)\]', html_text)
    category = ""
    if breadcrumbs:
        category = normalize_whitespace(re.sub(r'["\[\]]', " ", breadcrumbs.group(1)).replace(",", " "))
    return ProductContext(
        url=product_url,
        title=title,
        description=description,
        category=category,
        brand="Hollister",
        color=color,
        product_id=bv_product_id,
        provider_hints="Bazaarvoice",
        raw_html="",
    )


def parse_bv_product_id(html_text: str) -> str:
    match = re.search(r'data-bv-product-id=["\'](\d+)["\']', html_text)
    if match:
        return match.group(1)
    match = re.search(r'"reviewsSku"\s*:\s*"(\d+)"', html_text)
    if match:
        return match.group(1)
    return ""


def parse_review_pool_id(html_text: str, bv_product_id: str) -> str:
    match = re.search(r'collectionId\\?":\\?"(\d+)\\?"', html_text)
    if match:
        return f"collection:{match.group(1)}"
    match = re.search(r'"BV_FE_FAMILY".{0,240}?"Value"\s*:\s*"(\d+)"', html_text, flags=re.S)
    if match:
        return f"collection:{match.group(1)}"
    return f"product:{bv_product_id}" if bv_product_id else ""


def fetch_product_context(product_url: str) -> Tuple[ProductContext, str, str]:
    html_text = fetch_text(product_url, user_agent=PRODUCT_UA, referer=SITE_ROOT)
    bv_product_id = parse_bv_product_id(html_text)
    context = parse_product_context(product_url, html_text, bv_product_id)
    return context, bv_product_id, html_text


def fetch_bazaarvoice_json(params: Dict[str, object]) -> Dict[str, object]:
    url = f"{BAZAARVOICE_BASE}?{urlencode(params, doseq=True)}"
    return fetch_json(
        url,
        headers={
            "Origin": SITE_ROOT,
            "Referer": f"{SITE_ROOT}/",
            "bv-bfd-token": BV_BFD_TOKEN,
        },
        retries=5,
    )


def fetch_photo_reviews(bv_product_id: str) -> Tuple[List[Dict[str, object]], int, int]:
    reviews: List[Dict[str, object]] = []
    seen = set()
    pages = 0
    offset = 0
    total = 0
    while True:
        payload = fetch_bazaarvoice_json(
            {
                "resource": "reviews",
                "action": "PHOTOS_TYPE",
                "filter": [
                    f"productid:eq:{bv_product_id}",
                    "contentlocale:eq:en_US,en_US",
                    "isratingsonly:eq:false",
                    "HasMedia:eq:true",
                ],
                "filter_reviews": "contentlocale:eq:en_US,en_US",
                "include": "authors,products,comments",
                "filteredstats": "reviews",
                "Stats": "Reviews",
                "limit": REVIEW_PAGE_SIZE,
                "offset": offset,
                "limit_comments": 3,
                "sort": "submissiontime:desc",
                "Offset": offset,
                "apiversion": "5.5",
                "displaycode": DISPLAY_CODE,
            }
        )
        pages += 1
        response = payload.get("response") if isinstance(payload, dict) else {}
        if not isinstance(response, dict):
            break
        total = int(response.get("TotalResults") or total or 0)
        results = response.get("Results") or []
        if not isinstance(results, list) or not results:
            break
        for review in results:
            if not isinstance(review, dict):
                continue
            review_id = normalize_whitespace(review.get("Id"))
            if review_id and review_id in seen:
                continue
            seen.add(review_id)
            reviews.append(review)
        offset += REVIEW_PAGE_SIZE
        if offset >= total:
            break
    return reviews, pages, total


def nested_value(container: Dict[str, object], outer_key: str, inner_key: str = "Value") -> str:
    values = container.get(outer_key) or {}
    if isinstance(values, dict):
        return normalize_whitespace(values.get(inner_key))
    return ""


def review_context_value(review: Dict[str, object], key: str) -> str:
    values = review.get("ContextDataValues") or {}
    if isinstance(values, dict):
        return nested_value(values, key)
    return ""


def additional_value(review: Dict[str, object], key: str) -> str:
    values = review.get("AdditionalFields") or {}
    if isinstance(values, dict):
        return nested_value(values, key)
    return ""


def height_display(raw: str) -> str:
    value = normalize_whitespace(raw)
    if re.fullmatch(r"\d{2}", value):
        return f"{value[0]}'{value[1]}\""
    if re.fullmatch(r"\d{3}", value):
        return f"{value[0]}'{value[1:]}\""
    return value


def weight_display(raw: str) -> str:
    value = normalize_whitespace(raw)
    match = re.fullmatch(r"(\d{2,3})(\d{2,3})Lbs", value)
    if match:
        return f"{match.group(1)}-{match.group(2)} lbs"
    match = re.fullmatch(r"(\d{2,3})Lbs", value)
    if match:
        return f"{match.group(1)} lbs"
    return value.replace("Lbs", " lbs")


def photo_url(photo: Dict[str, object]) -> str:
    sizes = photo.get("Sizes") or {}
    if not isinstance(sizes, dict):
        return ""
    for key in ["large", "normal", "thumbnail"]:
        item = sizes.get(key) or {}
        if isinstance(item, dict) and item.get("Url"):
            return normalize_whitespace(item.get("Url"))
    return ""


def build_review_images(review: Dict[str, object], context: ProductContext) -> List[ReviewImage]:
    review_id = normalize_whitespace(review.get("Id"))
    title = normalize_whitespace(review.get("Title"))
    body = normalize_whitespace(review.get("ReviewText"))
    height = height_display(review_context_value(review, "WhatIsYourHeight"))
    weight = weight_display(review_context_value(review, "WeightRange_1"))
    size = additional_value(review, "SizePurchased")
    rating = normalize_whitespace(review.get("Rating"))
    extras = [body]
    if height:
        extras.append(f"Height: {height}.")
    if weight:
        extras.append(f"Weight: {weight}.")
    if size:
        extras.append(f"Size purchased: {size}.")
    if rating:
        extras.append(f"Rating: {rating}.")
    review_body = normalize_whitespace(" ".join(extras))
    product_title = normalize_whitespace(review.get("OriginalProductName")) or context.title
    images: List[ReviewImage] = []
    for photo in review.get("Photos") or []:
        if not isinstance(photo, dict):
            continue
        image_url = photo_url(photo)
        if not image_url:
            continue
        photo_id = normalize_whitespace(photo.get("Id"))
        caption = normalize_whitespace(photo.get("Caption"))
        images.append(
            ReviewImage(
                image_url=image_url,
                review_id=f"hollister-{review_id}-{photo_id or len(images) + 1}",
                review_title=title,
                review_body=normalize_whitespace(" ".join(part for part in [review_body, caption] if part)),
                reviewer_name=normalize_whitespace(review.get("UserNickname")),
                date_raw=normalize_whitespace(review.get("SubmissionTime")),
                size_raw=size,
                rating=rating,
                extra={
                    "image_source_type": "customer_review_image",
                    "image_source_detail": "public Bazaarvoice review photo",
                    "product_url": context.url,
                    "product_title": product_title,
                    "product_description": context.description,
                    "product_category": context.category,
                    "product_variant": context.color,
                },
            )
        )
    return images


def process_product(
    product_url: str,
    fetched_at: str,
    seen_review_pools: set[str],
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    context, bv_product_id, _html = fetch_product_context(product_url)
    review_pool_id = parse_review_pool_id(_html, bv_product_id)
    if not bv_product_id:
        return [], {
            "product_url": product_url,
            "product_title": context.title,
            "bv_product_id": "",
            "review_pool_id": review_pool_id,
            "review_pages_scanned": 0,
            "photo_reviews_found": 0,
            "photo_reviews_total_reported": 0,
            "rows": 0,
            "skipped_from_output": True,
            "skip_reason": "missing_bazaarvoice_product_id",
        }
    if review_pool_id and review_pool_id in seen_review_pools:
        return [], {
            "product_url": product_url,
            "product_title": context.title,
            "bv_product_id": bv_product_id,
            "review_pool_id": review_pool_id,
            "review_pages_scanned": 0,
            "photo_reviews_found": 0,
            "photo_reviews_total_reported": 0,
            "rows": 0,
            "skipped_from_output": True,
            "skip_reason": "duplicate_syndicated_review_pool_already_scraped",
        }
    if review_pool_id:
        seen_review_pools.add(review_pool_id)
    reviews, pages, total = fetch_photo_reviews(bv_product_id)
    rows: List[Dict[str, str]] = []
    for review in reviews:
        for review_image in build_review_images(review, context):
            row = build_intake_row(context, review_image, fetched_at)
            if row.get("original_url_display") and row.get("product_page_url_display"):
                rows.append(row)
    return rows, {
        "product_url": product_url,
        "product_title": context.title,
        "bv_product_id": bv_product_id,
        "review_pool_id": review_pool_id,
        "review_pages_scanned": pages,
        "photo_reviews_found": len(reviews),
        "photo_reviews_total_reported": total,
        "rows": len(rows),
        "skipped_from_output": not rows,
        "skip_reason": "" if rows else "no_customer_review_images",
    }


def metric_summary(rows: Sequence[Dict[str, str]]) -> Dict[str, int]:
    return {
        "rows_written": len(rows),
        "distinct_reviews": len({row.get("id", "") for row in rows if row.get("id")}),
        "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
        "distinct_products": len({row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}),
        "rows_with_customer_image": sum(1 for row in rows if row.get("image_source_type") == "customer_review_image"),
        "rows_with_any_measurement": sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS)),
        "rows_with_customer_ordered_size": sum(1 for row in rows if row.get("size_display")),
        "rows_supabase_qualified": sum(
            1
            for row in rows
            if row.get("original_url_display")
            and row.get("product_page_url_display")
            and row.get("size_display")
            and any(row.get(field) for field in MEASUREMENT_FIELDS)
        ),
        "rows_with_image_product_and_user_comment": sum(
            1
            for row in rows
            if row.get("original_url_display") and row.get("product_page_url_display") and row.get("user_comment")
        ),
    }


def run(args: argparse.Namespace) -> Dict[str, object]:
    started_at = utc_now()
    output_csv, summary_json = output_paths(DOMAIN)
    product_urls = discover_product_urls()
    discovered_count = len(product_urls)
    if args.limit_products:
        product_urls = product_urls[: args.limit_products]
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    stopped_early = False
    review_pages_scanned = 0
    seen_review_pools: set[str] = set()
    for index, product_url in enumerate(product_urls, start=1):
        try:
            product_rows, product_summary = process_product(product_url, started_at, seen_review_pools)
        except StopScrape as exc:
            errors.append(str(exc))
            stopped_early = True
            break
        except Exception as exc:
            errors.append(f"{product_url}: {exc}")
            product_rows = []
            product_summary = {
                "product_url": product_url,
                "product_title": title_from_url(product_url),
                "bv_product_id": "",
                "review_pool_id": "",
                "review_pages_scanned": 0,
                "photo_reviews_found": 0,
                "rows": 0,
                "skipped_from_output": True,
                "skip_reason": "fetch_or_parse_error",
            }
        rows.extend(product_rows)
        product_summaries.append(product_summary)
        review_pages_scanned += int(product_summary.get("review_pages_scanned") or 0)
        print(f"[product {index}/{len(product_urls)}] rows={len(product_rows)} total={len(rows)} {product_url}", flush=True)
        if args.request_delay_seconds:
            time.sleep(args.request_delay_seconds)
    rows = dedupe_rows(rows)
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    summary: Dict[str, object] = {
        "site": DOMAIN,
        "retailer": "hollisterco_com",
        "adapter": "hollister_sitemap_product_pages_bazaarvoice_bfd_photo_reviews",
        "review_platform_provider": "Bazaarvoice",
        "triage_bucket": "new_sheet_candidate_unverified_good",
        "product_sources": {"hollister_product_sitemap": discovered_count},
        "products_discovered": discovered_count,
        "products_scanned": len(product_summaries),
        "products_requested_this_run": len(product_urls),
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "review_pools_scanned": len(seen_review_pools),
        "duplicate_review_pool_product_pages": sum(
            1 for item in product_summaries if item.get("skip_reason") == "duplicate_syndicated_review_pool_already_scraped"
        ),
        "review_pages_scanned": review_pages_scanned,
        "exhaustive_review_paging": not stopped_early,
        "coverage_exhaustive": not stopped_early and not args.limit_products and len(product_summaries) == discovered_count,
        "access_policy": "public Hollister sitemap, public product pages, and public Bazaarvoice BFD review JSON only; stop on challenge/rate-limit",
        "output_csv": str(output_csv),
        "product_summaries": product_summaries,
        "errors": errors,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    summary.update(metric_summary(rows))
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Hollister Bazaarvoice customer review photos.")
    parser.add_argument("--limit-products", type=int, default=0)
    parser.add_argument("--request-delay-seconds", type=float, default=REQUEST_DELAY_SECONDS)
    args = parser.parse_args(argv)
    summary = run(args)
    print(json.dumps({key: summary.get(key) for key in ["products_discovered", "products_scanned", "rows_written", "rows_supabase_qualified", "errors"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
