#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
    ProductContext,
    ReviewImage,
    build_intake_row,
    canonical_product_url,
    classify_clothing_type,
    dedupe_rows,
    normalize_whitespace,
    output_paths,
    review_date_from_raw,
    strip_tags,
    utc_now,
    validate_rows,
    write_intake_csv,
)


SITE_ROOT = "https://macduggal.com"
SHOP_DOMAIN = "macduggal.myshopify.com"
BRAND = "Mac Duggal"
RETAILER = "macduggal_com"
PRODUCTS_PER_PAGE = 250
STAMPED_API_KEY = "26da45ba-60e1-455a-99b7-609cbcbfb08b"
STAMPED_STORE_ID = "350740"
STAMPED_REVIEWS_URL = "https://stamped.io/api/widget/reviews"
STAMPED_PHOTO_BASE = "https://cdn.stamped.io/uploads/photos/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
PRESSURE_STATUS_CODES = {401, 403, 407, 423, 429, 430, 503}
CHALLENGE_RE = re.compile(
    r"\b(?:captcha|cloudflare challenge|cf-chl|datadome|access denied|attention required|verify you are human|just a moment)\b",
    re.I,
)
NON_CLOTHING_RE = re.compile(
    r"\b(?:gift\s*card|swatch|hanger|shipping|protection|insurance|return|membership|catalog)\b",
    re.I,
)
STRICT_MEASUREMENT_FIELDS = [
    "height_in_display",
    "weight_display_display",
    "weight_lbs_display",
    "bust_in_number_display",
    "hips_in_display",
    "waist_in",
    "inseam_inches_display",
]


class StopScrape(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


NO_REDIRECT_OPENER = build_opener(NoRedirect)


def request_text(url: str, *, accept: str = "text/html,application/json,application/xml;q=0.9,*/*;q=0.8", retries: int = 3) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": accept,
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"{SITE_ROOT}/",
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                status = getattr(resp, "status", 200)
                body = resp.read().decode("utf-8", "replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code in PRESSURE_STATUS_CODES:
                raise StopScrape(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
            if exc.code not in {408, 500, 502, 504}:
                raise
            time.sleep(min(2**attempt, 12))
            continue
        except URLError as exc:
            last_error = exc
            time.sleep(min(2**attempt, 12))
            continue
        if status in PRESSURE_STATUS_CODES:
            raise StopScrape(f"blocked_or_rate_limited_http_{status}: {url}")
        if CHALLENGE_RE.search(body[:8000]):
            raise StopScrape(f"blocked_or_challenged_response: {url}")
        return body
    raise RuntimeError(f"Failed request for {url}: {last_error}")


def request_json(url: str, *, retries: int = 3) -> Dict[str, object]:
    text = request_text(url, accept="application/json,text/plain,*/*", retries=retries)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StopScrape(f"non_json_response: {url}") from exc
    if not isinstance(payload, dict):
        raise StopScrape(f"unexpected_json_response: {url}")
    return payload


def product_url(handle: str) -> str:
    return canonical_product_url(f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}")


def variant_detail(product: Dict[str, object]) -> str:
    values: List[str] = []
    for variant in product.get("variants") if isinstance(product.get("variants"), list) else []:
        if not isinstance(variant, dict):
            continue
        title = normalize_whitespace(variant.get("title"))
        if title and title.lower() != "default title" and title not in values:
            values.append(title)
    return " | ".join(values[:300])


def context_from_product(product: Dict[str, object]) -> ProductContext:
    handle = normalize_whitespace(product.get("handle"))
    tags = product.get("tags") if isinstance(product.get("tags"), list) else []
    category_parts = [
        normalize_whitespace(product.get("product_type")),
        " ".join(normalize_whitespace(tag) for tag in tags if tag),
    ]
    return ProductContext(
        url=product_url(handle) if handle else "",
        title=normalize_whitespace(product.get("title")),
        description=strip_tags(product.get("body_html")),
        detail=variant_detail(product),
        category=normalize_whitespace(" ".join(part for part in category_parts if part)),
        brand=normalize_whitespace(product.get("vendor")) or BRAND,
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=SHOP_DOMAIN,
        provider_hints="Stamped",
    )


def discover_products() -> Tuple[List[ProductContext], Dict[str, object]]:
    by_url: Dict[str, ProductContext] = {}
    by_id: Dict[str, ProductContext] = {}
    sources: List[Dict[str, object]] = []
    page = 1
    while True:
        url = f"{SITE_ROOT}/products.json?limit={PRODUCTS_PER_PAGE}&page={page}"
        payload = request_json(url)
        batch = [item for item in payload.get("products", []) if isinstance(item, dict)]
        sources.append({"source": "products.json", "page": page, "url": url, "count": len(batch)})
        if not batch:
            break
        for product in batch:
            context = context_from_product(product)
            if not context.url:
                continue
            by_url[context.url] = context
            if context.product_id:
                by_id[context.product_id] = context
        print(f"[catalog products.json page {page}] products={len(batch)} total={len(by_url)}", flush=True)
        if len(batch) < PRODUCTS_PER_PAGE:
            break
        page += 1
        time.sleep(0.15)

    sitemap_index_url = f"{SITE_ROOT}/sitemap.xml"
    sitemap_index = request_text(sitemap_index_url, accept="application/xml,text/xml,*/*")
    sitemap_urls = [
        html.unescape(match)
        for match in re.findall(r"<loc>(https://macduggal\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index, re.I)
    ]
    sitemap_counts: List[Dict[str, object]] = []
    for sitemap_url in sitemap_urls:
        xml = request_text(sitemap_url, accept="application/xml,text/xml,*/*")
        urls = [
            canonical_product_url(html.unescape(match).split("?", 1)[0])
            for match in re.findall(r"<loc>(https://macduggal\.com/products/[^<]+)</loc>", xml, re.I)
        ]
        sitemap_counts.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        for url in urls:
            if url not in by_url:
                handle = url.rstrip("/").rsplit("/", 1)[-1]
                by_url[url] = ProductContext(
                    url=url,
                    title=handle.replace("-", " ").title(),
                    brand=BRAND,
                    handle=handle,
                    shop_domain=SHOP_DOMAIN,
                    provider_hints="sitemap_only; Stamped unknown product id",
                )
    sources.extend(sitemap_counts)
    sources.append(
        {
            "source": "reconciled_products",
            "count": len(by_url),
            "products_json_count": len(by_id),
            "sitemap_missing_from_products_json": sum(1 for context in by_url.values() if not context.product_id),
        }
    )
    coverage = {
        "product_sources": sources,
        "products_json_unique_product_ids": len(by_id),
        "sitemap_product_sitemaps": len(sitemap_urls),
        "unique_product_urls": len(by_url),
    }
    return list(by_url.values()), coverage


def in_womens_clothing_scope(context: ProductContext) -> Tuple[bool, str]:
    text = f"{context.title} {context.category} {context.description} {context.url}".lower()
    if NON_CLOTHING_RE.search(text):
        return False, "out_of_scope_non_clothing"
    clothing_type = classify_clothing_type(context)
    if clothing_type:
        return True, ""
    if re.search(r"\b(?:gown|kaftan|caftan|sari|saree|lehenga|jumpsuit|romper|cape|shrug|bolero)\b", text, re.I):
        return True, ""
    return False, "no_womens_clothing_signal_in_title_category_description"


def stamped_photo_urls(value: object) -> List[str]:
    urls: List[str] = []
    for part in re.split(r"[,|]", normalize_whitespace(value)):
        clean = normalize_whitespace(part)
        if not clean:
            continue
        url = clean if clean.startswith("http") else STAMPED_PHOTO_BASE + clean.lstrip("/")
        if url not in urls:
            urls.append(url)
    return urls


def ordered_size_from_variant(value: object) -> str:
    variant = normalize_whitespace(value)
    if not variant or variant.lower() == "undefined":
        return ""
    parts = [normalize_whitespace(part) for part in variant.split("/") if normalize_whitespace(part)]
    if len(parts) > 1:
        return parts[-1]
    return variant


def normalize_stamped_review_date(value: object) -> str:
    raw = normalize_whitespace(value)
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return review_date_from_raw(raw)


def stamped_reviews_url(page: int, skip: int = 100) -> str:
    params = {
        "apiKey": STAMPED_API_KEY,
        "sId": STAMPED_STORE_ID,
        "storeUrl": SHOP_DOMAIN,
        "page": page,
        "skip": skip,
        "minRating": 1,
        "isWithPhotos": "true",
        "type": "widget-carousel-photos",
    }
    return f"{STAMPED_REVIEWS_URL}?{urlencode(params)}"


def resolve_stamped_product_redirect(url: str, cache: Dict[str, str]) -> str:
    clean = normalize_whitespace(url)
    if not clean:
        return ""
    if clean in cache:
        return cache[clean]
    if "stamped.io/go/" not in clean:
        parsed = urlparse(clean)
        if parsed.netloc.endswith("macduggal.com") and "/products/" in parsed.path:
            cache[clean] = canonical_product_url(clean)
            return cache[clean]
        cache[clean] = ""
        return ""
    req = Request(
        clean,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{SITE_ROOT}/",
        },
    )
    try:
        NO_REDIRECT_OPENER.open(req, timeout=30)
    except HTTPError as exc:
        if exc.code in {301, 302, 303, 307, 308}:
            location = normalize_whitespace(exc.headers.get("Location"))
            parsed = urlparse(location)
            if parsed.netloc.endswith("macduggal.com") and "/products/" in parsed.path:
                cache[clean] = canonical_product_url(location)
                return cache[clean]
        if exc.code in PRESSURE_STATUS_CODES:
            raise StopScrape(f"blocked_or_rate_limited_http_{exc.code}: {clean}") from exc
    except URLError as exc:
        cache[clean] = ""
        return ""
    cache[clean] = ""
    return ""


def scrape_photo_reviews(
    product_by_id: Dict[str, ProductContext],
    product_by_title: Dict[str, ProductContext],
) -> Tuple[List[Dict[str, str]], Dict[str, object], List[str], List[ProductContext]]:
    rows: List[Dict[str, str]] = []
    errors: List[str] = []
    fetched_at = utc_now()
    review_pages: List[Dict[str, object]] = []
    missing_product_context: Dict[str, Dict[str, str]] = {}
    redirected_contexts: Dict[str, ProductContext] = {}
    redirect_cache: Dict[str, str] = {}
    skipped_out_of_scope_review_rows = 0
    skipped_missing_public_product_url_rows = 0
    seen_reviews = set()

    for page in range(1, 100000):
        url = stamped_reviews_url(page)
        payload = request_json(url, retries=2)
        data = payload.get("data")
        if not isinstance(data, list):
            raise StopScrape(f"unexpected_stamped_payload_page_{page}")
        review_pages.append({"source": "stamped_photo_reviews", "page": page, "url": url, "reviews": len(data)})
        print(f"[stamped photo reviews page {page}] reviews={len(data)} rows_so_far={len(rows)}", flush=True)
        if not data:
            break
        for item in data:
            if not isinstance(item, dict):
                continue
            review_id = normalize_whitespace(item.get("id"))
            product_id = normalize_whitespace(item.get("productId"))
            product_name = normalize_whitespace(item.get("productName"))
            context = product_by_id.get(product_id) or product_by_title.get(product_name.lower())
            if not context:
                redirected_url = resolve_stamped_product_redirect(normalize_whitespace(item.get("productUrl")), redirect_cache)
                if redirected_url:
                    context = redirected_contexts.get(redirected_url)
                    if not context:
                        context = ProductContext(
                            url=redirected_url,
                            title=product_name,
                            brand=BRAND,
                            product_id=product_id,
                            shop_domain=SHOP_DOMAIN,
                            provider_hints="Stamped photo review redirect product URL",
                        )
                        redirected_contexts[redirected_url] = context
                        if product_id:
                            product_by_id[product_id] = context
                        if product_name:
                            product_by_title[product_name.lower()] = context
                if context:
                    pass
            if not context:
                key = product_id or product_name or "unknown"
                missing_product_context[key] = {"product_id": product_id, "product_title": product_name}
                context = ProductContext(
                    url="",
                    title=product_name,
                    brand=BRAND,
                    product_id=product_id,
                    shop_domain=SHOP_DOMAIN,
                    provider_hints="Stamped photo review not reconciled to current public Shopify catalog",
                )
            image_urls = stamped_photo_urls(item.get("reviewUserPhotos"))
            if not image_urls:
                continue
            in_scope, _skip_reason = in_womens_clothing_scope(context)
            if not in_scope:
                skipped_out_of_scope_review_rows += len(image_urls)
                continue
            if review_id:
                seen_reviews.add(review_id)
            rating = normalize_whitespace(item.get("reviewRating"))
            title = normalize_whitespace(item.get("reviewTitle"))
            body = normalize_whitespace(item.get("reviewMessage"))
            if rating:
                body = normalize_whitespace(f"{body} Rating: {rating}/5")
            date_raw = normalize_whitespace(item.get("reviewDate") or item.get("dateCreated"))
            for image_index, image_url in enumerate(image_urls, start=1):
                if not context.url:
                    skipped_missing_public_product_url_rows += 1
                    continue
                review = ReviewImage(
                    image_url=image_url,
                    review_id=f"macduggal-stamped-{review_id}" if review_id else f"macduggal-stamped-{product_id}-{page}",
                    review_title=title,
                    review_body=body,
                    reviewer_name=normalize_whitespace(item.get("author")),
                    date_raw=date_raw,
                    review_date=normalize_stamped_review_date(date_raw),
                    size_raw=ordered_size_from_variant(item.get("productVariantName")),
                    rating=rating,
                    extra={
                        "product_url": context.url,
                        "product_title": product_name or context.title,
                        "product_description": context.description,
                        "product_detail": context.detail,
                        "product_category": context.category,
                        "product_variant": normalize_whitespace(item.get("productVariantName")),
                        "image_source_detail": f"Stamped review_id={review_id}; rating={rating}/5; product_id={product_id}",
                    },
                )
                rows.append(build_intake_row(context, review, fetched_at))
        time.sleep(0.1)
    meta = {
        "review_pages_scanned": len(review_pages),
        "review_page_details": review_pages,
        "exhaustive_review_paging": bool(review_pages and review_pages[-1].get("reviews") == 0),
        "photo_reviews_seen": len(seen_reviews),
        "missing_product_context_count": len(missing_product_context),
        "missing_product_context": list(missing_product_context.values())[:200],
        "stamped_redirect_product_urls_discovered": len(redirected_contexts),
        "skipped_out_of_scope_review_rows": skipped_out_of_scope_review_rows,
        "skipped_review_image_rows_missing_public_product_url": skipped_missing_public_product_url_rows,
    }
    return rows, meta, errors, list(redirected_contexts.values())


def complete_metrics(rows: Sequence[Dict[str, str]]) -> Dict[str, object]:
    validation = validate_rows(rows)
    rows_with_distinct_product_url = len(
        {row.get("product_page_url_display") or row.get("monetized_product_url_display") for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display")}
    )
    rows_with_any_measurement = sum(1 for row in rows if any(row.get(field) for field in STRICT_MEASUREMENT_FIELDS))
    rows_with_customer_image = sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image")
    rows_with_customer_ordered_size = sum(1 for row in rows if row.get("size_display") and row.get("size_display", "").lower() != "unknown")
    rows_supabase_qualified = sum(
        1
        for row in rows
        if row.get("original_url_display")
        and (row.get("product_page_url_display") or row.get("monetized_product_url_display"))
        and row.get("size_display")
        and row.get("size_display", "").lower() != "unknown"
        and any(row.get(field) for field in STRICT_MEASUREMENT_FIELDS)
    )
    validation.update(
        {
            "rows_with_distinct_product_url": rows_with_distinct_product_url,
            "rows_with_any_measurement": rows_with_any_measurement,
            "rows_with_customer_image": rows_with_customer_image,
            "rows_with_customer_ordered_size": rows_with_customer_ordered_size,
            "rows_supabase_qualified": rows_supabase_qualified,
        }
    )
    return validation


def write_summary_file(path: Path, summary: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def write_triage_note(output_dir: Path, message: str, started_at: str, product_coverage: Optional[Dict[str, object]] = None) -> Path:
    path = output_dir / "macduggal_com_triage_note.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# macduggal.com triage note",
                "",
                f"- started_at: {started_at}",
                f"- stopped_at: {utc_now()}",
                f"- reason: {message}",
                "- action: stopped immediately without attempting bypass",
                "",
                "Coverage gathered before stop:",
                "```json",
                json.dumps(product_coverage or {}, indent=2),
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def scrape() -> Dict[str, object]:
    started_at = utc_now()
    output_csv, summary_json = output_paths("macduggal.com")
    product_coverage: Dict[str, object] = {}
    try:
        products, product_coverage = discover_products()
        product_by_id = {context.product_id: context for context in products if context.product_id}
        product_by_title = {context.title.lower(): context for context in products if context.title}
        rows, review_meta, errors, redirected_products = scrape_photo_reviews(product_by_id, product_by_title)
        existing_urls = {context.url for context in products}
        for context in redirected_products:
            if context.url and context.url not in existing_urls:
                products.append(context)
                existing_urls.add(context.url)
        if redirected_products:
            product_coverage.setdefault("product_sources", []).append(
                {
                    "source": "stamped_photo_review_redirect_product_urls",
                    "count": len(redirected_products),
                }
            )
    except StopScrape as exc:
        triage_path = write_triage_note(output_csv.parent, str(exc), started_at, product_coverage)
        raise StopScrape(f"{exc}; triage_note={triage_path}") from exc

    rows = dedupe_rows(rows)
    product_row_counts: Dict[str, int] = {}
    for row in rows:
        product_row_counts[row.get("product_page_url_display", "")] = product_row_counts.get(row.get("product_page_url_display", ""), 0) + 1

    product_summaries: List[Dict[str, object]] = []
    excluded = 0
    for index, context in enumerate(products, start=1):
        in_scope, skip_reason = in_womens_clothing_scope(context)
        if not in_scope:
            excluded += 1
        row_count = product_row_counts.get(context.url, 0)
        product_summaries.append(
            {
                "product_index": index,
                "product_id": context.product_id,
                "product_url": context.url,
                "product_title": context.title,
                "product_type_or_category": context.category,
                "provider_hints": context.provider_hints,
                "adapter_used": "stamped_sitewide_photo_reviews",
                "matching_review_image_rows": row_count if in_scope else 0,
                "skipped_from_output": not in_scope,
                "skip_reason": skip_reason,
            }
        )

    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    summary: Dict[str, object] = {
        "site": "https://macduggal.com/",
        "retailer": RETAILER,
        "adapter": "Stamped sitewide public photo review endpoint reconciled to Shopify catalog",
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": product_coverage.get("product_sources", []),
        "products_discovered": len(products),
        "products_scanned": len(products),
        "products_excluded_from_output": excluded,
        "review_pages_scanned": review_meta["review_pages_scanned"],
        "review_page_details": review_meta["review_page_details"],
        "exhaustive_review_paging": review_meta["exhaustive_review_paging"],
        "photo_reviews_seen": review_meta["photo_reviews_seen"],
        "missing_product_context_count": review_meta["missing_product_context_count"],
        "missing_product_context": review_meta["missing_product_context"],
        "stamped_redirect_product_urls_discovered": review_meta["stamped_redirect_product_urls_discovered"],
        "skipped_out_of_scope_review_rows": review_meta["skipped_out_of_scope_review_rows"],
        "skipped_review_image_rows_missing_public_product_url": review_meta["skipped_review_image_rows_missing_public_product_url"],
        "product_summaries": product_summaries,
        "errors": errors[:500],
    }
    summary.update(complete_metrics(rows))
    write_summary_file(summary_json, summary)
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args(argv)
    try:
        summary = scrape()
    except StopScrape as exc:
        print(f"STOPPED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: summary[k] for k in [
        "products_discovered",
        "products_scanned",
        "products_excluded_from_output",
        "review_pages_scanned",
        "exhaustive_review_paging",
        "rows_written",
        "distinct_reviews",
        "distinct_images",
        "rows_with_distinct_product_url",
        "rows_with_any_measurement",
        "rows_with_customer_image",
        "rows_with_customer_ordered_size",
        "rows_supabase_qualified",
        "output_csv",
    ]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
