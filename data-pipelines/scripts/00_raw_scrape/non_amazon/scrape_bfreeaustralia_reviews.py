#!/usr/bin/env python3
from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = legacy_raw_run_dir("bfreeaustralia_com")
OUTPUT_CSV = OUTPUT_DIR / "bfreeaustralia_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "bfreeaustralia_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://www.bfreeaustralia.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
STAMPED_REVIEWS_URL = "https://stamped.io/api/widget/reviews"
STAMPED_STORE_URL = "www.bfreeaustralia.com"
STAMPED_API_KEY = "pubkey-503131bs4fsU32W9jva35iQ3LeZitu"
STAMPED_STORE_ID = "6990"
STAMPED_PHOTO_BASE = "https://cdn1.stamped.io/uploads/photos/"
BRAND = "B Free Australia"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

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
WAIST_RE = re.compile(r"\b(?:waist\s*(?:is|:)?\s*(\d{2,3}(?:\.\d+)?)|(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist)\b", re.I)
HIPS_RE = re.compile(r"\b(?:hips?\s*(?:are|is|:)?\s*(\d{2,3}(?:\.\d+)?)|(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?)\b", re.I)
BUST_RE = re.compile(r"\b(?:(?:bust|chest)\s*(?:is|:)?\s*(\d{2,3}(?:\.\d+)?)|(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*(?:bust|chest))\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*inseam\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
BRA_SIZE_RE = re.compile(r"\b((?:2[8-9]|3[0-9]|4[0-9]|5[0-4])\s*(?:aaa|aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k))\b", re.I)
SIZE_RE = re.compile(
    r"\b(?:ordered|bought|purchased|got|wearing|wore|in a|size|sz)\s+(?:a\s+|an\s+|the\s+|my\s+)?"
    r"(?:size\s*)?(xxs|xs|small|s|medium|m|large|l|xl|xlarge|x-large|xxl|2xl|2x|3xl|3x|4xl|4x|5xl|5x|6xl|6x|"
    r"\d{1,2}(?:-\d{1,2})?)\b",
    re.I,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(value: object) -> str:
    return WS_RE.sub(" ", str(value or "").replace("\xa0", " ")).strip()


def strip_tags(value: object) -> str:
    text = re.sub(r"</p\s*>|<br\s*/?>|</li\s*>", " ", str(value or ""), flags=re.I)
    return norm(html.unescape(TAG_RE.sub(" ", text)))


def fetch_text(url: str, retries: int = 6, referer: str = SOURCE_SITE) -> str:
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
            with urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", "replace")
        except (HTTPError, URLError) as exc:
            last_error = exc
            if isinstance(exc, HTTPError) and exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
            if isinstance(exc, HTTPError) and exc.code == 429:
                time.sleep(min(10 * (attempt + 1), 60))
                continue
        time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"Failed text request for {url}: {last_error}")


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, referer: str = SOURCE_SITE) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    return json.loads(fetch_text(query_url, referer=referer))


def product_url_for(product: Dict[str, object]) -> str:
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else norm(product.get("_url"))


def canonical_product_url(url: object, fallback: str = "") -> str:
    text = norm(url)
    if text.startswith("//"):
        text = "https:" + text
    if text.startswith("/"):
        text = urljoin(SITE_ROOT, text)
    if not text:
        text = fallback
    text = re.sub(r"^https://www\.bfreeaustralia\.com\.au", SITE_ROOT, text)
    text = re.sub(r"^https://bfreeaustralia\.com", SITE_ROOT, text)
    return text.split("?", 1)[0].rstrip("/")


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

    sitemap_product_urls: List[str] = []
    try:
        sitemap_index = fetch_text(SITEMAP_URL)
        sitemap_urls = [
            html.unescape(url)
            for url in re.findall(r"<loc>(https://www\.bfreeaustralia\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index)
        ]
        for sitemap_url in sitemap_urls:
            text = fetch_text(sitemap_url)
            urls = sorted(set(re.findall(r"https://www\.bfreeaustralia\.com/products/[^<\s\"']+", text)))
            urls = [canonical_product_url(html.unescape(url)) for url in urls]
            sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
            sitemap_product_urls.extend(urls)
    except Exception as exc:  # noqa: BLE001
        sources.append({"source": "product_sitemap", "error": str(exc), "count": 0})

    by_url: Dict[str, Dict[str, object]] = {canonical_product_url(product_url_for(product)): product for product in products if product_url_for(product)}
    missing = [url for url in sorted(set(sitemap_product_urls)) if url not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {"id": "", "handle": handle, "title": handle.replace("-", " ").title(), "product_type": "", "body_html": "", "variants": [], "_url": url}
    sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)})
    out = list(by_url.values())
    if limit_products:
        out = out[:limit_products]
    return out, sources


def stamped_params(product: Dict[str, object], page: int) -> Dict[str, object]:
    return {
        "productId": product.get("id"),
        "apiKey": STAMPED_API_KEY,
        "sId": STAMPED_STORE_ID,
        "page": page,
        "take": REVIEWS_PER_PAGE,
        "sortReviews": "recent",
        "storeUrl": STAMPED_STORE_URL,
    }


def photo_urls(review: Dict[str, object]) -> List[str]:
    value = norm(review.get("reviewUserPhotos"))
    urls: List[str] = []
    if value:
        for part in re.split(r"[,|]", value):
            part = norm(part)
            if not part:
                continue
            url = part if part.startswith("http") else STAMPED_PHOTO_BASE + part.lstrip("/")
            if url not in urls:
                urls.append(url)
    for key in ["reviewUserPhoto", "photoUrl", "imageUrl"]:
        value = norm(review.get(key))
        if value and value not in urls:
            urls.append(value if value.startswith("http") else STAMPED_PHOTO_BASE + value.lstrip("/"))
    return urls


def fetch_product_reviews(product: Dict[str, object], limit_pages: Optional[int] = None) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    product_url = product_url_for(product)
    meta: Dict[str, object] = {
        "product_url": product_url,
        "product_title": product.get("title"),
        "adapter_used": "stamped_product_level",
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "matching_review_images": 0,
        "errors": [],
    }
    if not product.get("id"):
        meta["errors"].append("missing_shopify_product_id")
        return [], meta

    reviews: List[Dict[str, object]] = []
    seen = set()
    total = 0
    page = 1
    while True:
        if limit_pages is not None and page > limit_pages:
            break
        try:
            payload = fetch_json(STAMPED_REVIEWS_URL, stamped_params(product, page), referer=product_url)
        except Exception as exc:  # noqa: BLE001
            meta["errors"].append(str(exc))
            break
        page_reviews = [item for item in payload.get("data", []) if isinstance(item, dict)]
        total = int(payload.get("total") or total or 0)
        if not page_reviews:
            break
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"]) + 1
        for review in page_reviews:
            review_id = norm(review.get("id"))
            if review_id and review_id in seen:
                continue
            seen.add(review_id)
            reviews.append(review)
        if len(page_reviews) < REVIEWS_PER_PAGE:
            break
        page += 1
        if total and page > math.ceil(total / REVIEWS_PER_PAGE):
            break
    meta["review_count_hint"] = total
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
    value_text = next((group for group in match.groups() if group), "")
    if not value_text:
        return "", None
    value = float(value_text)
    if max_value is not None and value > max_value:
        return "", None
    return norm(match.group(0)), value


def parse_height(text: str) -> Tuple[str, Optional[float]]:
    match = HEIGHT_RE.search(text.replace("\u2018", "'").replace("\u2019", "'"))
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


def parse_bra_size(text: str) -> Tuple[str, str, str]:
    match = BRA_SIZE_RE.search(text)
    if not match:
        return "", "", ""
    raw = re.sub(r"\s+", "", match.group(1)).upper()
    band = re.match(r"\d+", raw)
    cup = re.search(r"[A-Z]+$", raw)
    return raw, band.group(0) if band else "", cup.group(0) if cup else ""


def normalize_size(value: object) -> str:
    text = norm(value).upper().replace(" ", "")
    aliases = {
        "SMALL": "S",
        "MEDIUM": "M",
        "LARGE": "L",
        "XLARGE": "XL",
        "X-LARGE": "XL",
        "XXL": "2XL",
        "2X": "2XL",
        "3X": "3XL",
        "4X": "4XL",
        "5X": "5XL",
        "6X": "6XL",
    }
    return aliases.get(text, text)


def extract_size(review: Dict[str, object], text: str) -> Tuple[str, str, str]:
    option_text = " ".join(norm(value) for key, value in review.items() if key.lower().startswith("reviewoption") and norm(value))
    bra_raw, band, cup = parse_bra_size(" ".join([option_text, text]))
    if bra_raw:
        return bra_raw, band, cup
    match = SIZE_RE.search(" ".join([option_text, text]))
    return (normalize_size(match.group(1)), "", "") if match else ("", "", "")


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
    if "bra" in value or "bralette" in value:
        return "bra"
    if any(term in value for term in ["brief", "underwear", "panty", "panties", "knicker", "shortie"]):
        return "underwear"
    if any(term in value for term in ["pyjama", "pajama", "sleep", "nightie", "nightdress"]):
        return "sleepwear"
    if any(term in value for term in ["top", "tank", "cami", "singlet"]):
        return "top"
    if any(term in value for term in ["legging", "shorts", "pants"]):
        return "pants"
    if "dress" in value:
        return "dress"
    if "swim" in value:
        return "swimwear"
    return norm(product.get("product_type")).lower()


def output_skip_reason(product: Dict[str, object]) -> str:
    title_type = f"{product.get('title') or ''} {product.get('handle') or ''} {product.get('product_type') or ''}".lower()
    value = f"{title_type} {' '.join(product.get('tags') or []) if isinstance(product.get('tags'), list) else ''}".lower()
    if "gift card" in value:
        return "out_of_scope_gift_card"
    if "free gift" in title_type:
        return "out_of_scope_free_gift"
    if "returns" in title_type or "exchanges" in title_type:
        return "out_of_scope_returns"
    if "baby" in title_type or "babysuit" in title_type or "kids" in title_type:
        return "out_of_scope_baby_or_kids"
    if "shipping protection" in value or "insurance" in value:
        return "out_of_scope_shipping_protection"
    if "gift wrapping" in title_type:
        return "out_of_scope_gift_wrap"
    if "stick on bra" in title_type:
        return "out_of_scope_accessory_or_hosiery"
    if re.search(
        r"\b("
        r"nipple covers?|breast lift|cleavage booster|bra pads?|butt shaper pads?|hip boosters?|booty pads?|"
        r"body tape|shapewear straps?|boob tape|fashion tape|bra extender|bra strap|delicates washbag|"
        r"laundry bag|detergent|hanger|socks?|stockings?|pantyhose|tights|"
        r"reusable .*pads?|stay-dry .*pads?|sanitary pads?|incontinence pads?|lbl pads?|panty liners?|"
        r"herbal tea|relief tea|feminine balance|waist trimmer|waist trainer|waist cincher|corset belt|"
        r"support belt|sweat belt|butt lifting"
        r")\b",
        value,
    ):
        return "out_of_scope_accessory_or_hosiery"
    return ""


def row_for(product: Dict[str, object], review: Dict[str, object], image_url: str, image_index: int, fetched: str) -> Dict[str, str]:
    title = strip_tags(review.get("reviewTitle"))
    body = strip_tags(review.get("reviewMessage"))
    option_text = " ".join(norm(value) for key, value in review.items() if key.lower().startswith("reviewoption") and norm(value))
    text = norm(" ".join(part for part in [title, body, option_text] if part))
    height_raw, height_in = parse_height(text)
    weight_raw, weight = parse_num(WEIGHT_RE, text, 700)
    waist_raw, waist = parse_num(WAIST_RE, text, 90)
    hips_raw, hips = parse_num(HIPS_RE, text, 90)
    bust_raw, bust = parse_num(BUST_RE, text, 70)
    inseam_raw, inseam = parse_num(INSEAM_RE, text, 45)
    age_raw, age = parse_age(text)
    size_display, band, cup = extract_size(review, text)
    product_url = canonical_product_url("", product_url_for(product))
    product_title = norm(review.get("productName") or product.get("title"))
    review_id = norm(review.get("id")) or f"{product.get('id')}-{image_index}"
    review_date = norm(review.get("reviewDate"))
    return {
        "created_at_display": fetched,
        "id": f"stamped-{review_id}-{image_index}",
        "original_url_display": image_url,
        "product_page_url_display": product_url,
        "monetized_product_url_display": product_url,
        "height_raw": height_raw,
        "weight_raw": weight_raw,
        "user_comment": text,
        "date_review_submitted_raw": review_date,
        "height_in_display": maybe_num(height_in),
        "review_date": review_date,
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
        "search_fts": norm(" ".join([BRAND, product_title, strip_tags(product.get("body_html")), text])),
        "weight_display_display": maybe_num(weight),
        "weight_raw_needs_correction": "",
        "clothing_type_id": classify(product, review),
        "reviewer_profile_url": "",
        "reviewer_name_raw": norm(review.get("author")),
        "inseam_inches_display": maybe_num(inseam),
        "color_canonical": "",
        "color_display": "",
        "size_display": size_display,
        "bust_in_number_display": band or maybe_num(bust),
        "cupsize_display": cup,
        "weight_lbs_display": maybe_num(weight),
        "weight_lbs_raw_issue": "",
        "product_title_raw": product_title,
        "product_subtitle_raw": title,
        "product_description_raw": strip_tags(product.get("body_html")),
        "product_detail_raw": variant_detail(product),
        "product_category_raw": norm(product.get("product_type")),
        "product_variant_raw": "",
    }


def has_measurement(row: Dict[str, str]) -> bool:
    fields = ["height_in_display", "weight_lbs_display", "bust_in_number_display", "hips_in_display", "waist_in", "inseam_inches_display"]
    return any(norm(row.get(field)) for field in fields)


def has_product_url(row: Dict[str, str]) -> bool:
    return bool(norm(row.get("product_page_url_display") or row.get("monetized_product_url_display")))


def is_supabase_qualified(row: Dict[str, str]) -> bool:
    return bool(norm(row.get("original_url_display")) and has_product_url(row) and has_measurement(row) and norm(row.get("size_display")))


def dedupe_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
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
    workers = 6
    progress_every = 25
    if "--limit-products" in argv:
        limit_products = int(argv[argv.index("--limit-products") + 1])
    if "--limit-pages-per-product" in argv:
        limit_pages = int(argv[argv.index("--limit-pages-per-product") + 1])
    if "--workers" in argv:
        workers = int(argv[argv.index("--workers") + 1])
    if "--progress-every" in argv:
        progress_every = int(argv[argv.index("--progress-every") + 1])

    started = now_iso()
    products, product_sources = fetch_products(limit_products=limit_products)
    print(f"Discovered {len(products)} products")
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    total_pages = 0
    total_hint = 0
    products_excluded = 0
    fetched = now_iso()

    def scrape_product(idx_product: Tuple[int, Dict[str, object]]) -> Tuple[int, List[Dict[str, str]], Dict[str, object], int, int, int]:
        idx, product = idx_product
        reviews, meta = fetch_product_reviews(product, limit_pages=limit_pages)
        skip_reason = output_skip_reason(product)
        product_rows: List[Dict[str, str]] = []
        if not skip_reason:
            for review in reviews:
                for image_index, image_url in enumerate(photo_urls(review), start=1):
                    product_rows.append(row_for(product, review, image_url, image_index, fetched))
        summary = {
            "product_index": idx,
            "product_id": product.get("id"),
            "product_title": product.get("title"),
            "product_type": product.get("product_type"),
            "product_url": product_url_for(product),
            "review_count_hint": meta.get("review_count_hint"),
            "review_pages_scanned": meta.get("review_pages_scanned"),
            "matching_review_images": meta.get("matching_review_images"),
            "rows": len(product_rows),
            "errors": meta.get("errors"),
            "adapter_used": meta.get("adapter_used"),
            "skipped_from_output": bool(skip_reason),
            "skip_reason": skip_reason,
        }
        return idx, product_rows, summary, int(meta.get("review_pages_scanned") or 0), int(meta.get("review_count_hint") or 0), 1 if skip_reason else 0

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(scrape_product, item) for item in enumerate(products, start=1)]
        completed = 0
        for future in as_completed(futures):
            idx, product_rows, product_summary, pages, hint, excluded = future.result()
            rows.extend(product_rows)
            product_summaries.append(product_summary)
            total_pages += pages
            total_hint += hint
            products_excluded += excluded
            completed += 1
            status = f" skipped={product_summary['skip_reason']}" if product_summary.get("skip_reason") else ""
            if completed == len(products) or completed % max(1, progress_every) == 0 or product_summary.get("rows") or product_summary.get("skip_reason"):
                print(
                    f"[{completed}/{len(products)} done; product {idx}] {product_summary.get('product_title')} "
                    f"reviews={product_summary.get('review_count_hint')} pages={product_summary.get('review_pages_scanned')} "
                    f"rows={product_summary.get('rows')}{status}",
                    flush=True,
                )

    product_summaries.sort(key=lambda item: int(item.get("product_index") or 0))

    deduped = dedupe_rows(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(deduped)

    product_urls = {row.get("product_page_url_display") or row.get("monetized_product_url_display") for row in deduped if has_product_url(row)}
    summary = {
        "site": SITE_ROOT,
        "retailer": "bfreeaustralia_com",
        "adapter": "stamped_product_level",
        "stamped_store_url": STAMPED_STORE_URL,
        "stamped_api_key": STAMPED_API_KEY,
        "stamped_store_id": STAMPED_STORE_ID,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "products_excluded_from_output": products_excluded,
        "products_with_review_rows": sum(1 for item in product_summaries if item.get("rows")),
        "exhaustive_review_paging": limit_pages is None,
        "review_pages_scanned": total_pages,
        "product_review_count_hint": total_hint,
        "rows_written": len(deduped),
        "distinct_reviews": len({row["id"].rsplit("-", 1)[0] for row in deduped}),
        "distinct_images": len({re.sub(r"\?.*$", "", row["original_url_display"]) for row in deduped}),
        "distinct_product_urls": len(product_urls),
        "distinct_products": len(product_urls),
        "rows_with_distinct_product_url": sum(1 for row in deduped if has_product_url(row)),
        "rows_with_product_url": sum(1 for row in deduped if has_product_url(row)),
        "rows_missing_product_url": sum(1 for row in deduped if not has_product_url(row)),
        "rows_with_any_measurement": sum(1 for row in deduped if has_measurement(row)),
        "rows_with_customer_image": sum(1 for row in deduped if norm(row.get("original_url_display"))),
        "rows_with_customer_ordered_size": sum(1 for row in deduped if norm(row.get("size_display"))),
        "rows_with_size": sum(1 for row in deduped if norm(row.get("size_display"))),
        "rows_supabase_qualified": sum(1 for row in deduped if is_supabase_qualified(row)),
        "rows_with_image_product_and_measurement": sum(1 for row in deduped if norm(row.get("original_url_display")) and has_product_url(row) and has_measurement(row)),
        "rows_with_image_product_size_and_measurement": sum(1 for row in deduped if is_supabase_qualified(row)),
        "output_csv": str(OUTPUT_CSV),
        "summary_json": str(SUMMARY_JSON),
        "started_at": started,
        "finished_at": now_iso(),
        "product_summaries": product_summaries,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
