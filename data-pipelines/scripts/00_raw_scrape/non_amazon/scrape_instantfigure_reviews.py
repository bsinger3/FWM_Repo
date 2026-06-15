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
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = legacy_raw_run_dir("instantfigure_com")
OUTPUT_CSV = OUTPUT_DIR / "instantfigure_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "instantfigure_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://instantfigure.com"
SOURCE_SITE = f"{SITE_ROOT}/"
SHOP_DOMAIN = "instantfigureinc.myshopify.com"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
TARGETBAY_REVIEW_WIDGET_URL = "https://app.targetbay.com/api/v1/webhooks/review-widget"
TARGETBAY_API_KEY = "085dd51f-5593-4225-8cf2-a5ddbe8a3886"
BRAND = "InstantFigure"
PRODUCTS_PER_PAGE = 250
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
    r"(?:size\s*)?(xxs|xs|small|s|medium|m|large|l|xl|xlarge|x-large|xxl|2xl|2x|3xl|3x|"
    r"4xl|4x|5xl|5x|6xl|6x|\d{1,2}(?:-\d{1,2})?)\b",
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
            if isinstance(exc, HTTPError) and exc.code == 429:
                time.sleep(min(30 * (attempt + 1), 120))
                continue
            if isinstance(exc, HTTPError) and exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
        time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"Failed text request for {url}: {last_error}")


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, referer: str = SOURCE_SITE) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    return json.loads(fetch_text(query_url, referer=referer))


def product_url_for(product: Dict[str, object]) -> str:
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else norm(product.get("_url"))


def canonical_product_url(url: object) -> str:
    text = norm(url)
    if text.startswith("//"):
        text = "https:" + text
    if text.startswith("/"):
        text = urljoin(SITE_ROOT, text)
    if not text:
        return ""
    parsed = urlparse(text)
    return f"{SITE_ROOT}{parsed.path.rstrip('/')}" if parsed.path else SITE_ROOT


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

    sitemap_urls: List[str] = []
    try:
        sitemap_index = fetch_text(SITEMAP_URL)
        product_sitemaps = [
            html.unescape(match)
            for match in re.findall(r"<loc>(https://instantfigure\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index, re.I)
        ]
        for sitemap_url in product_sitemaps:
            text = fetch_text(sitemap_url)
            urls = sorted(set(re.findall(r"https://instantfigure\.com/products/[^<\s\"']+", text, re.I)))
            urls = [canonical_product_url(html.unescape(url)) for url in urls]
            sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
            sitemap_urls.extend(urls)
    except Exception as exc:  # noqa: BLE001
        sources.append({"source": "product_sitemap", "url": SITEMAP_URL, "count": 0, "error": str(exc)})

    by_url = {canonical_product_url(product_url_for(product)): product for product in products if product_url_for(product)}
    missing = [url for url in sorted(set(sitemap_urls)) if url not in by_url]
    if limit_products is not None:
        missing = missing[: max(0, limit_products - len(by_url))]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {"id": "", "handle": handle, "title": handle.replace("-", " ").title(), "product_type": "", "body_html": "", "variants": [], "_url": url}
    sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)})
    out = list(by_url.values())
    if limit_products:
        out = out[:limit_products]
    return out, sources


def maybe_number_text(value: Optional[float]) -> str:
    if value is None:
        return ""
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def first_numeric_match(pattern: re.Pattern[str], text: str, max_value: Optional[float] = None) -> Tuple[str, Optional[float]]:
    match = pattern.search(text)
    if not match:
        return "", None
    raw_value = next((group for group in match.groups() if group), "")
    if not raw_value:
        return "", None
    value = float(raw_value)
    if max_value is not None and value > max_value:
        return "", None
    return norm(match.group(0)), value


def parse_height_inches(text: str) -> Tuple[str, Optional[float]]:
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


def extract_bra_size(text: str) -> Tuple[str, str]:
    match = BRA_SIZE_RE.search(text)
    if not match:
        return "", ""
    raw = norm(match.group(1)).upper().replace(" ", "")
    band = re.match(r"\d+", raw)
    cup = re.search(r"[A-Z]+$", raw)
    return (band.group(0) if band else "", cup.group(0) if cup else "")


def normalize_size(value: object) -> str:
    text = norm(value).upper().replace("X-LARGE", "XL").replace("X-SMALL", "XS")
    aliases = {"SMALL": "S", "MEDIUM": "M", "LARGE": "L", "2XL": "2X", "3XL": "3X", "4XL": "4X", "XXL": "2X", "XXXL": "3X"}
    return aliases.get(text, text)


def extract_size(text: str, variant: str) -> str:
    for source in [variant, text]:
        match = SIZE_RE.search(source)
        if match:
            return normalize_size(match.group(1))
    return ""


def variant_titles(product: Dict[str, object]) -> List[str]:
    titles: List[str] = []
    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants[:250]:
            if isinstance(variant, dict):
                title = norm(variant.get("title"))
                if title and title.lower() != "default title" and title not in titles:
                    titles.append(title)
    return titles


def split_color_from_variant(variant: str) -> Tuple[str, str]:
    parts = [norm(part) for part in variant.split("/") if norm(part)]
    color = parts[0] if parts else ""
    return color.lower(), color


def classify_clothing_type(product: Dict[str, object], title: str) -> str:
    value = f"{title} {product.get('product_type') or ''}".lower()
    if any(term in value for term in ["bag", "tote", "accessor", "jewelry"]):
        return ""
    if any(term in value for term in ["legging", "pant", "jean"]):
        return "pants"
    if "short" in value:
        return "shorts"
    if "skirt" in value:
        return "skirt"
    if "dress" in value:
        return "dress"
    if "bra" in value or "bandeau" in value:
        return "bra"
    if any(term in value for term in ["top", "tank", "shirt", "camisole"]):
        return "top"
    if "shapewear" in value or "bodysuit" in value:
        return "shapewear"
    return norm(product.get("product_type")).lower()


def output_skip_reason(product: Dict[str, object]) -> str:
    title = norm(product.get("title")).lower()
    product_type = norm(product.get("product_type")).lower()
    value = f"{title} {product_type}"
    if "gift card" in value:
        return "out_of_scope_gift_card"
    if product_type in {"accessories", "accessory", "bag", "bags", "jewelry"}:
        return "out_of_scope_accessory"
    accessory_terms = [
        "bag", "tote", "handbag", "necklace", "earring", "bracelet", "belt", "bowtie", "bow tie",
        "cummerbund", "hanky", "hat", "necktie", "tie bar", "sock", "stocking", "hosiery",
    ]
    if any(term in title for term in accessory_terms):
        return "out_of_scope_accessory"
    if any(term in value for term in ["men's", "mens", " man ", " boy", "boys", "kids", "child", "prodogg", "dog"]):
        return "out_of_scope_non_womens"
    support_terms = [
        "face mask", "wrist", "knee", "elbow", "forearm", "ankle", "chin strap", "gun holder",
        "bulletproof", "tactical", "medical", "post-surgical", "post surgical", "compression sleeve",
        "arm sleeve", "leg sleeve", "strap",
    ]
    if any(term in value for term in support_terms):
        return "out_of_scope_non_clothing_support"
    return ""


def targetbay_params(product: Dict[str, object], page: int = 1) -> Dict[str, object]:
    product_url = product_url_for(product)
    image_url = ""
    images = product.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            image_url = norm(first.get("src"))
    return {
        "shop": SHOP_DOMAIN,
        "index_name": TARGETBAY_API_KEY,
        "product_id": product.get("id") or "",
        "product_name": norm(product.get("title")),
        "user_id": "12345",
        "user_name": "anonymous",
        "user_email": "anonymous",
        "qaDisplay": "1",
        "product_url": urlparse(product_url).path,
        "product_image_url": image_url,
        "review_sort_by": "recent",
        "qa_sort_by": "recent",
        "pinned": "1",
        "productreviewpage": page,
    }


def split_targetbay_cards(content: str) -> List[str]:
    return re.split(r'<div class="targetbay_reviews_tgb_review_list tb-review-list-item">', content or "")[1:]


def first_text(card: str, pattern: str) -> str:
    match = re.search(pattern, card, re.I | re.S)
    return strip_tags(match.group(1)) if match else ""


def customer_picture_urls(card: str) -> List[str]:
    urls: List[str] = []
    for url in re.findall(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)["\']', card, re.I | re.S):
        url = html.unescape(norm(url))
        if not url or "no-image" in url.lower():
            continue
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("/"):
            url = urljoin("https://app.targetbay.com", url)
        if "targetbay.com" not in url and "tb-list.com" not in url and "cdn" not in url:
            continue
        if url not in urls:
            urls.append(url)
    return urls


def review_id_from_card(card: str, fallback: str) -> str:
    matches = re.findall(r"tbSiteVoting\('[^']+','([^']+)'", card)
    if matches:
        return matches[0]
    match = re.search(r"review_id[\"'=:\s]+([A-Za-z0-9_-]+)", card)
    return match.group(1) if match else fallback


def build_search_fts(parts: Sequence[str]) -> str:
    return norm(" ".join(part for part in parts if part))


def parse_review_rows(card: str, product: Dict[str, object], fetched_at: str, fallback_index: int) -> List[Dict[str, str]]:
    picture_urls = customer_picture_urls(card)
    if not picture_urls:
        return []
    product_url = product_url_for(product)
    product_title = norm(product.get("title"))
    reviewer_name = first_text(card, r'popup-client-head-name[^>]*>.*?<b[^>]*>(.*?)</b>')
    raw_date = first_text(card, r'product-date-readable[^>]*>\s*(.*?)\s*</p>')
    title = first_text(card, r'reviews-product-page-reviews-title["\'][^>]*>\s*<b[^>]*>(.*?)</b>')
    body = first_text(card, r'reviews-product-page-reviews-content["\'][^>]*>\s*(.*?)\s*</p>')
    text_pool = norm(" ".join([title, body]))
    review_id = review_id_from_card(card, f"{product.get('id')}-{fallback_index}")
    variant = ""

    height_raw, height_in = parse_height_inches(text_pool)
    weight_raw, weight_lbs = first_numeric_match(WEIGHT_RE, text_pool, max_value=700)
    waist_raw, waist_in = first_numeric_match(WAIST_RE, text_pool, max_value=90)
    hips_raw, hips_in = first_numeric_match(HIPS_RE, text_pool, max_value=90)
    bust_raw, bust_in = first_numeric_match(BUST_RE, text_pool, max_value=70)
    age_raw, age_years = parse_age(text_pool)
    _inseam_raw, inseam_in = first_numeric_match(INSEAM_RE, text_pool, max_value=45)
    bra_band, cupsize = extract_bra_size(text_pool)
    color_canonical, color_display = split_color_from_variant(variant)
    size_display = extract_size(text_pool, variant)
    product_description = strip_tags(product.get("body_html") or product.get("description") or "")
    product_detail = norm(" | ".join(variant_titles(product)))
    clothing_type = classify_clothing_type(product, product_title)

    rows: List[Dict[str, str]] = []
    for index, picture_url in enumerate(picture_urls, start=1):
        rows.append(
            {
                "created_at_display": "",
                "id": f"{review_id}-{index}",
                "original_url_display": picture_url,
                "product_page_url_display": product_url,
                "monetized_product_url_display": "",
                "height_raw": height_raw,
                "weight_raw": weight_raw,
                "user_comment": text_pool,
                "date_review_submitted_raw": raw_date,
                "height_in_display": maybe_number_text(height_in),
                "review_date": raw_date,
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
                "waist_in": maybe_number_text(waist_in),
                "hips_in_display": maybe_number_text(hips_in),
                "age_years_display": age_years,
                "search_fts": build_search_fts([BRAND, product_title, product_description, title, body]),
                "weight_display_display": maybe_number_text(weight_lbs),
                "weight_raw_needs_correction": "",
                "clothing_type_id": clothing_type,
                "reviewer_profile_url": "",
                "reviewer_name_raw": reviewer_name,
                "inseam_inches_display": maybe_number_text(inseam_in),
                "color_canonical": color_canonical,
                "color_display": color_display,
                "size_display": size_display,
                "bust_in_number_display": bra_band or maybe_number_text(bust_in),
                "cupsize_display": cupsize,
                "weight_lbs_display": maybe_number_text(weight_lbs),
                "weight_lbs_raw_issue": "",
                "product_title_raw": product_title,
                "product_subtitle_raw": "",
                "product_description_raw": product_description,
                "product_detail_raw": product_detail,
                "product_category_raw": norm(product.get("product_type")),
                "product_variant_raw": variant,
            }
        )
    return rows


def fetch_product_reviews(product: Dict[str, object], fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    product_url = product_url_for(product)
    meta: Dict[str, object] = {
        "product_id": product.get("id"),
        "product_title": product.get("title"),
        "product_type": product.get("product_type"),
        "product_url": product_url,
        "review_count_hint": 0,
        "review_pages_scanned": 0,
        "matching_review_images": 0,
        "adapter_used": "targetbay_review_widget",
        "errors": [],
    }
    if not product.get("id"):
        meta["errors"] = ["missing_product_id"]
        return [], meta

    rows: List[Dict[str, str]] = []
    try:
        payload = fetch_json(TARGETBAY_REVIEW_WIDGET_URL, targetbay_params(product, page=1), referer=product_url)
        content = str(payload.get("content") or "")
        meta["review_pages_scanned"] = 1
        count_match = re.search(r"Reviews\s*\((\d+)\)", strip_tags(content), re.I)
        if count_match:
            meta["review_count_hint"] = int(count_match.group(1))
        cards = split_targetbay_cards(content)
        for index, card in enumerate(cards, start=1):
            rows.extend(parse_review_rows(card, product, fetched_at, index))
    except Exception as exc:  # noqa: BLE001
        meta["errors"] = [str(exc)]

    meta["matching_review_images"] = len(rows)
    return rows, meta


def dedupe_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        image_key = re.sub(r"([?&](?:w|width|auto|format)=[^&]+)", "", row.get("original_url_display", ""))
        key = (row.get("id", "").rsplit("-", 1)[0], image_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def scrape_reviews(limit_products: Optional[int] = None) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    fetched_at = now_iso()
    products, product_sources = fetch_products(limit_products=limit_products)
    rows: List[Dict[str, str]] = []
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": "instantfigure_com",
        "adapter": "targetbay_product_level_review_widget",
        "shop_domain": SHOP_DOMAIN,
        "started_at": fetched_at,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": 0,
        "products_excluded_from_output": 0,
        "products_with_review_rows": 0,
        "review_pages_scanned": 0,
        "product_review_count_hint": 0,
        "exhaustive_review_paging": True,
        "product_level_required": True,
        "aggregate_only": False,
        "access_policy": "public_product_and_review_pages_only; restricted_or_unavailable_pages_are_skipped; polite_retries",
        "measurement_extraction": "deterministic_regex_and_provider_fields_only",
        "product_summaries": [],
        "errors": [],
    }

    for index, product in enumerate(products, start=1):
        product_rows, meta = fetch_product_reviews(product, fetched_at)
        skip_reason = output_skip_reason(product)
        summary["products_scanned"] = int(summary["products_scanned"]) + 1
        summary["review_pages_scanned"] = int(summary["review_pages_scanned"]) + int(meta.get("review_pages_scanned") or 0)
        summary["product_review_count_hint"] = int(summary["product_review_count_hint"]) + int(meta.get("review_count_hint") or 0)
        if skip_reason:
            summary["products_excluded_from_output"] = int(summary["products_excluded_from_output"]) + 1
        if product_rows and not skip_reason:
            summary["products_with_review_rows"] = int(summary["products_with_review_rows"]) + 1
            rows.extend(product_rows)
        if meta.get("errors"):
            summary["errors"].append({"product_url": product_url_for(product), "errors": meta["errors"]})
        summary["product_summaries"].append(
            {
                "product_index": index,
                **meta,
                "rows": 0 if skip_reason else len(product_rows),
                "skipped_from_output": bool(skip_reason),
                "skip_reason": skip_reason,
            }
        )
        note = f" skipped={skip_reason}" if skip_reason else ""
        print(
            f"[product {index}/{len(products)}] pages={meta.get('review_pages_scanned')} "
            f"hint={meta.get('review_count_hint')} rows={0 if skip_reason else len(product_rows)} "
            f"url={product_url_for(product)}{note}",
            flush=True,
        )

    summary["finished_at"] = now_iso()
    return dedupe_rows(rows), summary


def write_csv(rows: Sequence[Dict[str, str]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in HEADERS})


def has_product_url(row: Dict[str, str]) -> bool:
    return bool(row.get("product_page_url_display") or row.get("monetized_product_url_display"))


def has_measurement(row: Dict[str, str]) -> bool:
    return any(
        row.get(key)
        for key in [
            "height_in_display", "weight_display_display", "weight_lbs_display", "bust_in_number_display",
            "hips_in_display", "waist_in", "inseam_inches_display",
        ]
    )


def is_supabase_qualified(row: Dict[str, str]) -> bool:
    return bool(has_product_url(row) and has_measurement(row) and row.get("original_url_display") and row.get("size_display") and row.get("size_display") != "unknown")


def enrich_summary(summary: Dict[str, object], rows: Sequence[Dict[str, str]], output_csv: Path) -> Dict[str, object]:
    product_urls = {row.get("product_page_url_display") or row.get("monetized_product_url_display") for row in rows if has_product_url(row)}
    qualified_reviews = {row.get("id", "").rsplit("-", 1)[0] for row in rows if row.get("id") and is_supabase_qualified(row)}
    summary.update(
        {
            "output_csv": str(output_csv),
            "rows_written": len(rows),
            "distinct_reviews": len({row.get("id", "").rsplit("-", 1)[0] for row in rows if row.get("id")}),
            "distinct_images": len({row.get("original_url_display") for row in rows if row.get("original_url_display")}),
            "distinct_product_urls": len(product_urls),
            "distinct_products": len(product_urls),
            "rows_with_distinct_product_url": sum(1 for row in rows if has_product_url(row)),
            "rows_with_product_url": sum(1 for row in rows if has_product_url(row)),
            "rows_missing_product_url": sum(1 for row in rows if not has_product_url(row)),
            "rows_with_customer_image": sum(1 for row in rows if row.get("original_url_display")),
            "rows_with_image_url": sum(1 for row in rows if row.get("original_url_display")),
            "rows_missing_image_url": sum(1 for row in rows if not row.get("original_url_display")),
            "rows_with_user_comment": sum(1 for row in rows if row.get("user_comment")),
            "rows_with_size": sum(1 for row in rows if row.get("size_display")),
            "rows_with_customer_ordered_size": sum(1 for row in rows if row.get("size_display")),
            "rows_with_any_measurement": sum(1 for row in rows if has_measurement(row)),
            "rows_supabase_qualified": sum(1 for row in rows if is_supabase_qualified(row)),
            "distinct_qualified_reviews": len(qualified_reviews),
            "rows_with_image_and_product_url": sum(1 for row in rows if row.get("original_url_display") and has_product_url(row)),
            "rows_with_image_product_and_measurement": sum(1 for row in rows if row.get("original_url_display") and has_product_url(row) and has_measurement(row)),
            "rows_with_image_product_size_and_measurement": sum(1 for row in rows if is_supabase_qualified(row)),
            "rows_with_image_product_and_user_comment": sum(1 for row in rows if row.get("original_url_display") and has_product_url(row) and row.get("user_comment")),
            "rows_with_product_context": sum(1 for row in rows if row.get("product_title_raw")),
        }
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    limit_products: Optional[int] = None
    if "--limit-products" in argv:
        idx = argv.index("--limit-products")
        limit_products = int(argv[idx + 1])

    rows, summary = scrape_reviews(limit_products=limit_products)
    summary = enrich_summary(summary, rows, OUTPUT_CSV)
    write_csv(rows, OUTPUT_CSV)
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
