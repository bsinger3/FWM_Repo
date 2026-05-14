#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import html
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from step1_intake_utils import INTAKE_HEADERS, normalize_whitespace, strip_tags


RETAILER = "desigual_com"
SITE_ROOT = "https://www.desigual.com"
SITEMAP_INDEX_URL = f"{SITE_ROOT}/es_ES/sitemap_index.xml"
PRODUCT_SITEMAP_RE = re.compile(r"https://www\.desigual\.com/es_ES/sitemap-custom_sitemap_product_es_US\.xml")
BRAND = "Desigual"
DEFAULT_DELAY_SECONDS = 0.12
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
BLOCK_RE = re.compile(
    r"captcha|access denied|attention required|verify you are human|cloudflare challenge|datadome|perimeterx",
    re.I,
)
BLOCK_PAGE_RE = re.compile(
    r"<title>\s*(?:access denied|attention required|captcha|just a moment|verify you are human)\s*</title>|"
    r"<h1[^>]*>\s*(?:access denied|attention required|captcha|verify you are human)\s*</h1>",
    re.I,
)
WOMENS_RE = re.compile(r"\b(woman|women|women's|womens|mujer)\b|/woman/", re.I)
NON_CLOTHING_RE = re.compile(r"\b(bag|wallet|backpack|jewelry|shoe|sneaker|sandal|boot|belt|hat|glove|foulard|phone)\b", re.I)
HEIGHT_CM_RE = re.compile(r"\bheight:\s*(\d+(?:\.\d+)?)\s*cm\b", re.I)
WAIST_CM_RE = re.compile(r"\bwaist:\s*(\d+(?:\.\d+)?)\s*cm\b", re.I)
HIP_CM_RE = re.compile(r"\bhips?:\s*(\d+(?:\.\d+)?)\s*cm\b", re.I)


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema_summary.json"


class StopScrape(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_text(url: str, delay: float) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xml,text/xml,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": SITE_ROOT + "/en_US/",
        },
    )
    try:
        with urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code in {403, 409, 418, 429}:
            raise StopScrape(f"Stopped after HTTP {exc.code} for {url}") from exc
        raise
    except URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc
    first_chunk = body[:100000]
    if BLOCK_PAGE_RE.search(first_chunk) or (
        BLOCK_RE.search(first_chunk)
        and re.search(r"\b(blocked|request id|ray id|security check|unusual traffic|enable cookies)\b", first_chunk, re.I)
    ):
        raise StopScrape(f"Stopped after block/challenge-like content for {url}")
    if delay:
        time.sleep(delay)
    return body


def clean_url(url: object) -> str:
    text = html.unescape(normalize_whitespace(url))
    parts = urlsplit(text)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def discover_product_urls(delay: float) -> Tuple[List[str], List[Dict[str, object]]]:
    index_text = fetch_text(SITEMAP_INDEX_URL, delay)
    sitemap_urls = [html.unescape(match) for match in re.findall(r"<loc>(.*?)</loc>", index_text, re.I)]
    product_sitemaps = [url for url in sitemap_urls if PRODUCT_SITEMAP_RE.fullmatch(url)]
    sources: List[Dict[str, object]] = [{"source": "sitemap_index", "url": SITEMAP_INDEX_URL, "count": len(sitemap_urls)}]
    product_urls: List[str] = []
    for sitemap_url in product_sitemaps:
        sitemap_text = fetch_text(sitemap_url, delay)
        urls = [html.unescape(match) for match in re.findall(r"<loc>(.*?)</loc>", sitemap_text, re.I)]
        urls = [url.replace("/es_US/", "/en_US/") for url in urls if url.endswith(".html")]
        product_urls.extend(urls)
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
    deduped = list(dict.fromkeys(clean_url(url) for url in product_urls if url))
    sources.append({"source": "reconciled_products", "count": len(deduped), "duplicates_removed": len(product_urls) - len(deduped)})
    return deduped, sources


def parse_initial_product(page_html: str) -> Optional[Dict[str, object]]:
    match = re.search(r':initial-product="(.*?)"\s+:is-bundle', page_html, re.S)
    if not match:
        return None
    try:
        return json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError:
        return None


def cm_to_inches(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(round(float(value) / 2.54, 1))
    except ValueError:
        return ""


def classify_clothing(product: Dict[str, object]) -> str:
    text = " ".join(
        normalize_whitespace(product.get(field)).lower()
        for field in ["productName", "primaryCategoryName", "primaryCategoryId", "longDescription"]
    )
    if "jean" in text or "trouser" in text or "pants" in text:
        return "pants"
    if "dress" in text:
        return "dress"
    if "skirt" in text:
        return "skirt"
    if "jacket" in text or "coat" in text:
        return "jacket"
    if "shirt" in text or "top" in text or "t-shirt" in text or "sweatshirt" in text:
        return "top"
    if "swim" in text or "bikini" in text:
        return "swimwear"
    return ""


def skip_reason(product: Optional[Dict[str, object]], product_url: str) -> str:
    if not product:
        return "missing_initial_product_json"
    category_bits = " ".join(str(x) for x in product.get("categoryIds", []) if x) if isinstance(product.get("categoryIds"), list) else ""
    text = " ".join(
        normalize_whitespace(value)
        for value in [
            product.get("productName"),
            product.get("primaryCategoryName"),
            product.get("primaryCategoryId"),
            category_bits,
            product_url,
        ]
        if value
    )
    if not WOMENS_RE.search(text):
        return "out_of_scope_no_womens_signal"
    if NON_CLOTHING_RE.search(text) and not re.search(r"\b(clothing|apparel|dress|jean|skirt|shirt|top|trouser|jacket|coat)\b", text, re.I):
        return "out_of_scope_accessory_or_non_clothing"
    if not product.get("heightDescription"):
        return "missing_model_measurements"
    if not product.get("sizeDescription"):
        return "missing_model_size"
    images = product.get("images")
    large_images = images.get("large") if isinstance(images, dict) else []
    if not isinstance(large_images, list) or not large_images:
        return "missing_catalog_model_image"
    return ""


def image_url(product: Dict[str, object]) -> str:
    images = product.get("images")
    large_images = images.get("large") if isinstance(images, dict) else []
    if not isinstance(large_images, list):
        return ""
    for image in large_images:
        if isinstance(image, dict) and image.get("url"):
            return html.unescape(str(image["url"]).replace("&amp;", "&"))
    return ""


def row_from_product(product: Dict[str, object], product_url: str, fetched_at: str) -> Dict[str, str]:
    measurements = normalize_whitespace(product.get("heightDescription"))
    height = cm_to_inches((HEIGHT_CM_RE.search(measurements) or [None, ""])[1])
    waist = cm_to_inches((WAIST_CM_RE.search(measurements) or [None, ""])[1])
    hips = cm_to_inches((HIP_CM_RE.search(measurements) or [None, ""])[1])
    product_name = normalize_whitespace(product.get("productName"))
    category = normalize_whitespace(product.get("primaryCategoryName") or product.get("primaryCategoryId"))
    description = strip_tags(product.get("longDescription"))
    size = normalize_whitespace(product.get("sizeDescription"))
    row = {header: "" for header in INTAKE_HEADERS}
    row.update(
        {
            "id": f"{normalize_whitespace(product.get('id'))}-catalog-model",
            "original_url_display": image_url(product),
            "image_source_type": "catalog_model_image",
            "image_source_detail": "desigual_product_page_model_image",
            "product_page_url_display": product_url,
            "height_raw": measurements,
            "user_comment": f"Catalog model measurements: {measurements}. Model wears {size}.",
            "height_in_display": height,
            "source_site_display": SITE_ROOT + "/",
            "status_code": "200",
            "fetched_at": fetched_at,
            "updated_at": fetched_at,
            "brand": BRAND,
            "waist_raw_display": measurements,
            "hips_raw": measurements,
            "waist_in": waist,
            "hips_in_display": hips,
            "search_fts": normalize_whitespace(f"{BRAND} {product_name} {description} {measurements} {size}"),
            "clothing_type_id": classify_clothing(product),
            "size_display": size,
            "product_title_raw": product_name,
            "product_description_raw": description,
            "product_category_raw": category,
            "product_variant_raw": normalize_whitespace(product.get("id")),
        }
    )
    return row


def write_csv(rows: Sequence[Dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INTAKE_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in INTAKE_HEADERS})


def count_measurement_rows(rows: Sequence[Dict[str, str]]) -> int:
    fields = ["height_in_display", "weight_display_display", "weight_lbs_display", "bust_in_number_display", "hips_in_display", "waist_in", "inseam_inches_display"]
    return sum(1 for row in rows if any(row.get(field) for field in fields))


def scrape(limit_products: Optional[int], delay: float) -> Dict[str, object]:
    started_at = utc_now()
    product_urls, sources = discover_product_urls(delay)
    if limit_products is not None:
        product_urls = product_urls[:limit_products]
        sources.append({"source": "limit_products_debug", "count": len(product_urls)})
    fetched_at = utc_now()
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    excluded = 0
    errors: List[str] = []
    for index, product_url in enumerate(product_urls, 1):
        try:
            page_html = fetch_text(product_url, delay)
            product = parse_initial_product(page_html)
            reason = skip_reason(product, product_url)
            if reason:
                excluded += 1
            else:
                assert product is not None
                rows.append(row_from_product(product, product_url, fetched_at))
            product_summaries.append(
                {
                    "index": index,
                    "product_url": product_url,
                    "product_id": normalize_whitespace(product.get("id")) if product else "",
                    "product_title": normalize_whitespace(product.get("productName")) if product else "",
                    "product_category": normalize_whitespace(product.get("primaryCategoryName") or product.get("primaryCategoryId")) if product else "",
                    "skipped_from_output": bool(reason),
                    "skip_reason": reason,
                    "matching_catalog_model_rows": 0 if reason else 1,
                }
            )
        except StopScrape:
            raise
        except Exception as exc:
            excluded += 1
            errors.append(f"{product_url}: {exc}")
            product_summaries.append(
                {
                    "index": index,
                    "product_url": product_url,
                    "skipped_from_output": True,
                    "skip_reason": f"error: {exc}",
                    "matching_catalog_model_rows": 0,
                }
            )
        if index % 100 == 0:
            print(f"[product {index}/{len(product_urls)}] rows={len(rows)} excluded={excluded}", flush=True)
    write_csv(rows)
    finished_at = utc_now()
    rows_with_measurement = count_measurement_rows(rows)
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "salesforce_sitemap_product_pages_catalog_model_measurements",
        "access_policy": "public sitemap and product pages only; stopped on 429/captcha/WAF/challenge responses",
        "product_sources": sources,
        "products_discovered": len(product_urls),
        "products_scanned": len(product_urls),
        "products_excluded_from_output": excluded,
        "review_pages_scanned": 0,
        "exhaustive_review_paging": False,
        "rows_written": len(rows),
        "distinct_reviews": 0,
        "distinct_images": len({row["original_url_display"] for row in rows if row.get("original_url_display")}),
        "rows_with_distinct_product_url": len({row["product_page_url_display"] for row in rows if row.get("product_page_url_display")}),
        "rows_with_any_measurement": rows_with_measurement,
        "rows_with_customer_image": 0,
        "rows_with_catalog_model_image": sum(1 for row in rows if row.get("image_source_type") == "catalog_model_image"),
        "rows_with_customer_ordered_size": sum(1 for row in rows if row.get("size_display")),
        "rows_supabase_qualified": 0,
        "rows_catalog_model_qualified": sum(1 for row in rows if row.get("original_url_display") and row.get("product_page_url_display") and row.get("size_display") and any(row.get(field) for field in ["height_in_display", "waist_in", "hips_in_display"])),
        "output_csv": str(OUTPUT_CSV),
        "started_at": started_at,
        "finished_at": finished_at,
        "product_summaries": product_summaries,
        "errors": errors,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape Desigual public catalog model measurement rows.")
    parser.add_argument("--limit-products", type=int, default=None)
    parser.add_argument("--request-delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    args = parser.parse_args()
    try:
        summary = scrape(args.limit_products, args.request_delay_seconds)
    except StopScrape as exc:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        summary = {
            "site": SITE_ROOT,
            "retailer": RETAILER,
            "adapter": "salesforce_sitemap_product_pages_catalog_model_measurements",
            "stopped": True,
            "stop_reason": str(exc),
            "rows_written": 0,
            "products_discovered": 0,
            "products_scanned": 0,
            "products_excluded_from_output": 0,
            "review_pages_scanned": 0,
            "rows_with_distinct_product_url": 0,
            "rows_with_any_measurement": 0,
            "rows_with_customer_image": 0,
            "rows_with_customer_ordered_size": 0,
            "rows_supabase_qualified": 0,
            "output_csv": str(OUTPUT_CSV),
            "finished_at": utc_now(),
        }
        SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)
        return 2
    print(json.dumps({k: summary.get(k) for k in [
        "products_discovered",
        "products_scanned",
        "products_excluded_from_output",
        "rows_written",
        "distinct_images",
        "rows_with_distinct_product_url",
        "rows_with_any_measurement",
        "rows_with_customer_image",
        "rows_with_catalog_model_image",
        "rows_with_customer_ordered_size",
        "rows_supabase_qualified",
        "rows_catalog_model_qualified",
        "output_csv",
    ]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
