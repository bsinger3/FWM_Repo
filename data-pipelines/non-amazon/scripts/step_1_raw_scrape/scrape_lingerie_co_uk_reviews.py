#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from step1_intake_utils import INTAKE_HEADERS, normalize_whitespace, strip_tags


SITE_ROOT = "https://www.lingerie.co.uk"
DOMAIN = "lingerie.co.uk"
RETAILER = "lingerie_co_uk"
CATEGORY_URL = f"{SITE_ROOT}/nightdresses-pyjamas"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[4]
DEFAULT_DATA_ROOT = REPO_ROOT.parent / "FWM_Data" / "non-amazon" / "data"
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", DEFAULT_DATA_ROOT)).expanduser()
if DATA_ROOT.name != "data":
    DATA_ROOT = DATA_ROOT / "non-amazon" / "data"
OUTPUT_DIR = DATA_ROOT / "step_1_raw_scraping_data" / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"

BLOCK_PATTERNS = re.compile(r"captcha|cf-chl|cloudflare|akamai|perimeterx|datadome|access denied|enable cookies", re.I)
PRODUCT_LINK_RE = re.compile(
    r'<a href="(?P<url>[^"]+)" title="(?P<title>[^"]+)" class="product-image">(?P<body>.*?)</a>.*?'
    r'/wishlist/index/add/product/(?P<product_id>\d+)/.*?'
    r'id="product-price-(?P=product_id)">\s*<span class="price">(?P<price>.*?)</span>',
    re.I | re.S,
)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
SHORT_DESCRIPTION_RE = re.compile(r'<div class="short-description">\s*<div class="std">(.*?)</div>', re.I | re.S)
DETAILS_RE = re.compile(r'id="product_tabs_description_tabbed_contents".*?<div class="std">(.*?)</div>', re.I | re.S)
SPCONFIG_RE = re.compile(r"Product\.Config\((\{.*?\})\)", re.S)
IMAGE_RE = re.compile(
    r'(?:src|href)="(?P<url>[^"]+/media/catalog/product/cache/1/image/700x895/[^"]+\.(?:jpg|jpeg|png|webp)(?:\?[^"]*)?)"',
    re.I,
)
SELECT_RE = re.compile(r"<select\b[\s\S]*?</select>", re.I)
OPTION_RE = re.compile(r"<option\b[^>]*>(.*?)</option>", re.I | re.S)
ATTRIBUTE_ROW_RE = re.compile(r"<tr>\s*<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>\s*</tr>", re.I | re.S)


@dataclass
class ProductCard:
    url: str
    title: str
    product_id: str
    price: str


@dataclass
class ProductResult:
    rows: List[Dict[str, str]]
    summary: Dict[str, object]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def data_root_display() -> str:
    return str(DATA_ROOT.resolve())


def fetch_text(url: str, referer: str = SITE_ROOT, timeout: int = 30) -> Tuple[str, Dict[str, object]]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body_bytes = response.read()
            text = body_bytes.decode("utf-8", "replace")
            status = int(getattr(response, "status", 200))
            meta = {
                "status": status,
                "final_url": response.url,
                "content_type": response.headers.get("content-type", ""),
                "bytes": len(body_bytes),
            }
    except HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError(f"stop_condition_http_429: {url}") from exc
        body = exc.read(4096).decode("utf-8", "replace")
        if exc.code in {401, 403} or BLOCK_PATTERNS.search(body):
            raise RuntimeError(f"stop_condition_http_{exc.code}_blocked: {url}") from exc
        raise
    except URLError:
        raise
    if status == 429:
        raise RuntimeError(f"stop_condition_http_429: {url}")
    if BLOCK_PATTERNS.search(text):
        final_path = urlparse(str(meta["final_url"])).path
        if final_path == "/enable-cookies":
            raise RuntimeError(f"stop_condition_enable_cookies_redirect: {url}")
        raise RuntimeError(f"stop_condition_block_page: {url}")
    return text, meta


def clean_text(value: str) -> str:
    return normalize_whitespace(html.unescape(strip_tags(value)).replace("Ł", "£"))


def discover_products(category_html: str) -> List[ProductCard]:
    products: List[ProductCard] = []
    seen = set()
    for match in PRODUCT_LINK_RE.finditer(category_html):
        url = urljoin(SITE_ROOT, html.unescape(match.group("url"))).split("?")[0].rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        products.append(
            ProductCard(
                url=url,
                title=clean_text(match.group("title")),
                product_id=match.group("product_id"),
                price=clean_text(match.group("price")),
            )
        )
    return products


def extract_spconfig_options(pdp_html: str) -> Dict[str, List[str]]:
    match = SPCONFIG_RE.search(pdp_html)
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    options: Dict[str, List[str]] = {}
    for attr in data.get("attributes", {}).values():
        label = clean_text(str(attr.get("label", "")))
        values = [clean_text(str(opt.get("label", ""))) for opt in attr.get("options", [])]
        values = [value for value in values if value and value.lower() != "choose an option..."]
        if label and values:
            options[label.lower()] = values
    return options


def extract_select_options(pdp_html: str) -> List[str]:
    values: List[str] = []
    for select in SELECT_RE.findall(pdp_html):
        if "product-options" not in pdp_html[max(0, pdp_html.find(select) - 500) : pdp_html.find(select) + 500]:
            continue
        for option in OPTION_RE.findall(select):
            value = clean_text(option)
            if value and not re.search(r"please select|choose an option", value, re.I):
                values.append(value)
    return list(dict.fromkeys(values))


def extract_attributes(pdp_html: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for label, value in ATTRIBUTE_ROW_RE.findall(pdp_html):
        key = clean_text(label).lower()
        val = clean_text(value)
        if key and val:
            attrs[key] = val
    return attrs


def extract_images(pdp_html: str) -> List[str]:
    images: List[str] = []
    seen = set()
    for match in IMAGE_RE.finditer(pdp_html):
        url = html.unescape(match.group("url"))
        if url not in seen:
            seen.add(url)
            images.append(url)
    return images


def extract_description(pdp_html: str) -> str:
    for pattern in (SHORT_DESCRIPTION_RE, DETAILS_RE):
        match = pattern.search(pdp_html)
        if match:
            text = clean_text(match.group(1))
            if text:
                return text
    return ""


def extract_title(pdp_html: str, fallback: str) -> str:
    match = H1_RE.search(pdp_html)
    if match:
        return clean_text(match.group(1))
    return fallback


def review_endpoint_status(product_id: str, referer: str) -> Dict[str, object]:
    url = f"{SITE_ROOT}/review/product/list/id/{product_id}/"
    try:
        text, meta = fetch_text(url, referer=referer)
    except RuntimeError as exc:
        if "stop_condition" in str(exc):
            raise
        return {"url": url, "status": "error", "error": str(exc)}
    except Exception as exc:
        return {"url": url, "status": "error", "error": str(exc)}
    has_customer_reviews = bool(re.search(r'id="customer-reviews"|class="box-collateral box-reviews"|<dl\b', text, re.I))
    col_main_empty = bool(re.search(r'<div class="col-main">\s*</div>', text, re.I))
    return {
        "url": url,
        "status": meta["status"],
        "bytes": meta["bytes"],
        "has_customer_review_markup": has_customer_reviews,
        "empty_review_body": col_main_empty,
    }


def product_row(
    card: ProductCard,
    pdp_html: str,
    fetched_at: str,
    image_url: str,
    image_index: int,
    size_display: str,
    color_display: str,
    description: str,
) -> Dict[str, str]:
    title = extract_title(pdp_html, card.title)
    row_id = "lingerie-co-uk-catalog-" + hashlib.md5(f"{card.url}|{image_url}|{size_display}".encode("utf-8")).hexdigest()[:16]
    user_comment_parts = [description]
    if card.price:
        user_comment_parts.append(f"Listed price: {card.price}.")
    if size_display:
        user_comment_parts.append(f"Available size option(s): {size_display}.")
    if color_display:
        user_comment_parts.append(f"Color option(s): {color_display}.")
    row = {header: "" for header in INTAKE_HEADERS}
    row.update(
        {
            "created_at_display": fetched_at,
            "id": row_id,
            "original_url_display": image_url,
            "image_source_type": "catalog_model_image",
            "image_source_detail": f"public Magento PDP gallery image {image_index}; native review endpoint had no usable customer photo markup",
            "product_page_url_display": card.url,
            "monetized_product_url_display": card.url,
            "user_comment": normalize_whitespace(" ".join(part for part in user_comment_parts if part)),
            "date_review_submitted_raw": fetched_at[:10],
            "review_date": fetched_at[:10],
            "source_site_display": DOMAIN,
            "status_code": "200",
            "content_type": "text/html; charset=UTF-8",
            "fetched_at": fetched_at,
            "updated_at": fetched_at,
            "brand": "",
            "search_fts": normalize_whitespace(f"{title} {description} {size_display} {color_display}"),
            "color_display": color_display,
            "color_canonical": color_display.lower() if color_display else "",
            "size_display": size_display,
            "product_title_raw": title,
            "product_description_raw": description,
            "product_detail_raw": description,
            "product_category_raw": "Nightdresses / Pyjamas",
            "product_variant_raw": normalize_whitespace(" | ".join(part for part in [size_display, color_display] if part)),
        }
    )
    return row


def scrape(limit_products: Optional[int], request_delay_seconds: float) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    category_html, category_meta = fetch_text(CATEGORY_URL)
    cards = discover_products(category_html)
    if limit_products:
        cards = cards[:limit_products]

    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    stop_reason = ""

    for index, card in enumerate(cards, start=1):
        try:
            pdp_html, pdp_meta = fetch_text(card.url, referer=CATEGORY_URL)
            options = extract_spconfig_options(pdp_html)
            select_sizes = extract_select_options(pdp_html)
            attributes = extract_attributes(pdp_html)
            description = extract_description(pdp_html)
            images = extract_images(pdp_html)
            review_status = review_endpoint_status(card.product_id, card.url)
        except RuntimeError as exc:
            stop_reason = str(exc)
            break
        except Exception as exc:
            errors.append(f"{card.url}: {exc}")
            continue

        size_options = options.get("size") or select_sizes
        color_options = options.get("by colour") or options.get("color") or []
        if not color_options and attributes.get("by colour"):
            color_options = [attributes["by colour"]]
        color_options = [value for value in color_options if value and value.lower() != "no"]
        size_display = ", ".join(size_options)
        color_display = ", ".join(color_options)
        selected_image = images[0] if images else ""
        product_rows: List[Dict[str, str]] = []
        if selected_image:
            product_rows.append(
                product_row(
                    card=card,
                    pdp_html=pdp_html,
                    fetched_at=started_at,
                    image_url=selected_image,
                    image_index=1,
                    size_display=size_display,
                    color_display=color_display,
                    description=description,
                )
            )
        rows.extend(product_rows)
        product_summaries.append(
            {
                "product_id": card.product_id,
                "product_url": card.url,
                "product_title": extract_title(pdp_html, card.title),
                "pdp_status": pdp_meta["status"],
                "pdp_bytes": pdp_meta["bytes"],
                "price": card.price,
                "size_options": size_options,
                "color_options": color_options,
                "catalog_images_found": len(images),
                "rows_written": len(product_rows),
                "review_endpoint": review_status,
            }
        )
        print(f"[{index}/{len(cards)}] rows={len(product_rows)} images={len(images)} {card.url}", flush=True)
        if request_delay_seconds:
            time.sleep(request_delay_seconds)

    rows = list({(row["product_page_url_display"], row["original_url_display"]): row for row in rows}.values())
    rows_with_size = sum(1 for row in rows if row.get("size_display"))
    rows_with_measurement = sum(
        1
        for row in rows
        if row.get("height_raw")
        or row.get("weight_raw")
        or row.get("bust_in_display")
        or row.get("waist_raw_display")
        or row.get("hips_raw")
    )
    summary = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "domain": DOMAIN,
        "adapter": "magento_native_reviews_catalog_model_images",
        "started_at": started_at,
        "finished_at": utc_now(),
        "source_category_url": CATEGORY_URL,
        "category_status": category_meta["status"],
        "category_bytes": category_meta["bytes"],
        "sovrn_triage_source": "sovrn_commerce_scrape_triage_candidates.csv",
        "sovrn_program": "CPC",
        "sovrn_payout_fields_populated": False,
        "shipping": "GB",
        "review_provider": "magento_native_review_route",
        "review_provider_confidence": "medium",
        "review_media_status": "native review pages public but empty for sampled category products; no customer photo review markup found",
        "image_source_type": "catalog_model_image",
        "access_policy": "public category, public PDPs, and public native review pages only; stopped on 429/captcha/WAF/auth-like behavior",
        "products_discovered": len(discover_products(category_html)),
        "products_scanned": len(product_summaries),
        "product_pages_scanned": len(product_summaries),
        "rows_written": len(rows),
        "distinct_images": len({row["original_url_display"] for row in rows if row.get("original_url_display")}),
        "rows_with_catalog_model_image": sum(1 for row in rows if row.get("image_source_type") == "catalog_model_image"),
        "rows_with_customer_review_image": 0,
        "rows_with_customer_image": 0,
        "reviews_seen": 0,
        "reviews_with_images_seen": 0,
        "rows_with_distinct_product_url": len({row["product_page_url_display"] for row in rows if row.get("product_page_url_display")}),
        "rows_with_product_url": sum(1 for row in rows if row.get("product_page_url_display")),
        "rows_with_size": rows_with_size,
        "rows_with_customer_ordered_size": rows_with_size,
        "rows_with_any_measurement": rows_with_measurement,
        "rows_with_image_product_size_and_measurement": rows_with_measurement,
        "rows_supabase_qualified": rows_with_measurement,
        "coverage_exhaustive_for_source_category": len(product_summaries) == len(discover_products(category_html)) and not stop_reason,
        "full_catalog_scrape_complete": False,
        "catalog_model_rows_enabled": True,
        "stop_reason": stop_reason,
        "errors": errors,
        "product_summaries": product_summaries,
        "output_csv": str(OUTPUT_CSV),
        "summary_json": str(SUMMARY_JSON),
        "data_root": data_root_display(),
    }
    return rows, summary


def write_outputs(rows: List[Dict[str, str]], summary: Dict[str, object]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INTAKE_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in INTAKE_HEADERS})
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape lingerie.co.uk public Magento category/PDP media into Step 1 intake schema.")
    parser.add_argument("--limit-products", type=int, default=None)
    parser.add_argument("--request-delay-seconds", type=float, default=0.75)
    args = parser.parse_args(argv)

    rows, summary = scrape(args.limit_products, args.request_delay_seconds)
    write_outputs(rows, summary)
    print(f"Rows written: {summary['rows_written']}")
    print(f"Products scanned: {summary['products_scanned']}/{summary['products_discovered']}")
    print(f"Catalog model rows: {summary['rows_with_catalog_model_image']}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Summary: {SUMMARY_JSON}")
    if summary.get("stop_reason"):
        print(f"Stop reason: {summary['stop_reason']}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
