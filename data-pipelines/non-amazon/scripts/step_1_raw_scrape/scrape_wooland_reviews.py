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
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "wooland_com"
OUTPUT_CSV = OUTPUT_DIR / "wooland_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "wooland_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://wooland.com"
SOURCE_SITE = f"{SITE_ROOT}/"
SHOP_DOMAIN = "wool-and.myshopify.com"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
JUDGEME_WIDGET_URL = "https://api.judge.me/reviews/reviews_for_widget"
BRAND = "wool&"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

HEADERS = [
    "created_at_display",
    "id",
    "original_url_display",
    "product_page_url_display",
    "monetized_product_url_display",
    "height_raw",
    "weight_raw",
    "user_comment",
    "date_review_submitted_raw",
    "height_in_display",
    "review_date",
    "source_site_display",
    "status_code",
    "content_type",
    "bytes",
    "width",
    "height",
    "hash_md5",
    "fetched_at",
    "updated_at",
    "brand",
    "waist_raw_display",
    "hips_raw",
    "age_raw",
    "waist_in",
    "hips_in_display",
    "age_years_display",
    "search_fts",
    "weight_display_display",
    "weight_raw_needs_correction",
    "clothing_type_id",
    "reviewer_profile_url",
    "reviewer_name_raw",
    "inseam_inches_display",
    "color_canonical",
    "color_display",
    "size_display",
    "bust_in_number_display",
    "cupsize_display",
    "weight_lbs_display",
    "weight_lbs_raw_issue",
    "product_title_raw",
    "product_subtitle_raw",
    "product_description_raw",
    "product_detail_raw",
    "product_category_raw",
    "product_variant_raw",
]

TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
HEIGHT_RE = re.compile(r"\b([4-6])\s*(?:ft|feet|foot|['\u2019])\s*(\d{1,2})?\s*(?:in|inches|[\"\u201d])?", re.I)
WEIGHT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?|#)\b", re.I)
WAIST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b", re.I)
HIPS_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
BUST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*(?:bust|chest)\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*inseam\b", re.I)
BRA_SIZE_RE = re.compile(r"\b((?:2[8-9]|3[0-9]|4[0-8])\s*(?:aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k))\b", re.I)
SIZE_ORDER_RE = re.compile(
    r"\b(?:ordered|bought|purchased|got|wearing|wore|in a|size)\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:size\s*)?(xs|s|m|l|xl|1x|2x|3x|4x|5x|6x|7x|8x|xxs|xxl|xxxl|small|medium|large)\b",
    re.I,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_whitespace(text: object) -> str:
    return WHITESPACE_RE.sub(" ", str(text or "").replace("\xa0", " ")).strip()


def strip_tags(value: object) -> str:
    text = re.sub(r"</p\s*>|<br\s*/?>|</li\s*>", " ", str(value or ""), flags=re.I)
    return normalize_whitespace(html.unescape(TAG_RE.sub(" ", text)))


def fetch_text(url: str, retries: int = 8, referer: str = SOURCE_SITE) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/json,*/*",
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
                time.sleep(min(60 * (attempt + 1), 180))
                continue
            if isinstance(exc, HTTPError) and exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
        time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"Failed text request for {url}: {last_error}")


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, referer: str = SOURCE_SITE) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    return json.loads(fetch_text(query_url, referer=referer))


def product_url_for(product: Dict[str, object]) -> str:
    handle = normalize_whitespace(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def canonical_product_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("/"):
        url = urljoin(SITE_ROOT, url)
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return f"{SITE_ROOT}{path}" if path else SITE_ROOT


def fetch_products_from_json(limit_products: Optional[int] = None) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
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
    return products, sources


def product_urls_from_sitemap() -> Tuple[List[str], List[Dict[str, object]]]:
    sources: List[Dict[str, object]] = []
    urls: List[str] = []
    try:
        sitemap_index = fetch_text(SITEMAP_URL)
    except Exception as exc:  # noqa: BLE001
        sources.append({"source": "product_sitemap", "url": SITEMAP_URL, "count": 0, "error": str(exc)})
        return urls, sources
    sitemap_urls = [
        html.unescape(match)
        for match in re.findall(r"<loc>(https://wooland\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index, re.I)
    ]
    sitemap_urls = [url for url in sitemap_urls if "/en-gb/" not in url]
    for sitemap_url in sitemap_urls:
        try:
            text = fetch_text(sitemap_url)
        except Exception as exc:  # noqa: BLE001
            sources.append({"source": "product_sitemap", "url": sitemap_url, "count": 0, "error": str(exc)})
            continue
        page_urls = sorted(set(re.findall(r"https://wooland\.com/products/[^<\s\"']+", text, re.I)))
        page_urls = [canonical_product_url(html.unescape(url)) for url in page_urls]
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(page_urls)})
        urls.extend(page_urls)
    return sorted(set(urls)), sources


def fetch_missing_product(handle: str, fallback_url: str) -> Dict[str, object]:
    try:
        payload = fetch_json(f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}.json")
        product = payload.get("product")
        if isinstance(product, dict):
            return product
    except Exception:
        pass
    return {"id": "", "handle": handle, "title": handle.replace("-", " ").title(), "product_type": "", "body_html": "", "variants": [], "_url": fallback_url}


def discover_products(limit_products: Optional[int] = None) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products, product_sources = fetch_products_from_json(limit_products=limit_products)
    sitemap_urls, sitemap_sources = product_urls_from_sitemap()
    by_url: Dict[str, Dict[str, object]] = {canonical_product_url(product_url_for(product)): product for product in products if product_url_for(product)}
    missing_urls = [url for url in sitemap_urls if url not in by_url]
    if limit_products is not None:
        missing_urls = missing_urls[: max(0, limit_products - len(by_url))]
    for url in missing_urls:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = fetch_missing_product(handle, url)
    ordered = list(by_url.values())
    if limit_products is not None:
        ordered = ordered[:limit_products]
    product_sources.extend(sitemap_sources)
    product_sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing_urls)})
    return ordered, product_sources


def widget_params(product_id: object, page: int) -> Dict[str, object]:
    return {
        "url": "wooland.com",
        "shop_domain": SHOP_DOMAIN,
        "platform": "shopify",
        "per_page": REVIEWS_PER_PAGE,
        "page": page,
        "product_id": product_id,
        "sort_by": "with_pictures",
    }


def maybe_number_text(value: Optional[float]) -> str:
    if value is None:
        return ""
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def parse_numeric(pattern: re.Pattern[str], text: str, max_value: Optional[float] = None) -> Tuple[str, Optional[float]]:
    match = pattern.search(text)
    if not match:
        return "", None
    value = float(match.group(1))
    if max_value is not None and value > max_value:
        return "", None
    return normalize_whitespace(match.group(0)), value


def parse_height_inches(text: str) -> Tuple[str, Optional[float]]:
    match = HEIGHT_RE.search(text)
    if not match:
        return "", None
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    if 4 <= feet <= 7 and 0 <= inches <= 11:
        return normalize_whitespace(match.group(0)), feet * 12 + inches
    return "", None


def parse_age(text: str) -> Tuple[str, str]:
    match = AGE_RE.search(text)
    return (normalize_whitespace(match.group(0)), match.group(1) or match.group(2) or "") if match else ("", "")


def extract_bra_size(text: str) -> Tuple[str, str]:
    match = BRA_SIZE_RE.search(text)
    if not match:
        return "", ""
    raw = normalize_whitespace(match.group(1)).upper().replace(" ", "")
    band = re.match(r"\d+", raw)
    cup = re.search(r"[A-Z]+$", raw)
    return (band.group(0) if band else "", cup.group(0) if cup else "")


def normalize_size(value: object) -> str:
    text = normalize_whitespace(value).upper()
    aliases = {
        "SMALL": "S",
        "MEDIUM": "M",
        "LARGE": "L",
        "XXL": "2X",
        "XXXL": "3X",
    }
    return aliases.get(text, text)


def extract_wooland_size(custom_fields: Dict[str, str], text: str, variant: str) -> str:
    for key, value in custom_fields.items():
        if any(token in key.lower() for token in ["size", "fit"]):
            parts = [normalize_whitespace(part) for part in re.split(r"[|/]", value) if normalize_whitespace(part)]
            if parts:
                return normalize_size(parts[-1])
    for source in [variant, text]:
        match = SIZE_ORDER_RE.search(source)
        if match:
            return normalize_size(match.group(1))
    return ""


def attr_value(fragment: str, name: str) -> str:
    match = re.search(rf"\b{name}=(['\"])(.*?)\1", fragment, re.I | re.S)
    return html.unescape(match.group(2)) if match else ""


def text_for_class(fragment: str, class_name: str) -> str:
    match = re.search(
        rf"<[^>]*class=(['\"])[^'\"]*\b{re.escape(class_name)}\b[^'\"]*\1[^>]*>(.*?)</[^>]+>",
        fragment,
        re.I | re.S,
    )
    return strip_tags(match.group(2)) if match else ""


def split_review_cards(html_text: str) -> List[str]:
    html_text = html.unescape(html_text or "")
    starts = [match.start() for match in re.finditer(r"<div class='jdgm-rev\b|<div class=\"jdgm-rev\b", html_text, re.I)]
    cards: List[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(html_text)
        cards.append(html_text[start:end])
    return cards


def custom_fields_from_review(card: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for answer in re.findall(r"<div class='jdgm-rev__cf-ans'.*?</div>\s*</div>|<div class=\"jdgm-rev__cf-ans\".*?</div>\s*</div>", card, re.I | re.S):
        title = text_for_class(answer, "jdgm-rev__cf-ans__title")
        value = text_for_class(answer, "jdgm-rev__cf-ans__value")
        if title and value:
            fields[title.rstrip(":")] = value
    return fields


def customer_picture_urls(card: str) -> List[str]:
    urls: List[str] = []
    for raw in re.findall(r"(?:data-mfp-src|href|data-src|src)=(['\"])(.*?)\1", card, re.I | re.S):
        url = html.unescape(normalize_whitespace(raw[1]))
        if url.startswith("//"):
            url = "https:" + url
        if "judgeme.imgix.net" not in url:
            continue
        if url and url not in urls:
            urls.append(url)
    return urls


def variant_titles(product: Dict[str, object]) -> List[str]:
    titles: List[str] = []
    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants[:250]:
            if isinstance(variant, dict):
                title = normalize_whitespace(variant.get("title"))
                if title and title.lower() != "default title" and title not in titles:
                    titles.append(title)
    return titles


def split_color_from_variant(variant: str) -> Tuple[str, str]:
    parts = [normalize_whitespace(part) for part in variant.split("/") if normalize_whitespace(part)]
    color = parts[0] if parts else ""
    return color.lower(), color


def classify_clothing_type(product: Dict[str, object], title: str) -> str:
    value = f"{title} {product.get('product_type') or ''}".lower()
    if "gift card" in value or "credit" in value:
        return ""
    if any(term in value for term in ["legging", "capri", "pant"]):
        return "pants"
    if "short" in value or "skort" in value:
        return "shorts"
    if "swim" in value or "bikini" in value or "one-piece" in value or "rash guard" in value:
        return "swimwear"
    if "bra" in value:
        return "bra"
    if any(term in value for term in ["tank", "tee", "t-shirt", "shirt"]):
        return "top"
    if "dress" in value:
        return "dress"
    if any(term in value for term in ["sweater", "hoodie"]):
        return "outerwear"
    return normalize_whitespace(product.get("product_type")).lower()


def output_skip_reason(product: Dict[str, object]) -> str:
    title = normalize_whitespace(product.get("title")).lower()
    product_type = normalize_whitespace(product.get("product_type")).lower()
    value = f"{title} {product_type}"
    if "gift card" in value:
        return "out_of_scope_gift_card"
    if "exchange and return credit" in value:
        return "out_of_scope_store_credit"
    if product_type in {"accs", "accessories", "bag", "bags", "necklace", "earrings", "shoes", "shoe", "boots"}:
        return "out_of_scope_accessory"
    if any(term in title for term in ["necklace", "earrings", "handbag", "waist chain", "body chain", "sock", "beanie"]):
        return "out_of_scope_accessory"
    if any(term in value for term in [" for him", "men's", "mens", " boxer", "trunks"]):
        return "out_of_scope_non_womens"
    return ""


def product_for_review(product: Dict[str, object], review_product_url: str, by_url: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    return by_url.get(canonical_product_url(review_product_url)) or product


def build_search_fts(parts: Sequence[str]) -> str:
    return normalize_whitespace(" ".join(part for part in parts if part))


def parse_review_rows(card: str, product: Dict[str, object], by_url: Dict[str, Dict[str, object]], fetched_at: str) -> List[Dict[str, str]]:
    picture_urls = customer_picture_urls(card)
    if not picture_urls:
        return []
    review_id = normalize_whitespace(attr_value(card, "data-review-id"))
    product_url = canonical_product_url(attr_value(card, "data-product-url") or product_url_for(product))
    row_product = product_for_review(product, product_url, by_url)
    product_title = strip_tags(attr_value(card, "data-product-title") or row_product.get("title") or product.get("title") or "")
    reviewer_name = text_for_class(card, "jdgm-rev__author")
    timestamp_match = re.search(r"class=(['\"])[^'\"]*\bjdgm-rev__timestamp\b[^'\"]*\1[^>]*data-content=(['\"])(.*?)\2", card, re.I | re.S)
    timestamp = normalize_whitespace(html.unescape(timestamp_match.group(3))) if timestamp_match else ""
    review_date = timestamp.split(" ", 1)[0].split("T", 1)[0] if timestamp else ""
    title = text_for_class(card, "jdgm-rev__title")
    body = text_for_class(card, "jdgm-rev__body")
    custom_fields = custom_fields_from_review(card)
    custom_text = normalize_whitespace(" ".join(f"{key}: {value}" for key, value in custom_fields.items()))
    variant = text_for_class(card, "jdgm-rev__variant-label")
    text_pool = normalize_whitespace(" ".join([title, body, custom_text]))

    height_raw, height_in = parse_height_inches(text_pool)
    weight_raw, weight_lbs = parse_numeric(WEIGHT_RE, text_pool, max_value=700)
    waist_raw, waist_in = parse_numeric(WAIST_RE, text_pool, max_value=90)
    hips_raw, hips_in = parse_numeric(HIPS_RE, text_pool, max_value=90)
    bust_raw, bust_in = parse_numeric(BUST_RE, text_pool, max_value=70)
    age_raw, age_years = parse_age(text_pool)
    _inseam_raw, inseam_in = parse_numeric(INSEAM_RE, text_pool, max_value=45)
    bra_band, cupsize = extract_bra_size(text_pool)
    color_canonical, color_display = split_color_from_variant(variant)
    size_display = extract_wooland_size(custom_fields, text_pool, variant)
    product_description = strip_tags(row_product.get("body_html") or "")
    product_detail = normalize_whitespace(" | ".join(variant_titles(row_product)))
    clothing_type = classify_clothing_type(row_product, product_title)

    rows: List[Dict[str, str]] = []
    for index, picture_url in enumerate(picture_urls, start=1):
        rows.append(
            {
                "created_at_display": "",
                "id": f"{review_id}-{index}" if review_id else f"{abs(hash(picture_url))}-{index}",
                "original_url_display": picture_url,
                "product_page_url_display": product_url,
                "monetized_product_url_display": "",
                "height_raw": height_raw,
                "weight_raw": weight_raw,
                "user_comment": text_pool,
                "date_review_submitted_raw": timestamp,
                "height_in_display": maybe_number_text(height_in),
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
                "waist_in": maybe_number_text(waist_in),
                "hips_in_display": maybe_number_text(hips_in),
                "age_years_display": age_years,
                "search_fts": build_search_fts([BRAND, product_title, product_description, title, body, custom_text, variant]),
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
                "product_category_raw": normalize_whitespace(row_product.get("product_type")),
                "product_variant_raw": variant,
            }
        )
    return rows


def parse_cards_from_html(html_text: str, product: Dict[str, object], by_url: Dict[str, Dict[str, object]], fetched_at: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for card in split_review_cards(html_text):
        rows.extend(parse_review_rows(card, product, by_url, fetched_at))
    return rows


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


def scrape_reviews(limit_products: Optional[int] = None, limit_pages_per_product: Optional[int] = None) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    fetched_at = now_iso()
    products, product_sources = discover_products(limit_products=limit_products)
    by_url = {canonical_product_url(product_url_for(product)): product for product in products if product_url_for(product)}
    rows: List[Dict[str, str]] = []
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": "wooland_com",
        "adapter": "judge_me_reviews_for_widget_product_level",
        "shop_domain": SHOP_DOMAIN,
        "started_at": fetched_at,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": 0,
        "products_excluded_from_output": 0,
        "products_with_review_rows": 0,
        "review_pages_scanned": 0,
        "product_review_count_hint": 0,
        "exhaustive_review_paging": limit_pages_per_product is None,
        "product_level_required": True,
        "aggregate_only": False,
        "access_policy": "public_product_and_review_pages_only; restricted_or_unavailable_pages_are_skipped; polite_retries",
        "measurement_extraction": "deterministic_regex_and_provider_fields_only",
        "product_summaries": [],
        "errors": [],
    }

    for index, product in enumerate(products, start=1):
        product_id = product.get("id")
        product_url = product_url_for(product)
        product_rows: List[Dict[str, str]] = []
        skip_reason = output_skip_reason(product)
        page = 1
        pages_scanned = 0
        product_review_count_hint = 0
        errors: List[str] = []
        if product_id:
            while True:
                if limit_pages_per_product is not None and page > limit_pages_per_product:
                    break
                try:
                    payload = fetch_json(JUDGEME_WIDGET_URL, widget_params(product_id, page), referer=product_url or SOURCE_SITE)
                except Exception as exc:  # noqa: BLE001
                    errors.append(str(exc))
                    break

                html_text = str(payload.get("html") or "")
                page_rows = parse_cards_from_html(html_text, product, by_url, fetched_at)
                if not html_text or not page_rows and page > 1:
                    break
                total_count = int(payload.get("total_count") or product_review_count_hint or 0)
                product_review_count_hint = max(product_review_count_hint, total_count)
                pages_scanned += 1
                product_rows.extend(page_rows)

                page_numbers = [
                    int(match[1])
                    for match in re.findall(r"data-page=(['\"])(\d+)\1", html.unescape(html_text), re.I)
                ]
                total_pages = max(page_numbers) if page_numbers else 0
                if total_pages and page >= total_pages:
                    break
                if total_count and page * REVIEWS_PER_PAGE >= total_count:
                    break
                if not total_pages and len(page_rows) < REVIEWS_PER_PAGE:
                    break
                page += 1
        else:
            errors.append("missing_product_id")

        summary["products_scanned"] = int(summary["products_scanned"]) + 1
        summary["review_pages_scanned"] = int(summary["review_pages_scanned"]) + pages_scanned
        summary["product_review_count_hint"] = int(summary["product_review_count_hint"]) + product_review_count_hint
        if skip_reason:
            summary["products_excluded_from_output"] = int(summary["products_excluded_from_output"]) + 1
        if product_rows and not skip_reason:
            summary["products_with_review_rows"] = int(summary["products_with_review_rows"]) + 1
            rows.extend(product_rows)
        if errors:
            summary["errors"].append({"product_url": product_url, "errors": errors})
        summary["product_summaries"].append(
            {
                "product_index": index,
                "product_id": product_id,
                "product_title": product.get("title"),
                "product_type": product.get("product_type"),
                "product_url": product_url,
                "review_count_hint": product_review_count_hint,
                "review_pages_scanned": pages_scanned,
                "matching_review_images": len(product_rows),
                "rows": 0 if skip_reason else len(product_rows),
                "adapter_used": "judge_me_reviews_for_widget_product_level" if product_id else "missing-product-id",
                "skipped_from_output": bool(skip_reason),
                "skip_reason": skip_reason,
                "errors": errors,
            }
        )
        skip_note = f" skipped={skip_reason}" if skip_reason else ""
        print(
            f"[product {index}/{len(products)}] id={product_id} pages={pages_scanned} rows={0 if skip_reason else len(product_rows)} url={product_url}{skip_note}",
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
            "height_in_display",
            "weight_display_display",
            "weight_lbs_display",
            "bust_in_number_display",
            "hips_in_display",
            "waist_in",
            "inseam_inches_display",
        ]
    )


def is_supabase_qualified(row: Dict[str, str]) -> bool:
    return bool(
        has_product_url(row)
        and has_measurement(row)
        and row.get("original_url_display")
        and row.get("size_display")
        and row.get("size_display") != "unknown"
    )


def enrich_summary(summary: Dict[str, object], rows: Sequence[Dict[str, str]], output_csv: Path) -> Dict[str, object]:
    product_urls = {
        row.get("product_page_url_display") or row.get("monetized_product_url_display")
        for row in rows
        if has_product_url(row)
    }
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
    limit_pages_per_product: Optional[int] = None
    if "--limit-products" in argv:
        idx = argv.index("--limit-products")
        limit_products = int(argv[idx + 1])
    if "--limit-pages-per-product" in argv:
        idx = argv.index("--limit-pages-per-product")
        limit_pages_per_product = int(argv[idx + 1])

    rows, summary = scrape_reviews(limit_products=limit_products, limit_pages_per_product=limit_pages_per_product)
    summary = enrich_summary(summary, rows, OUTPUT_CSV)
    write_csv(rows, OUTPUT_CSV)
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
