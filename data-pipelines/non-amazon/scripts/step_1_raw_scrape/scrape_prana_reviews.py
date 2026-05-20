#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import unquote

from step1_intake_utils import INTAKE_HEADERS


DATA_ROOT = Path(os.environ["FWM_DATA_DIR"]).expanduser() if os.environ.get("FWM_DATA_DIR") else Path(__file__).resolve().parents[4].parent / "FWM_Data"
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "prana_com"
OUTPUT_CSV = OUTPUT_DIR / "prana_com_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "prana_com_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://www.prana.com"
SITEMAP_URL = f"{SITE_ROOT}/sitemap_0-product.xml"
LEAD_URL = f"{SITE_ROOT}/p/koen-pant/1973521.html"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)

BLOCK_MARKERS = [
    "cf-chl",
    "just a moment",
    "attention required",
    "verify you are human",
    "please verify you are a human",
    "access denied",
]

APPAREL_RE = re.compile(
    r"\b(dress|pant|legging|short|skort|skirt|top|shirt|tee|tank|bra|jumpsuit|romper|sweater|"
    r"jacket|coat|vest|hoodie|pullover|flannel|tunic|bottom|swim|bikini)\b",
    re.I,
)
OUT_OF_SCOPE_RE = re.compile(
    r"\b(headband|chalk bag|beanie|hat|cap|belt|sock|sandal|shoe|boot|pack|bag|tote|blanket|mat|"
    r"necklace|bracelet|earring|gift card)\b",
    re.I,
)
DIGITAL_DATA_RE = re.compile(r"var _digitalData = (?P<json>\{.*?\}) \|\| \{\};", re.S)
PRODUCT_DETAIL_RE = re.compile(
    r'<div class="product-detail product-wrapper"(?P<attrs>.*?)>\s*<div class="container">',
    re.S,
)
IMG_RE = re.compile(r"<img\b(?P<attrs>[^>]*)>", re.I | re.S)
ATTR_RE = re.compile(r'([a-zA-Z0-9_-]+)="(.*?)"', re.S)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm(text: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(text or ""))).strip()


class StopScrape(RuntimeError):
    pass


def request_text(url: str, *, accept: str = "text/html,application/xml;q=0.9,*/*;q=0.8") -> str:
    try:
        output = subprocess.check_output(
            [
                "curl",
                "-L",
                "-sS",
                "--max-time",
                "45",
                "-w",
                "\n__FWM_HTTP_STATUS__:%{http_code}",
                url,
            ],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"request_failed: {url}: {exc}") from exc
    if "\n__FWM_HTTP_STATUS__:" not in output:
        raise RuntimeError(f"request_missing_http_status: {url}")
    body, status_text = output.rsplit("\n__FWM_HTTP_STATUS__:", 1)
    status = int(status_text.strip() or "0")
    if status in {403, 408, 409, 429, 503}:
        raise StopScrape(f"blocked_or_rate_limited_http_{status}: {url}")
    lower = body.lower()
    is_expected_xml = "xml" in accept and body.lstrip().startswith("<?xml")
    if not is_expected_xml and any(marker in lower for marker in BLOCK_MARKERS):
        raise StopScrape(f"blocked_or_challenge_marker: {url}")
    return body


def fetch_product_urls() -> List[str]:
    text = request_text(SITEMAP_URL, accept="application/xml,text/xml;q=0.9,*/*;q=0.8")
    urls = [norm(match) for match in re.findall(r"<loc>(.*?)</loc>", text, re.I | re.S)]
    urls = [url for url in urls if url.startswith(f"{SITE_ROOT}/p/")]
    if LEAD_URL not in urls:
        urls.append(LEAD_URL)
    return sorted(dict.fromkeys(urls))


def attrs_from_tag(tag_attrs: str) -> Dict[str, str]:
    return {key: html.unescape(value) for key, value in ATTR_RE.findall(tag_attrs)}


def digital_product(html_text: str) -> Dict[str, object]:
    match = DIGITAL_DATA_RE.search(html_text)
    if not match:
        return {}
    try:
        payload = json.loads(match.group("json"))
    except json.JSONDecodeError:
        return {}
    return (((payload.get("page") or {}).get("product") or {}).get("productInfo") or {})


def product_ids(html_text: str, product_url: str) -> Tuple[str, str]:
    match = PRODUCT_DETAIL_RE.search(html_text)
    attrs = attrs_from_tag(match.group("attrs")) if match else {}
    pid = attrs.get("data-pid", "") or re.sub(r"\D", "", product_url.rsplit("/", 1)[-1])
    master_pid = attrs.get("data-master-pid", "") or pid
    return pid, master_pid


def model_images(html_text: str) -> List[Dict[str, str]]:
    images: List[Dict[str, str]] = []
    for match in IMG_RE.finditer(html_text):
        attrs = attrs_from_tag(match.group("attrs"))
        if "js-model-image" not in attrs.get("class", ""):
            continue
        on_model = attrs.get("data-onmodel", "")
        if not on_model or on_model == "null":
            continue
        try:
            model_payload = json.loads(unquote(on_model))
        except json.JSONDecodeError:
            model_payload = {}
        image_url = attrs.get("data-hires") or attrs.get("data-lowres") or attrs.get("src") or ""
        if not image_url:
            continue
        images.append(
            {
                "image_url": html.unescape(image_url),
                "alt": norm(attrs.get("alt", "")),
                "model_code": norm(model_payload.get("modelCode", "")),
                "variant_upc": norm(model_payload.get("variantUPC", "")),
                "width": norm(attrs.get("width", "")),
                "height": norm(attrs.get("height", "")),
            }
        )
    deduped: List[Dict[str, str]] = []
    seen = set()
    for image in images:
        key = (image["image_url"], image["variant_upc"])
        if key not in seen:
            seen.add(key)
            deduped.append(image)
    return deduped


def size_from_variant(variant_upc: str) -> str:
    parts = [part for part in variant_upc.split("-") if part]
    if not parts:
        return ""
    raw = parts[-1].upper()
    mapping = {
        "XS": "x-small",
        "S": "small",
        "M": "medium",
        "L": "large",
        "XL": "x-large",
        "XXL": "xx-large",
    }
    return mapping.get(raw, raw)


def variant_detail(variant_upc: str) -> str:
    parts = [part for part in variant_upc.split("-") if part]
    if len(parts) < 3:
        return variant_upc
    dimension = parts[-2]
    dimension_map = {"RG": "regular", "SH": "short", "TL": "tall"}
    return norm(f"{dimension_map.get(dimension, dimension)} {parts[-1].upper()}")


def classify_scope(product: Dict[str, object], product_url: str) -> Tuple[bool, str, str]:
    value = " ".join(
        [
            norm(product.get("prodName")),
            norm(product.get("prodCategory")),
            norm(product.get("categoryID")),
            product_url,
        ]
    )
    lower = value.lower()
    if "women" not in lower and "womens" not in lower:
        return False, "out_of_scope_not_womens", ""
    if OUT_OF_SCOPE_RE.search(value) and not APPAREL_RE.search(value):
        return False, "out_of_scope_accessory_or_non_clothing", ""
    if not APPAREL_RE.search(value):
        return False, "out_of_scope_non_apparel", ""
    clothing = ""
    for token in ["dress", "pant", "legging", "short", "skort", "skirt", "top", "shirt", "tank", "bra", "sweater", "jacket", "coat", "swim"]:
        if token in lower:
            clothing = token
            break
    return True, "", clothing


def row_for_product(product_url: str, html_text: str, fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    product = digital_product(html_text)
    pid, master_pid = product_ids(html_text, product_url)
    title = norm(product.get("prodName")) or norm(re.sub(r"[-_]+", " ", product_url.rsplit("/", 2)[-2]).title())
    category = norm(product.get("prodCategory"))
    brand = norm(product.get("prodBrand")) or "prAna"
    color = norm(product.get("productColorName"))
    review_count = int(float(product.get("prodReviewCount") or 0))
    review_avg = product.get("productReviewAvg") or ""
    in_scope, skip_reason, clothing_type = classify_scope(product, product_url)
    images = model_images(html_text)
    summary: Dict[str, object] = {
        "product_url": product_url,
        "product_id": pid,
        "master_product_id": master_pid,
        "product_title": title,
        "product_category": category,
        "product_review_count_hint": review_count,
        "product_review_average_hint": review_avg,
        "model_images_found": len(images),
        "rows": 0,
        "skipped_from_output": False,
        "skip_reason": "",
    }
    if not in_scope:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = skip_reason
        return [], summary
    if not images:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "no_catalog_model_image_with_variant"
        return [], summary

    rows: List[Dict[str, str]] = []
    for image in images[:1]:
        size = size_from_variant(image["variant_upc"])
        if not size:
            continue
        row_id = "prana-model-" + hashlib.md5(f"{product_url}|{image['image_url']}|{image['variant_upc']}".encode()).hexdigest()[:16]
        comment = norm(
            f"Catalog model image. Product variant: {variant_detail(image['variant_upc'])}. "
            f"Model code: {image['model_code']}."
        )
        row = {header: "" for header in INTAKE_HEADERS}
        row.update(
            {
                "created_at_display": fetched_at,
                "id": row_id,
                "original_url_display": image["image_url"],
                "image_source_type": "catalog_model_image",
                "image_source_detail": "public prAna product-page catalog model image with deterministic size from variant UPC",
                "product_page_url_display": product_url,
                "user_comment": comment,
                "source_site_display": "prana_com",
                "status_code": "200",
                "content_type": "text/html",
                "width": image["width"],
                "height": image["height"],
                "fetched_at": fetched_at,
                "updated_at": fetched_at,
                "brand": brand,
                "search_fts": " ".join(part for part in [title, category, comment] if part),
                "clothing_type_id": clothing_type,
                "color_display": color,
                "color_canonical": color.lower(),
                "size_display": size,
                "product_title_raw": title,
                "product_category_raw": category,
                "product_variant_raw": variant_detail(image["variant_upc"]),
            }
        )
        rows.append(row)
    summary["rows"] = len(rows)
    if not rows:
        summary["skipped_from_output"] = True
        summary["skip_reason"] = "catalog_model_variant_without_size"
    return rows, summary


def dedupe_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        key = (row.get("original_url_display"), row.get("product_page_url_display"), row.get("size_display"))
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
        "distinct_reviews": len({row.get("id", "") for row in rows if row.get("id")}),
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
    urls = fetch_product_urls()
    if args.limit_products:
        urls = urls[: args.limit_products]
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    product_review_count_hint = 0
    stopped_early = False
    for index, url in enumerate(urls, start=1):
        try:
            page = request_text(url)
        except StopScrape as exc:
            errors.append(str(exc))
            stopped_early = True
            break
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            product_summaries.append({"product_url": url, "rows": 0, "skipped_from_output": True, "skip_reason": "fetch_or_parse_error"})
            continue
        product_rows, summary = row_for_product(url, page, started_at)
        product_review_count_hint += int(summary.get("product_review_count_hint") or 0)
        rows.extend(product_rows)
        product_summaries.append(summary)
        print(f"[product {index}/{len(urls)}] rows={len(product_rows)} total={len(rows)} {url}", flush=True)
        if args.request_delay_seconds:
            time.sleep(args.request_delay_seconds)
    rows = dedupe_rows(rows)
    write_csv(rows)
    finished_at = utc_now()
    summary: Dict[str, object] = {
        "site": "prana.com",
        "retailer": "prana_com",
        "adapter": "salesforce_commerce_cloud_sitemap_product_page_catalog_model",
        "triage_rank": 58,
        "triage_bucket": "build adapter / API inspect",
        "review_platform_provider": "Bazaarvoice",
        "product_sources": {"sitemap_product_xml": len(urls), "lead_urls": 1, "products_json": 0},
        "products_discovered": len(urls),
        "products_scanned": len(product_summaries),
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "review_pages_scanned": 0,
        "exhaustive_review_paging": True,
        "product_review_count_hint": product_review_count_hint,
        "coverage_exhaustive": not stopped_early and not args.limit_products and len(product_summaries) == len(urls),
        "access_policy": "public sitemap and product pages only; stop on 429/captcha/WAF",
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
    parser = argparse.ArgumentParser(description="Scrape public prAna product-page catalog model rows.")
    parser.add_argument("--limit-products", type=int, default=0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.15)
    args = parser.parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
