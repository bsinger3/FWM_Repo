#!/usr/bin/env python3
from __future__ import annotations

import csv
from datetime import datetime, timezone
import html
import json
import math
import os
import re
import sys
import time
from pathlib import Path

PIPELINE_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, legacy_raw_run_dir, raw_scraped_data_root, reports_root  # noqa: E402
from step1_intake_utils import extract_measurements, INTAKE_HEADERS
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = legacy_raw_run_dir("annecole_com")
OUTPUT_CSV = OUTPUT_DIR / "annecole_com_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "annecole_com_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://www.annecole.com"
CANONICAL_ROOT = "https://annecole.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
OKENDO_STORE_ID = "1dc5cfe2-35fb-4c7d-867b-c9b34787ff4e"
OKENDO_API_ROOT = f"https://api.okendo.io/v1/stores/{OKENDO_STORE_ID}"
BRAND = "Anne Cole"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36"

HEADERS = INTAKE_HEADERS

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
SIZE_ORDER_RE = re.compile(
    r"\b(?:ordered|order|bought|purchased|got|wearing|wore|went with|ended up with|in a|size)\s+(?:a\s+|an\s+|the\s+)?"
    r"((?:xxs|xs|s|m|l|xl|xxl|2xl|3xl|[0-9]{1,2}|[0-9]{1,2}w)(?:/[0-9]{1,2})?)\b",
    re.I,
)
CHALLENGE_RE = re.compile(r"\b(?:captcha|cloudflare|datadome|access denied|attention required|verify you are human|cf-chl)\b", re.I)


class StopScrape(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(text: object) -> str:
    return WS_RE.sub(" ", str(text or "")).strip()


def strip_tags(value: object) -> str:
    text = re.sub(r"</p\s*>|<br\s*/?>", " ", str(value or ""), flags=re.I)
    return norm(html.unescape(TAG_RE.sub(" ", text)))


def stop_if_challenge(body: str, url: str) -> None:
    if CHALLENGE_RE.search(body[:10000]):
        raise StopScrape(f"Stopping on challenge-like response for {url}")


def fetch_text(url: str, retries: int = 5) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        try:
            with urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8", "replace")
                stop_if_challenge(body, url)
                return body
        except (HTTPError, URLError) as exc:
            last_error = exc
            if isinstance(exc, HTTPError) and exc.code in {403, 429}:
                raise StopScrape(f"Stopping on HTTP {exc.code} for {url}") from exc
            if isinstance(exc, HTTPError) and exc.code not in {500, 502, 503, 504}:
                raise
        time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"Failed text request for {url}: {last_error}")


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, referer: Optional[str] = None, retries: int = 5) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            query_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": SITE_ROOT,
                "Referer": referer or SOURCE_SITE,
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8", "replace")
                stop_if_challenge(body, query_url)
                return json.loads(body)
        except HTTPError as exc:
            last_error = exc
            if exc.code in {403, 429}:
                raise StopScrape(f"Stopping on HTTP {exc.code} for {query_url}") from exc
            if exc.code not in {500, 502, 503, 504}:
                raise
        except (URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"Failed JSON request for {query_url}: {last_error}")


def product_url_for(product: Dict[str, object]) -> str:
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def canonicalize_product_url(url: str) -> str:
    return re.sub(r"^https://(?:www\.)?annecole\.com", SITE_ROOT, url).split("?", 1)[0].rstrip("/")


def fetch_products(limit_products: Optional[int] = None) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    sources: List[Dict[str, object]] = []
    page = 1
    while True:
        payload = fetch_json(PRODUCTS_JSON_URL, {"limit": PRODUCTS_PER_PAGE, "page": page})
        page_products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        sources.append({"source": "products.json", "page": page, "count": len(page_products)})
        if not page_products:
            break
        products.extend(page_products)
        if len(page_products) < PRODUCTS_PER_PAGE or (limit_products and len(products) >= limit_products):
            break
        page += 1

    sitemap_index = fetch_text(SITEMAP_URL)
    sitemap_urls = [
        html.unescape(url)
        for url in re.findall(r"<loc>(https://(?:www\.)?annecole\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index)
        if "/en-" not in html.unescape(url)
    ]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url)
        urls = sorted(set(re.findall(r"https://(?:www\.)?annecole\.com/products/[^<\s\"']+", text)))
        urls = [canonicalize_product_url(html.unescape(url)) for url in urls if "/en-" not in url]
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        sitemap_product_urls.extend(urls)

    by_url: Dict[str, Dict[str, object]] = {canonicalize_product_url(product_url_for(product)): product for product in products if product_url_for(product)}
    missing = [url for url in sorted(set(sitemap_product_urls)) if url not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {"id": "", "handle": handle, "title": handle.replace("-", " ").title(), "product_type": "", "body_html": "", "variants": []}
    sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)})
    products_out = list(by_url.values())
    if limit_products:
        products_out = products_out[:limit_products]
    return products_out, sources


def okendo_reviews_url(product_id: object) -> str:
    return f"{OKENDO_API_ROOT}/products/shopify-{product_id}/reviews"


def normalize_product_url(value: object, fallback: str) -> str:
    text = norm(value)
    if text.startswith("//"):
        return canonicalize_product_url("https:" + text)
    if text.startswith("/"):
        return canonicalize_product_url(urljoin(SITE_ROOT, text))
    return canonicalize_product_url(text or fallback) if text or fallback else ""


def media_urls(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    media = review.get("media")
    if not isinstance(media, list):
        return urls
    for item in media:
        if not isinstance(item, dict):
            continue
        if norm(item.get("type")).lower() not in {"", "image", "photo"}:
            continue
        url = norm(item.get("fullSizeUrl") or item.get("largeUrl") or item.get("thumbnailUrl"))
        if url and url not in urls:
            urls.append(url)
    return urls


def maybe_num(value: Optional[float]) -> str:
    if value is None:
        return ""
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def parse_variant(variant: object, text: str) -> Tuple[str, str, str]:
    variant_text = norm(variant)
    parts = [part.strip() for part in variant_text.split("/") if part.strip()]
    color = parts[0] if len(parts) >= 2 else ""
    size = parts[-1] if len(parts) >= 2 else ""
    if not size:
        match = SIZE_ORDER_RE.search(text)
        size = match.group(1).upper() if match else ""
    return color, color.lower(), size


def variant_detail(product: Dict[str, object]) -> str:
    vals: List[str] = []
    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants[:250]:
            if isinstance(variant, dict):
                title = norm(variant.get("title"))
                if title and title.lower() != "default title" and title not in vals:
                    vals.append(title)
    return " | ".join(vals)


def classify(product: Dict[str, object], review: Optional[Dict[str, object]] = None) -> str:
    review = review or {}
    value = f"{product.get('title') or ''} {product.get('product_type') or ''} {review.get('productName') or ''}".lower()
    if "cover" in value or "dress" in value or "tunic" in value or "caftan" in value:
        return "cover_up"
    if "tankini" in value:
        return "tankini"
    if "bikini" in value:
        return "bikini"
    if "swim" in value or "rash guard" in value or "one piece" in value:
        return "swimwear"
    return "womens_clothing"


def output_skip_reason(product: Dict[str, object]) -> str:
    value = f"{product.get('title') or ''} {product.get('product_type') or ''} {' '.join(product.get('tags') or []) if isinstance(product.get('tags'), list) else ''}".lower()
    if "gift card" in value:
        return "out_of_scope_gift_card"
    if any(term in value for term in ["hat", "bag", "tote", "towel", "sunscreen", "shipping protection"]):
        return "out_of_scope_accessory"
    return ""


def fetch_product_reviews(product: Dict[str, object], limit_pages: Optional[int] = None) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    product_url = product_url_for(product)
    meta: Dict[str, object] = {
        "product_url": product_url,
        "product_title": product.get("title"),
        "adapter_used": "okendo_product_level",
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "matching_review_images": 0,
        "errors": [],
    }
    product_id = product.get("id")
    if not product_id:
        meta["errors"].append("missing_shopify_product_id")
        return [], meta

    reviews: List[Dict[str, object]] = []
    seen = set()
    url = okendo_reviews_url(product_id)
    params: Optional[Dict[str, object]] = {"limit": REVIEWS_PER_PAGE, "orderBy": "date desc"}
    while url:
        if limit_pages is not None and int(meta["review_pages_scanned"]) >= limit_pages:
            break
        try:
            payload = fetch_json(url, params=params, referer=product_url)
        except Exception as exc:  # noqa: BLE001
            meta["errors"].append(str(exc))
            break
        params = None
        page_reviews = [item for item in payload.get("reviews", []) if isinstance(item, dict)]
        if not page_reviews:
            break
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"]) + 1
        for review in page_reviews:
            review_id = norm(review.get("reviewId"))
            if review_id and review_id in seen:
                continue
            seen.add(review_id)
            reviews.append(review)
        next_url = norm(payload.get("nextUrl"))
        url = "https://api.okendo.io/v1" + next_url if next_url.startswith("/stores/") else ""
    meta["review_count_hint"] = len(reviews)
    meta["matching_review_images"] = sum(len(media_urls(review)) for review in reviews)
    return reviews, meta


def row_for(product: Dict[str, object], review: Dict[str, object], image_url: str, image_index: int) -> Dict[str, str]:
    title = strip_tags(review.get("title"))
    body = strip_tags(review.get("body"))
    variant_name = norm(review.get("productVariantName"))
    text = norm(" ".join(part for part in [title, body, f"Variant: {variant_name}" if variant_name else ""] if part))
    color_display, color_canonical, size_display = parse_variant(variant_name, text)
    m = extract_measurements(text, size_display)
    product_url = normalize_product_url(review.get("productUrl"), product_url_for(product))
    product_title = norm(review.get("productName") or product.get("title"))
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    review_id = norm(review.get("reviewId")) or f"{product.get('id')}-{image_index}"
    fetched = now_iso()
    return {
        "created_at_display": fetched,
        "id": f"{review_id}-{image_index}",
        "original_url_display": image_url,
        "image_source_type": "customer_review_image",
        "image_source_detail": "okendo_review_media",
        "product_page_url_display": product_url,
        "monetized_product_url_display": product_url,
        "height_raw": m["height_raw"],
        "weight_raw": m["weight_raw"],
        "user_comment": text,
        "date_review_submitted_raw": norm(review.get("dateCreated")),
        "height_in_display": m["height_in_display"],
        "review_date": norm(review.get("dateCreated"))[:10],
        "source_site_display": SOURCE_SITE,
        "status_code": "",
        "content_type": "",
        "bytes": "",
        "width": "",
        "height": "",
        "hash_md5": "",
        "fetched_at": fetched,
        "updated_at": fetched,
        "brand": BRAND,
        "waist_raw_display": m["waist_raw_display"],
        "hips_raw": m["hips_raw"],
        "age_raw": m["age_raw"],
        "waist_in": m["waist_in"],
        "hips_in_display": m["hips_in_display"],
        "age_years_display": m["age_years_display"],
        "search_fts": norm(" ".join([BRAND, product_title, strip_tags(product.get("body_html")), text])),
        "weight_display_display": m["weight_display_display"],
        "weight_raw_needs_correction": "",
        "clothing_type_id": classify(product, review),
        "reviewer_profile_url": "",
        "reviewer_name_raw": norm(reviewer.get("displayName")),
        "inseam_inches_display": m["inseam_inches_display"],
        "color_canonical": color_canonical,
        "color_display": color_display,
        "size_display": size_display,
        "bust_in_display": m["bust_in_display"],
        "bra_band_in_display": m["bra_band_in_display"],
        "bust_in_number_display": m["bust_in_number_display"],
        "cupsize_display": m["cupsize_display"],
        "weight_lbs_display": m["weight_lbs_display"],
        "weight_lbs_raw_issue": "",
        "product_title_raw": product_title,
        "product_subtitle_raw": title,
        "product_description_raw": strip_tags(product.get("body_html")),
        "product_detail_raw": variant_detail(product),
        "product_category_raw": norm(product.get("product_type")),
        "product_variant_raw": variant_name,
    }


def is_measurement_row(row: Dict[str, str]) -> bool:
    fields = ["height_in_display", "weight_lbs_display", "bust_in_display", "bra_band_in_display", "bust_in_number_display", "hips_in_display", "waist_in", "inseam_inches_display"]
    return any(norm(row.get(field)) for field in fields)


def invalid_numeric_fields(rows: List[Dict[str, str]]) -> Dict[str, int]:
    fields = [
        "height_in_display",
        "weight_lbs_display",
        "bust_in_display",
        "bra_band_in_display",
        "bust_in_number_display",
        "hips_in_display",
        "waist_in",
        "inseam_inches_display",
        "age_years_display",
    ]
    return {
        field: sum(1 for row in rows if norm(row.get(field)) and not re.fullmatch(r"\d+(?:\.\d+)?", norm(row.get(field))))
        for field in fields
    }


def dedupe_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        image_key = re.sub(r"\?.*$", "", row.get("original_url_display", ""))
        key = (row.get("id", "").rsplit("-", 1)[0], image_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def main(argv: List[str]) -> int:
    limit_products: Optional[int] = None
    limit_pages: Optional[int] = None
    if "--limit-products" in argv:
        limit_products = int(argv[argv.index("--limit-products") + 1])
    if "--limit-pages-per-product" in argv:
        limit_pages = int(argv[argv.index("--limit-pages-per-product") + 1])

    started = now_iso()
    products, product_sources = fetch_products(limit_products=limit_products)
    print(f"Discovered {len(products)} products")
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    total_pages = 0
    total_hint = 0
    products_excluded = 0

    for idx, product in enumerate(products, start=1):
        reviews, meta = fetch_product_reviews(product, limit_pages=limit_pages)
        skip_reason = output_skip_reason(product)
        if skip_reason:
            products_excluded += 1
        total_pages += int(meta.get("review_pages_scanned") or 0)
        total_hint += int(meta.get("review_count_hint") or 0)
        product_rows = 0
        if not skip_reason:
            for review in reviews:
                for image_index, image_url in enumerate(media_urls(review), start=1):
                    rows.append(row_for(product, review, image_url, image_index))
                    product_rows += 1
        summary = {
            "product_index": idx,
            "product_id": product.get("id"),
            "product_title": product.get("title"),
            "product_url": product_url_for(product),
            "review_count_hint": meta.get("review_count_hint"),
            "review_pages_scanned": meta.get("review_pages_scanned"),
            "matching_review_images": meta.get("matching_review_images"),
            "rows": product_rows,
            "errors": meta.get("errors"),
            "adapter_used": meta.get("adapter_used"),
            "skipped_from_output": bool(skip_reason),
            "skip_reason": skip_reason,
        }
        product_summaries.append(summary)
        status = f" skipped={skip_reason}" if skip_reason else ""
        print(f"[{idx}/{len(products)}] {product.get('title')} reviews={summary['review_count_hint']} pages={summary['review_pages_scanned']} rows={product_rows}{status}", flush=True)

    deduped = dedupe_rows(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(deduped)

    rows_with_product_url = sum(1 for row in deduped if norm(row.get("product_page_url_display") or row.get("monetized_product_url_display")))
    rows_with_measurement = sum(1 for row in deduped if is_measurement_row(row))
    rows_with_image = sum(1 for row in deduped if norm(row.get("original_url_display")))
    rows_with_size = sum(1 for row in deduped if norm(row.get("size_display")) and norm(row.get("size_display")).lower() != "unknown")
    rows_supabase = sum(
        1
        for row in deduped
        if norm(row.get("original_url_display"))
        and norm(row.get("product_page_url_display") or row.get("monetized_product_url_display"))
        and is_measurement_row(row)
        and norm(row.get("size_display"))
    )
    summary = {
        "site": "annecole.com",
        "adapter": "okendo_product_level",
        "okendo_store_id": OKENDO_STORE_ID,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "products_excluded_from_output": products_excluded,
        "exhaustive_review_paging": limit_pages is None,
        "review_pages_scanned": total_pages,
        "product_review_count_hint": total_hint,
        "rows_written": len(deduped),
        "distinct_reviews": len({row["id"].rsplit("-", 1)[0] for row in deduped}),
        "distinct_images": len({re.sub(r'\?.*$', '', row["original_url_display"]) for row in deduped}),
        "distinct_products": len({row["product_page_url_display"] for row in deduped}),
        "rows_with_distinct_product_url": len({row["product_page_url_display"] or row["monetized_product_url_display"] for row in deduped if row["product_page_url_display"] or row["monetized_product_url_display"]}),
        "rows_with_product_url": rows_with_product_url,
        "rows_with_any_measurement": rows_with_measurement,
        "rows_with_customer_image": rows_with_image,
        "rows_with_customer_review_image": sum(1 for row in deduped if norm(row.get("original_url_display")) and row.get("image_source_type") == "customer_review_image"),
        "rows_with_customer_ordered_size": rows_with_size,
        "rows_with_size": rows_with_size,
        "rows_supabase_qualified": rows_supabase,
        "supabase_qualified_rows": rows_supabase,
        "rows_with_image_and_product_url": rows_with_product_url,
        "output_csv": str(OUTPUT_CSV),
        "summary_json": str(SUMMARY_JSON),
        "started_at": started,
        "finished_at": now_iso(),
        "invalid_numeric_fields": invalid_numeric_fields(deduped),
        "access_policy": "public_product_and_review_pages_only; no_auth_bypass; no_captcha_bypass; stop_on_429_captcha_waf",
        "product_summaries": product_summaries,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(deduped)} rows to {OUTPUT_CSV}")
    print(f"Supabase-qualified rows: {rows_supabase}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
