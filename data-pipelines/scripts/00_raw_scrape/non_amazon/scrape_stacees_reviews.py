#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import re
import time
from html import unescape
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
    ProductContext,
    ReviewImage,
    build_intake_row,
    canonical_product_url,
    dedupe_rows,
    normalize_whitespace,
    utc_now,
    write_intake_csv,
)


SITE_ROOT = "https://www.stacees.com"
API_ROOT = "https://api-nl.stacees.com"
RETAILER = "stacees_com"
SITEMAP_INDEX = f"{SITE_ROOT}/sitemap.xml"
PRODUCT_SITEMAP = f"{SITE_ROOT}/sitemap/sitemap_product.xml.gz"
CDN_ROOT = "https://cdn-1.stacees.co.uk"

try:
    from step1_intake_utils import STEP1_OUTPUT_ROOT
except ImportError:  # pragma: no cover
    STEP1_OUTPUT_ROOT = Path(__file__).resolve().parents[4] / "data-pipelines" / "non-amazon" / "data" / "step_1_raw_scraping_data"

OUTPUT_DIR = STEP1_OUTPUT_ROOT / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.csv"
RAW_JSONL = OUTPUT_DIR / f"{RETAILER}_review_rows_raw.jsonl"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 FWM"
PRESSURE_STATUS_CODES = {401, 403, 407, 408, 409, 423, 429, 430, 503}
BLOCK_MARKERS = [
    "Just a moment...",
    "challenges.cloudflare.com",
    "cf-chl",
    "Attention Required! | Cloudflare",
    "datadome",
    "Please verify you are a human",
    "verify you are human",
    "Access denied",
    "captcha",
]
APPAREL_RE = re.compile(
    r"\b(bridesmaid|dress|dresses|gown|jumpsuit|mother|prom|wedding|homecoming|suit|tuxedo)\b",
    re.I,
)


class PressureStop(RuntimeError):
    pass


def request_bytes(url: str, *, accept: str = "*/*", retries: int = 3) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{SITE_ROOT}/",
        },
    )
    last_error: Optional[BaseException] = None
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=45) as response:
                status = getattr(response, "status", 200)
                body = response.read()
                content_type = response.headers.get("content-type", "")
            break
        except HTTPError as exc:
            if exc.code in PRESSURE_STATUS_CODES:
                raise PressureStop(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
            last_error = exc
        except (TimeoutError, URLError) as exc:
            last_error = exc
        if attempt < retries - 1:
            time.sleep(2 * (attempt + 1))
    else:
        raise PressureStop(f"request_failed_after_retries: {url}: {last_error}") from last_error
    if status in PRESSURE_STATUS_CODES:
        raise PressureStop(f"blocked_or_rate_limited_http_{status}: {url}")
    if "text" in content_type or "json" in content_type or "html" in content_type:
        text = body.decode("utf-8", "replace").lower()
        if any(marker.lower() in text for marker in BLOCK_MARKERS):
            raise PressureStop(f"blocked_or_challenged_response: {url}")
    return body


def request_text(url: str, *, accept: str = "text/html,application/xml;q=0.9,*/*;q=0.8") -> str:
    body = request_bytes(url, accept=accept)
    if url.endswith(".gz"):
        body = gzip.decompress(body)
    return body.decode("utf-8-sig", "replace")


def request_json(path: str, params: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    query = f"?{urlencode(params or {})}" if params else ""
    url = f"{API_ROOT}{path}{query}"
    text = request_text(url, accept="application/json,text/plain,*/*")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PressureStop(f"non_json_response: {url}") from exc
    if not isinstance(payload, dict):
        raise PressureStop(f"unexpected_json_response: {url}")
    if payload.get("code") in PRESSURE_STATUS_CODES:
        raise PressureStop(f"api_blocked_code_{payload.get('code')}: {url}")
    return payload


def sku_from_product_url(product_url: str) -> str:
    slug = urlparse(product_url).path.rstrip("/").rsplit("/", 1)[-1]
    if "-" not in slug:
        return ""
    return slug.rsplit("-", 1)[-1].strip()


def title_from_product_url(product_url: str, sku: str = "") -> str:
    slug = urlparse(product_url).path.rstrip("/").rsplit("/", 1)[-1]
    if sku and slug.lower().endswith(f"-{sku.lower()}"):
        slug = slug[: -(len(sku) + 1)]
    return normalize_whitespace(slug.replace("-", " ")).title()


def image_url(path: str) -> str:
    path = normalize_whitespace(path)
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return urljoin(CDN_ROOT + "/", path.lstrip("/"))


def review_url(review: Dict[str, object]) -> str:
    gallery_id = normalize_whitespace(review.get("gallery"))
    if gallery_id:
        return f"{SITE_ROOT}/style-gallery?galleryId={quote(gallery_id)}"
    review_id = normalize_whitespace(review.get("id"))
    product_sku = normalize_whitespace(review.get("web_sku"))
    return f"{SITE_ROOT}/reviews?reviewId={quote(review_id)}&sku={quote(product_sku)}"


def discover_product_urls() -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    root = request_text(SITEMAP_INDEX)
    sitemap_urls = [unescape(url) for url in re.findall(r"<loc>(.*?)</loc>", root)]
    product_sitemaps = [url for url in sitemap_urls if url.replace("&amp;", "&") == PRODUCT_SITEMAP]
    if not product_sitemaps:
        product_sitemaps = [PRODUCT_SITEMAP]

    products: List[Dict[str, str]] = []
    source_pages: List[Dict[str, object]] = []
    seen = set()
    for sitemap_url in product_sitemaps:
        xml = request_text(sitemap_url.replace("&amp;", "&"))
        urls = [canonical_product_url(unescape(url)) for url in re.findall(r"<loc>(.*?)</loc>", xml)]
        product_urls = [url for url in urls if "/products/" in url]
        source_pages.append({"url": sitemap_url, "products": len(product_urls)})
        for product_url in product_urls:
            if product_url in seen:
                continue
            sku = sku_from_product_url(product_url)
            seen.add(product_url)
            products.append(
                {
                    "url": product_url,
                    "sku": sku,
                    "base_sku": sku[1:] if sku.startswith("S") else sku,
                    "title": title_from_product_url(product_url, sku),
                }
            )
    return products, {
        "sitemap_index": SITEMAP_INDEX,
        "product_sitemaps": source_pages,
        "unique_product_urls": len(products),
    }


def condition_values(items: object, key: str = "value") -> List[str]:
    values: List[str] = []
    if not isinstance(items, list):
        return values
    for item in items:
        if isinstance(item, dict):
            value = normalize_whitespace(item.get(key) or item.get("name"))
        else:
            value = normalize_whitespace(item)
        if value and value not in values:
            values.append(value)
    return values


def review_filters(conditions: Dict[str, object]) -> List[Dict[str, str]]:
    data = conditions.get("data") if isinstance(conditions.get("data"), dict) else {}
    sizes = condition_values(data.get("size"), "value")
    colors = condition_values(data.get("color"), "name")
    grades = condition_values(data.get("grade"))
    if sizes:
        return [{"size": size} for size in sizes]
    if colors:
        return [{"color": color} for color in colors]
    if grades:
        return [{"grade": grade} for grade in grades]
    return []


def fetch_reviews_for_filter(product: Dict[str, str], params: Dict[str, str], *, delay: float) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    seen = set()
    page = 1
    total = None
    while True:
        api_params = {
            "web_sku": product["sku"],
            "base_sku": product["base_sku"],
            "page": page,
        }
        api_params.update(params)
        payload = request_json("/comment/ajaxreviews", api_params)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        batch = data.get("review") if isinstance(data.get("review"), list) else []
        if total is None:
            try:
                total = int(data.get("total") or 0)
            except (TypeError, ValueError):
                total = 0
        for review in batch:
            if not isinstance(review, dict):
                continue
            review_id = normalize_whitespace(review.get("id"))
            if review_id in seen:
                continue
            seen.add(review_id)
            rows.append(review)
        if not batch or (total is not None and len(rows) >= total):
            break
        page += 1
        time.sleep(delay)
    return rows


def product_context(product: Dict[str, str], review: Dict[str, object]) -> ProductContext:
    return ProductContext(
        url=product["url"],
        title=product["title"],
        brand="STACEES",
        category="apparel" if APPAREL_RE.search(product["title"]) else "",
        shop_domain="stacees.com",
        provider_hints="Stacees public comment API filtered by appCommentConditions",
    )


def rows_from_review(product: Dict[str, str], review: Dict[str, object], fetched_at: str) -> Tuple[List[Dict[str, str]], List[Dict[str, object]]]:
    title = normalize_whitespace(review.get("title"))
    body = normalize_whitespace(review.get("content"))
    review_id = normalize_whitespace(review.get("id"))
    detail_url = review_url(review)
    rating = normalize_whitespace(review.get("grade"))
    ordered_size = normalize_whitespace(review.get("size"))
    color = normalize_whitespace(review.get("color"))
    context = product_context(product, review)
    context.color = color
    context.variant = normalize_whitespace(" ".join(part for part in [ordered_size, color] if part))

    images = []
    thumb_list = review.get("thumb_list")
    if isinstance(thumb_list, list):
        for image in thumb_list:
            if isinstance(image, dict):
                url = image_url(normalize_whitespace(image.get("img") or image.get("thumb")))
                if url:
                    images.append(url)
    fallback = image_url(normalize_whitespace(review.get("thumb")))
    if fallback and not images:
        images.append(fallback)

    intake_rows: List[Dict[str, str]] = []
    raw_rows: List[Dict[str, object]] = []
    for index, url in enumerate(dict.fromkeys(images), start=1):
        review_image = ReviewImage(
            image_url=url,
            review_id=f"stacees-{review_id}-{index}" if review_id else f"stacees-{product['sku']}-{index}",
            review_title=title,
            review_body=body,
            reviewer_name=normalize_whitespace(review.get("username")),
            date_raw=normalize_whitespace(review.get("add_time")),
            review_date=normalize_whitespace(review.get("add_time")),
            size_raw=ordered_size,
            extra={
                "image_source_type": "customer_review_image",
                "image_source_detail": normalize_whitespace(
                    f"review_id={review_id}; review_url={detail_url}; rating={rating}; "
                    f"overall_fit={normalize_whitespace(review.get('overall_fit'))}; "
                    f"gallery_id={normalize_whitespace(review.get('gallery'))}"
                ),
            },
        )
        row = build_intake_row(context, review_image, fetched_at)
        row["product_page_url_display"] = product["url"]
        row["product_title_raw"] = product["title"]
        row["product_variant_raw"] = context.variant
        intake_rows.append(row)
        raw_rows.append(
            {
                "retailer": RETAILER,
                "product_url": product["url"],
                "product_title": product["title"],
                "web_sku": normalize_whitespace(review.get("web_sku")) or product["sku"],
                "base_sku": normalize_whitespace(review.get("base_sku")) or product["base_sku"],
                "review_id": review_id,
                "review_url": detail_url,
                "review_title": title,
                "review_text": body,
                "reviewer_name": normalize_whitespace(review.get("username")),
                "rating": rating,
                "date_raw": normalize_whitespace(review.get("add_time")),
                "add_time_origin": normalize_whitespace(review.get("add_time_origin")),
                "ordered_size": ordered_size,
                "color": color,
                "overall_fit": normalize_whitespace(review.get("overall_fit")),
                "body_measurement_data": {field: row.get(field, "") for field in MEASUREMENT_FIELDS if row.get(field)},
                "image_url": url,
                "image_source_type": "customer_review_image",
                "image_index": index,
                "gallery_id": normalize_whitespace(review.get("gallery")),
                "source_api": "/comment/ajaxreviews",
                "fetched_at": fetched_at,
            }
        )
    return intake_rows, raw_rows


def scrape(*, delay: float = 0.05, limit: Optional[int] = None) -> Dict[str, object]:
    fetched_at = utc_now()
    products, product_source_summary = discover_product_urls()
    if limit:
        products = products[:limit]

    by_sku = {product["sku"]: product for product in products if product["sku"]}
    intake_rows: List[Dict[str, str]] = []
    raw_rows: List[Dict[str, object]] = []
    product_results: List[Dict[str, object]] = []
    conditions_with_filters = 0
    reviewed_products = set()
    api_calls = 0

    for index, product in enumerate(products, start=1):
        if not product["sku"]:
            product_results.append({"url": product["url"], "sku": "", "status": "missing_sku", "reviews": 0})
            continue
        conditions = request_json("/api/appCommentConditions", {"sku": product["sku"]})
        api_calls += 1
        filters = review_filters(conditions)
        if filters:
            conditions_with_filters += 1
        product_review_count = 0
        product_review_ids = set()
        for params in filters:
            reviews = fetch_reviews_for_filter(product, params, delay=delay)
            api_calls += 1
            for review in reviews:
                review_id = normalize_whitespace(review.get("id"))
                if review_id in product_review_ids:
                    continue
                product_review_ids.add(review_id)
                rows, raw = rows_from_review(product, review, fetched_at)
                intake_rows.extend(rows)
                raw_rows.extend(raw)
                product_review_count += 1
        if product_review_count:
            reviewed_products.add(product["url"])
        product_results.append(
            {
                "url": product["url"],
                "sku": product["sku"],
                "filters": filters,
                "reviews": product_review_count,
                "status": "review_rows_found" if product_review_count else ("review_filters_no_media_rows" if filters else "no_public_review_filters"),
            }
        )
        if index % 100 == 0:
            print(
                f"[stacees] products={index}/{len(products)} filters={conditions_with_filters} "
                f"reviews={len(product_review_ids)} rows={len(intake_rows)} api_calls={api_calls}",
                flush=True,
            )
        time.sleep(delay)

    intake_rows = dedupe_rows(intake_rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_intake_csv(intake_rows, OUTPUT_CSV)
    with RAW_JSONL.open("w", encoding="utf-8") as handle:
        for row in raw_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    products_with_reviews = [result for result in product_results if int(result.get("reviews") or 0) > 0]
    rows_supabase_qualified = sum(
        1
        for row in intake_rows
        if row.get("original_url_display")
        and row.get("product_page_url_display")
        and row.get("size_display")
        and any(row.get(field) for field in MEASUREMENT_FIELDS)
    )
    summary = {
        "retailer": RETAILER,
        "site_root": SITE_ROOT,
        "api_root": API_ROOT,
        "created_at": fetched_at,
        "outputs": {
            "csv": str(OUTPUT_CSV),
            "raw_jsonl": str(RAW_JSONL),
            "summary_json": str(SUMMARY_JSON),
        },
        "scrape_policy": "public_sitemap_and_public_stacees_review_api_only; stopped on 429/captcha/WAF/auth markers",
        "blocked": False,
        "blocked_note": "",
        "product_sources": product_source_summary,
        "product_coverage": {
            "public_products_discovered": len(products),
            "public_products_checked_for_review_conditions": len(product_results),
            "products_with_review_filters": conditions_with_filters,
            "products_with_customer_review_image_rows": len(products_with_reviews),
            "products_without_public_review_filters": sum(1 for result in product_results if result["status"] == "no_public_review_filters"),
            "products_with_filters_but_no_media_rows": sum(1 for result in product_results if result["status"] == "review_filters_no_media_rows"),
            "api_calls": api_calls,
        },
        "review_metrics": {
            "raw_review_image_rows": len(raw_rows),
            "deduped_intake_rows": len(intake_rows),
            "unique_reviews": len({row["review_id"] for row in raw_rows if row.get("review_id")}),
            "unique_product_urls_in_rows": len({row["product_url"] for row in raw_rows if row.get("product_url")}),
            "rows_with_customer_image": sum(1 for row in raw_rows if row.get("image_url")),
            "rows_with_ordered_size": sum(1 for row in raw_rows if row.get("ordered_size")),
            "rows_with_measurement_fields": sum(1 for row in intake_rows if any(row.get(field) for field in MEASUREMENT_FIELDS)),
            "rows_supabase_qualified": rows_supabase_qualified,
            "supabase_qualified_rows": rows_supabase_qualified,
            "rows_with_image_product_size_and_measurement": rows_supabase_qualified,
            "rows_with_rating": sum(1 for row in raw_rows if row.get("rating")),
            "rows_with_review_url": sum(1 for row in raw_rows if row.get("review_url")),
        },
        "reviewed_products_sample": products_with_reviews[:20],
        "product_results": product_results,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Stacees public product review image rows.")
    parser.add_argument("--delay", type=float, default=0.05, help="Delay between public API calls.")
    parser.add_argument("--limit", type=int, default=None, help="Optional product limit for smoke tests.")
    args = parser.parse_args(argv)
    try:
        summary = scrape(delay=args.delay, limit=args.limit)
    except PressureStop as exc:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        note = {
            "retailer": RETAILER,
            "created_at": utc_now(),
            "blocked": True,
            "blocked_note": str(exc),
            "revisit_note": "Stopped immediately per scrape rules after a blocked/rate-limited/challenge/auth-like response.",
        }
        SUMMARY_JSON.write_text(json.dumps(note, indent=2), encoding="utf-8")
        print(json.dumps(note, indent=2), flush=True)
        return 2
    print(json.dumps({k: summary[k] for k in ["retailer", "created_at", "blocked", "product_coverage", "review_metrics"]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
