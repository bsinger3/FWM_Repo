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
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "leonisa_com"
OUTPUT_CSV = OUTPUT_DIR / "leonisa_com_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "leonisa_com_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://www.leonisa.com"
SOURCE_SITE = f"{SITE_ROOT}/"
SHOP_DOMAIN = "leonisa-usa.myshopify.com"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
JUDGEME_WIDGET_URL = "https://api.judge.me/reviews/reviews_for_widget"
JUDGEME_ALL_REVIEWS_URL = "https://cdn.judge.me/reviews/all_reviews_js_based"
BRAND = "Leonisa"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 20
ALL_REVIEWS_PER_PAGE = 100
REQUEST_DELAY_SECONDS = 0.15
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
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*inseam\b", re.I)
BRA_SIZE_RE = re.compile(r"\b((?:2[8-9]|3[0-9]|4[0-8])\s*(?:aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k))\b", re.I)
BLOCK_STATUS_CODES = {403, 429}
BLOCK_TEXT_RE = re.compile(r"\b(?:captcha|cloudflare|datadome|access denied|blocked|forbidden|unusual traffic|verify you are human)\b", re.I)
SHOPPER_IMAGE_RE = re.compile(r"judgeme\.(?:imgix|s3)|judge\.me", re.I)
REVIEW_SPLIT_RE = re.compile(r"(?=<div class='jdgm-rev\b)")

SIZE_TOKEN = r"(?:\d{1,2}[a-z]{0,3}|xxs|xs|s|m|l|xl|xxl|xxxl|2x|3x|small|medium|large|x-large|xx-large|xxx-large)"
SIZE_PATTERNS = [
    re.compile(
        r"\b(?:size|sz)\s*(?:up|down|is|was|ordered|bought|got|:)?\s*"
        rf"({SIZE_TOKEN})\b",
        re.I,
    ),
    re.compile(
        r"\b(?:ordered|bought|got|purchased|wear(?:ing)?)\s+(?:a|an|the)?\s*"
        rf"(?:size\s*)?({SIZE_TOKEN})\b",
        re.I,
    ),
    re.compile(
        rf"\b(?:ped[ií]|compr[eé]|orden[eé]|us[eé])\s+(?:una|la|un|el)?\s*(?:talla\s*)?({SIZE_TOKEN})\b",
        re.I,
    ),
    re.compile(
        rf"\b(?:talla)\s+({SIZE_TOKEN})\b(?=[^.?!]{{0,80}}\b(?:ped[ií]|compr[eé]|orden[eé]))",
        re.I,
    ),
]
HEIGHT_CM_RE = re.compile(r"\b(?:mido|height|estatura)\s*:?\s*(1[.,]\d{2}|[1-2]\d{2})\s*(?:m|cm|centimeters?|centimetros|centímetros)\b", re.I)
WEIGHT_KG_RE = re.compile(r"\b(?:peso|weight)\s*:?\s*(\d{2,3}(?:[.,]\d+)?)\s*(?:kg|kilos?|kilograms?)\b", re.I)
SPANISH_WEIGHT_LBS_RE = re.compile(r"\b(?:peso)\s*:?\s*(\d{2,3}(?:[.,]\d+)?)\s*(?:lbs?|libras?)\b", re.I)


class BlockedScrapeError(RuntimeError):
    pass


def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def repair_mojibake(text: str) -> str:
    if not text or "Ã" not in text and "â" not in text:
        return text
    try:
        return text.encode("latin1").decode("utf-8")
    except UnicodeError:
        return text


def strip_tags(value: str) -> str:
    cleaned = re.sub(r"</p\s*>|<br\s*/?>", " ", value or "", flags=re.I)
    return repair_mojibake(normalize_whitespace(html.unescape(TAG_RE.sub(" ", cleaned))))


def clean_url(value: str) -> str:
    url = normalize_whitespace(html.unescape(value or "")).replace("&amp;", "&")
    if not url:
        return ""
    url = urljoin(SITE_ROOT, url)
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))


def detect_blocked_response(status: int, body: str, url: str) -> None:
    if status in BLOCK_STATUS_CODES or BLOCK_TEXT_RE.search(body[:5000]):
        raise BlockedScrapeError(f"Blocked response while fetching {url}: status={status}")


def fetch_text(url: str, retries: int = 4) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        try:
            with urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8", "replace")
                detect_blocked_response(resp.status, text, url)
                return text
        except HTTPError as exc:
            if exc.code in BLOCK_STATUS_CODES:
                raise BlockedScrapeError(f"Blocked response while fetching {url}: status={exc.code}") from exc
            last_error = exc
            time.sleep(min(2**attempt, 10))
        except URLError as exc:
            last_error = exc
            time.sleep(min(2**attempt, 10))
    raise RuntimeError(f"Failed text request for {url}: {last_error}")


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, retries: int = 5, referer: Optional[str] = None) -> Dict[str, object]:
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
                raw = resp.read().decode("utf-8", "replace")
                detect_blocked_response(resp.status, raw, query_url)
                return json.loads(raw)
        except HTTPError as exc:
            last_error = exc
            if exc.code in BLOCK_STATUS_CODES:
                raise BlockedScrapeError(f"Blocked response while fetching {query_url}: status={exc.code}") from exc
            if exc.code not in {500, 502, 503, 504}:
                raise
        except (URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(REQUEST_DELAY_SECONDS)
        time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"Failed JSON request for {query_url}: {last_error}")


def product_url_for(product: Dict[str, object]) -> str:
    explicit_url = normalize_whitespace(str(product.get("url") or ""))
    if explicit_url:
        return clean_url(explicit_url)
    handle = normalize_whitespace(str(product.get("handle") or ""))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def fetch_products_from_json() -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    pages: List[Dict[str, object]] = []
    page = 1
    while True:
        payload = fetch_json(PRODUCTS_JSON_URL, {"limit": PRODUCTS_PER_PAGE, "page": page})
        page_products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        pages.append({"source": "products.json", "page": page, "count": len(page_products)})
        if not page_products:
            break
        products.extend(page_products)
        if len(page_products) < PRODUCTS_PER_PAGE:
            break
        page += 1
    return products, pages


def json_loads_relaxed(raw: str) -> Optional[object]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json.loads(raw.encode("utf-8").decode("unicode_escape"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None


def extract_product_from_page(product_url: str) -> Dict[str, object]:
    text = fetch_text(product_url)
    handle = product_url.rstrip("/").rsplit("/", 1)[-1]
    product_id = ""
    title = ""
    product_type = ""
    body_html = ""
    variants: List[Dict[str, object]] = []

    id_patterns = [
        r"\bProductID\s*:\s*(\d+)",
        r'"product_id"\s*:\s*"?(?P<id>\d+)"?',
        r'"productId"\s*:\s*"?(?P<id>\d+)"?',
        r'"id"\s*:\s*(?P<id>\d{10,})',
    ]
    for pattern in id_patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            product_id = match.groupdict().get("id") or match.group(1)
            break

    variants_match = re.search(r'"variants"\s*:\s*(\[[\s\S]{0,250000}?\])\s*,\s*"available"', text)
    if not variants_match:
        variants_match = re.search(r'"variants"\s*:\s*(\[[\s\S]{0,250000}?\])\s*,\s*"images"', text)
    if variants_match:
        parsed = json_loads_relaxed(variants_match.group(1))
        if isinstance(parsed, list):
            variants = [item for item in parsed if isinstance(item, dict)]
            if not product_id:
                for variant in variants:
                    variant_product_id = variant.get("product_id")
                    if variant_product_id:
                        product_id = str(variant_product_id)
                        break

    json_ld_matches = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>', text, flags=re.I)
    for raw_json in json_ld_matches:
        parsed = json_loads_relaxed(html.unescape(raw_json.strip()))
        candidates = parsed if isinstance(parsed, list) else [parsed]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("@type") != "Product":
                continue
            title = title or strip_tags(str(candidate.get("name") or ""))
            body_html = body_html or strip_tags(str(candidate.get("description") or ""))
            brand = candidate.get("brand")
            if isinstance(brand, dict):
                product_type = product_type or strip_tags(str(brand.get("name") or ""))

    if not title:
        match = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', text, flags=re.I)
        if match:
            title = strip_tags(match.group(1))
    if not body_html:
        match = re.search(r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']+)["\']', text, flags=re.I)
        if match:
            body_html = strip_tags(match.group(1))

    return {
        "id": int(product_id) if product_id.isdigit() else product_id,
        "handle": handle,
        "url": product_url,
        "title": title or handle.replace("-", " ").title(),
        "product_type": "" if product_type == BRAND else product_type,
        "body_html": body_html,
        "variants": variants,
    }


def product_urls_from_sitemap() -> Tuple[List[str], List[Dict[str, object]]]:
    index = fetch_text(SITEMAP_URL)
    sitemap_urls = [html.unescape(match) for match in re.findall(r"<loc>(https://www\.leonisa\.com/sitemap_products_[^<]+)</loc>", index)]
    urls: List[str] = []
    sources: List[Dict[str, object]] = [{"source": "sitemap_index", "count": len(sitemap_urls)}]
    for sitemap_url in sitemap_urls:
        if "/es/" in sitemap_url:
            continue
        text = fetch_text(sitemap_url)
        page_urls = sorted(set(re.findall(r"https://www\.leonisa\.com/products/[^<\s\"']+", text)))
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(page_urls)})
        urls.extend(page_urls)
    return sorted(set(urls)), sources


def discover_products(limit_products: Optional[int] = None) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    product_sources: List[Dict[str, object]] = []
    try:
        products, product_sources = fetch_products_from_json()
    except Exception as exc:  # noqa: BLE001
        product_sources.append({"source": "products.json", "error": str(exc), "fallback": "product_sitemap_and_product_pages"})
    sitemap_urls, sitemap_sources = product_urls_from_sitemap()
    by_url: Dict[str, Dict[str, object]] = {product_url_for(product): product for product in products if product_url_for(product)}
    missing_urls = [url for url in sitemap_urls if url not in by_url]
    for url in missing_urls:
        try:
            by_url[url] = extract_product_from_page(url)
        except Exception as exc:  # noqa: BLE001
            handle = url.rstrip("/").rsplit("/", 1)[-1]
            by_url[url] = {
                "id": "",
                "handle": handle,
                "url": url,
                "title": handle.replace("-", " ").title(),
                "product_type": "",
                "body_html": "",
                "variants": [],
                "page_parse_error": str(exc),
            }
    ordered = list(by_url.values())
    if limit_products is not None:
        ordered = ordered[:limit_products]
    product_sources.extend(sitemap_sources)
    product_sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing_urls)})
    return ordered, product_sources


def widget_params(product_id: object, page: int) -> Dict[str, object]:
    return {
        "url": "www.leonisa.com",
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


def parse_height_inches(text: str) -> Tuple[str, Optional[float]]:
    match = HEIGHT_RE.search(text)
    if match:
        feet = int(match.group(1))
        inches = int(match.group(2) or 0)
        if 4 <= feet <= 7 and 0 <= inches <= 11:
            return normalize_whitespace(match.group(0)), feet * 12 + inches
    metric_match = HEIGHT_CM_RE.search(text)
    if metric_match:
        raw_value = metric_match.group(1).replace(",", ".")
        cm = float(raw_value) * 100 if "." in raw_value else float(raw_value)
        if 120 <= cm <= 220:
            return normalize_whitespace(metric_match.group(0)), round(cm / 2.54, 1)
    return "", None


def parse_numeric(pattern: re.Pattern[str], text: str, max_value: Optional[float] = None) -> Tuple[str, Optional[float]]:
    match = pattern.search(text)
    if not match:
        return "", None
    value = float(match.group(1))
    if max_value is not None and value > max_value:
        return "", None
    return normalize_whitespace(match.group(0)), value


def parse_weight_lbs(text: str) -> Tuple[str, Optional[float], str]:
    for pattern, factor in [(WEIGHT_RE, 1.0), (SPANISH_WEIGHT_LBS_RE, 1.0), (WEIGHT_KG_RE, 2.2046226218)]:
        match = pattern.search(text)
        if not match:
            continue
        value = float(match.group(1).replace(",", "."))
        pounds = value * factor
        if 50 <= pounds <= 500:
            return normalize_whitespace(match.group(0)), pounds, "converted_from_kg" if factor != 1.0 else ""
    return "", None, ""


def parse_age(text: str) -> Tuple[str, str]:
    match = AGE_RE.search(text)
    if not match:
        return "", ""
    return normalize_whitespace(match.group(0)), match.group(1) or match.group(2) or ""


def extract_bra_size(text: str) -> Tuple[str, str]:
    match = BRA_SIZE_RE.search(text)
    if not match:
        return "", ""
    compact = re.sub(r"\s+", "", match.group(1)).upper()
    band = re.match(r"(\d{2})", compact)
    cup = re.search(r"[A-Z]+$", compact)
    return (band.group(1) if band else "", cup.group(0) if cup else "")


def normalize_size(value: str) -> str:
    cleaned = normalize_whitespace(value)
    mapping = {
        "s": "small",
        "m": "medium",
        "l": "large",
        "xl": "x-large",
        "xxl": "xx-large",
        "xxxl": "xxx-large",
        "2x": "xx-large",
        "3x": "xxx-large",
    }
    return mapping.get(cleaned.lower(), cleaned)


def valid_size_candidate(value: str, match_text: str) -> bool:
    cleaned = value.lower().rstrip("prt")
    if cleaned.isdigit():
        numeric = int(cleaned)
        if numeric < 6 or numeric > 60:
            return False
    return not re.search(r"\b(?:lb|lbs|pounds?|years?|age|waist|hips?|inseam|height)\b", match_text, re.I)


def extract_size(text: str, variant: str) -> str:
    for source in [variant, text]:
        for pattern in SIZE_PATTERNS:
            match = pattern.search(source)
            if match and valid_size_candidate(match.group(1), match.group(0)):
                return normalize_size(match.group(1))
    return ""


def variant_titles(product: Dict[str, object]) -> List[str]:
    titles: List[str] = []
    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants[:200]:
            if isinstance(variant, dict):
                title = normalize_whitespace(str(variant.get("title") or ""))
                if title and title.lower() != "default title" and title not in titles:
                    titles.append(title)
    return titles


def cf_answers_text(review: Dict[str, object]) -> str:
    answers = review.get("cf_answers")
    if isinstance(answers, dict):
        return normalize_whitespace(" ".join(f"{key}: {value}" for key, value in answers.items() if value))
    if isinstance(answers, list):
        pieces: List[str] = []
        for answer in answers:
            if isinstance(answer, dict):
                pieces.append(" ".join(str(value) for value in answer.values() if value))
            elif answer:
                pieces.append(str(answer))
        return normalize_whitespace(" ".join(pieces))
    return ""


def customer_picture_urls(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    pictures = review.get("pictures_urls")
    if not isinstance(pictures, list):
        return urls
    for picture in pictures:
        if not isinstance(picture, dict):
            continue
        raw_url = picture.get("original") or picture.get("large") or picture.get("compact") or picture.get("small")
        url = normalize_whitespace(str(raw_url or ""))
        if url and url not in urls:
            urls.append(url)
    return urls


def classify_clothing_type(product: Dict[str, object], title: str) -> str:
    value = f"{title} {product.get('product_type') or ''}".lower()
    if any(term in value for term in ["brief", "boxer", "trunk", "men's", "mens"]):
        return "mens"
    if any(term in value for term in ["legging", "capri", "pant"]):
        return "pants"
    if "short" in value:
        return "shorts"
    if "swim" in value:
        return "swimwear"
    if any(term in value for term in ["panty", "panties", "thong", "hipster"]):
        return "underwear"
    if any(term in value for term in ["bra", "bralette", "bustier"]):
        return "bra"
    if any(term in value for term in ["bodysuit", "shaper", "faja", "cincher"]):
        return "shapewear"
    if "tee" in value or "tank" in value:
        return "top"
    return normalize_whitespace(str(product.get("product_type") or "")).lower()


def out_of_scope_product(product: Dict[str, object], title: str) -> Tuple[bool, str]:
    value = f"{title} {product.get('product_type') or ''}".lower()
    if any(term in value for term in ["men's", "mens", "masculin", "boxer", "trunk"]):
        return True, "mens_or_masculine_product"
    return False, ""


def split_color_from_variant(variant: str) -> Tuple[str, str]:
    parts = [normalize_whitespace(part) for part in variant.split("/") if normalize_whitespace(part)]
    color = parts[0] if parts else ""
    return color.lower(), color


def build_search_fts(parts: Iterable[str]) -> str:
    return normalize_whitespace(" ".join(part for part in parts if part))


def row_from_review_fields(
    *,
    review_id: str,
    picture_url: str,
    picture_index: int,
    product_url: str,
    product_title: str,
    product: Dict[str, object],
    fetched_at: str,
    timestamp: str,
    reviewer_name: str,
    title: str,
    body: str,
    cf_text: str,
    variant: str,
) -> Dict[str, str]:
    review_date = timestamp.split("T", 1)[0].split(" ", 1)[0] if timestamp else ""
    text_pool = normalize_whitespace(" ".join([title, body, cf_text]))
    height_raw, height_in = parse_height_inches(text_pool)
    weight_raw, weight_lbs, weight_issue = parse_weight_lbs(text_pool)
    waist_raw, waist_in = parse_numeric(WAIST_RE, text_pool, max_value=60)
    hips_raw, hips_in = parse_numeric(HIPS_RE, text_pool, max_value=80)
    age_raw, age_years = parse_age(text_pool)
    _inseam_raw, inseam_in = parse_numeric(INSEAM_RE, text_pool, max_value=40)
    bust_in, cupsize = extract_bra_size(text_pool)
    color_canonical, color_display = split_color_from_variant(variant)
    size_display = extract_size(text_pool, variant)
    clothing_type = classify_clothing_type(product, product_title)
    product_description = strip_tags(str(product.get("body_html") or ""))
    product_detail = normalize_whitespace(" | ".join(variant_titles(product)))

    return {
        "created_at_display": "",
        "id": f"{review_id}-{picture_index}" if review_id else f"{hash(picture_url)}-{picture_index}",
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
        "search_fts": build_search_fts([BRAND, product_title, product_description, title, body, cf_text, variant]),
        "weight_display_display": maybe_number_text(weight_lbs),
        "weight_raw_needs_correction": "",
        "clothing_type_id": clothing_type,
        "reviewer_profile_url": "",
        "reviewer_name_raw": reviewer_name,
        "inseam_inches_display": maybe_number_text(inseam_in),
        "color_canonical": color_canonical,
        "color_display": color_display,
        "size_display": size_display,
        "bust_in_number_display": bust_in,
        "cupsize_display": cupsize,
        "weight_lbs_display": maybe_number_text(weight_lbs),
        "weight_lbs_raw_issue": weight_issue,
        "product_title_raw": product_title,
        "product_subtitle_raw": "",
        "product_description_raw": product_description,
        "product_detail_raw": product_detail,
        "product_category_raw": normalize_whitespace(str(product.get("product_type") or "")),
        "product_variant_raw": variant,
    }


def parse_review_rows(review: Dict[str, object], product: Dict[str, object], fetched_at: str) -> List[Dict[str, str]]:
    picture_urls = customer_picture_urls(review)
    if not picture_urls:
        return []
    review_id = normalize_whitespace(str(review.get("uuid") or review.get("id") or ""))
    timestamp = normalize_whitespace(str(review.get("created_at") or ""))
    reviewer_name = strip_tags(str(review.get("reviewer_name") or ""))
    title = strip_tags(str(review.get("title") or ""))
    body = strip_tags(str(review.get("body") or review.get("body_html") or ""))
    cf_text = strip_tags(cf_answers_text(review))
    product_title = strip_tags(str(review.get("product_title") or product.get("title") or ""))
    product_url = clean_url(str(review.get("product_url_with_utm") or review.get("product_url") or "")) or product_url_for(product)
    variant = normalize_whitespace(str(review.get("product_variant_title") or ""))

    rows: List[Dict[str, str]] = []
    for index, picture_url in enumerate(picture_urls, start=1):
        rows.append(
            row_from_review_fields(
                review_id=review_id,
                picture_url=picture_url,
                picture_index=index,
                product_url=product_url,
                product_title=product_title,
                product=product,
                fetched_at=fetched_at,
                timestamp=timestamp,
                reviewer_name=reviewer_name,
                title=title,
                body=body,
                cf_text=cf_text,
                variant=variant,
            )
        )
    return rows


def attr_value(fragment: str, name: str) -> str:
    match = re.search(rf"\b{name}=(['\"])(.*?)\1", fragment, flags=re.I | re.S)
    return html.unescape(match.group(2)) if match else ""


def first_match_text(pattern: str, fragment: str) -> str:
    match = re.search(pattern, fragment, flags=re.I | re.S)
    return strip_tags(match.group(1)) if match else ""


def extract_cf_answers_from_html(fragment: str) -> str:
    answers: List[str] = []
    for block in re.findall(r"<div class='jdgm-rev__cf-ans'[\s\S]*?(?=<div class='jdgm-rev__cf-ans'|<b class='jdgm-rev__title'|<div class='jdgm-rev__body'|$)", fragment):
        title = first_match_text(r"<b class='jdgm-rev__cf-ans__title'[^>]*>([\s\S]*?)</b>", block)
        value = first_match_text(r"<span class='jdgm-rev__cf-ans__value'[^>]*>([\s\S]*?)</span>", block)
        if not value:
            pointer = attr_value(block, "style")
            if pointer:
                slider = re.search(r"left:\s*(\d{1,3})%", pointer)
                lower = first_match_text(r"<span class='jdgm-rev__slider-first'[^>]*>([\s\S]*?)</span>", block)
                upper = first_match_text(r"<span class='jdgm-rev__slider-last'[^>]*>([\s\S]*?)</span>", block)
                if slider:
                    value = f"{slider.group(1)} {lower} {upper}".strip()
        if title or value:
            answers.append(normalize_whitespace(f"{title} {value}"))
    return normalize_whitespace(" ".join(answers))


def customer_picture_urls_from_html(fragment: str) -> List[str]:
    urls: List[str] = []
    for link in re.findall(r"<a\b[^>]*class=['\"][^'\"]*jdgm-rev__pic-link[^'\"]*['\"][^>]*>", fragment, flags=re.I | re.S):
        if "jdgm-rev__product-picture" in link:
            continue
        url = attr_value(link, "href") or attr_value(link, "data-mfp-src")
        url = normalize_whitespace(url)
        if url and SHOPPER_IMAGE_RE.search(url) and url not in urls:
            urls.append(url)
    return urls


def parse_store_media_html_rows(html_text: str, products_by_url: Dict[str, Dict[str, object]], fetched_at: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for fragment in [part for part in REVIEW_SPLIT_RE.split(html_text) if part.startswith("<div class='jdgm-rev")]:
        picture_urls = customer_picture_urls_from_html(fragment)
        if not picture_urls:
            continue
        review_id = attr_value(fragment, "data-review-id")
        timestamp = attr_value(fragment, "data-content")
        if timestamp:
            timestamp = timestamp.replace(" UTC", "Z").replace(" ", "T", 1)
        reviewer_name = first_match_text(r"<span class='jdgm-rev__author'[^>]*>([\s\S]*?)</span>", fragment)
        title = first_match_text(r"<b class='jdgm-rev__title'[^>]*>([\s\S]*?)</b>", fragment)
        body = first_match_text(r"<div class='jdgm-rev__body'[^>]*>([\s\S]*?)</div>", fragment)
        cf_text = extract_cf_answers_from_html(fragment)
        product_link = re.search(r"<a\b[^>]*class=['\"][^'\"]*jdgm-rev__prod-link[^'\"]*['\"][^>]*>([\s\S]*?)</a>", fragment, flags=re.I | re.S)
        product_title = strip_tags(product_link.group(1)) if product_link else ""
        product_url = ""
        if product_link:
            product_url = clean_url(attr_value(product_link.group(0), "href").split("#", 1)[0])
        if not product_url or product_url.rstrip("/") == SOURCE_SITE.rstrip("/"):
            continue
        product = products_by_url.get(product_url) or {
            "id": "",
            "handle": product_url.rstrip("/").rsplit("/", 1)[-1],
            "url": product_url,
            "title": product_title,
            "product_type": "",
            "body_html": "",
            "variants": [],
        }
        skipped, _reason = out_of_scope_product(product, product_title)
        if skipped:
            continue
        for index, picture_url in enumerate(picture_urls, start=1):
            rows.append(
                row_from_review_fields(
                    review_id=review_id,
                    picture_url=picture_url,
                    picture_index=index,
                    product_url=product_url,
                    product_title=product_title or strip_tags(str(product.get("title") or "")),
                    product=product,
                    fetched_at=fetched_at,
                    timestamp=timestamp,
                    reviewer_name=reviewer_name,
                    title=title,
                    body=body,
                    cf_text=cf_text,
                    variant="",
                )
            )
    return rows


def all_reviews_params(page: int) -> Dict[str, object]:
    return {
        "url": SHOP_DOMAIN,
        "shop_domain": SHOP_DOMAIN,
        "platform": "shopify",
        "per_page": ALL_REVIEWS_PER_PAGE,
        "page": page,
        "review_type": "all-reviews",
        "sort_by": "with_media",
    }


def scrape_store_media_rows(
    products_by_url: Dict[str, Dict[str, object]],
    fetched_at: str,
    limit_pages: Optional[int] = None,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    rows: List[Dict[str, str]] = []
    page_summaries: List[Dict[str, object]] = []
    page = 1
    while True:
        if limit_pages is not None and page > limit_pages:
            break
        payload = fetch_json(JUDGEME_ALL_REVIEWS_URL, all_reviews_params(page), referer=SOURCE_SITE)
        html_text = str(payload.get("html") or "")
        if not html_text.strip():
            page_summaries.append({"page": page, "html_reviews": 0, "rows": 0, "stop_reason": "empty_html"})
            break
        page_rows = parse_store_media_html_rows(html_text, products_by_url, fetched_at)
        rows.extend(page_rows)
        page_summaries.append(
            {
                "page": page,
                "html_review_markers": html_text.count("data-review-id="),
                "raw_picture_links": html_text.count("jdgm-rev__pic-link"),
                "rows": len(page_rows),
                "number_of_product_reviews": payload.get("number_of_product_reviews"),
                "number_of_shop_reviews": payload.get("number_of_shop_reviews"),
            }
        )
        print(f"[store-media page {page}] rows={len(page_rows)} raw_picture_links={html_text.count('jdgm-rev__pic-link')}", flush=True)
        page += 1
        time.sleep(REQUEST_DELAY_SECONDS)
    return rows, {"pages": page_summaries, "pages_scanned": len(page_summaries)}


def dedupe_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        image_key = re.sub(r"[?&]w=\d+", "", row.get("original_url_display", ""))
        key = (row.get("id", "").rsplit("-", 1)[0], image_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


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
    return bool(has_product_url(row) and has_measurement(row) and row.get("original_url_display") and row.get("size_display"))


def scrape_reviews(
    limit_products: Optional[int] = None,
    limit_pages_per_product: Optional[int] = None,
    limit_store_media_pages: Optional[int] = None,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    products, product_sources = discover_products(limit_products=limit_products)
    products_by_url = {product_url_for(product): product for product in products if product_url_for(product)}
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": "leonisa_com",
        "adapter": "judge_me_product_level_plus_all_reviews_media",
        "shop_domain": SHOP_DOMAIN,
        "started_at": fetched_at,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": 0,
        "products_excluded_from_output": 0,
        "products_with_review_rows": 0,
        "review_pages_scanned": 0,
        "store_media_review_pages_scanned": 0,
        "product_review_count_hint": 0,
        "exhaustive_review_paging": False,
        "exhaustive_media_paging": limit_pages_per_product is None and limit_store_media_pages is None,
        "review_paging_note": "Exhausted product-level with_pictures pages and the store all-reviews with_media endpoint; did not crawl every non-media text review page because the scrape target is review-image rows.",
        "access_policy": "public_product_and_review_pages_only; restricted_or_unavailable_pages_are_skipped; polite_retries",
        "measurement_extraction": "deterministic_regex_and_provider_fields_only",
        "store_media_endpoint": JUDGEME_ALL_REVIEWS_URL,
        "errors": [],
    }

    for index, product in enumerate(products, start=1):
        product_id = product.get("id")
        product_url = product_url_for(product)
        product_rows: List[Dict[str, str]] = []
        pages_scanned = 0
        review_count_hint = 0
        errors: List[str] = []
        skipped_from_output, skip_reason = out_of_scope_product(product, str(product.get("title") or ""))
        if product_id:
            page = 1
            while True:
                if limit_pages_per_product is not None and page > limit_pages_per_product:
                    break
                try:
                    payload = fetch_json(JUDGEME_WIDGET_URL, widget_params(product_id, page), referer=product_url or SOURCE_SITE)
                except Exception as exc:  # noqa: BLE001
                    errors.append(str(exc))
                    break
                reviews = payload.get("reviews")
                review_count_hint = int(payload.get("number_of_reviews") or review_count_hint or 0)
                if not isinstance(reviews, list) or not reviews:
                    break
                pages_scanned += 1
                for review in reviews:
                    if isinstance(review, dict):
                        if not skipped_from_output:
                            product_rows.extend(parse_review_rows(review, product, fetched_at))
                pagination = payload.get("pagination")
                total_pages = int(pagination.get("total_pages") or 0) if isinstance(pagination, dict) else 0
                if total_pages and page >= total_pages:
                    break
                page += 1
                time.sleep(REQUEST_DELAY_SECONDS)
        else:
            errors.append("missing_product_id_from_products_json")

        product_summaries.append(
            {
                "product_index": index,
                "product_url": product_url,
                "product_title": product.get("title"),
                "product_type": product.get("product_type"),
                "shopify_product_id": product_id,
                "adapter_used": "judgeme_product_level" if product_id else "missing-product-id",
                "review_pages_scanned": pages_scanned,
                "review_count_hint": review_count_hint,
                "matching_review_images": len(product_rows),
                "rows": len(product_rows),
                "skipped_from_output": skipped_from_output,
                "skip_reason": skip_reason,
                "errors": errors,
            }
        )
        summary["products_scanned"] = int(summary["products_scanned"]) + 1
        summary["review_pages_scanned"] = int(summary["review_pages_scanned"]) + pages_scanned
        summary["product_review_count_hint"] = int(summary["product_review_count_hint"]) + review_count_hint
        if product_rows:
            summary["products_with_review_rows"] = int(summary["products_with_review_rows"]) + 1
        if skipped_from_output:
            summary["products_excluded_from_output"] = int(summary["products_excluded_from_output"]) + 1
        if errors:
            summary["errors"].append({"product_url": product_url, "errors": errors})
        rows.extend(product_rows)
        print(f"[product {index}/{len(products)}] reviews={review_count_hint} pages={pages_scanned} rows={len(product_rows)} url={product_url}", flush=True)
        time.sleep(REQUEST_DELAY_SECONDS)

    store_rows, store_media_summary = scrape_store_media_rows(products_by_url, fetched_at, limit_pages=limit_store_media_pages)
    rows.extend(store_rows)
    summary["store_media_review_pages_scanned"] = store_media_summary["pages_scanned"]
    summary["store_media_page_summaries"] = store_media_summary["pages"]
    summary["store_media_rows_before_dedupe"] = len(store_rows)

    summary["product_summaries"] = product_summaries
    summary["finished_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return dedupe_rows(rows), summary


def write_csv(rows: Sequence[Dict[str, str]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in HEADERS})


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
            "distinct_images": len({re.sub(r"[?&]w=\d+", "", row.get("original_url_display", "")) for row in rows if row.get("original_url_display")}),
            "distinct_product_urls": len(product_urls),
            "distinct_products": len(product_urls),
            "rows_with_distinct_product_url": len(product_urls),
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
            "rows_for_bra_products": sum(1 for row in rows if row.get("clothing_type_id") == "bra"),
            "rows_for_bra_products_with_customer_bra_size": sum(
                1 for row in rows if row.get("clothing_type_id") == "bra" and row.get("bust_in_number_display") and row.get("cupsize_display")
            ),
        }
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    limit_products: Optional[int] = None
    limit_pages_per_product: Optional[int] = None
    if "--limit-products" in argv:
        index = argv.index("--limit-products")
        limit_products = int(argv[index + 1])
    if "--limit-pages-per-product" in argv:
        index = argv.index("--limit-pages-per-product")
        limit_pages_per_product = int(argv[index + 1])
    limit_store_media_pages: Optional[int] = None
    if "--limit-store-media-pages" in argv:
        index = argv.index("--limit-store-media-pages")
        limit_store_media_pages = int(argv[index + 1])

    try:
        rows, summary = scrape_reviews(
            limit_products=limit_products,
            limit_pages_per_product=limit_pages_per_product,
            limit_store_media_pages=limit_store_media_pages,
        )
    except BlockedScrapeError as exc:
        print(f"Stopping on blocked response: {exc}", file=sys.stderr)
        return 2
    rows.sort(
        key=lambda row: (
            row.get("review_date", ""),
            row.get("product_page_url_display", ""),
            row.get("reviewer_name_raw", ""),
            row.get("original_url_display", ""),
        ),
        reverse=True,
    )
    write_csv(rows, OUTPUT_CSV)
    summary = enrich_summary(summary, rows, OUTPUT_CSV)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Rows written: {len(rows)}")
    print(f"Supabase-qualified rows: {summary['rows_supabase_qualified']}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
