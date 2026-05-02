#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import html
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "babyboofashion_com"
OUTPUT_CSV = OUTPUT_DIR / "babyboofashion_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "babyboofashion_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://www.babyboofashion.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
YOTPO_APP_KEY = "tO3jqlCKujvE6ZF5NeHgnBnKgT8x148OgHudA2TC"
YOTPO_REVIEWS_ROOT = f"https://api-cdn.yotpo.com/v1/widget/{YOTPO_APP_KEY}/products"
BRAND = "Babyboo"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
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
CM_HEIGHT_RE = re.compile(r"\b(1[4-9]\d)\s*cm\b", re.I)
WEIGHT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?|#)\b", re.I)
WAIST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*(?:waist|ways)\b", re.I)
HIPS_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
BUST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*(?:bust|breast)\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*inseam\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
SIZE_ORDERED_RE = re.compile(r"\b(?:ordered|bought|purchased|got|wearing|wore|size up and get|in)\s+(?:a\s+|an\s+)?(xxs|xs|s|m|l|xl|xxl|xxxl|[0-9]{1,2})\b", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(text: object) -> str:
    return WS_RE.sub(" ", str(text or "")).strip()


def strip_tags(value: object) -> str:
    text = re.sub(r"</p\s*>|<br\s*/?>|</li\s*>", " ", str(value or ""), flags=re.I)
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


def fetch_json_url(url: str, referer: Optional[str] = None, retries: int = 5) -> Dict[str, object]:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": SITE_ROOT,
                "Referer": referer or SOURCE_SITE,
            },
        )
        try:
            with urlopen(req, timeout=90) as resp:
                return json.load(resp)
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
        except (URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"Failed JSON request for {url}: {last_error}")


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, referer: Optional[str] = None) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    return fetch_json_url(query_url, referer=referer)


def product_url_for(product: Dict[str, object]) -> str:
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/en-us/products/{quote(handle, safe='/-._~')}" if handle else ""


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
    sitemap_urls = [html.unescape(u) for u in re.findall(r"<loc>(https://www\.babyboofashion\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index)]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        if "/en-us/" not in sitemap_url:
            continue
        text = fetch_text(sitemap_url)
        urls = sorted(set(re.findall(r"https://www\.babyboofashion\.com/en-us/products/[^<\s\"']+", text)))
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        sitemap_product_urls.extend(urls)

    by_url: Dict[str, Dict[str, object]] = {product_url_for(product): product for product in products if product_url_for(product)}
    missing = [url for url in sorted(set(sitemap_product_urls)) if url not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {"id": "", "handle": handle, "title": handle.replace("-", " ").title(), "product_type": "", "body_html": "", "tags": [], "variants": []}
    sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)})
    products_out = list(by_url.values())
    if limit_products:
        products_out = products_out[:limit_products]
    return products_out, sources


def yotpo_reviews_url(product_id: object, page: int) -> str:
    return f"{YOTPO_REVIEWS_ROOT}/{product_id}/reviews.json?{urlencode({'per_page': REVIEWS_PER_PAGE, 'page': page})}"


def maybe_num(value: Optional[float]) -> str:
    if value is None:
        return ""
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def parse_height(text: str) -> Tuple[str, Optional[float]]:
    match = HEIGHT_RE.search(text)
    if match:
        feet = int(match.group(1))
        inches = int(match.group(2) or 0)
        if 4 <= feet <= 7 and 0 <= inches <= 11:
            return norm(match.group(0)), feet * 12 + inches
    cm = CM_HEIGHT_RE.search(text)
    if cm:
        return norm(cm.group(0)), round(float(cm.group(1)) / 2.54, 1)
    return "", None


def parse_num(pattern: re.Pattern[str], text: str, max_value: Optional[float] = None) -> Tuple[str, Optional[float]]:
    match = pattern.search(text)
    if not match:
        return "", None
    value = float(match.group(1))
    if max_value is not None and value > max_value:
        return "", None
    return norm(match.group(0)), value


def parse_age(text: str) -> Tuple[str, str]:
    match = AGE_RE.search(text)
    return (norm(match.group(0)), match.group(1) or match.group(2) or "") if match else ("", "")


def custom_fields(review: Dict[str, object]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    fields = review.get("custom_fields")
    if not isinstance(fields, dict):
        return out
    for value in fields.values():
        if not isinstance(value, dict):
            continue
        title = norm(value.get("title")).lower()
        field_value = norm(value.get("value"))
        if title and field_value:
            out[title] = field_value
    return out


def parse_review_measurements(review: Dict[str, object], body: str) -> Dict[str, str]:
    fields = custom_fields(review)
    joined = " ".join(part for part in [body, fields.get("height", ""), fields.get("age", "")] if part)
    height_raw, height = parse_height(joined)
    weight_raw, weight = parse_num(WEIGHT_RE, body, max_value=700)
    waist_raw, waist = parse_num(WAIST_RE, body, max_value=90)
    hips_raw, hips = parse_num(HIPS_RE, body, max_value=90)
    bust_raw, bust = parse_num(BUST_RE, body, max_value=70)
    inseam_raw, inseam = parse_num(INSEAM_RE, body, max_value=45)
    age_raw, age = parse_age(joined)
    if not age and re.fullmatch(r"\d{2}\s*-\s*\d{2}", fields.get("age", "")):
        age_raw = fields.get("age", "")
    return {
        "height_raw": height_raw or fields.get("height", ""),
        "height_in_display": maybe_num(height),
        "weight_raw": weight_raw,
        "weight_display_display": maybe_num(weight),
        "weight_lbs_display": maybe_num(weight),
        "waist_raw_display": waist_raw,
        "waist_in": maybe_num(waist),
        "hips_raw": hips_raw,
        "hips_in_display": maybe_num(hips),
        "bust_in_number_display": maybe_num(bust),
        "inseam_inches_display": maybe_num(inseam),
        "age_raw": age_raw,
        "age_years_display": age,
        "cupsize_display": fields.get("cup size", ""),
    }


def parse_size(review: Dict[str, object], body: str) -> str:
    fields = custom_fields(review)
    if fields.get("size"):
        return fields["size"].upper()
    match = SIZE_ORDERED_RE.search(body)
    return norm(match.group(1)).upper() if match else ""


def media_urls(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    for image in review.get("images_data") or []:
        if not isinstance(image, dict):
            continue
        url = norm(image.get("original_url") or image.get("thumb_url"))
        if url and url not in urls:
            urls.append(url)
    return urls


def image_url_loads(url: str) -> bool:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*", "Referer": SOURCE_SITE})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.status == 200 and norm(resp.headers.get("Content-Type")).lower().startswith("image/")
    except Exception:
        return False


def clothing_type(product: Dict[str, object]) -> str:
    hay = " ".join([norm(product.get("title")), norm(product.get("product_type")), " ".join(norm(t) for t in product.get("tags", []) if isinstance(t, str))]).lower()
    if "dress" in hay or "gown" in hay:
        return "dress"
    if "skirt" in hay:
        return "skirt"
    if "short" in hay or "skort" in hay:
        return "shorts"
    if any(token in hay for token in ["top", "corset", "bodysuit", "tee", "shirt", "blouse", "tank", "vest"]):
        return "top"
    if "pant" in hay or "trouser" in hay:
        return "pants"
    if "jumpsuit" in hay or "romper" in hay:
        return "jumpsuit"
    if "bikini" in hay or "swim" in hay:
        return "swimwear"
    return ""


def skip_reason(product: Dict[str, object]) -> str:
    product_type = norm(product.get("product_type")).lower()
    title = norm(product.get("title")).lower()
    hay = " ".join([title, product_type, " ".join(norm(t) for t in product.get("tags", []) if isinstance(t, str))]).lower()
    if "gift card" in hay:
        return "out_of_scope_gift_card"
    if product_type in {"accessories", "shoe", "shoes"} or re.search(r"\b(heels?|sandals?|boots?|bags?|purses?|earrings?|necklace|bracelet|hat|cap|sunglasses|gloves?|stickers?)\b", title):
        return "out_of_scope_accessory"
    if re.search(r"\b(kids?|girls?|baby|toddler)\b", hay):
        return "out_of_scope_kids"
    if re.search(r"\b(mens|men's)\b", hay):
        return "out_of_scope_mens"
    if not clothing_type(product):
        return "out_of_scope_non_clothing_or_unknown"
    return ""


def review_pages(product_id: object, product_url: str) -> Tuple[List[Dict[str, object]], int, int, List[str]]:
    if not norm(product_id):
        return [], 0, 0, ["missing_shopify_product_id"]
    reviews: List[Dict[str, object]] = []
    errors: List[str] = []
    pages = 0
    total = 0
    page = 1
    while True:
        try:
            payload = fetch_json_url(yotpo_reviews_url(product_id, page), referer=product_url)
        except Exception as exc:
            errors.append(f"review_fetch_error:{type(exc).__name__}:{exc}")
            break
        response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
        pagination = response.get("pagination") if isinstance(response.get("pagination"), dict) else {}
        page_reviews = [item for item in response.get("reviews", []) if isinstance(item, dict)]
        total = int(pagination.get("total") or total or 0)
        if not page_reviews:
            if page == 1:
                pages = 1
            break
        reviews.extend(page_reviews)
        pages += 1
        if len(reviews) >= total or len(page_reviews) < REVIEWS_PER_PAGE:
            break
        page += 1
    return reviews, pages, total, errors


def row_for(product: Dict[str, object], review: Dict[str, object], image_url: str, fetched_at: str) -> Dict[str, str]:
    body = norm(" ".join(part for part in [norm(review.get("title")), norm(review.get("content"))] if part))
    measurements = parse_review_measurements(review, body)
    user = review.get("user") if isinstance(review.get("user"), dict) else {}
    variants = product.get("variants") if isinstance(product.get("variants"), list) else []
    variant_detail = " | ".join(norm(v.get("title")) for v in variants[:100] if isinstance(v, dict) and norm(v.get("title")))
    row = {key: "" for key in HEADERS}
    row.update({
        "created_at_display": norm(review.get("created_at")),
        "id": norm(review.get("id")),
        "original_url_display": image_url,
        "product_page_url_display": product_url_for(product),
        "user_comment": body,
        "date_review_submitted_raw": norm(review.get("created_at")),
        "review_date": norm(review.get("created_at"))[:10],
        "source_site_display": SOURCE_SITE,
        "fetched_at": fetched_at,
        "updated_at": fetched_at,
        "brand": BRAND,
        "search_fts": " ".join([BRAND, norm(product.get("title")), body]),
        "clothing_type_id": clothing_type(product),
        "reviewer_name_raw": norm(user.get("display_name") if isinstance(user, dict) else ""),
        "size_display": parse_size(review, body),
        "product_title_raw": norm(product.get("title")),
        "product_description_raw": strip_tags(product.get("body_html")),
        "product_detail_raw": variant_detail,
        "product_category_raw": norm(product.get("product_type")),
        "product_variant_raw": "",
    })
    row.update(measurements)
    return row


def scan_product(index: int, product: Dict[str, object]) -> Dict[str, object]:
    product_url = product_url_for(product)
    reviews, pages, total, errors = review_pages(product.get("id"), product_url)
    reason = skip_reason(product)
    rows: List[Dict[str, str]] = []
    raw_image_count = 0
    if not reason:
        fetched_at = now_iso()
        seen = set()
        for review in reviews:
            urls = media_urls(review)
            raw_image_count += len(urls)
            for image_url in urls:
                key = (norm(review.get("id")), image_url)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row_for(product, review, image_url, fetched_at))
    return {
        "index": index,
        "product_id": norm(product.get("id")),
        "handle": norm(product.get("handle")),
        "title": norm(product.get("title")),
        "product_url": product_url,
        "product_type": norm(product.get("product_type")),
        "reviews_scanned": len(reviews),
        "review_count_hint": total,
        "review_pages_scanned": pages,
        "review_image_count": raw_image_count,
        "rows_written": len(rows),
        "skipped_from_output": bool(reason),
        "skip_reason": reason,
        "errors": errors,
        "rows": rows,
    }


def has_measurement(row: Dict[str, str]) -> bool:
    return any(norm(row.get(col)) for col in ["height_in_display", "weight_display_display", "weight_lbs_display", "bust_in_number_display", "hips_in_display", "waist_in", "inseam_inches_display"])


def summarize(rows: List[Dict[str, str]]) -> Dict[str, int]:
    distinct_urls = {norm(r.get("product_page_url_display")) or norm(r.get("monetized_product_url_display")) for r in rows if norm(r.get("product_page_url_display")) or norm(r.get("monetized_product_url_display"))}
    return {
        "rows_written": len(rows),
        "distinct_reviews": len({norm(r.get("id")) for r in rows if norm(r.get("id"))}),
        "distinct_images": len({norm(r.get("original_url_display")) for r in rows if norm(r.get("original_url_display"))}),
        "rows_with_distinct_product_url": len(distinct_urls),
        "rows_with_customer_image": sum(1 for r in rows if norm(r.get("original_url_display"))),
        "rows_with_customer_ordered_size": sum(1 for r in rows if norm(r.get("size_display")) and norm(r.get("size_display")).lower() != "unknown"),
        "rows_with_any_measurement": sum(1 for r in rows if has_measurement(r)),
        "rows_supabase_qualified": sum(1 for r in rows if norm(r.get("original_url_display")) and (norm(r.get("product_page_url_display")) or norm(r.get("monetized_product_url_display"))) and norm(r.get("size_display")) and has_measurement(r)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-products", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    started_at = now_iso()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    products, product_sources = fetch_products(args.limit_products)

    results: List[Dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(scan_product, index, product) for index, product in enumerate(products, start=1)]
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if done % 25 == 0 or done == len(futures):
                print(f"scanned {done}/{len(futures)} products; rows={sum(len(r['rows']) for r in results)}")

    results.sort(key=lambda item: int(item["index"]))
    rows: List[Dict[str, str]] = []
    seen_rows = set()
    for result in results:
        for row in result["rows"]:
            key = (norm(row.get("id")), norm(row.get("original_url_display")))
            if key in seen_rows:
                continue
            seen_rows.add(key)
            rows.append(row)

    invalid_image_urls: List[str] = []
    if rows:
        with ThreadPoolExecutor(max_workers=min(32, max(4, args.workers * 2))) as pool:
            image_checks = {pool.submit(image_url_loads, norm(row.get("original_url_display"))): row for row in rows}
            valid_rows: List[Dict[str, str]] = []
            for done, future in enumerate(as_completed(image_checks), start=1):
                row = image_checks[future]
                image_url = norm(row.get("original_url_display"))
                if future.result():
                    valid_rows.append(row)
                else:
                    invalid_image_urls.append(image_url)
                if done % 250 == 0 or done == len(image_checks):
                    print(f"validated {done}/{len(image_checks)} image urls")
        rows = valid_rows

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    product_summaries = [{k: v for k, v in item.items() if k != "rows"} for item in results]
    summary = {
        "site": SOURCE_SITE,
        "provider": "Yotpo product reviews API",
        "yotpo_app_key": YOTPO_APP_KEY,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(results),
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "review_pages_scanned": sum(int(item.get("review_pages_scanned") or 0) for item in product_summaries),
        "product_review_count_hint": sum(int(item.get("review_count_hint") or 0) for item in product_summaries),
        "raw_review_image_occurrences_before_dedupe": sum(int(item.get("review_image_count") or 0) for item in product_summaries),
        "rows_filtered_invalid_images": len(invalid_image_urls),
        "invalid_image_urls_sample": invalid_image_urls[:25],
        "exhaustive_review_paging": True,
        "output_csv": str(OUTPUT_CSV),
        "started_at": started_at,
        "finished_at": now_iso(),
        "product_summaries": product_summaries,
    }
    summary.update(summarize(rows))
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in [
        "products_discovered", "products_scanned", "products_excluded_from_output", "review_pages_scanned",
        "product_review_count_hint", "raw_review_image_occurrences_before_dedupe", "rows_filtered_invalid_images",
        "rows_written", "distinct_reviews", "distinct_images", "rows_with_distinct_product_url",
        "rows_with_customer_image", "rows_with_customer_ordered_size", "rows_with_any_measurement",
        "rows_supabase_qualified",
    ]}, indent=2))


if __name__ == "__main__":
    main()
