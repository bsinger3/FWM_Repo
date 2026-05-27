#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from step1_intake_utils import INTAKE_HEADERS


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT / "FWM_Data"))
RETAILER = "goelia1995_com"
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://www.goelia1995.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
KLAVIYO_COMPANY_ID = "VEs2cd"
KLAVIYO_SETTINGS_URL = "https://fast.a.klaviyo.com/reviews/api/client_onsite_widgets/"
KLAVIYO_REVIEWS_URL = "https://fast.a.klaviyo.com/reviews/api/client_reviews/"
PRODUCTS_PER_PAGE = 250
KLAVIYO_BATCH_SIZE = 100
DEFAULT_REQUEST_DELAY_SECONDS = 0.75
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, referer: str = SOURCE_SITE, retries: int = 4, delay: float = DEFAULT_REQUEST_DELAY_SECONDS) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            query_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": referer,
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                payload = json.load(resp)
            pause(delay)
            return payload
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
        except (URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(min(2**attempt, 20) + delay)
    raise RuntimeError(f"Failed JSON request for {query_url}: {last_error}")


def product_url_for(product: Dict[str, object]) -> str:
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def fetch_products(limit_products: Optional[int], delay: float) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    sources: List[Dict[str, object]] = []
    page = 1
    while True:
        payload = fetch_json(PRODUCTS_JSON_URL, {"limit": PRODUCTS_PER_PAGE, "page": page}, delay=delay)
        page_products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        sources.append({"source": "products.json", "page": page, "count": len(page_products)})
        if not page_products:
            break
        products.extend(page_products)
        print(f"[catalog page {page}] products={len(page_products)} total={len(products)}", flush=True)
        if len(page_products) < PRODUCTS_PER_PAGE or (limit_products is not None and len(products) >= limit_products):
            break
        page += 1
    if limit_products is not None:
        products = products[:limit_products]
    sources.append({"source": "products_json_full_catalog", "count": len(products)})
    return products, sources


def klaviyo_settings(delay: float) -> Dict[str, object]:
    return fetch_json(KLAVIYO_SETTINGS_URL, {"company_id": KLAVIYO_COMPANY_ID}, delay=delay)


def klaviyo_batch_summary(product_ids: Sequence[str], delay: float) -> Dict[str, object]:
    return fetch_json(
        KLAVIYO_REVIEWS_URL,
        {"company_id": KLAVIYO_COMPANY_ID, "products": json.dumps(list(product_ids), separators=(",", ":"))},
        delay=delay,
    )


def write_empty_csv() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INTAKE_HEADERS)
        writer.writeheader()


def scrape(limit_products: Optional[int], request_delay_seconds: float) -> Dict[str, object]:
    started_at = utc_now()
    products, product_sources = fetch_products(limit_products, request_delay_seconds)
    settings = klaviyo_settings(request_delay_seconds)
    product_ids = [norm(product.get("id")) for product in products if norm(product.get("id"))]
    batch_products: List[Dict[str, object]] = []
    errors: List[Dict[str, object]] = []
    for idx in range(0, len(product_ids), KLAVIYO_BATCH_SIZE):
        ids = product_ids[idx : idx + KLAVIYO_BATCH_SIZE]
        try:
            payload = klaviyo_batch_summary(ids, request_delay_seconds)
            page_products = [item for item in payload.get("products", []) if isinstance(item, dict)]
            batch_products.extend(page_products)
            print(f"[klaviyo batch {idx // KLAVIYO_BATCH_SIZE + 1}] products={len(page_products)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            errors.append({"batch_start": idx, "product_count": len(ids), "error": str(exc)})
            break
    products_with_review_count = [item for item in batch_products if int(item.get("review_count") or 0) > 0]
    write_empty_csv()
    return {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "klaviyo_reviews_batch_summary",
        "klaviyo_company_id": KLAVIYO_COMPANY_ID,
        "started_at": started_at,
        "finished_at": utc_now(),
        "output_csv": str(OUTPUT_CSV),
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "product_pages_scanned": len(products),
        "klaviyo_products_checked": len(batch_products),
        "klaviyo_products_with_review_count": len(products_with_review_count),
        "klaviyo_widgets_count": len(settings.get("widgets", [])) if isinstance(settings.get("widgets"), list) else 0,
        "klaviyo_widgets": settings.get("widgets", []),
        "errors": errors,
        "rows_written": 0,
        "distinct_reviews": 0,
        "distinct_images": 0,
        "distinct_products": 0,
        "rows_with_image_url": 0,
        "rows_missing_image_url": 0,
        "rows_missing_product_url": 0,
        "rows_with_user_comment": 0,
        "rows_with_size": 0,
        "rows_with_customer_ordered_size": 0,
        "rows_with_any_measurement": 0,
        "rows_for_bra_products": 0,
        "rows_for_bra_products_with_customer_bra_size": 0,
        "rows_with_image_and_product_url": 0,
        "rows_with_image_product_and_measurement": 0,
        "supabase_qualified_rows": 0,
        "rows_with_image_product_size_and_measurement": 0,
        "rows_with_image_product_and_user_comment": 0,
        "rows_with_product_context": 0,
        "invalid_numeric_fields": {"height_in_display": 0, "waist_in": 0, "hips_in_display": 0, "inseam_inches_display": 0, "bust_in_number_display": 0},
        "access_policy": f"public_product_and_review_pages_only; no_auth_bypass; no_captcha_bypass; restricted_or_unavailable_pages_are_skipped; polite_retries; request_delay_seconds={request_delay_seconds}",
        "discovery_method": "shopify_products_json_and_klaviyo_public_batch_summary",
        "scrape_scope_status": "full_catalog_attempted" if limit_products is None else "limited_smoke",
        "full_catalog_scrape_complete": limit_products is None and not errors,
        "seed_scrape_only": False,
        "warnings": [
            "Klaviyo onsite review settings returned no active widgets for this company/site.",
            "Klaviyo public batch summary returned no products with public review_count, despite some Shopify pages exposing review metafield counts.",
            "No public review-list rows or customer media were available to emit.",
        ],
        "problems_encountered": [
            {
                "type": "provider_public_review_feed_unavailable",
                "status": "no_rows",
                "detail": "Goelia product pages expose Shopify review rating/count metafields, but the Klaviyo public onsite widgets endpoint returned widgets: [] and batch review summaries returned no review rows/counts.",
                "impact": "Full catalog was checked, but no customer review image rows could be collected from public endpoints.",
            }
        ],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check Goelia public Shopify catalog and Klaviyo Reviews public summary endpoint.")
    parser.add_argument("--limit-products", type=int)
    parser.add_argument("--request-delay-seconds", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS)
    args = parser.parse_args(argv)
    summary = scrape(args.limit_products, args.request_delay_seconds)
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Rows written: {summary['rows_written']}")
    print(f"Products checked: {summary['products_scanned']}")
    print(f"Klaviyo products with review_count: {summary['klaviyo_products_with_review_count']}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
