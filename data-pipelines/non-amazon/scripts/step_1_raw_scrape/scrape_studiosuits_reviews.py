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
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "studiosuits_com"
OUTPUT_CSV = OUTPUT_DIR / "studiosuits_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "studiosuits_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://www.studiosuits.com"
SOURCE_SITE = f"{SITE_ROOT}/pages/testimonials"
SHOP_DOMAIN = "studio-suits-prod.myshopify.com"
JUDGEME_API_URL = "https://api.judge.me/reviews/all_reviews_js_based"
BRAND = "StudioSuits"
REVIEWS_PER_PAGE = 10
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
REVIEW_SPLIT_RE = re.compile(r"(?=<div class='jdgm-rev )")
HEIGHT_RE = re.compile(
    r"\b([4-6])\s*(?:ft|feet|foot|['\u2019])\s*(?:(\d{1,2})\s*)?(?:in|inches|[\"\u201d])?",
    re.I,
)
WEIGHT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?|#)\b", re.I)
WAIST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b", re.I)
HIPS_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?(?:\s*old)?)\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*inseam\b", re.I)
BRA_SIZE_RE = re.compile(r"\b((?:2[8-9]|3[0-9]|4[0-8])\s*(?:aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k))\b", re.I)
SIZE_RE = re.compile(
    r"\b(?:size|sz|ordered|wear(?:ing)?|bought|got|purchased)\s*(?:a|an|the|my|:)?\s*"
    r"(\d{1,2}(?:\.\d+)?|xxs|xs|s|m|l|xl|2xl|3xl|4xl|5xl|small|medium|large)\b",
    re.I,
)


def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def strip_tags(value: str) -> str:
    cleaned = re.sub(r"</p\s*>|<br\s*/?>", " ", value or "", flags=re.I)
    return normalize_whitespace(html.unescape(TAG_RE.sub(" ", cleaned)))


def fetch_text(url: str, retries: int = 4) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": SITE_ROOT,
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
        except URLError as exc:
            last_error = exc
        time.sleep(min(2**attempt, 10))
    raise RuntimeError(f"Failed HTML request for {url}: {last_error}")


def fetch_json(url: str, params: Dict[str, object], retries: int = 4) -> Dict[str, object]:
    from urllib.parse import urlencode

    query_url = f"{url}?{urlencode(params)}"
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            query_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/javascript,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": SITE_ROOT,
                "Referer": SOURCE_SITE,
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
        time.sleep(min(2**attempt, 10))
    raise RuntimeError(f"Failed JSON request for {query_url}: {last_error}")


def first_match(pattern: str, text: str, flags: int = re.I | re.S) -> str:
    match = re.search(pattern, text, flags)
    return html.unescape(match.group(1)).strip() if match else ""


def extract_review_blocks(page_html: str) -> List[str]:
    return [block for block in REVIEW_SPLIT_RE.split(page_html) if block.startswith("<div class='jdgm-rev ")]


def extract_images(block: str) -> List[str]:
    pics = first_match(r"<div class='jdgm-rev__pics'>(.*?)</div>", block)
    values = re.findall(r"(?:href|src|data-src)=[\"']([^\"']+)[\"']", pics, flags=re.I)
    images: List[str] = []
    for value in values:
        if "judge.me" in value or "cdn.shopify" in value or value.startswith("//") or value.startswith("/"):
            images.append(urljoin(SITE_ROOT, value))
    return list(dict.fromkeys(images))


def parse_height(text: str) -> Tuple[str, str]:
    match = HEIGHT_RE.search(text)
    if not match:
        return "", ""
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    if inches >= 12:
        return "", ""
    return match.group(0), str(feet * 12 + inches)


def parse_measurements(text: str) -> Dict[str, str]:
    height_raw, height_in = parse_height(text)
    weight = first_match(WEIGHT_RE.pattern, text, re.I)
    waist = first_match(WAIST_RE.pattern, text, re.I)
    hips = first_match(HIPS_RE.pattern, text, re.I)
    age_match = AGE_RE.search(text)
    age = next((part for part in age_match.groups() if part), "") if age_match else ""
    inseam = first_match(INSEAM_RE.pattern, text, re.I)
    bra = first_match(BRA_SIZE_RE.pattern, text, re.I).replace(" ", "").upper()
    bust = ""
    cup = ""
    if bra:
        bra_match = re.match(r"(\d{2})([A-Z]+)", bra)
        if bra_match:
            bust, cup = bra_match.groups()
    size = first_match(SIZE_RE.pattern, text, re.I)
    return {
        "height_raw": height_raw,
        "height_in_display": height_in,
        "weight_raw": weight,
        "weight_display_display": weight,
        "weight_lbs_display": weight,
        "waist_raw_display": waist,
        "waist_in": waist,
        "hips_raw": hips,
        "hips_in_display": hips,
        "age_raw": age,
        "age_years_display": age,
        "inseam_inches_display": inseam,
        "bust_in_number_display": bust,
        "cupsize_display": cup,
        "size_display": normalize_whitespace(size).upper() if size else "",
    }


def classify_product(title: str) -> str:
    text = title.lower()
    if any(term in text for term in ["jean", "pant", "trouser", "short"]):
        return "bottom"
    if any(term in text for term in ["bra", "bikini top"]):
        return "bra"
    if any(term in text for term in ["jacket", "shirt", "vest", "blazer", "coat"]):
        return "top"
    return ""


def parse_review(block: str, fetched_at: str) -> List[Dict[str, str]]:
    review_id = first_match(r"data-review-id='([^']+)'", block)
    review_date = first_match(r"data-content='([^']+)'", block)
    author = strip_tags(first_match(r"<span class='jdgm-rev__author'[^>]*>(.*?)</span>", block))
    product_href = first_match(r"<a href='([^']+)'[^>]*class='jdgm-rev__prod-link'", block)
    product_title = strip_tags(first_match(r"<a href='[^']+'[^>]*class='jdgm-rev__prod-link'[^>]*>(.*?)</a>", block))
    title = strip_tags(first_match(r"<b class='jdgm-rev__title'>(.*?)</b>", block))
    body = strip_tags(first_match(r"<div class='jdgm-rev__body'>(.*?)</div>", block))
    comment = normalize_whitespace(f"{title}. {body}" if title and body else title or body)
    product_url = urljoin(SITE_ROOT, product_href.split("#", 1)[0]) if product_href else ""
    measurements = parse_measurements(comment)
    images = extract_images(block) or [""]
    rows: List[Dict[str, str]] = []
    for image_index, image_url in enumerate(images, start=1):
        row = {header: "" for header in HEADERS}
        row.update(
            {
                "created_at_display": fetched_at,
                "id": f"studiosuits-{review_id}-{image_index}" if review_id else f"studiosuits-unknown-{image_index}",
                "original_url_display": image_url,
                "product_page_url_display": product_url,
                "monetized_product_url_display": product_url,
                "user_comment": comment,
                "date_review_submitted_raw": review_date,
                "review_date": review_date[:10],
                "source_site_display": SITE_ROOT,
                "fetched_at": fetched_at,
                "updated_at": fetched_at,
                "brand": BRAND,
                "reviewer_name_raw": author,
                "product_title_raw": product_title,
                "product_detail_raw": product_title,
                "product_category_raw": classify_product(product_title),
                "clothing_type_id": classify_product(product_title),
                "search_fts": normalize_whitespace(f"{product_title} {comment} {author}"),
            }
        )
        row.update(measurements)
        rows.append(row)
    return rows


def parse_json_review(review: Dict[str, object], fetched_at: str) -> List[Dict[str, str]]:
    review_id = normalize_whitespace(str(review.get("uuid") or ""))
    title = strip_tags(str(review.get("title") or ""))
    body = strip_tags(str(review.get("body") or review.get("body_html") or ""))
    comment = normalize_whitespace(f"{title}. {body}" if title and body else title or body)
    product_title = normalize_whitespace(str(review.get("product_title") or ""))
    product_url_raw = normalize_whitespace(str(review.get("product_url") or ""))
    product_url = urljoin(SITE_ROOT, product_url_raw) if product_url_raw else ""
    if product_url == SITE_ROOT + "/":
        product_url = SITE_ROOT
    product_variant = normalize_whitespace(str(review.get("product_variant_title") or ""))
    created_at = normalize_whitespace(str(review.get("created_at") or ""))
    reviewer_name = normalize_whitespace(str(review.get("reviewer_name") or ""))
    measurements = parse_measurements(comment)
    images: List[str] = []
    for value in review.get("pictures_urls") or []:
        image_url = ""
        if isinstance(value, dict):
            image_url = normalize_whitespace(
                str(value.get("original") or value.get("huge") or value.get("compact") or value.get("small") or "")
            )
        else:
            image_url = normalize_whitespace(str(value))
        if image_url.startswith("https:/") and not image_url.startswith("https://"):
            image_url = "https://" + image_url[len("https:/") :]
        if image_url:
            images.append(urljoin(SITE_ROOT, image_url))
    images = list(dict.fromkeys(images)) or [""]
    rows: List[Dict[str, str]] = []
    for image_index, image_url in enumerate(images, start=1):
        row = {header: "" for header in HEADERS}
        row.update(
            {
                "created_at_display": fetched_at,
                "id": f"studiosuits-{review_id}-{image_index}" if review_id else f"studiosuits-unknown-{image_index}",
                "original_url_display": image_url,
                "product_page_url_display": product_url,
                "monetized_product_url_display": product_url,
                "user_comment": comment,
                "date_review_submitted_raw": created_at,
                "review_date": created_at[:10],
                "source_site_display": SITE_ROOT,
                "fetched_at": fetched_at,
                "updated_at": fetched_at,
                "brand": BRAND,
                "reviewer_name_raw": reviewer_name,
                "product_title_raw": product_title,
                "product_detail_raw": product_title,
                "product_category_raw": classify_product(product_title),
                "product_variant_raw": product_variant,
                "clothing_type_id": classify_product(product_title),
                "search_fts": normalize_whitespace(f"{product_title} {product_variant} {comment} {reviewer_name}"),
            }
        )
        row.update(measurements)
        rows.append(row)
    return rows


def fetch_reviews_page(page: int) -> Dict[str, object]:
    return fetch_json(
        JUDGEME_API_URL,
        {
            "shop_domain": SHOP_DOMAIN,
            "platform": "shopify",
            "widget_type": "all-reviews-widget-v2025",
            "page": page,
            "per_page": REVIEWS_PER_PAGE,
            "review_type": "all-reviews",
            "sort_by": "created_at",
            "sort_dir": "desc",
            "require_json": "true",
        },
    )


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
            "distinct_qualified_reviews": len({row.get("id", "").rsplit("-", 1)[0] for row in rows if row.get("id") and is_supabase_qualified(row)}),
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
            "rows_for_bra_products": sum(1 for row in rows if row.get("clothing_type_id") == "bra"),
            "rows_for_bra_products_with_customer_bra_size": sum(
                1 for row in rows if row.get("clothing_type_id") == "bra" and row.get("bust_in_number_display") and row.get("cupsize_display")
            ),
        }
    )
    return summary


def scrape_reviews(limit_pages: Optional[int] = None) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[Dict[str, object]] = []
    total_count = 0
    total_pages = 0
    pages_scanned = 0
    first_payload: Optional[Dict[str, object]] = None
    try:
        first_payload = fetch_reviews_page(1)
        pagination = first_payload.get("pagination") if isinstance(first_payload.get("pagination"), dict) else {}
        total_count = int(pagination.get("total_count") or 0)
        total_pages = int(pagination.get("total_pages") or math.ceil(total_count / REVIEWS_PER_PAGE) or 1)
    except Exception as exc:
        errors.append({"page": 1, "error": str(exc)})
        total_pages = 0

    pages_to_scan = min(total_pages, limit_pages) if limit_pages else total_pages
    for page in range(1, pages_to_scan + 1):
        try:
            payload = first_payload if page == 1 and first_payload is not None else fetch_reviews_page(page)
            reviews = [item for item in payload.get("reviews", []) if isinstance(item, dict)]
            for review in reviews:
                parsed_rows = parse_json_review(review, started_at)
                rows.extend(parsed_rows)
                product_summaries.append(
                    {
                        "review_uuid": review.get("uuid"),
                        "product_title": review.get("product_title"),
                        "product_url": review.get("product_url"),
                        "matching_review_images": len(review.get("pictures_urls") or []),
                        "has_measurement": any(has_measurement(row) for row in parsed_rows),
                        "has_size": any(row.get("size_display") for row in parsed_rows),
                    }
                )
            pages_scanned += 1
            print(f"[page {page}/{pages_to_scan}] reviews={len(reviews)} rows_total={len(rows)}", flush=True)
            if not reviews:
                break
        except Exception as exc:
            errors.append({"page": page, "error": str(exc)})
            print(f"[page {page}/{pages_to_scan}] error={exc}", flush=True)
            if page == 1:
                break

    if not rows:
        page_html = fetch_text(SOURCE_SITE)
        blocks = extract_review_blocks(page_html)
        for block in blocks:
            rows.extend(parse_review(block, started_at))
    else:
        blocks = []
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": "studiosuits_com",
        "adapter": "judgeme_all_reviews_js_based",
        "source_url": SOURCE_SITE,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "access_policy": "public_pages_only; no_auth_bypass; no_captcha_bypass; polite_retries",
        "review_blocks_found": len(blocks),
        "review_pages_scanned": pages_scanned,
        "review_pages_available": total_pages,
        "review_count_hint": total_count,
        "product_summaries": product_summaries[:200],
        "notes": [
            "Scraper uses the public Judge.me all_reviews_js_based JSON feed for the StudioSuits all-reviews widget.",
            "The static testimonials page remains as a fallback if the JSON feed fails.",
        ],
        "errors": errors,
    }
    return rows, summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    limit_pages: Optional[int] = None
    if "--limit-pages" in argv:
        index = argv.index("--limit-pages")
        limit_pages = int(argv[index + 1])

    rows, summary = scrape_reviews(limit_pages=limit_pages)
    rows.sort(key=lambda row: (row.get("review_date", ""), row.get("product_page_url_display", "")), reverse=True)
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
