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
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "fashionpass_com"
OUTPUT_CSV = OUTPUT_DIR / "fashionpass_com_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "fashionpass_com_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://www.fashionpass.com"
SOURCE_SITE = f"{SITE_ROOT}/"
LEAD_URL = f"{SITE_ROOT}/product/ronny-kobo/verna-top"
COLLECTION_API = "https://collections.fashionpass.com/api/v1/collections/SearchByString2/"
REVIEW_API = "https://reviews.fashionpass.com/api/v1/Review/GetReviews"
REVIEW_IMAGE_ROOT = "https://fashionpass.s3-us-west-1.amazonaws.com/"
BRAND = "FashionPass"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36"
BLOCK_STATUS_CODES = {403, 429}
BLOCK_TEXT_RE = re.compile(r"\b(?:access denied|blocked|forbidden|unusual traffic|verify you are human|captcha)\b", re.I)

HEADERS = [
    "created_at_display", "id", "original_url_display", "product_page_url_display", "monetized_product_url_display",
    "height_raw", "weight_raw", "user_comment", "date_review_submitted_raw", "height_in_display", "review_date",
    "source_site_display", "status_code", "content_type", "bytes", "width", "height", "hash_md5", "fetched_at",
    "updated_at", "brand", "waist_raw_display", "hips_raw", "age_raw", "waist_in", "hips_in_display",
    "age_years_display", "search_fts", "weight_display_display", "weight_raw_needs_correction", "clothing_type_id",
    "reviewer_profile_url", "reviewer_name_raw", "inseam_inches_display", "color_canonical", "color_display",
    "size_display", "bust_in_number_display", "cupsize_display", "weight_lbs_display", "weight_lbs_raw_issue",
    "product_title_raw", "product_subtitle_raw", "product_description_raw", "product_detail_raw",
    "product_category_raw", "product_variant_raw", "image_source_type",
]

WS_RE = re.compile(r"\s+")
APPAREL_WORDS = {
    "dress", "dresses", "tops", "top", "bottoms", "shorts", "skirts", "skort", "pants", "jeans", "rompers",
    "jumpsuits", "jackets", "sweaters", "sets", "matching set", "clothing", "blouses",
}
NON_APPAREL_WORDS = {"accessories", "bags", "jewelry", "earrings", "necklace", "bracelet", "heels", "shoes", "boots"}


class BlockedScrapeError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(value: object) -> str:
    if value is None:
        return ""
    return WS_RE.sub(" ", str(value)).strip()


def maybe_num(value: object) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if math.isclose(number, round(number)):
        return str(int(round(number)))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def fetch_text(url: str, referer: str = SOURCE_SITE, retries: int = 2) -> str:
    last_error: Optional[BaseException] = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Origin": SITE_ROOT,
                "Referer": referer,
            })
            with urlopen(req, timeout=45) as resp:
                text = resp.read().decode("utf-8", "replace")
                if resp.status in BLOCK_STATUS_CODES or BLOCK_TEXT_RE.search(text[:2000]):
                    raise BlockedScrapeError(f"Blocked response while fetching {url}: status={resp.status}")
                return text
        except (HTTPError, URLError) as exc:
            last_error = exc
            if isinstance(exc, HTTPError) and exc.code in BLOCK_STATUS_CODES:
                raise BlockedScrapeError(f"Blocked response while fetching {url}: status={exc.code}") from exc
            if isinstance(exc, HTTPError) and exc.code not in {408, 500, 502, 503, 504}:
                raise
        time.sleep(min(2 ** attempt, 5))
    raise RuntimeError(f"Failed request for {url}: {last_error}")


def fetch_json(url: str, referer: str = SOURCE_SITE) -> Dict[str, object]:
    return json.loads(fetch_text(url, referer=referer))


def product_url(product: Dict[str, object]) -> str:
    vendor = norm(product.get("vendor_handle"))
    handle = norm(product.get("handle") or product.get("product_handle"))
    if vendor and handle:
        return f"{SITE_ROOT}/product/{quote(vendor, safe='')}/{quote(handle, safe='')}"
    if handle:
        return f"{SITE_ROOT}/product/{quote(handle, safe='')}"
    return ""


def product_title(product: Dict[str, object]) -> str:
    return norm(product.get("title") or product.get("product_title")).title()


def product_vendor(product: Dict[str, object]) -> str:
    return norm(product.get("vendor") or product.get("vendor_name"))


def product_id(product: Dict[str, object]) -> object:
    return product.get("id") or product.get("product_id")


def classify_product(product: Dict[str, object]) -> str:
    hay = " ".join([
        product_title(product),
        norm(product.get("categoryList")),
        " ".join(norm(x) for x in product.get("tags", []) if isinstance(x, str)),
        " ".join(norm(x) for x in product.get("images", []) if isinstance(x, str)),
    ]).lower()
    if any(word in hay for word in NON_APPAREL_WORDS):
        return ""
    if "dress" in hay:
        return "dress"
    if any(word in hay for word in ["skirt", "skort"]):
        return "skirt"
    if any(word in hay for word in ["short"]):
        return "shorts"
    if any(word in hay for word in ["pant", "jean"]):
        return "pants"
    if any(word in hay for word in ["romper", "jumpsuit"]):
        return "jumpsuit"
    if any(word in hay for word in ["top", "blouse", "shirt", "sweater", "jacket"]):
        return "top"
    if any(word in hay for word in APPAREL_WORDS):
        return "clothing"
    return ""


def skip_reason(product: Dict[str, object]) -> str:
    return "" if classify_product(product) else "out_of_scope_non_clothing_or_accessory"


def parse_height(value: object) -> Tuple[str, str]:
    raw = norm(value)
    match = re.match(r"^([4-6])[-'\u2019 ]+(\d{1,2})$", raw)
    if match:
        feet = int(match.group(1))
        inches = int(match.group(2))
        if 0 <= inches <= 11:
            return raw, str(feet * 12 + inches)
    return raw, ""


def parse_cup(value: object) -> str:
    raw = norm(value)
    match = re.search(r"\b\d{2,3}\s*:?\s*([a-z]{1,3})\b", raw, re.I)
    return match.group(1).upper() if match else ""


def image_url(path: object) -> str:
    value = norm(path)
    if not value:
        return ""
    if value.startswith("http"):
        return value
    return REVIEW_IMAGE_ROOT + value.lstrip("/")


def user_comment(review: Dict[str, object]) -> str:
    parts = [
        norm(review.get("title")),
        norm(review.get("text")),
        f"fit: {norm(review.get('name'))}" if review.get("name") else "",
        f"body type: {norm(review.get('bodytype'))}" if review.get("bodytype") else "",
        f"bra size: {norm(review.get('brasize'))}" if review.get("brasize") else "",
        f"rented for: {norm(review.get('rentedfor'))}" if review.get("rentedfor") else "",
    ]
    return norm(" ".join(part for part in parts if part))


def row_for(product: Dict[str, object], review: Dict[str, object], fetched_at: str) -> Dict[str, str]:
    height_raw, height_in = parse_height(review.get("height"))
    title = product_title(product)
    vendor = product_vendor(product)
    category = norm(product.get("categoryList"))
    row = {header: "" for header in HEADERS}
    row.update({
        "created_at_display": norm(review.get("reviewDate")),
        "id": f"fashionpass-{norm(review.get('review_id'))}",
        "original_url_display": image_url(review.get("img_link_s3")),
        "product_page_url_display": product_url(product),
        "height_raw": height_raw,
        "weight_raw": norm(review.get("weight")),
        "user_comment": user_comment(review),
        "date_review_submitted_raw": norm(review.get("reviewDate")),
        "height_in_display": height_in,
        "review_date": norm(review.get("reviewDate"))[:10],
        "source_site_display": SOURCE_SITE,
        "fetched_at": fetched_at,
        "updated_at": fetched_at,
        "brand": BRAND,
        "age_raw": norm(review.get("age")),
        "age_years_display": maybe_num(review.get("age")),
        "search_fts": norm(" ".join([BRAND, vendor, title, user_comment(review)])),
        "weight_display_display": maybe_num(review.get("weight")),
        "clothing_type_id": classify_product(product),
        "reviewer_name_raw": norm(review.get("person_name")),
        "size_display": norm(review.get("sizeworn")).upper(),
        "cupsize_display": parse_cup(review.get("brasize")),
        "weight_lbs_display": maybe_num(review.get("weight")),
        "product_title_raw": title,
        "product_subtitle_raw": vendor,
        "product_detail_raw": ", ".join(item.get("name", "") for item in product.get("attributes", {}).get("detail", []) if isinstance(item, dict)),
        "product_category_raw": category,
        "product_variant_raw": norm(review.get("size")),
        "image_source_type": "customer_review_image",
    })
    return row


def has_measurement(row: Dict[str, str]) -> bool:
    return any(row.get(key) for key in ["height_in_display", "weight_display_display", "weight_lbs_display", "bust_in_number_display", "hips_in_display", "waist_in", "inseam_inches_display"])


def is_qualified(row: Dict[str, str]) -> bool:
    return bool(row.get("original_url_display") and row.get("product_page_url_display") and row.get("size_display") and has_measurement(row))


def catalog_url(page: int) -> str:
    return f"{COLLECTION_API}?{urlencode({'page': page})}"


def review_url(product_id: object, limit: int = -1) -> str:
    return f"{REVIEW_API}?{urlencode({'befirst': 0, 'type': 'clothing', 'limit': limit, 'cid': 0, 'product_id': product_id})}"


def add_product(products: List[Dict[str, object]], seen: set, product: object) -> None:
    if not isinstance(product, dict):
        return
    pid = product.get("id") or product.get("product_id")
    if not pid or pid in seen:
        return
    seen.add(pid)
    products.append(product)


def discover_seed_products() -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    html_text = fetch_text(LEAD_URL, referer=SOURCE_SITE)
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_text)
    if not match:
        raise RuntimeError("Could not locate FashionPass __NEXT_DATA__ on lead product page")
    state = json.loads(html.unescape(match.group(1)))["props"]["pageProps"]["initialState"]
    products: List[Dict[str, object]] = []
    seen = set()
    product_info = state.get("product", {}).get("product_detail", {}).get("product_info", {})
    add_product(products, seen, product_info)
    pairings = product_info.get("product_pairings", {}) if isinstance(product_info, dict) else {}
    if isinstance(pairings, dict):
        for group in pairings.values():
            if isinstance(group, list):
                for item in group:
                    add_product(products, seen, item)
    recent = state.get("recentProducts", {}).get("RecentProducts", [])
    if isinstance(recent, list):
        for item in recent:
            if isinstance(item, dict):
                add_product(products, seen, item.get("product_info"))
    return products, {"source": "lead_pdp_next_data_related_products", "lead_url": LEAD_URL, "products_seen": len(products)}


def discover_products(limit_pages: Optional[int] = None) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    products: List[Dict[str, object]] = []
    seen = set()
    pages_total = 0
    page = 1
    while True:
        payload = fetch_json(catalog_url(page))
        product_list = payload.get("product_list") if isinstance(payload.get("product_list"), dict) else {}
        pages_total = int(product_list.get("pages") or pages_total or page)
        items = [item for item in product_list.get("result_items", []) if isinstance(item, dict)]
        for item in items:
            pid = item.get("id")
            if pid in seen:
                continue
            seen.add(pid)
            products.append(item)
        print(f"catalog_page={page} items={len(items)} products={len(products)}", flush=True)
        if limit_pages and page >= limit_pages:
            break
        if page >= pages_total or not items:
            break
        page += 1
    return products, {"source": "collections/SearchByString2", "pages_scanned": page, "pages_total": pages_total, "products_seen": len(products)}


def scrape(limit_catalog_pages: Optional[int] = None, limit_products: Optional[int] = None, full_catalog: bool = False) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = now_iso()
    products, source = discover_products(limit_pages=limit_catalog_pages) if full_catalog else discover_seed_products()
    rows: List[Dict[str, str]] = []
    summaries: List[Dict[str, object]] = []
    review_products_scanned = 0
    reviews_seen = 0
    reviews_with_images = 0
    fetched_at = now_iso()
    products_to_scan = products[:limit_products] if limit_products else products
    for index, product in enumerate(products_to_scan, start=1):
        reason = skip_reason(product)
        summary = {
            "product_id": product_id(product),
            "product_title": product_title(product),
            "product_url": product_url(product),
            "skipped_from_output": bool(reason),
            "skip_reason": reason,
            "reviews_seen": 0,
            "image_rows": 0,
            "review_api_scanned": False,
        }
        rating = float(product.get("averageReviewRating") or 0)
        should_scan_reviews = not reason and (not full_catalog or rating > 0)
        if should_scan_reviews:
            review_products_scanned += 1
            summary["review_api_scanned"] = True
            payload = fetch_json(review_url(product_id(product)), referer=product_url(product) or SOURCE_SITE)
            reviews = [item for item in payload.get("rows", []) if isinstance(item, dict) and item.get("show_status", True)]
            summary["reviews_seen"] = len(reviews)
            reviews_seen += len(reviews)
            for review in reviews:
                if not norm(review.get("img_link_s3")):
                    continue
                reviews_with_images += 1
                row = row_for(product, review, fetched_at)
                if row["original_url_display"]:
                    rows.append(row)
                    summary["image_rows"] = int(summary["image_rows"]) + 1
        summaries.append(summary)
        if index % 100 == 0 or index == len(products_to_scan):
            print(f"product={index}/{len(products_to_scan)} id={product_id(product)} reviews={summary['reviews_seen']} rows={len(rows)}", flush=True)
    summary = {
        "site": SOURCE_SITE,
        "retailer": "fashionpass_com",
        "adapter": "fashionpass_lead_neighborhood_review_api" if not full_catalog else "fashionpass_full_catalog_review_api",
        "product_sources": [source],
        "products_discovered": len(products),
        "products_scanned": len(products_to_scan),
        "products_excluded_from_output": sum(1 for product in products_to_scan if skip_reason(product)),
        "review_products_scanned": review_products_scanned,
        "review_pages_scanned": review_products_scanned,
        "reviews_seen": reviews_seen,
        "reviews_with_images_seen": reviews_with_images,
        "exhaustive_review_paging": bool(full_catalog and limit_catalog_pages is None and limit_products is None),
        "product_summaries": summaries,
        "started_at": started_at,
        "finished_at": now_iso(),
    }
    return rows, summary


def dedupe_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        key = (row.get("id"), row.get("original_url_display"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def enrich_summary(summary: Dict[str, object], rows: Sequence[Dict[str, str]]) -> Dict[str, object]:
    urls = {row.get("product_page_url_display") or row.get("monetized_product_url_display") for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display")}
    summary.update({
        "rows_written": len(rows),
        "distinct_reviews": len({row.get("id") for row in rows if row.get("id")}),
        "distinct_images": len({row.get("original_url_display") for row in rows if row.get("original_url_display")}),
        "rows_with_distinct_product_url": len(urls),
        "rows_with_product_url": sum(1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display")),
        "rows_with_customer_image": sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image"),
        "rows_with_customer_ordered_size": sum(1 for row in rows if row.get("size_display") and row.get("size_display").lower() != "unknown"),
        "rows_with_any_measurement": sum(1 for row in rows if has_measurement(row)),
        "rows_supabase_qualified": sum(1 for row in rows if is_qualified(row)),
        "output_csv": str(OUTPUT_CSV),
        "summary_json": str(SUMMARY_JSON),
    })
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    limit_catalog_pages = None
    limit_products = None
    full_catalog = "--full-catalog" in argv
    if "--limit-catalog-pages" in argv:
        limit_catalog_pages = int(argv[argv.index("--limit-catalog-pages") + 1])
    if "--limit-products" in argv:
        limit_products = int(argv[argv.index("--limit-products") + 1])
    try:
        rows, summary = scrape(limit_catalog_pages=limit_catalog_pages, limit_products=limit_products, full_catalog=full_catalog)
    except BlockedScrapeError as exc:
        print(f"Stopping on blocked response: {exc}", file=sys.stderr)
        return 2
    rows = dedupe_rows(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    summary = enrich_summary(summary, rows)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    keys = ["products_discovered", "products_scanned", "products_excluded_from_output", "review_products_scanned", "reviews_seen", "reviews_with_images_seen", "rows_written", "distinct_reviews", "distinct_images", "rows_with_distinct_product_url", "rows_with_customer_image", "rows_with_customer_ordered_size", "rows_with_any_measurement", "rows_supabase_qualified"]
    print(json.dumps({key: summary[key] for key in keys}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
