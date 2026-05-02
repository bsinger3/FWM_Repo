#!/usr/bin/env python3
from __future__ import annotations

import base64
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
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "shapedly_com"
OUTPUT_CSV = OUTPUT_DIR / "shapedly_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "shapedly_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://shapedly.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
LAI_SHOP_NAME = "2fc540"
LAI_API_ROOT = "https://store.laireviews.com/api/load-more"
BRAND = "Shapedly"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 250
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36"

HEADERS = [
    "created_at_display", "id", "original_url_display", "product_page_url_display", "monetized_product_url_display",
    "height_raw", "weight_raw", "user_comment", "date_review_submitted_raw", "height_in_display", "review_date",
    "source_site_display", "status_code", "content_type", "bytes", "width", "height", "hash_md5", "fetched_at",
    "updated_at", "brand", "waist_raw_display", "hips_raw", "age_raw", "waist_in", "hips_in_display",
    "age_years_display", "search_fts", "weight_display_display", "weight_raw_needs_correction", "clothing_type_id",
    "reviewer_profile_url", "reviewer_name_raw", "inseam_inches_display", "color_canonical", "color_display",
    "size_display", "bust_in_number_display", "cupsize_display", "weight_lbs_display", "weight_lbs_raw_issue",
    "product_title_raw", "product_subtitle_raw", "product_description_raw", "product_detail_raw",
    "product_category_raw", "product_variant_raw",
]

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
HEIGHT_RE = re.compile(r"\b([4-6])\s*(?:ft|feet|foot|['\u2019])\s*(\d{1,2})?\s*(?:in|inches|[\"\u201d])?", re.I)
WEIGHT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?|#)\b", re.I)
WAIST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b", re.I)
HIPS_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*inseam\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
BRA_RE = re.compile(r"\b((?:2[8-9]|3[0-9]|4[0-8])\s*(?:aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k))\b", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm(text: object) -> str:
    return WS_RE.sub(" ", str(text or "")).strip()


def strip_tags(value: object) -> str:
    text = re.sub(r"</p\s*>|<br\s*/?>", " ", str(value or ""), flags=re.I)
    return norm(html.unescape(TAG_RE.sub(" ", text)))


def fetch_text(url: str, retries: int = 5) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        try:
            with urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", "replace")
        except (HTTPError, URLError) as exc:
            last_error = exc
            if isinstance(exc, HTTPError) and exc.code not in {429, 500, 502, 503, 504}:
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
                return json.load(resp)
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
        except (URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"Failed JSON request for {query_url}: {last_error}")


def product_url_for(product: Dict[str, object]) -> str:
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


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
    sitemap_urls = [html.unescape(url) for url in re.findall(r"<loc>(https://shapedly\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index)]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url)
        urls = sorted(set(re.findall(r"https://shapedly\.com/products/[^<\s\"']+", text)))
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        sitemap_product_urls.extend(urls)

    by_url: Dict[str, Dict[str, object]] = {product_url_for(product): product for product in products if product_url_for(product)}
    missing = [url for url in sorted(set(sitemap_product_urls)) if url not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {"id": "", "handle": handle, "title": handle.replace("-", " ").title(), "product_type": "", "body_html": "", "variants": []}
    sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)})
    products_out = list(by_url.values())
    if limit_products:
        products_out = products_out[:limit_products]
    return products_out, sources


def decode_reviews(block_reviews: object) -> List[Dict[str, object]]:
    raw = norm(block_reviews)
    if not raw:
        return []
    try:
        decoded = base64.b64decode(raw).decode("utf-8", "replace")
        parsed = json.loads(decoded)
        return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []
    except (ValueError, json.JSONDecodeError):
        return []


def photo_urls(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    photos_array = review.get("photosArray")
    if isinstance(photos_array, list):
        urls.extend(norm(url) for url in photos_array if norm(url))
    if not urls:
        photos = review.get("photos")
        if isinstance(photos, str) and photos:
            try:
                parsed = json.loads(photos)
                if isinstance(parsed, list):
                    urls.extend(norm(url) for url in parsed if norm(url))
            except json.JSONDecodeError:
                pass
    return list(dict.fromkeys(urls))


def fetch_product_reviews(product: Dict[str, object], limit_pages: Optional[int] = None) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    product_url = product_url_for(product)
    meta: Dict[str, object] = {
        "product_url": product_url,
        "product_title": product.get("title"),
        "adapter_used": "lai_product_reviews",
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "matching_review_images": 0,
        "errors": [],
    }
    product_id = norm(product.get("id"))
    if not product_id:
        meta["errors"].append("missing_shopify_product_id")
        return [], meta

    reviews: List[Dict[str, object]] = []
    seen = set()
    page = 1
    load_more = 1
    total_hint = 0
    while load_more:
        if limit_pages is not None and int(meta["review_pages_scanned"]) >= limit_pages:
            break
        params = {
            "productShopifyId": product_id,
            "shopName": LAI_SHOP_NAME,
            "shop": LAI_SHOP_NAME,
            "page": page,
            "reviewPerPage": REVIEWS_PER_PAGE,
            "sortValue": "photo",
            "source": "homePage",
        }
        try:
            payload = fetch_json(LAI_API_ROOT, params=params, referer=product_url)
        except Exception as exc:  # noqa: BLE001
            meta["errors"].append(str(exc))
            break
        page_reviews = decode_reviews(payload.get("blockReviews"))
        load_more = int(payload.get("loadMore") or 0)
        total_hint = max(total_hint, int(payload.get("total") or 0))
        if not page_reviews and not load_more:
            break
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"]) + 1
        for review in page_reviews:
            review_id = norm(review.get("review_id") or review.get("id"))
            if review_id and review_id in seen:
                continue
            seen.add(review_id)
            reviews.append(review)
        page += 1
    meta["review_count_hint"] = total_hint or len(reviews)
    meta["matching_review_images"] = sum(len(photo_urls(review)) for review in reviews)
    return reviews, meta


def maybe_num(value: Optional[float]) -> str:
    if value is None:
        return ""
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def parse_num(pattern: re.Pattern[str], text: str, max_value: Optional[float] = None) -> Tuple[str, Optional[float]]:
    match = pattern.search(text)
    if not match:
        return "", None
    value = float(match.group(1))
    if max_value is not None and value > max_value:
        return "", None
    return norm(match.group(0)), value


def parse_height(text: str) -> Tuple[str, Optional[float]]:
    match = HEIGHT_RE.search(text)
    if not match:
        return "", None
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    if 4 <= feet <= 7 and 0 <= inches <= 11:
        return norm(match.group(0)), feet * 12 + inches
    return "", None


def parse_age(text: str) -> Tuple[str, str]:
    match = AGE_RE.search(text)
    return (norm(match.group(0)), match.group(1) or match.group(2) or "") if match else ("", "")


def parse_bra(text: str) -> Tuple[str, str]:
    match = BRA_RE.search(text)
    if not match:
        return "", ""
    compact = re.sub(r"\s+", "", match.group(1)).upper()
    band = re.match(r"(\d{2})", compact)
    cup = re.search(r"[A-Z]+$", compact)
    return (band.group(1) if band else "", cup.group(0) if cup else "")


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


def classify(product: Dict[str, object]) -> str:
    value = f"{product.get('title') or ''} {product.get('product_type') or ''}".lower()
    if "swim" in value or "bikini" in value:
        return "swimwear"
    if "bra" in value or "bralette" in value:
        return "bra"
    if "underwear" in value or "panty" in value or "brief" in value:
        return "underwear"
    if "dress" in value:
        return "dress"
    return "womens_clothing"


def output_skip_reason(product: Dict[str, object]) -> str:
    title = norm(product.get("title")).lower()
    product_type = norm(product.get("product_type")).lower()
    value = f"{title} {product_type}"
    if "shipping protection" in value:
        return "out_of_scope_shipping_protection"
    if "gift card" in value:
        return "out_of_scope_gift_card"
    if "washing bag" in value or "wash bag" in value:
        return "out_of_scope_accessory_washing_bag"
    if "nipple cover" in value or "nipple covers" in value:
        return "out_of_scope_accessory_nipple_covers"
    return ""


def row_for(product: Dict[str, object], review: Dict[str, object], image_url: str, image_index: int) -> Dict[str, str]:
    text = strip_tags(review.get("review"))
    height_raw, height_in = parse_height(text)
    weight_raw, weight = parse_num(WEIGHT_RE, text, 500)
    waist_raw, waist = parse_num(WAIST_RE, text, 80)
    hips_raw, hips = parse_num(HIPS_RE, text, 90)
    inseam_raw, inseam = parse_num(INSEAM_RE, text, 50)
    age_raw, age = parse_age(text)
    bust, cup = parse_bra(text)
    product_url = product_url_for(product)
    review_id = norm(review.get("review_id") or review.get("id") or f"{product.get('id')}-{image_index}")
    fetched = now_iso()
    return {
        "created_at_display": fetched,
        "id": f"{review_id}-{image_index}",
        "original_url_display": image_url,
        "product_page_url_display": product_url,
        "monetized_product_url_display": product_url,
        "height_raw": height_raw,
        "weight_raw": weight_raw,
        "user_comment": text,
        "date_review_submitted_raw": norm(review.get("date")),
        "height_in_display": maybe_num(height_in),
        "review_date": norm(review.get("date"))[:10],
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
        "waist_raw_display": waist_raw,
        "hips_raw": hips_raw,
        "age_raw": age_raw,
        "waist_in": maybe_num(waist),
        "hips_in_display": maybe_num(hips),
        "age_years_display": age,
        "search_fts": text,
        "weight_display_display": maybe_num(weight),
        "weight_raw_needs_correction": "",
        "clothing_type_id": classify(product),
        "reviewer_profile_url": "",
        "reviewer_name_raw": norm(review.get("author")),
        "inseam_inches_display": maybe_num(inseam),
        "color_canonical": "",
        "color_display": "",
        "size_display": "",
        "bust_in_number_display": bust,
        "cupsize_display": cup,
        "weight_lbs_display": maybe_num(weight),
        "weight_lbs_raw_issue": "",
        "product_title_raw": norm(product.get("title")),
        "product_subtitle_raw": "",
        "product_description_raw": strip_tags(product.get("body_html")),
        "product_detail_raw": variant_detail(product),
        "product_category_raw": norm(product.get("product_type")),
        "product_variant_raw": "",
    }


def is_measurement_row(row: Dict[str, str]) -> bool:
    return any(norm(row.get(field)) for field in ["height_in_display", "weight_lbs_display", "bust_in_number_display", "hips_in_display", "waist_in", "inseam_inches_display"])


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

    for idx, product in enumerate(products, start=1):
        reviews, meta = fetch_product_reviews(product, limit_pages=limit_pages)
        total_pages += int(meta.get("review_pages_scanned") or 0)
        total_hint += int(meta.get("review_count_hint") or 0)
        product_rows = 0
        skip_reason = output_skip_reason(product)
        for review in reviews:
            for image_index, image_url in enumerate(photo_urls(review), start=1):
                if not skip_reason:
                    rows.append(row_for(product, review, image_url, image_index))
                    product_rows += 1
        product_summaries.append({
            "product_index": idx,
            "product_id": product.get("id"),
            "product_title": product.get("title"),
            "product_url": product_url_for(product),
            "review_count_hint": meta.get("review_count_hint"),
            "review_pages_scanned": meta.get("review_pages_scanned"),
            "matching_review_images": meta.get("matching_review_images"),
            "rows": product_rows,
            "errors": meta.get("errors"),
            "skipped_from_output": bool(skip_reason),
            "skip_reason": skip_reason,
        })
        skip_note = f" skipped={skip_reason}" if skip_reason else ""
        print(f"[{idx}/{len(products)}] {product.get('title')} reviews={meta.get('review_count_hint')} pages={meta.get('review_pages_scanned')} rows={product_rows}{skip_note}")

    seen = set()
    deduped: List[Dict[str, str]] = []
    for row in rows:
        key = (row["id"], row["original_url_display"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

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
        "site": "shapedly.com",
        "adapter": "lai_product_reviews",
        "lai_shop_name": LAI_SHOP_NAME,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "exhaustive_review_paging": limit_pages is None,
        "review_pages_scanned": total_pages,
        "product_review_count_hint": total_hint,
        "rows_written": len(deduped),
        "distinct_reviews": len({row["id"].rsplit("-", 1)[0] for row in deduped}),
        "distinct_images": len({row["original_url_display"] for row in deduped}),
        "distinct_products": len({row["product_page_url_display"] for row in deduped}),
        "rows_with_distinct_product_url": len({row["product_page_url_display"] or row["monetized_product_url_display"] for row in deduped if row["product_page_url_display"] or row["monetized_product_url_display"]}),
        "rows_with_product_url": rows_with_product_url,
        "rows_with_any_measurement": rows_with_measurement,
        "rows_with_customer_image": rows_with_image,
        "rows_with_customer_ordered_size": rows_with_size,
        "rows_with_size": rows_with_size,
        "rows_supabase_qualified": rows_supabase,
        "output_csv": str(OUTPUT_CSV),
        "summary_json": str(SUMMARY_JSON),
        "started_at": started,
        "finished_at": now_iso(),
        "product_summaries": product_summaries,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(deduped)} rows to {OUTPUT_CSV}")
    print(f"Supabase-qualified rows: {rows_supabase}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
