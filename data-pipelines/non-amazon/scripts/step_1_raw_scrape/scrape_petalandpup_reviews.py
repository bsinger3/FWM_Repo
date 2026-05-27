#!/usr/bin/env python
"""Scrape Petal & Pup review images from public Shopify catalog and Yotpo JSON."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE = "https://petalandpup.com"
APP_KEY = "JOE1NcE1bLGVtqlxx4dnobIm3hEQidt8DiLL9olv"
SOURCE_SITE = "https://petalandpup.com/"

CSV_COLUMNS = [
    "created_at_display",
    "id",
    "original_url_display",
    "image_source_type",
    "image_source_detail",
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

OUT_OF_SCOPE_RE = re.compile(
    r"\b(earring|necklace|bracelet|ring|belt|bag|clutch|wallet|hat|cap|scarf|shoe|sandal|boot|heel|"
    r"gift|card|perfume|candle|sunglasses|headband|clip|scrunchie)\b",
    re.I,
)
APPAREL_RE = re.compile(
    r"\b(dress|top|shirt|blouse|bodysuit|skirt|pant|jean|short|jumpsuit|romper|coat|jacket|"
    r"blazer|vest|cardigan|sweater|knit|set|gown|maxi|midi|mini|clothing)\b",
    re.I,
)


def data_root() -> Path:
    if os.environ.get("FWM_DATA_DIR"):
        return Path(os.environ["FWM_DATA_DIR"])
    cwd_candidate = Path.cwd() / "FWM_Data"
    if cwd_candidate.exists():
        return cwd_candidate
    return Path(__file__).resolve().parents[4] / "FWM_Data"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


SUSPICIOUS_RE = re.compile(r"(captcha|cloudflare|access denied|temporarily blocked|suspicious request|bot detection|waf)", re.I)


def suspicious_response(status: int | None, body: str) -> str:
    if status == 429:
        return "rate_limited"
    if status in {403, 503} and SUSPICIOUS_RE.search(body or ""):
        return "suspicious_request"
    if SUSPICIOUS_RE.search((body or "")[:5000]):
        return "suspicious_request"
    return ""


def fetch_json(url: str, timeout: int = 30, retries: int = 0, delay: float = 0.5) -> tuple[int | None, dict[str, Any] | None, str]:
    for attempt in range(retries + 1):
        try:
            status, raw, err = fetch_with_curl(url, "application/json,text/plain,*/*", timeout)
            suspicious = suspicious_response(status, raw)
            if suspicious:
                return status, None, suspicious
            if status != 200:
                return status, None, err or f"http_{status}"
            return status, json.loads(raw), ""
        except Exception as exc:
            err = str(exc)
        if attempt < retries:
            time.sleep(delay * (attempt + 1))
    return None, None, err


def fetch_with_curl(url: str, accept: str, timeout: int = 30) -> tuple[int | None, str, str]:
    curl_bin = shutil.which("curl.exe") or shutil.which("curl") or "curl"
    cmd = [
        curl_bin,
        "-sS",
        "-L",
        url,
        "--max-time",
        str(timeout),
        "-w",
        "\n__HTTP_STATUS__:%{http_code}",
        "-H",
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "-H",
        f"Accept: {accept}",
        "-H",
        "Accept-Language: en-US,en;q=0.9",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout + 5,
        check=False,
    )
    output = proc.stdout or ""
    marker = "\n__HTTP_STATUS__:"
    if marker not in output:
        return None, output, proc.stderr.strip()
    body, status_text = output.rsplit(marker, 1)
    try:
        status = int(status_text.strip()[:3])
    except ValueError:
        status = None
    return status, body, proc.stderr.strip()


def fetch_text(url: str, timeout: int = 30, retries: int = 0, delay: float = 0.5) -> tuple[int | None, str, str]:
    for attempt in range(retries + 1):
        try:
            status, body, err = fetch_with_curl(
                url,
                "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                timeout,
            )
            suspicious = suspicious_response(status, body)
            if suspicious:
                return status, "", suspicious
            if status != 200:
                return status, body, err or f"http_{status}"
            return status, body, ""
        except Exception as exc:
            err = str(exc)
        if attempt < retries:
            time.sleep(delay * (attempt + 1))
    return None, "", err


def fetch_products_json_page(page: int) -> tuple[int | None, list[dict[str, Any]], str]:
    url = f"{BASE}/products.json?limit=250&page={page}"
    status, payload, error = fetch_json(url)
    if status != 200 or not payload:
        return status, [], error or f"http_{status}"
    return status, list(payload.get("products") or []), ""


def discover_products_json(limit_pages: int | None, request_delay: float) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    page = 1
    while True:
        if limit_pages and page > limit_pages:
            break
        status, batch, error = fetch_products_json_page(page)
        if status == 429:
            raise RuntimeError(f"catalog_rate_limited_page_{page}")
        if status != 200:
            raise RuntimeError(f"catalog_fetch_failed_page_{page}: {error or status}")
        if not batch:
            break
        products.extend(batch)
        print(f"catalog page {page}: {len(batch)} products; total={len(products)}", flush=True)
        page += 1
        if request_delay:
            time.sleep(request_delay)
    return products


def parse_sitemap_locs(xml_text: str) -> list[str]:
    root = ET.fromstring(xml_text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [loc.text.strip() for loc in root.findall(".//sm:loc", ns) if loc.text]


def discover_product_urls_from_sitemap(request_delay: float) -> list[str]:
    status, xml_text, error = fetch_text(f"{BASE}/sitemap.xml")
    if status != 200:
        raise RuntimeError(f"sitemap_index_fetch_failed: {error or status}")
    sitemap_urls = [url for url in parse_sitemap_locs(xml_text) if "sitemap_products" in url]
    product_urls: OrderedDict[str, None] = OrderedDict()
    for sitemap_url in sitemap_urls:
        status, product_xml, error = fetch_text(sitemap_url)
        if status != 200:
            raise RuntimeError(f"product_sitemap_fetch_failed: {sitemap_url}: {error or status}")
        for url in parse_sitemap_locs(product_xml):
            if "/products/" in url:
                product_urls.setdefault(url.split("?")[0], None)
        print(f"sitemap {Path(urllib.parse.urlparse(sitemap_url).path).name}: total_urls={len(product_urls)}", flush=True)
        if request_delay:
            time.sleep(request_delay)
    return list(product_urls)


def product_from_url(url: str, request_delay: float) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    js_url = url.rstrip("/") + ".js"
    status, payload, error = fetch_json(js_url)
    if request_delay:
        time.sleep(request_delay)
    if status == 429:
        return None, {"url": url, "status": "rate_limited"}
    if status != 200 or not payload:
        return None, {"url": url, "status": "fetch_failed", "error": error or status}
    payload["source_url"] = url
    return payload, {"url": url, "status": "ok"}


def discover_products(limit_pages: int | None, request_delay: float, limit_products: int | None, workers: int) -> list[dict[str, Any]]:
    if limit_pages:
        return discover_products_json(limit_pages, request_delay)
    urls = discover_product_urls_from_sitemap(request_delay)
    if limit_products:
        urls = urls[: max(limit_products * 4, limit_products)]
    products: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(product_from_url, url, request_delay): url for url in urls}
        for idx, future in enumerate(as_completed(futures), 1):
            product, result = future.result()
            if product:
                products.append(product)
            if result.get("status") == "rate_limited":
                raise RuntimeError("product_js_rate_limited")
            if idx % 100 == 0 or idx == len(urls):
                print(f"metadata {idx}/{len(urls)} products; ok={len(products)}", flush=True)
    return products


def is_apparel(product: dict[str, Any]) -> bool:
    text = " ".join(
        str(x or "")
        for x in [
            product.get("title"),
            product.get("handle"),
            product.get("product_type"),
            " ".join(product.get("tags") or []),
        ]
    )
    if OUT_OF_SCOPE_RE.search(text):
        return False
    return bool(APPAREL_RE.search(text))


def product_url(product: dict[str, Any]) -> str:
    return str(product.get("source_url") or f"{BASE}/products/{product.get('handle')}")


def yotpo_reviews(product_id: Any, per_page: int, request_delay: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    first_url = (
        f"https://api-cdn.yotpo.com/v1/widget/{APP_KEY}/products/{product_id}/reviews.json?"
        f"page=1&per_page={per_page}"
    )
    status, payload, error = fetch_json(first_url)
    if request_delay:
        time.sleep(request_delay)
    if status == 429:
        return [], {"status": "rate_limited"}
    if status != 200 or not payload:
        return [], {"status": "fetch_failed", "error": error or status}
    response = payload.get("response") or {}
    pagination = response.get("pagination") or {}
    total = int(pagination.get("total") or 0)
    reviews = list(response.get("reviews") or [])
    pages = max(1, math.ceil(total / per_page)) if total else 1
    for page in range(2, pages + 1):
        url = (
            f"https://api-cdn.yotpo.com/v1/widget/{APP_KEY}/products/{product_id}/reviews.json?"
            f"page={page}&per_page={per_page}"
        )
        status, payload, error = fetch_json(url)
        if request_delay:
            time.sleep(request_delay)
        if status == 429:
            return reviews, {"status": "partial_rate_limited", "total": total}
        if status != 200 or not payload:
            continue
        reviews.extend((payload.get("response") or {}).get("reviews") or [])
    return reviews, {"status": "ok", "total": total, "reviews_seen": len(reviews)}


def custom_fields(review: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in (review.get("custom_fields") or {}).values():
        if not isinstance(field, dict):
            continue
        title = str(field.get("title") or "").strip().lower()
        value = str(field.get("value") or "").strip()
        if title and value:
            values[title] = value
    return values


def parse_bust(value: str) -> tuple[str, str]:
    match = re.search(r"\b(\d{1,3})\s*([A-Za-z]{1,4})\b", value or "")
    return (match.group(1), match.group(2).upper()) if match else ("", value or "")


def normalize_date(value: str) -> str:
    return value[:10] if value and re.match(r"\d{4}-\d{2}-\d{2}", value) else ""


def row_id(product: dict[str, Any], review: dict[str, Any], image: dict[str, Any]) -> str:
    basis = f"petalandpup|{product.get('id')}|{review.get('id')}|{image.get('id')}|{image.get('original_url')}"
    return hashlib.md5(basis.encode("utf-8")).hexdigest()


def rows_for_product(product: dict[str, Any], per_page: int, request_delay: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    reviews, result = yotpo_reviews(product.get("id"), per_page, request_delay)
    rows: list[dict[str, Any]] = []
    now = utc_now()
    purl = product_url(product)
    category = str(product.get("product_type") or "")
    description = re.sub(r"<[^>]+>", " ", str(product.get("body_html") or ""))
    description = re.sub(r"\s+", " ", description).strip()
    title = str(product.get("title") or "")
    for review in reviews:
        images = review.get("images_data") or []
        if not images:
            continue
        fields = custom_fields(review)
        size = fields.get("size", "")
        height = fields.get("height", "")
        weight = fields.get("weight", "")
        bust_num, cup = parse_bust(fields.get("bust size", ""))
        comment = " ".join(part for part in [str(review.get("title") or ""), str(review.get("content") or "")] if part).strip()
        date_raw = str(review.get("created_at") or "")
        user = review.get("user") or {}
        for image in images:
            image_url = image.get("original_url") or image.get("thumb_url")
            if not image_url:
                continue
            rows.append(
                {
                    "created_at_display": date_raw,
                    "id": row_id(product, review, image),
                    "original_url_display": image_url,
                    "image_source_type": "customer_review_image",
                    "image_source_detail": "Yotpo public widget review image",
                    "product_page_url_display": purl,
                    "monetized_product_url_display": "",
                    "height_raw": height,
                    "weight_raw": weight,
                    "user_comment": comment,
                    "date_review_submitted_raw": date_raw,
                    "height_in_display": "",
                    "review_date": normalize_date(date_raw),
                    "source_site_display": SOURCE_SITE,
                    "status_code": "",
                    "content_type": "",
                    "bytes": "",
                    "width": "",
                    "height": "",
                    "hash_md5": "",
                    "fetched_at": now,
                    "updated_at": now,
                    "brand": "Petal & Pup",
                    "waist_raw_display": "",
                    "hips_raw": "",
                    "age_raw": "",
                    "waist_in": "",
                    "hips_in_display": "",
                    "age_years_display": "",
                    "search_fts": " ".join(part for part in [title, comment] if part),
                    "weight_display_display": weight,
                    "weight_raw_needs_correction": "",
                    "clothing_type_id": "",
                    "reviewer_profile_url": "",
                    "reviewer_name_raw": user.get("display_name") or "",
                    "inseam_inches_display": "",
                    "color_canonical": "",
                    "color_display": "",
                    "size_display": size,
                    "bust_in_number_display": bust_num,
                    "cupsize_display": cup,
                    "weight_lbs_display": weight,
                    "weight_lbs_raw_issue": "",
                    "product_title_raw": title,
                    "product_subtitle_raw": "",
                    "product_description_raw": description,
                    "product_detail_raw": "",
                    "product_category_raw": category,
                    "product_variant_raw": size,
                }
            )
    result.update({"product_url": purl, "product_id": product.get("id"), "rows_found": len(rows)})
    return rows, result


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})


def read_existing_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as fh:
        rows = []
        for row in csv.DictReader(fh):
            if row.get("original_url_display") and not row.get("image_source_type"):
                row["image_source_type"] = "customer_review_image"
                row["image_source_detail"] = "Yotpo public widget review image"
            rows.append(dict(row))
        return rows


def read_existing_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def count_qualified(rows: list[dict[str, Any]]) -> int:
    return sum(
        1
        for row in rows
        if row.get("original_url_display")
        and row.get("product_page_url_display")
        and row.get("size_display")
        and (
            row.get("height_raw")
            or row.get("weight_raw")
            or row.get("bust_in_number_display")
            or row.get("cupsize_display")
        )
    )


def merge_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique_rows: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for row in rows:
        key = str(row.get("id") or row.get("original_url_display"))
        unique_rows[key] = row
    return list(unique_rows.values())


def scan_products(apparel_products: list[dict[str, Any]], args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    all_rows: list[dict[str, Any]] = []
    product_results: list[dict[str, Any]] = []
    blocker = ""
    max_workers = max(1, args.workers)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(rows_for_product, product, args.per_page, args.review_delay): product
            for product in apparel_products
        }
        for idx, future in enumerate(as_completed(futures), 1):
            rows, result = future.result()
            all_rows.extend(rows)
            product_results.append(result)
            status = str(result.get("status") or "")
            if "rate_limited" in status or "suspicious" in status:
                blocker = f"review_{status}_{result.get('product_url')}"
                break
            if idx % 50 == 0 or idx == len(apparel_products):
                print(f"processed {idx}/{len(apparel_products)} apparel products; rows={len(all_rows)}", flush=True)
    return all_rows, product_results, blocker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-prefix", default="petalandpup_com")
    parser.add_argument("--limit-products", type=int)
    parser.add_argument("--limit-catalog-pages", type=int)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--catalog-delay", type=float, default=0.25)
    parser.add_argument("--review-delay", type=float, default=0.05)
    parser.add_argument("--resume-existing", action="store_true")
    parser.add_argument("--catalog-start-page", type=int)
    parser.add_argument("--page-checkpoint", action="store_true")
    args = parser.parse_args()

    root = data_root()
    output_dir = root / "non-amazon/data/step_1_raw_scraping_data/petalandpup_com"
    csv_path = output_dir / f"{args.output_prefix}_reviews_matching_intake_schema.csv"
    summary_path = output_dir / f"{args.output_prefix}_reviews_matching_intake_schema_summary.json"
    standard_csv_path = output_dir / f"{args.output_prefix}_reviews_matching_amazon_schema.csv"
    standard_summary_path = output_dir / f"{args.output_prefix}_reviews_matching_amazon_schema_summary.json"
    checkpoint_path = output_dir / f"{args.output_prefix}_catalog_pages_checkpoint.jsonl"
    started = utc_now()

    existing_rows = read_existing_rows(csv_path) if args.resume_existing else []
    existing_summary = read_existing_summary(summary_path) if args.resume_existing else {}
    product_results: list[dict[str, Any]] = list(existing_summary.get("product_results") or [])
    all_rows: list[dict[str, Any]] = list(existing_rows)
    catalog_blocker = ""
    products_discovered = int(existing_summary.get("products_discovered") or 0) if args.resume_existing else 0
    apparel_products_scanned = int(existing_summary.get("apparel_products_scanned") or 0) if args.resume_existing else 0
    pages_completed: list[int] = []

    if args.catalog_start_page or args.page_checkpoint:
        page = args.catalog_start_page or 1
        while True:
            if args.limit_catalog_pages and page > args.limit_catalog_pages:
                break
            status, batch, error = fetch_products_json_page(page)
            if status != 200:
                catalog_blocker = f"products.json page {page}: {error or status}"
                print(f"stopping on catalog blocker: {catalog_blocker}", flush=True)
                break
            if not batch:
                pages_completed.append(page)
                break
            products_discovered += len(batch)
            pages_completed.append(page)
            if args.page_checkpoint:
                with checkpoint_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"page": page, "fetched_at": utc_now(), "products": batch}, ensure_ascii=False) + "\n")
            page_apparel = [product for product in batch if is_apparel(product)]
            if args.limit_products:
                remaining = max(args.limit_products - (apparel_products_scanned if args.resume_existing else 0), 0)
                page_apparel = page_apparel[:remaining]
            print(f"catalog page {page}: {len(batch)} products; apparel_to_scan={len(page_apparel)}", flush=True)
            rows, results, review_blocker = scan_products(page_apparel, args)
            all_rows.extend(rows)
            product_results.extend(results)
            apparel_products_scanned += len(page_apparel)
            all_rows = merge_rows(all_rows)
            write_csv(csv_path, all_rows)
            if review_blocker:
                catalog_blocker = review_blocker
                print(f"stopping on review blocker: {catalog_blocker}", flush=True)
                break
            if args.limit_products and apparel_products_scanned >= args.limit_products:
                break
            page += 1
            if args.catalog_delay:
                time.sleep(args.catalog_delay)
    else:
        products = discover_products(args.limit_catalog_pages, args.catalog_delay, args.limit_products, args.workers)
        products_discovered = len(products)
        apparel_products = [product for product in products if is_apparel(product)]
        if args.limit_products:
            apparel_products = apparel_products[: args.limit_products]
        rows, product_results, catalog_blocker = scan_products(apparel_products, args)
        all_rows.extend(rows)
        apparel_products_scanned = len(apparel_products)

    all_rows = merge_rows(all_rows)
    write_csv(csv_path, all_rows)
    shutil.copyfile(csv_path, standard_csv_path)

    distinct_product_urls = len({row["product_page_url_display"] for row in all_rows})
    summary = {
        "site": "https://petalandpup.com",
        "retailer": "petalandpup_com",
        "adapter": "yotpo_widget_json",
        "status": "blocked_rate_limited_or_suspicious" if catalog_blocker else "completed",
        "started_at": started,
        "finished_at": utc_now(),
        "products_discovered": products_discovered,
        "products_scanned": apparel_products_scanned,
        "apparel_products_scanned": apparel_products_scanned,
        "products_with_review_image_rows": distinct_product_urls,
        "output_csv": str(standard_csv_path),
        "legacy_output_csv": str(csv_path),
        "legacy_summary_json": str(summary_path),
        "rows_written": len(all_rows),
        "distinct_reviews": len({row["id"] for row in all_rows}),
        "distinct_images": len({row["original_url_display"] for row in all_rows}),
        "distinct_products": distinct_product_urls,
        "distinct_product_urls": distinct_product_urls,
        "rows_with_image_url": sum(1 for row in all_rows if row.get("original_url_display")),
        "rows_with_customer_image": sum(1 for row in all_rows if row.get("original_url_display")),
        "rows_with_customer_review_image": sum(
            1
            for row in all_rows
            if row.get("original_url_display") and (row.get("image_source_type") or "customer_review_image") == "customer_review_image"
        ),
        "rows_with_catalog_model_image": sum(
            1 for row in all_rows if row.get("original_url_display") and row.get("image_source_type") == "catalog_model_image"
        ),
        "rows_with_user_comment": sum(1 for row in all_rows if row.get("user_comment")),
        "rows_with_size": sum(1 for row in all_rows if row.get("size_display")),
        "rows_with_customer_ordered_size": sum(1 for row in all_rows if row.get("size_display")),
        "rows_with_any_measurement": sum(
            1
            for row in all_rows
            if row.get("height_raw")
            or row.get("weight_raw")
            or row.get("bust_in_number_display")
            or row.get("cupsize_display")
        ),
        "rows_with_image_and_product_url": sum(
            1 for row in all_rows if row.get("original_url_display") and row.get("product_page_url_display")
        ),
        "rows_with_image_product_and_measurement": sum(
            1
            for row in all_rows
            if row.get("original_url_display")
            and row.get("product_page_url_display")
            and (
                row.get("height_raw")
                or row.get("weight_raw")
                or row.get("bust_in_number_display")
                or row.get("cupsize_display")
            )
        ),
        "rows_with_image_product_size_and_measurement": sum(
            1
            for row in all_rows
            if row.get("original_url_display")
            and row.get("product_page_url_display")
            and row.get("size_display")
            and (
                row.get("height_raw")
                or row.get("weight_raw")
                or row.get("bust_in_number_display")
                or row.get("cupsize_display")
            )
        ),
        "supabase_qualified_rows": count_qualified(all_rows),
        "rows_supabase_qualified": count_qualified(all_rows),
        "review_pages_scanned": len(product_results),
        "review_pages_scanned_this_run": len(product_results),
        "review_pages_scanned_note": "For resume runs, this is the number of product review endpoints scanned in the current delta run; historical full-run page totals were not retained in the legacy summary.",
        "exhaustive_review_paging": not bool(catalog_blocker),
        "full_catalog_scrape_complete": not bool(catalog_blocker),
        "access_policy": "public_product_and_review_pages_only; stop_immediately_on_429_captcha_or_waf_like_response",
        "catalog_pages_completed_this_run": pages_completed,
        "catalog_blocker": catalog_blocker,
        "checkpoint_jsonl": str(checkpoint_path) if checkpoint_path.exists() else "",
        "product_results": product_results,
        "notes": [
            "Catalog discovery uses public Shopify products.json.",
            "Review rows use public Yotpo widget JSON keyed by Shopify product id.",
            "Rows are one per public customer review image URL.",
            "Rows are marked image_source_type=customer_review_image.",
            "Run stops on HTTP 429, captcha, WAF, or suspicious-request responses without aggressive retries.",
        ],
    }
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    with standard_summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    print(json.dumps({k: summary[k] for k in ["rows_written", "products_discovered", "apparel_products_scanned", "rows_with_image_product_size_and_measurement"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
