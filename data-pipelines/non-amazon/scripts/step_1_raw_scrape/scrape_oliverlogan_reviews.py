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
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "oliverlogan_com"
OUTPUT_CSV = OUTPUT_DIR / "oliverlogan_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "oliverlogan_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://oliverlogan.com"
SOURCE_SITE = f"{SITE_ROOT}/"
SHOP_DOMAIN = "oliver-logan.myshopify.com"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
REVIEWS_FOR_WIDGET_URL = "https://api.judge.me/reviews/reviews_for_widget"
BRAND = "Oliver Logan"
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
HEIGHT_RE = re.compile(
    r"(\d)\s*(?:ft|feet|foot|['\u2019])\s*(\d{1,2})?\s*(?:in|inches|[\"\u201d])?",
    re.I,
)
WEIGHT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?|#)\b", re.I)
WAIST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b", re.I)
HIPS_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*inseam\b", re.I)
SIZE_PATTERNS = [
    re.compile(
        r"\b(?:size|sz)\s*(?:up|down|is|was|ordered|bought|got|:)?\s*"
        r"(\d{2}(?:p|r|t)?|xxs|xs|s|m|l|xl|xxl|2x|3x|small|medium|large|x-large|xx-large)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:ordered|bought|got|purchased|wear(?:ing)?)\s+(?:a|an|the)?\s*"
        r"(?:size\s*)?(\d{2}(?:p|r|t)?|xxs|xs|s|m|l|xl|xxl|2x|3x|small|medium|large)\b",
        re.I,
    ),
    re.compile(r"\busual\s+size\s+(?:is\s+)?(\d{2}(?:p|r|t)?|xxs|xs|s|m|l|xl|xxl|small|medium|large)\b", re.I),
]

COLOR_WORDS = (
    "black",
    "blue",
    "brown",
    "cream",
    "dark aged",
    "dark blue",
    "ecru",
    "faded indigo",
    "grey",
    "gray",
    "high tide",
    "indigo",
    "light indigo",
    "optic white",
    "ralph",
    "shiver me timbers",
    "timbers",
    "vintage worn",
    "white",
)


def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def strip_tags(value: str) -> str:
    cleaned = re.sub(r"</p\s*>|<br\s*/?>", " ", value or "", flags=re.I)
    return normalize_whitespace(html.unescape(TAG_RE.sub(" ", cleaned)))


def clean_url(value: str) -> str:
    url = normalize_whitespace(html.unescape(value or "")).replace("&amp;", "&")
    if not url:
        return ""
    url = urljoin(SITE_ROOT, url)
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def fetch_json(
    url: str,
    params: Optional[Dict[str, object]] = None,
    retries: int = 6,
    referer: Optional[str] = None,
) -> Dict[str, object]:
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
        time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"Failed JSON request for {query_url}: {last_error}")


def fetch_text(url: str, retries: int = 6) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xml,text/xml,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": SOURCE_SITE,
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", "replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
        except URLError as exc:
            last_error = exc
        time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"Failed text request for {url}: {last_error}")


def product_url_for(product: Dict[str, object]) -> str:
    handle = normalize_whitespace(str(product.get("handle") or ""))
    return f"{SITE_ROOT}/products/{handle}" if handle else ""


def output_skip_reason(product: Dict[str, object]) -> str:
    value = f"{product.get('title') or ''} {product.get('product_type') or ''}".lower()
    if "gift card" in value:
        return "out_of_scope_gift_card"
    if "belt" in value:
        return "out_of_scope_accessory_belt"
    return ""


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
        if limit_products is not None and len(products) >= limit_products:
            return products[:limit_products], sources
        if len(page_products) < PRODUCTS_PER_PAGE:
            break
        page += 1

    sitemap_index = fetch_text(SITEMAP_URL)
    sitemap_urls = [
        html.unescape(url)
        for url in re.findall(r"<loc>(https://oliverlogan\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index)
    ]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url)
        urls = sorted(set(re.findall(r"https://oliverlogan\.com/products/[^<\s\"']+", text)))
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        sitemap_product_urls.extend(urls)

    by_url: Dict[str, Dict[str, object]] = {product_url_for(product): product for product in products if product_url_for(product)}
    missing = [url for url in sorted(set(sitemap_product_urls)) if url not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {
            "id": "",
            "handle": handle,
            "title": handle.replace("-", " ").title(),
            "product_type": "",
            "body_html": "",
            "variants": [],
        }
    sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)})
    return list(by_url.values()), sources


def widget_params(product_id: object, page: int) -> Dict[str, object]:
    return {
        "url": "oliverlogan.com",
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
    if not match:
        return "", None
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    if feet < 4 or feet > 7 or inches > 11:
        return "", None
    return normalize_whitespace(match.group(0)), feet * 12 + inches


def parse_numeric(pattern: re.Pattern[str], text: str, max_value: Optional[float] = None) -> Tuple[str, Optional[float]]:
    match = pattern.search(text)
    if not match:
        return "", None
    value = float(match.group(1))
    if max_value is not None and value > max_value:
        return "", None
    return normalize_whitespace(match.group(0)), value


def parse_age(text: str) -> Tuple[str, str]:
    match = AGE_RE.search(text)
    if not match:
        return "", ""
    value = match.group(1) or match.group(2) or ""
    return normalize_whitespace(match.group(0)), value


def normalize_size(value: str) -> str:
    cleaned = normalize_whitespace(value)
    mapping = {
        "s": "small",
        "m": "medium",
        "l": "large",
        "xl": "x-large",
        "xxl": "xx-large",
        "2x": "xx-large",
        "3x": "xxx-large",
    }
    return mapping.get(cleaned.lower(), cleaned)


def valid_size_candidate(value: str, match_text: str) -> bool:
    cleaned = value.lower().rstrip("prt")
    if cleaned.isdigit():
        numeric = int(cleaned)
        if numeric < 23 or numeric > 36:
            return False
    return not re.search(r"\b(?:lb|lbs|pounds?|years?|age|waist|hips?|inseam|height)\b", match_text, re.I)


def extract_size(text: str) -> str:
    for pattern in SIZE_PATTERNS:
        match = pattern.search(text)
        if match and valid_size_candidate(match.group(1), match.group(0)):
            return normalize_size(match.group(1))
    return ""


def infer_color(title: str, product_url: str, variant: str) -> Tuple[str, str]:
    haystack = f"{title} {product_url} {variant}".lower().replace("-", " ")
    for color in sorted(COLOR_WORDS, key=len, reverse=True):
        if color in haystack:
            return color, color.title()
    return "", ""


def classify_clothing_type(title: str, product_url: str) -> str:
    value = f"{title} {product_url}".lower()
    if "jean" in value or "denim" in value:
        return "jeans"
    if "pant" in value or "trouser" in value:
        return "pants"
    if "short" in value:
        return "shorts"
    if "jacket" in value:
        return "jacket"
    return ""


def build_search_fts(parts: Iterable[str]) -> str:
    return normalize_whitespace(" ".join(part for part in parts if part))


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


def parse_review_rows(
    review: Dict[str, object],
    product: Dict[str, object],
    fetched_at: str,
) -> List[Dict[str, str]]:
    review_id = normalize_whitespace(str(review.get("uuid") or review.get("id") or ""))
    timestamp = normalize_whitespace(str(review.get("created_at") or ""))
    review_date = timestamp.split("T", 1)[0].split(" ", 1)[0] if timestamp else ""
    reviewer_name = strip_tags(str(review.get("reviewer_name") or ""))
    title = strip_tags(str(review.get("title") or ""))
    body = strip_tags(str(review.get("body") or review.get("body_html") or ""))
    cf_text = cf_answers_text(review)
    product_title = strip_tags(str(review.get("product_title") or product.get("title") or ""))
    product_url = clean_url(str(review.get("product_url_with_utm") or review.get("product_url") or "")) or product_url_for(product)
    variant = normalize_whitespace(str(review.get("product_variant_title") or ""))
    picture_urls = customer_picture_urls(review)
    if not picture_urls:
        return []

    text_pool = normalize_whitespace(" ".join([title, body, cf_text]))
    height_raw, height_in = parse_height_inches(text_pool)
    weight_raw, weight_lbs = parse_numeric(WEIGHT_RE, text_pool)
    waist_raw, waist_in = parse_numeric(WAIST_RE, text_pool, max_value=60)
    hips_raw, hips_in = parse_numeric(HIPS_RE, text_pool, max_value=80)
    age_raw, age_years = parse_age(text_pool)
    _inseam_raw, inseam_in = parse_numeric(INSEAM_RE, text_pool, max_value=40)
    color_canonical, color_display = infer_color(product_title, product_url, variant)
    clothing_type = classify_clothing_type(product_title, product_url)
    size_display = extract_size(text_pool)
    product_variant = normalize_whitespace(" / ".join(part for part in [variant, color_display, size_display] if part))

    rows: List[Dict[str, str]] = []
    for picture_url in picture_urls:
        rows.append(
            {
                "created_at_display": "",
                "id": review_id,
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
                "search_fts": build_search_fts([BRAND, product_title, title, body, cf_text, color_display, size_display]),
                "weight_display_display": maybe_number_text(weight_lbs),
                "weight_raw_needs_correction": "",
                "clothing_type_id": clothing_type,
                "reviewer_profile_url": "",
                "reviewer_name_raw": reviewer_name,
                "inseam_inches_display": maybe_number_text(inseam_in),
                "color_canonical": color_canonical,
                "color_display": color_display,
                "size_display": size_display,
                "bust_in_number_display": "",
                "cupsize_display": "",
                "weight_lbs_display": maybe_number_text(weight_lbs),
                "weight_lbs_raw_issue": "",
                "product_title_raw": product_title,
                "product_subtitle_raw": "",
                "product_description_raw": "",
                "product_detail_raw": "",
                "product_category_raw": clothing_type,
                "product_variant_raw": product_variant,
            }
        )
    return rows


def dedupe_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        key = (row.get("id"), row.get("original_url_display"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def scrape_reviews(
    limit_products: Optional[int] = None,
    limit_pages_per_product: Optional[int] = None,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    products, product_sources = fetch_products(limit_products=limit_products)
    rows: List[Dict[str, str]] = []
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": "oliverlogan_com",
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
        "measurement_extraction": "deterministic_regex_and_provider_fields_only",
        "product_summaries": [],
        "errors": [],
    }

    for index, product in enumerate(products, start=1):
        product_id = product.get("id")
        product_url = product_url_for(product)
        if not product_id:
            continue
        product_rows: List[Dict[str, str]] = []
        skip_reason = output_skip_reason(product)
        page = 1
        pages_scanned_before = int(summary["review_pages_scanned"])
        product_review_count_hint = 0
        errors_before = len(summary["errors"])
        while True:
            if limit_pages_per_product is not None and page > limit_pages_per_product:
                break
            try:
                payload = fetch_json(
                    REVIEWS_FOR_WIDGET_URL,
                    widget_params(product_id, page),
                    referer=product_url or SOURCE_SITE,
                )
            except Exception as exc:  # noqa: BLE001
                summary["errors"].append({"product_id": product_id, "page": page, "error": str(exc)})
                break

            reviews = payload.get("reviews")
            if not isinstance(reviews, list) or not reviews:
                break

            summary["review_pages_scanned"] = int(summary["review_pages_scanned"]) + 1
            product_review_count_hint = max(product_review_count_hint, int(payload.get("number_of_reviews") or 0))

            for review in reviews:
                if isinstance(review, dict):
                    product_rows.extend(parse_review_rows(review, product, fetched_at))

            pagination = payload.get("pagination")
            total_pages = 0
            if isinstance(pagination, dict):
                total_pages = int(pagination.get("total_pages") or 0)
            if total_pages and page >= total_pages:
                break
            page += 1

        summary["products_scanned"] = int(summary["products_scanned"]) + 1
        if skip_reason:
            summary["products_excluded_from_output"] = int(summary["products_excluded_from_output"]) + 1
        if product_rows and not skip_reason:
            summary["products_with_review_rows"] = int(summary["products_with_review_rows"]) + 1
        if not skip_reason:
            rows.extend(product_rows)
        summary["product_review_count_hint"] = int(summary["product_review_count_hint"] or 0) + product_review_count_hint
        summary["product_summaries"].append(
            {
                "product_index": index,
                "product_id": product_id,
                "product_title": product.get("title"),
                "product_url": product_url,
                "review_count_hint": product_review_count_hint,
                "review_pages_scanned": int(summary["review_pages_scanned"]) - pages_scanned_before,
                "matching_review_images": len(product_rows),
                "rows": 0 if skip_reason else len(product_rows),
                "errors": summary["errors"][errors_before:],
                "adapter_used": "judge_me_reviews_for_widget_product_level",
                "skipped_from_output": bool(skip_reason),
                "skip_reason": skip_reason,
            }
        )
        skip_note = f" skipped={skip_reason}" if skip_reason else ""
        print(
            f"[product {index}/{len(products)}] id={product_id} pages={page} rows={0 if skip_reason else len(product_rows)} url={product_url}{skip_note}",
            flush=True,
        )

    summary["finished_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return dedupe_rows(rows), summary


def write_csv(rows: Sequence[Dict[str, str]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in HEADERS})


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


def has_product_url(row: Dict[str, str]) -> bool:
    return bool(row.get("product_page_url_display") or row.get("monetized_product_url_display"))


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
    summary.update(
        {
            "output_csv": str(output_csv),
            "rows_written": len(rows),
            "distinct_reviews": len({row.get("id") for row in rows if row.get("id")}),
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
            "distinct_qualified_reviews": len({row.get("id") for row in rows if row.get("id") and is_supabase_qualified(row)}),
            "rows_with_image_and_product_url": sum(
                1 for row in rows if row.get("original_url_display") and has_product_url(row)
            ),
            "rows_with_image_product_and_measurement": sum(
                1 for row in rows if row.get("original_url_display") and has_product_url(row) and has_measurement(row)
            ),
            "rows_with_image_product_size_and_measurement": sum(1 for row in rows if is_supabase_qualified(row)),
            "rows_with_image_product_and_user_comment": sum(
                1
                for row in rows
                if row.get("original_url_display") and has_product_url(row) and row.get("user_comment")
            ),
            "rows_with_product_context": sum(1 for row in rows if row.get("product_title_raw")),
            "rows_for_bra_products": 0,
            "rows_for_bra_products_with_customer_bra_size": 0,
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

    rows, summary = scrape_reviews(
        limit_products=limit_products,
        limit_pages_per_product=limit_pages_per_product,
    )
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
