#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import time
from datetime import datetime
from typing import Dict, Iterable, List, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

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
)


SITE_ROOT = "https://www.wildsecretslingerie.co.nz"
DOMAIN = "wildsecretslingerie.co.nz"
RETAILER = "wildsecretslingerie_co_nz"
SEARCHSPRING_SITE_ID = "vua081"
SEARCHSPRING_URL = "https://vua081.a.searchspring.io/api/search/search.json"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 FWM"
PRESSURE_STATUS_CODES = {401, 403, 407, 408, 409, 423, 429, 430, 503}
BLOCK_MARKERS = [
    "captcha",
    "verify you are human",
    "access denied",
    "too many requests",
    "attention required",
    "datadome",
    "cf-chl",
    "challenges.cloudflare.com",
]

APPAREL_RE = re.compile(
    r"\b("
    r"bra|bralette|bustier|corset|chemise|babydoll|teddy|bodysuit|body\s*suit|lingerie|set|garter|"
    r"g[- ]?string|thong|pant(?:y|ies)|sleep\s*wear|hosiery|stocking|thigh\s*high|costume|robe"
    r")\b",
    re.I,
)
ACCESSORY_RE = re.compile(r"\b(gift card|toy|lube|candle|cleaner|battery|dvd|book|bag|game)\b", re.I)


class PressureStop(RuntimeError):
    pass


def request_text(url: str, *, accept: str = "text/html,application/json,*/*", referer: str = SITE_ROOT) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        },
    )
    try:
        with urlopen(req, timeout=30) as response:
            status = getattr(response, "status", 200)
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.code in PRESSURE_STATUS_CODES:
            raise PressureStop(f"pressure status {exc.code} for {url}") from exc
        raise
    except URLError as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc

    if status in PRESSURE_STATUS_CODES:
        raise PressureStop(f"pressure status {status} for {url}")
    lower = body[:20000].lower()
    if any(marker in lower for marker in BLOCK_MARKERS):
        raise PressureStop(f"block marker in response for {url}")
    return body


def searchspring_url(page: int, per_page: int) -> str:
    params = {
        "q": "lingerie",
        "resultsFormat": "native",
        "siteId": SEARCHSPRING_SITE_ID,
        "page": str(page),
        "resultsPerPage": str(per_page),
        "domain": "www.wildsecretslingerie.co.nz",
        "sort.ratingavg": "desc",
    }
    return f"{SEARCHSPRING_URL}?{urlencode(params)}"


def search_products(limit: int, per_page: int, delay: float) -> tuple[List[Dict[str, object]], Dict[str, object]]:
    products: List[Dict[str, object]] = []
    pages_scanned = 0
    total_results = 0
    page = 1
    while len(products) < limit:
        payload = json.loads(request_text(searchspring_url(page, per_page), accept="application/json", referer=SITE_ROOT))
        pages_scanned += 1
        pagination = payload.get("pagination") or {}
        total_results = int(pagination.get("totalResults") or total_results or 0)
        for result in payload.get("results") or []:
            text = " ".join(
                [
                    str(result.get("name") or ""),
                    " ".join(str(v) for v in result.get("category") or []),
                    str(result.get("product_type_unigram") or ""),
                ]
            )
            if not APPAREL_RE.search(text) or ACCESSORY_RE.search(text):
                continue
            products.append(result)
            if len(products) >= limit:
                break
        if not pagination.get("nextPage") or page >= int(pagination.get("totalPages") or page):
            break
        page += 1
        time.sleep(delay)
    return products, {"pages_scanned": pages_scanned, "total_results": total_results}


def full_url(value: object) -> str:
    raw = normalize_whitespace(value)
    if not raw:
        return ""
    if raw.startswith("//"):
        return "https:" + raw
    return urljoin(SITE_ROOT, raw)


def product_id_from_url(url: str) -> str:
    match = re.search(r"/p/(\d+)/", url)
    return match.group(1) if match else ""


def parse_product_images(html_text: str, product: Dict[str, object]) -> List[str]:
    images: List[str] = []
    for key in ["largeimageurl", "mouseoverimage", "imageUrl", "thumbnailImageUrl"]:
        url = full_url(product.get(key))
        if url:
            images.append(url)

    for match in re.finditer(r"data-product-gallery-colourways-value='([^']+)'", html_text):
        try:
            colourways = json.loads(html.unescape(match.group(1)))
        except json.JSONDecodeError:
            continue
        for colourway in colourways or []:
            for image in colourway.get("images") or []:
                if image.get("isVideo"):
                    continue
                for key in ["largeImageUrlWebp", "largeImageUrl"]:
                    url = full_url(image.get(key))
                    if url and "brand-assets/v2/wsl/" not in url:
                        images.append(url)

    deduped: List[str] = []
    seen = set()
    for url in images:
        clean = normalize_whitespace(url)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        deduped.append(clean)
    return deduped


def parse_colourway_context(html_text: str, product: Dict[str, object]) -> tuple[str, str, str]:
    colours = [normalize_whitespace(v) for v in product.get("colourgroups") or [] if normalize_whitespace(v)]
    sizes = [normalize_whitespace(v) for v in product.get("size") or [] if normalize_whitespace(v)]
    variant_bits: List[str] = []

    match = re.search(r"data-product-add-to-cart-selected-colourway-value='([^']+)'", html_text)
    if match:
        try:
            colourway = json.loads(html.unescape(match.group(1)))
            if colourway.get("name"):
                colours.append(normalize_whitespace(colourway.get("name")))
            variants = colourway.get("variants") or []
            size_labels = [normalize_whitespace(v.get("newDescription") or v.get("size")) for v in variants if v.get("newDescription") or v.get("size")]
            if size_labels:
                sizes.extend(size_labels)
            variant_bits.extend(
                normalize_whitespace(v.get("newDescriptionWithColour") or v.get("sizeAndColour"))
                for v in variants
                if v.get("newDescriptionWithColour") or v.get("sizeAndColour")
            )
        except json.JSONDecodeError:
            pass

    colour = next((value for value in colours if value), "")
    size_summary = ", ".join(dict.fromkeys(value for value in sizes if value))
    variant = "; ".join(dict.fromkeys(value for value in variant_bits if value))
    return colour, size_summary, variant


def parse_reviews(html_text: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html_text, "html.parser")
    container = soup.select_one("div.product-review-container.hide-tablet.hide-mobile") or soup.select_one(
        "div.product-review-container"
    )
    if not container:
        return []

    reviews: List[Dict[str, str]] = []
    seen_reviews = set()
    for item in container.select("div.review-item.review"):
        review_id = normalize_whitespace(item.get("data-review-id"))
        user_info = item.select_one(".review-item-user-info")
        details = item.select_one(".review-item-details")
        if not details:
            continue
        reviewer = normalize_whitespace(user_info.select_one("h2").get_text(" ", strip=True) if user_info and user_info.select_one("h2") else "")
        question_bits = []
        if user_info:
            question_bits = [normalize_whitespace(div.get_text(" ", strip=True)) for div in user_info.select(".questions div")]
        rating_alt = normalize_whitespace(details.select_one(".rating img").get("alt") if details.select_one(".rating img") else "")
        rating_match = re.search(r"([1-5](?:\.\d+)?)", rating_alt)
        date_raw = normalize_whitespace(details.select_one(".rating .date").get_text(" ", strip=True) if details.select_one(".rating .date") else "")
        date_raw = re.sub(r"^\s*-\s*", "", date_raw)
        comment = normalize_whitespace(details.select_one(".comment").get_text(" ", strip=True) if details.select_one(".comment") else "")
        if not comment:
            continue
        review_key = (review_id, reviewer, date_raw, comment)
        if review_key in seen_reviews:
            continue
        seen_reviews.add(review_key)
        size_raw = ""
        for bit in question_bits:
            if bit.lower().startswith("size:"):
                size_raw = normalize_whitespace(bit.split(":", 1)[1])
                break
        reviews.append(
            {
                "review_id": review_id,
                "reviewer": reviewer,
                "rating": rating_match.group(1) if rating_match else "",
                "date_raw": date_raw,
                "review_date": parse_ddmmyyyy(date_raw),
                "comment": comment,
                "questions": "; ".join(question_bits),
                "size_raw": size_raw,
                "verified": "Verified Purchase" if item.select_one(".verified") else "",
            }
        )
    return reviews


def parse_ddmmyyyy(value: str) -> str:
    raw = normalize_whitespace(value)
    for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, pattern).date().isoformat()
        except ValueError:
            continue
    return ""


def context_for_product(product: Dict[str, object], html_text: str) -> ProductContext:
    colour, size_summary, variant = parse_colourway_context(html_text, product)
    category = " > ".join(normalize_whitespace(v) for v in product.get("category") or [] if normalize_whitespace(v))
    description = strip_tags(html.unescape(str(product.get("description") or "")))
    detail_bits = [
        f"Available sizes: {size_summary}" if size_summary else "",
        f"Rating average: {product.get('ratingavg')} from {product.get('ratingcount') or product.get('ratingCount')} reviews",
        f"Price NZD: {product.get('price')}" if product.get("price") else "",
    ]
    return ProductContext(
        url=full_url(product.get("url")),
        title=html.unescape(normalize_whitespace(product.get("name"))),
        description=description,
        detail=normalize_whitespace(" | ".join(bit for bit in detail_bits if bit)),
        category=category,
        brand=normalize_whitespace(product.get("brand")),
        color=colour,
        variant=variant or (f"Available sizes: {size_summary}" if size_summary else ""),
        product_id=product_id_from_url(full_url(product.get("url"))) or normalize_whitespace(product.get("sku")),
        handle=normalize_whitespace(product.get("sku")),
        shop_domain=DOMAIN,
        provider_hints="native PHE/Excite ProductReview PDP markup; SearchSpring product discovery",
        raw_html=html_text,
    )


def rows_from_product(product: Dict[str, object], html_text: str, fetched_at: str) -> tuple[List[Dict[str, str]], Dict[str, object]]:
    context = context_for_product(product, html_text)
    images = parse_product_images(html_text, product)
    reviews = parse_reviews(html_text)
    rows: List[Dict[str, str]] = []
    for index, review in enumerate(reviews):
        if not images:
            continue
        image_url = images[index % len(images)]
        detail = normalize_whitespace(
            "catalog/model product-gallery image paired with native public ProductReview text; "
            f"source=Excite/PHE PDP; sku={product.get('sku')}; review_questions={review.get('questions')}"
        )
        review_image = ReviewImage(
            image_url=image_url,
            review_id=f"wildsecretslingerie-co-nz-{context.product_id}-{review.get('review_id') or index + 1}",
            review_title="Native product review",
            review_body=review.get("comment", ""),
            reviewer_name=review.get("reviewer", ""),
            date_raw=review.get("date_raw", ""),
            review_date=review.get("review_date", ""),
            size_raw=review.get("size_raw", ""),
            rating=review.get("rating", ""),
            extra={
                "product_url": context.url,
                "product_title": context.title,
                "product_description": context.description,
                "product_detail": context.detail,
                "product_category": context.category,
                "product_variant": context.variant,
                "image_source_type": "catalog_model_image",
                "image_source_detail": detail,
            },
        )
        rows.append(build_intake_row(context, review_image, fetched_at))

    summary = {
        "url": context.url,
        "product_id": context.product_id,
        "sku": product.get("sku"),
        "title": context.title,
        "brand": context.brand,
        "category": context.category,
        "searchspring_rating_count": product.get("ratingcount") or product.get("ratingCount"),
        "reviews_parsed": len(reviews),
        "catalog_images_found": len(images),
        "rows": len(rows),
        "image_source_type": "catalog_model_image" if rows else "none",
    }
    return rows, summary


def dedupe_products(products: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    seen = set()
    out = []
    for product in products:
        key = full_url(product.get("url")) or normalize_whitespace(product.get("sku"))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(product)
    return out


def summary_payload(
    *,
    rows: Sequence[Dict[str, str]],
    output_csv,
    started_at: str,
    finished_at: str,
    products_discovered: int,
    products_scanned: int,
    search_summary: Dict[str, object],
    product_summaries: Sequence[Dict[str, object]],
    errors: Sequence[str],
) -> Dict[str, object]:
    summary = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "searchspring_native_phe_product_reviews_catalog_model_images",
        "provider_identified": "native PHE/Excite ProductReview markup in public PDP HTML; no third-party review widget or customer-photo field observed in sample PDPs",
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": finished_at,
        "products_discovered": products_discovered,
        "products_scanned": products_scanned,
        "searchspring": search_summary,
        "product_summaries": list(product_summaries),
        "errors": list(errors),
        "access_policy": "public Wild Secrets NZ pages and public SearchSpring product API only; stop on 429/captcha/WAF/auth behavior.",
        "sovrn_triage_source": {
            "source_file": "data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv",
            "target": "wildsecretslingerie_co_nz",
            "status": "first-pass candidate",
            "pricing_model": "CPA",
            "reviews_present": "yes",
            "photo_review_status": "unknown_sample_too_small",
            "shipping_countries": "AU|NZ|US",
            "provider": "unknown at triage; native PHE/Excite identified during scrape",
            "payout_fields": "not_populated",
        },
    }
    summary.update(validate_rows(rows))
    summary["rows_with_customer_image"] = summary.get("rows_with_customer_review_image", 0)
    summary["rows_with_catalog_model_image"] = sum(1 for row in rows if row.get("image_source_type") == "catalog_model_image")
    summary["rows_with_native_review_text"] = sum(1 for row in rows if row.get("user_comment"))
    summary["summary_hash"] = hashlib.sha256(json.dumps(summary, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return summary


def write_summary_json(path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run(limit_products: int, per_page: int, delay: float) -> Dict[str, object]:
    started_at = utc_now()
    fetched_at = started_at
    output_csv, summary_json = output_paths(RETAILER)

    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    products, search_summary = search_products(limit_products, per_page, delay)
    products = dedupe_products(products)

    scanned = 0
    for product in products:
        url = full_url(product.get("url"))
        if not url:
            continue
        rating_count = int(float(product.get("ratingcount") or product.get("ratingCount") or 0))
        if rating_count <= 0:
            product_summaries.append(
                {
                    "url": url,
                    "sku": product.get("sku"),
                    "title": product.get("name"),
                    "searchspring_rating_count": rating_count,
                    "rows": 0,
                    "skip_reason": "searchspring_rating_count_zero",
                }
            )
            continue
        try:
            html_text = request_text(url, referer=SITE_ROOT)
            product_rows, product_summary = rows_from_product(product, html_text, fetched_at)
            rows.extend(product_rows)
            product_summaries.append(product_summary)
            scanned += 1
            time.sleep(delay)
        except PressureStop:
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
            product_summaries.append({"url": url, "sku": product.get("sku"), "rows": 0, "error": str(exc)})

    rows = dedupe_rows(rows)
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    payload = summary_payload(
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=finished_at,
        products_discovered=len(products),
        products_scanned=scanned,
        search_summary=search_summary,
        product_summaries=product_summaries,
        errors=errors,
    )
    write_summary_json(summary_json, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Wild Secrets Lingerie NZ native reviews with catalog/model images.")
    parser.add_argument("--limit-products", type=int, default=40)
    parser.add_argument("--per-page", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.4)
    args = parser.parse_args()

    payload = run(args.limit_products, args.per_page, args.delay)
    print(f"Rows: {payload.get('rows_written', 0)}")
    print(f"Catalog model rows: {payload.get('rows_with_catalog_model_image', 0)}")
    print(f"Products scanned: {payload.get('products_scanned', 0)}")
    print(f"Output: {payload.get('output_csv')}")


if __name__ == "__main__":
    main()
