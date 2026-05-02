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
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "miraclesuit_com"
OUTPUT_CSV = OUTPUT_DIR / "miraclesuit_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "miraclesuit_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://www.miraclesuit.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
YOTPO_APP_KEY = "kAnlBhdJrX7F2vUWmsX1T7dORtDmsXtvQGXcb76l"
YOTPO_API_ROOT = f"https://api-cdn.yotpo.com/v1/widget/{YOTPO_APP_KEY}"
BRAND = "Miraclesuit"
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
WEIGHT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?|#)\b", re.I)
WAIST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b", re.I)
HIPS_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*inseam\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
BRA_RE = re.compile(r"\b((?:2[8-9]|3[0-9]|4[0-8])\s*(?:aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k))\b", re.I)


def norm(text: str) -> str:
    return WS_RE.sub(" ", text or "").strip()


def strip_tags(value: str) -> str:
    return norm(html.unescape(TAG_RE.sub(" ", re.sub(r"</p\s*>|<br\s*/?>", " ", value or "", flags=re.I))))


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    with urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


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
    handle = norm(str(product.get("handle") or ""))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def fetch_products() -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
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
        if len(page_products) < PRODUCTS_PER_PAGE:
            break
        page += 1
    sitemap_index = fetch_text(SITEMAP_URL)
    sitemap_urls = [html.unescape(url) for url in re.findall(r"<loc>(https://www\.miraclesuit\.com/sitemap_products_[^<]+)</loc>", sitemap_index)]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        if "/en-" in sitemap_url:
            continue
        text = fetch_text(sitemap_url)
        urls = sorted(set(re.findall(r"https://www\.miraclesuit\.com/products/[^<\s\"']+", text)))
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        sitemap_product_urls.extend(urls)
    by_url: Dict[str, Dict[str, object]] = {product_url_for(product): product for product in products if product_url_for(product)}
    missing = [url for url in sorted(set(sitemap_product_urls)) if url not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {"id": "", "handle": handle, "title": handle.replace("-", " ").title(), "product_type": "", "body_html": "", "variants": []}
    sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)})
    return list(by_url.values()), sources


def yotpo_url(product_id: object) -> str:
    return f"{YOTPO_API_ROOT}/products/{product_id}/reviews.json"


def response_obj(payload: Dict[str, object]) -> Dict[str, object]:
    response = payload.get("response")
    return response if isinstance(response, dict) else {}


def image_urls(review: Dict[str, object]) -> List[str]:
    images = review.get("images_data")
    if not isinstance(images, list):
        return []
    urls: List[str] = []
    for item in images:
        if isinstance(item, dict):
            url = norm(str(item.get("original_url") or item.get("thumb_url") or ""))
            if url and url not in urls:
                urls.append(url)
    return urls


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
        for variant in variants[:200]:
            if isinstance(variant, dict):
                title = norm(str(variant.get("title") or ""))
                if title and title.lower() != "default title" and title not in vals:
                    vals.append(title)
    return " | ".join(vals)


def classify(product: Dict[str, object]) -> str:
    value = f"{product.get('title') or ''} {product.get('product_type') or ''}".lower()
    if "one piece" in value or "swimsuit" in value or "swim" in value:
        return "swimwear"
    if "tankini" in value:
        return "tankini"
    if "cover" in value or "dress" in value:
        return "cover up"
    if "bra" in value:
        return "bra"
    if "slip" in value or "shap" in value:
        return "shapewear"
    return norm(str(product.get("product_type") or "")).lower()


def row_for(review: Dict[str, object], product: Dict[str, object], image_url: str, index: int, fetched_at: str) -> Dict[str, str]:
    title = strip_tags(str(review.get("title") or ""))
    body = strip_tags(str(review.get("content") or ""))
    text = norm(" ".join([title, body]))
    review_id = norm(str(review.get("id") or ""))
    date = norm(str(review.get("created_at") or ""))
    review_date = date.split("T", 1)[0] if "T" in date else date.split(" ", 1)[0]
    user = review.get("user") if isinstance(review.get("user"), dict) else {}
    reviewer = strip_tags(str(user.get("display_name") or user.get("name") or ""))
    height_raw, height_in = parse_height(text)
    weight_raw, weight = parse_num(WEIGHT_RE, text)
    waist_raw, waist = parse_num(WAIST_RE, text, 60)
    hips_raw, hips = parse_num(HIPS_RE, text, 80)
    _inseam_raw, inseam = parse_num(INSEAM_RE, text, 40)
    age_raw, age = parse_age(text)
    bust, cup = parse_bra(text)
    product_title = strip_tags(str(product.get("title") or ""))
    product_desc = strip_tags(str(product.get("body_html") or ""))
    product_url = product_url_for(product)
    return {
        "created_at_display": "",
        "id": f"{review_id}-{index}" if review_id else f"{hash(image_url)}-{index}",
        "original_url_display": image_url,
        "product_page_url_display": product_url,
        "monetized_product_url_display": "",
        "height_raw": height_raw,
        "weight_raw": weight_raw,
        "user_comment": text,
        "date_review_submitted_raw": date,
        "height_in_display": maybe_num(height_in),
        "review_date": review_date,
        "source_site_display": SOURCE_SITE,
        "status_code": "200",
        "content_type": "",
        "bytes": "",
        "width": "",
        "height": "",
        "hash_md5": "",
        "fetched_at": fetched_at,
        "updated_at": fetched_at,
        "brand": BRAND,
        "waist_raw_display": waist_raw,
        "hips_raw": hips_raw,
        "age_raw": age_raw,
        "waist_in": maybe_num(waist),
        "hips_in_display": maybe_num(hips),
        "age_years_display": age,
        "search_fts": norm(" ".join([BRAND, product_title, product_desc, title, body])),
        "weight_display_display": maybe_num(weight),
        "weight_raw_needs_correction": "",
        "clothing_type_id": classify(product),
        "reviewer_profile_url": "",
        "reviewer_name_raw": reviewer,
        "inseam_inches_display": maybe_num(inseam),
        "color_canonical": "",
        "color_display": "",
        "size_display": "",
        "bust_in_number_display": bust,
        "cupsize_display": cup,
        "weight_lbs_display": maybe_num(weight),
        "weight_lbs_raw_issue": "",
        "product_title_raw": product_title,
        "product_subtitle_raw": "",
        "product_description_raw": product_desc,
        "product_detail_raw": variant_detail(product),
        "product_category_raw": norm(str(product.get("product_type") or "")),
        "product_variant_raw": "",
    }


def has_measurement(row: Dict[str, str]) -> bool:
    return any(row.get(k) for k in ["height_in_display", "weight_lbs_display", "bust_in_number_display", "hips_in_display", "waist_in", "inseam_inches_display"])


def is_qualified(row: Dict[str, str]) -> bool:
    return bool(row.get("original_url_display") and row.get("product_page_url_display") and row.get("size_display") and has_measurement(row))


def scrape(limit_products: Optional[int] = None, limit_pages_per_product: Optional[int] = None) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    products, product_sources = fetch_products()
    if limit_products is not None:
        products = products[:limit_products]
    rows: List[Dict[str, str]] = []
    summaries: List[Dict[str, object]] = []
    errors: List[Dict[str, object]] = []
    for idx, product in enumerate(products, start=1):
        pid = product.get("id")
        product_rows: List[Dict[str, str]] = []
        pages = 0
        total = 0
        if pid:
            page = 1
            while True:
                if limit_pages_per_product is not None and page > limit_pages_per_product:
                    break
                try:
                    payload = fetch_json(yotpo_url(pid), {"per_page": REVIEWS_PER_PAGE, "page": page}, product_url_for(product))
                except Exception as exc:  # noqa: BLE001
                    errors.append({"product_url": product_url_for(product), "page": page, "error": str(exc)})
                    break
                response = response_obj(payload)
                pagination = response.get("pagination") if isinstance(response.get("pagination"), dict) else {}
                total = int(pagination.get("total") or total or 0)
                reviews = [item for item in response.get("reviews", []) if isinstance(item, dict)]
                if not reviews:
                    break
                pages += 1
                for review in reviews:
                    for image_index, image_url in enumerate(image_urls(review), start=1):
                        product_rows.append(row_for(review, product, image_url, image_index, fetched_at))
                per_page = int(pagination.get("per_page") or REVIEWS_PER_PAGE)
                total_pages = max(1, (total + per_page - 1) // per_page) if total else page
                if page >= total_pages:
                    break
                page += 1
        rows.extend(product_rows)
        summaries.append({
            "product_index": idx, "product_url": product_url_for(product), "product_title": product.get("title"),
            "product_type": product.get("product_type"), "shopify_product_id": pid, "adapter_used": "yotpo_product_level",
            "review_pages_scanned": pages, "review_count_hint": total, "matching_review_images": len(product_rows),
            "rows": len(product_rows), "skipped_from_output": False, "skip_reason": "", "errors": [],
        })
        print(f"[product {idx}/{len(products)}] reviews={total} pages={pages} rows={len(product_rows)} url={product_url_for(product)}", flush=True)
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        key = (row.get("id", "").rsplit("-", 1)[0], re.sub(r"\?.*$", "", row.get("original_url_display", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    summary: Dict[str, object] = {
        "site": SITE_ROOT, "retailer": "miraclesuit_com", "adapter": "yotpo_product_level", "yotpo_app_key": YOTPO_APP_KEY,
        "started_at": fetched_at, "finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "product_sources": product_sources, "products_discovered": len(products), "products_scanned": len(products),
        "products_excluded_from_output": 0, "exhaustive_review_paging": limit_pages_per_product is None,
        "review_pages_scanned": sum(int(item["review_pages_scanned"]) for item in summaries),
        "product_review_count_hint": sum(int(item["review_count_hint"]) for item in summaries),
        "products_with_review_rows": sum(1 for item in summaries if int(item["rows"]) > 0), "product_summaries": summaries,
        "errors": errors, "access_policy": "public_pages_only; no_auth_bypass; no_captcha_bypass; polite_retries",
        "measurement_extraction": "deterministic_regex_and_provider_fields_only",
    }
    return deduped, summary


def write_csv(rows: Sequence[Dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in HEADERS})


def enrich(summary: Dict[str, object], rows: Sequence[Dict[str, str]]) -> Dict[str, object]:
    product_urls = {row.get("product_page_url_display") for row in rows if row.get("product_page_url_display")}
    summary.update({
        "output_csv": str(OUTPUT_CSV), "rows_written": len(rows),
        "distinct_reviews": len({row.get("id", "").rsplit("-", 1)[0] for row in rows if row.get("id")}),
        "distinct_images": len({re.sub(r"\?.*$", "", row.get("original_url_display", "")) for row in rows if row.get("original_url_display")}),
        "distinct_product_urls": len(product_urls), "distinct_products": len(product_urls),
        "rows_with_distinct_product_url": sum(1 for row in rows if row.get("product_page_url_display")),
        "rows_with_product_url": sum(1 for row in rows if row.get("product_page_url_display")),
        "rows_missing_product_url": sum(1 for row in rows if not row.get("product_page_url_display")),
        "rows_with_customer_image": sum(1 for row in rows if row.get("original_url_display")),
        "rows_with_image_url": sum(1 for row in rows if row.get("original_url_display")),
        "rows_missing_image_url": sum(1 for row in rows if not row.get("original_url_display")),
        "rows_with_user_comment": sum(1 for row in rows if row.get("user_comment")),
        "rows_with_size": sum(1 for row in rows if row.get("size_display")),
        "rows_with_customer_ordered_size": sum(1 for row in rows if row.get("size_display")),
        "rows_with_any_measurement": sum(1 for row in rows if has_measurement(row)),
        "rows_supabase_qualified": sum(1 for row in rows if is_qualified(row)),
        "distinct_qualified_reviews": len({row.get("id", "").rsplit("-", 1)[0] for row in rows if is_qualified(row)}),
        "rows_with_image_and_product_url": sum(1 for row in rows if row.get("original_url_display") and row.get("product_page_url_display")),
        "rows_with_image_product_and_measurement": sum(1 for row in rows if row.get("original_url_display") and row.get("product_page_url_display") and has_measurement(row)),
        "rows_with_image_product_size_and_measurement": sum(1 for row in rows if is_qualified(row)),
        "rows_with_image_product_and_user_comment": sum(1 for row in rows if row.get("original_url_display") and row.get("product_page_url_display") and row.get("user_comment")),
        "rows_with_product_context": sum(1 for row in rows if row.get("product_title_raw")),
    })
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    limit_products = int(argv[argv.index("--limit-products") + 1]) if "--limit-products" in argv else None
    limit_pages = int(argv[argv.index("--limit-pages-per-product") + 1]) if "--limit-pages-per-product" in argv else None
    rows, summary = scrape(limit_products=limit_products, limit_pages_per_product=limit_pages)
    rows.sort(key=lambda row: (row.get("review_date", ""), row.get("product_page_url_display", ""), row.get("original_url_display", "")), reverse=True)
    write_csv(rows)
    summary = enrich(summary, rows)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Rows written: {len(rows)}")
    print(f"Supabase-qualified rows: {summary['rows_supabase_qualified']}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
