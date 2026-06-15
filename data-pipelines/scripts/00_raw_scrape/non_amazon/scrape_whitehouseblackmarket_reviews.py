#!/usr/bin/env python3
from __future__ import annotations
import sys

import argparse
import csv
import html
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, legacy_raw_run_dir, raw_scraped_data_root, reports_root  # noqa: E402
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlencode, urlparse

from step1_intake_utils import INTAKE_HEADERS


DATA_ROOT = Path(os.environ["FWM_DATA_DIR"]).expanduser() if os.environ.get("FWM_DATA_DIR") else Path(__file__).resolve().parents[4].parent / "FWM_Data"
OUTPUT_DIR = legacy_raw_run_dir("whitehouseblackmarket_com")
OUTPUT_CSV = OUTPUT_DIR / "whitehouseblackmarket_com_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "whitehouseblackmarket_com_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://www.whitehouseblackmarket.com"
SITEMAP_URL = f"{SITE_ROOT}/sitemap/products-1.xml"
LEAD_URL = f"{SITE_ROOT}/store/product/bandage-wrap-bustier/570388667"
BAZAARVOICE_BASE = "https://apps.bazaarvoice.com/bfd/v1/clients/WhiteHouseBlackMarket/api-products/cv2/resources/data/reviews.json"
DISPLAY_CODE = "3015-en_us"
BV_BFD_TOKEN = "3015,main_site,en_US"

BLOCK_MARKERS = [
    "cf-chl",
    "just a moment",
    "attention required",
    "verify you are human",
    "please verify you are a human",
    "access denied",
]

APPAREL_RE = re.compile(
    r"\b(dress|jean|pant|trouser|legging|short|skirt|top|shirt|tee|tank|blouse|camisole|"
    r"bustier|bodysuit|sweater|jacket|coat|blazer|vest|cardigan|jumpsuit|romper)\b",
    re.I,
)
OUT_OF_SCOPE_RE = re.compile(
    r"\b(bracelet|necklace|earring|belt|bag|tote|shoe|sandal|boot|hat|scarf|sunglasses|"
    r"wallet|gift|perfume|fragrance)\b",
    re.I,
)


class StopScrape(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def request_text(url: str) -> str:
    try:
        output = subprocess.check_output(
            ["curl", "-L", "-sS", "--max-time", "45", "-w", "\n__FWM_HTTP_STATUS__:%{http_code}", url],
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        raise StopScrape(f"curl_failed_exit_{exc.returncode}: {url}: {norm(exc.output)}") from exc
    body, status_text = output.rsplit("\n__FWM_HTTP_STATUS__:", 1)
    status = int(status_text.strip() or "0")
    if status in {403, 408, 409, 429, 503}:
        raise StopScrape(f"blocked_or_rate_limited_http_{status}: {url}")
    lower = body.lower()
    if any(marker in lower for marker in BLOCK_MARKERS):
        raise StopScrape(f"blocked_or_challenge_marker: {url}")
    return body


def fetch_product_urls() -> List[str]:
    text = request_text(SITEMAP_URL)
    urls = [norm(match) for match in re.findall(r"<loc>(.*?)</loc>", text, re.I | re.S)]
    urls = [url for url in urls if url.startswith(f"{SITE_ROOT}/store/product/") and re.search(r"/\d+(?:[?#].*)?$", url)]
    if LEAD_URL not in urls:
        urls.append(LEAD_URL)
    return sorted(dict.fromkeys(urls))


def product_id_from_url(product_url: str) -> str:
    match = re.search(r"/(\d+)(?:[?#].*)?$", product_url)
    return match.group(1) if match else ""


def title_from_url(product_url: str) -> str:
    path = urlparse(product_url).path.rstrip("/")
    slug = path.split("/")[-2] if "/" in path else path
    return norm(slug.replace("-", " ").title())


def classify_product(title: str, product_url: str) -> Tuple[bool, str, str]:
    value = f"{title} {product_url}"
    if OUT_OF_SCOPE_RE.search(value) and not APPAREL_RE.search(value):
        return False, "out_of_scope_accessory_or_non_clothing", ""
    if not APPAREL_RE.search(value):
        return False, "out_of_scope_non_apparel", ""
    lower = value.lower()
    for token in ["dress", "jean", "pant", "trouser", "legging", "short", "skirt", "top", "shirt", "tee", "tank", "blouse", "bustier", "bodysuit", "sweater", "jacket", "coat", "blazer", "vest", "cardigan", "jumpsuit", "romper"]:
        if token in lower:
            return True, "", token
    return True, "", ""


def fetch_bazaarvoice_json(params: Dict[str, object]) -> Dict[str, object]:
    url = f"{BAZAARVOICE_BASE}?{urlencode(params, doseq=True)}"
    try:
        output = subprocess.check_output(
            [
                "curl",
                "-sS",
                "--max-time",
                "45",
                "-w",
                "\n__FWM_HTTP_STATUS__:%{http_code}",
                url,
                "-H",
                f"bv-bfd-token: {BV_BFD_TOKEN}",
                "-H",
                f"origin: {SITE_ROOT}",
                "-H",
                f"referer: {SITE_ROOT}/",
                "-H",
                "accept: */*",
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        raise StopScrape(f"curl_failed_exit_{exc.returncode}: {url}: {norm(exc.output)}") from exc
    body, status_text = output.rsplit("\n__FWM_HTTP_STATUS__:", 1)
    status = int(status_text.strip() or "0")
    if status in {403, 408, 409, 429, 503}:
        raise StopScrape(f"blocked_or_rate_limited_http_{status}: {url}")
    lower = body.lower()
    if any(marker in lower for marker in BLOCK_MARKERS):
        raise StopScrape(f"blocked_or_challenge_marker: {url}")
    return json.loads(body)


def fetch_photo_reviews(product_id: str) -> Tuple[List[Dict[str, object]], int]:
    reviews: List[Dict[str, object]] = []
    pages = 0
    seen = set()
    limit = 50
    offset = 0
    while True:
        payload = fetch_bazaarvoice_json(
            {
                "resource": "reviews",
                "action": "PHOTOS_TYPE",
                "filter": [
                    f"productid:eq:{product_id}",
                    "contentlocale:eq:en_US,en_US",
                    "isratingsonly:eq:false",
                    "HasMedia:eq:true",
                ],
                "filter_reviews": "contentlocale:eq:en_US,en_US",
                "include": "authors,products,comments",
                "filteredstats": "reviews",
                "Stats": "Reviews",
                "limit": limit,
                "offset": offset,
                "limit_comments": 3,
                "sort": "submissiontime:desc",
                "Offset": offset,
                "apiversion": "5.5",
                "displaycode": DISPLAY_CODE,
            }
        )
        pages += 1
        response = payload.get("response") or {}
        results = response.get("Results") or []
        if not isinstance(results, list) or not results:
            break
        for review in results:
            review_id = norm(review.get("Id"))
            if review_id and review_id not in seen:
                seen.add(review_id)
                reviews.append(review)
        total = int(response.get("TotalResults") or 0)
        offset += limit
        if offset >= total:
            break
    return reviews, pages


def context_value(review: Dict[str, object], key: str) -> str:
    values = review.get("ContextDataValues") or {}
    if not isinstance(values, dict):
        return ""
    item = values.get(key) or {}
    return norm(item.get("Value") if isinstance(item, dict) else "")


def additional_value(review: Dict[str, object], key: str) -> str:
    values = review.get("AdditionalFields") or {}
    if not isinstance(values, dict):
        return ""
    item = values.get(key) or {}
    return norm(item.get("Value") if isinstance(item, dict) else "")


def normalize_size(value: str) -> str:
    raw = norm(value)
    upper = raw.upper()
    mapping = {"XXS": "xx-small", "XS": "x-small", "S": "small", "M": "medium", "L": "large", "XL": "x-large", "XXL": "xx-large"}
    return mapping.get(upper, raw)


def height_display(raw: str) -> str:
    mapping = {
        "Under_5": "under 5 ft",
        "5_0_5_3": "5 ft 0 in - 5 ft 3 in",
        "5_4_5_6": "5 ft 4 in - 5 ft 6 in",
        "5_7_5_9": "5 ft 7 in - 5 ft 9 in",
        "5_10_6_0": "5 ft 10 in - 6 ft 0 in",
        "Over_6": "over 6 ft",
    }
    return mapping.get(raw, raw.replace("_", " "))


def weight_display(raw: str) -> str:
    if re.fullmatch(r"\d+_\d+", raw):
        return raw.replace("_", "-") + " lb"
    return raw.replace("_", " ")


def photo_url(photo: Dict[str, object]) -> str:
    sizes = photo.get("Sizes") or {}
    if not isinstance(sizes, dict):
        return ""
    for key in ["large", "normal", "thumbnail"]:
        item = sizes.get(key) or {}
        if isinstance(item, dict) and item.get("Url"):
            return norm(item.get("Url"))
    return ""


def build_row(product_url: str, product_title: str, clothing_type: str, review: Dict[str, object], photo: Dict[str, object], fetched_at: str) -> Dict[str, str]:
    image_url = photo_url(photo)
    review_id = norm(review.get("Id"))
    photo_id = norm(photo.get("Id"))
    size = normalize_size(additional_value(review, "SizePurchased_1"))
    height_raw = height_display(context_value(review, "Height"))
    weight_raw = weight_display(context_value(review, "Weight"))
    body_type = context_value(review, "BodyType")
    title = norm(review.get("Title"))
    text = norm(review.get("ReviewText"))
    comment = norm(" ".join(part for part in [title, text, f"Body type: {body_type}" if body_type else ""] if part))
    row = {header: "" for header in INTAKE_HEADERS}
    row.update(
        {
            "created_at_display": fetched_at,
            "id": f"whbm-{review_id}-{photo_id}",
            "original_url_display": image_url,
            "image_source_type": "customer_review_image",
            "image_source_detail": "public Bazaarvoice review photo",
            "product_page_url_display": product_url,
            "height_raw": height_raw,
            "weight_raw": weight_raw,
            "user_comment": comment,
            "date_review_submitted_raw": norm(review.get("SubmissionTime")),
            "review_date": norm(review.get("SubmissionTime"))[:10],
            "source_site_display": "whitehouseblackmarket_com",
            "status_code": "200",
            "content_type": "application/json",
            "fetched_at": fetched_at,
            "updated_at": fetched_at,
            "brand": "White House Black Market",
            "search_fts": " ".join(part for part in [product_title, comment, height_raw, weight_raw, size] if part),
            "weight_display_display": weight_raw,
            "clothing_type_id": clothing_type,
            "reviewer_name_raw": norm(review.get("UserNickname")),
            "size_display": size,
            "product_title_raw": product_title,
            "product_variant_raw": additional_value(review, "UsualSize_1"),
        }
    )
    return row


def process_product(product_url: str, fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    product_id = product_id_from_url(product_url)
    fallback_title = title_from_url(product_url)
    reviews, pages = fetch_photo_reviews(product_id)
    rows: List[Dict[str, str]] = []
    product_title = fallback_title
    in_scope, skip_reason, clothing_type = classify_product(product_title, product_url)
    for review in reviews:
        product_title = norm(review.get("OriginalProductName")) or product_title
        in_scope, skip_reason, clothing_type = classify_product(product_title, product_url)
        if not in_scope:
            continue
        for photo in review.get("Photos") or []:
            if isinstance(photo, dict):
                row = build_row(product_url, product_title, clothing_type, review, photo, fetched_at)
                if row.get("original_url_display"):
                    rows.append(row)
    summary = {
        "product_url": product_url,
        "product_id": product_id,
        "product_title": product_title,
        "review_pages_scanned": pages,
        "photo_reviews_found": len(reviews),
        "rows": len(rows),
        "skipped_from_output": not rows,
        "skip_reason": "" if rows else (skip_reason if not in_scope else "no_customer_review_images"),
    }
    return rows, summary


def dedupe_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        key = (row.get("id"), row.get("original_url_display"), row.get("product_page_url_display"))
        if key not in seen:
            seen.add(key)
            deduped.append(dict(row))
    return deduped


def write_csv(rows: Sequence[Dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INTAKE_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in INTAKE_HEADERS})


def metrics(rows: Sequence[Dict[str, str]]) -> Dict[str, int]:
    measurement_fields = [
        "height_in_display",
        "weight_display_display",
        "weight_lbs_display",
        "bust_in_number_display",
        "hips_in_display",
        "waist_in",
        "inseam_inches_display",
    ]
    return {
        "rows_written": len(rows),
        "distinct_reviews": len({row.get("id", "").rsplit("-", 1)[0] for row in rows if row.get("id")}),
        "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
        "rows_with_distinct_product_url": len({row.get("product_page_url_display", "") or row.get("monetized_product_url_display", "") for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display")}),
        "rows_with_any_measurement": sum(1 for row in rows if any(row.get(field) for field in measurement_fields)),
        "rows_with_customer_image": sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image"),
        "rows_with_catalog_model_image": sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "catalog_model_image"),
        "rows_with_customer_ordered_size": sum(1 for row in rows if row.get("size_display") and row.get("size_display") != "unknown"),
        "rows_supabase_qualified": sum(
            1
            for row in rows
            if row.get("original_url_display")
            and (row.get("product_page_url_display") or row.get("monetized_product_url_display"))
            and row.get("size_display")
            and row.get("size_display") != "unknown"
            and any(row.get(field) for field in measurement_fields)
        ),
    }


def run(args: argparse.Namespace) -> Dict[str, object]:
    started_at = utc_now()
    urls = list(args.product_url) if args.product_url else fetch_product_urls()
    if args.limit_products:
        urls = urls[: args.limit_products]
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    stopped_early = False
    review_pages_scanned = 0
    for index, url in enumerate(urls, start=1):
        try:
            product_rows, product_summary = process_product(url, started_at)
        except StopScrape as exc:
            errors.append(str(exc))
            stopped_early = True
            break
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            product_summary = {
                "product_url": url,
                "product_id": product_id_from_url(url),
                "rows": 0,
                "review_pages_scanned": 0,
                "skipped_from_output": True,
                "skip_reason": "fetch_or_parse_error",
            }
            product_rows = []
        review_pages_scanned += int(product_summary.get("review_pages_scanned") or 0)
        rows.extend(product_rows)
        product_summaries.append(product_summary)
        print(f"[product {index}/{len(urls)}] rows={len(product_rows)} total={len(rows)} {url}", flush=True)
        if args.request_delay_seconds:
            time.sleep(args.request_delay_seconds)
    rows = dedupe_rows(rows)
    write_csv(rows)
    finished_at = utc_now()
    summary: Dict[str, object] = {
        "site": "whitehouseblackmarket.com",
        "retailer": "whitehouseblackmarket_com",
        "adapter": "bazaarvoice_bfd_sitemap_photo_reviews",
        "triage_rank": 59,
        "triage_bucket": "build adapter / API inspect",
        "review_platform_provider": "Bazaarvoice",
        "product_sources": {"sitemap_products_xml": 0 if args.product_url else len(urls), "lead_urls": 1, "cli_product_urls": len(args.product_url)},
        "products_discovered": len(urls),
        "products_scanned": len(product_summaries),
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "review_pages_scanned": review_pages_scanned,
        "exhaustive_review_paging": not stopped_early,
        "coverage_exhaustive": not stopped_early and not errors and not args.limit_products and len(product_summaries) == len(urls),
        "access_policy": "public sitemap and Bazaarvoice BFD review JSON only; stop on 429/captcha/WAF",
        "product_summaries": product_summaries,
        "errors": errors,
        "output_csv": str(OUTPUT_CSV),
        "started_at": started_at,
        "finished_at": finished_at,
    }
    summary.update(metrics(rows))
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape White House Black Market Bazaarvoice customer review photos.")
    parser.add_argument("--limit-products", type=int, default=0)
    parser.add_argument("--product-url", action="append", default=[], help="Specific WHBM PDP URL to scan; repeatable.")
    parser.add_argument("--request-delay-seconds", type=float, default=0.05)
    args = parser.parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
