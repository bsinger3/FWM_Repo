#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import csv
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Sequence
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from step1_intake_utils import INTAKE_HEADERS


RETAILER = "petiteperfectjeans_com"
SITE_ROOT = "https://petiteperfectjeans.com"
BASE44_API_ROOT = "https://base44.app/api/apps/692767791db4b89b3f31e5a1/functions"
APP_ID = "692767791db4b89b3f31e5a1"
BRANDS = [
    "Abercrombie & Fitch",
    "American Eagle",
    "Gap",
    "J.Crew",
    "Kut from the Kloth",
    "Levi's",
    "Madewell",
    "Mother",
    "Paige",
    "Quince",
    "Ruti",
]
STYLES = [
    "Baggy",
    "Barrel",
    "Bootcut",
    "Flare",
    "Relaxed",
    "Skinny",
    "Slim",
    "Slim-Wide",
    "Straight",
    "Trouser",
    "Ultra Loose",
    "Wide Leg",
]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema_summary.json"
CATALOG_JSON = OUTPUT_DIR / f"{RETAILER}_public_catalog_snapshot.json"


class StopScrape(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def invoke_function(name: str, payload: Dict[str, object], delay: float) -> object:
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        f"{BASE44_API_ROOT}/{name}",
        data=body,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Content-Type": "application/json",
            "X-App-Id": APP_ID,
            "Referer": SITE_ROOT + "/",
        },
    )
    try:
        with urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code in {403, 409, 418, 429}:
            raise StopScrape(f"Stopped after HTTP {exc.code} for public Base44 function {name}") from exc
        raise
    if delay:
        time.sleep(delay)
    return json.loads(text)


def discover_catalog(delay: float) -> Dict[str, object]:
    products: Dict[str, Dict[str, object]] = {}
    function_calls: List[Dict[str, object]] = []
    for inseam in range(23, 31):
        payload = {
            "inseam": inseam,
            "rise": 10,
            "waist": 24,
            "fit": "classic",
            "styles": "all",
            "brands": "all",
        }
        data = invoke_function("searchJeans", payload, delay)
        matches = []
        if isinstance(data, dict):
            matches = [*(data.get("bestMatches") or []), *(data.get("potentialFits") or [])]
        function_calls.append({"function": "searchJeans", "payload": payload, "count": len(matches)})
        for item in matches:
            if not isinstance(item, dict):
                continue
            key = str(item.get("model_id") or item.get("id") or item.get("link") or item.get("model_name"))
            if key:
                products[key] = item

    size_payload = {"brands": BRANDS}
    size_mapping = invoke_function("searchSizeMapping", size_payload, delay)
    function_calls.append(
        {
            "function": "searchSizeMapping",
            "payload": size_payload,
            "count": len(size_mapping) if isinstance(size_mapping, list) else 0,
        }
    )
    return {
        "products": list(products.values()),
        "size_mapping": size_mapping if isinstance(size_mapping, list) else [],
        "function_calls": function_calls,
    }


def write_header_csv() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=INTAKE_HEADERS).writeheader()


def summarize(catalog: Dict[str, object], started_at: str, finished_at: str) -> Dict[str, object]:
    products = catalog["products"] if isinstance(catalog.get("products"), list) else []
    size_mapping = catalog["size_mapping"] if isinstance(catalog.get("size_mapping"), list) else []
    brands = sorted({str(item.get("brand") or "") for item in products if isinstance(item, dict) and item.get("brand")})
    products_with_links = sum(1 for item in products if isinstance(item, dict) and item.get("link"))
    products_with_garment_measurements = sum(
        1
        for item in products
        if isinstance(item, dict)
        and any(item.get(field) is not None for field in ["inseam_in", "front_rise_in_published", "leg_opening_in"])
    )
    return {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "base44_public_jeans_recommendation_catalog_probe",
        "access_policy": "public site pages and public Base44 app functions only; no auth, private endpoints, or challenge handling",
        "product_sources": catalog.get("function_calls", []),
        "products_discovered": len(products),
        "products_scanned": len(products),
        "products_excluded_from_output": len(products),
        "review_pages_scanned": 0,
        "exhaustive_review_paging": False,
        "rows_written": 0,
        "distinct_reviews": 0,
        "distinct_images": 0,
        "rows_with_distinct_product_url": 0,
        "rows_with_any_measurement": 0,
        "rows_with_customer_image": 0,
        "rows_with_customer_ordered_size": 0,
        "rows_supabase_qualified": 0,
        "products_with_links": products_with_links,
        "products_with_garment_measurements": products_with_garment_measurements,
        "size_mapping_rows": len(size_mapping),
        "brands_seen": brands,
        "output_csv": str(OUTPUT_CSV),
        "catalog_snapshot_json": str(CATALOG_JSON),
        "started_at": started_at,
        "finished_at": finished_at,
        "errors": [
            "Public data exposes recommendation/catalog rows and garment measurements, but no customer review image or catalog model image URLs."
        ],
    }


def main() -> int:
    started_at = utc_now()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        catalog = discover_catalog(delay=0.2)
    except StopScrape as exc:
        finished_at = utc_now()
        write_header_csv()
        summary = {
            "site": SITE_ROOT,
            "retailer": RETAILER,
            "adapter": "base44_public_jeans_recommendation_catalog_probe",
            "status": "stopped",
            "stop_reason": str(exc),
            "products_discovered": 0,
            "products_scanned": 0,
            "products_excluded_from_output": 0,
            "review_pages_scanned": 0,
            "exhaustive_review_paging": False,
            "rows_written": 0,
            "distinct_reviews": 0,
            "distinct_images": 0,
            "rows_with_distinct_product_url": 0,
            "rows_with_any_measurement": 0,
            "rows_with_customer_image": 0,
            "rows_with_customer_ordered_size": 0,
            "rows_supabase_qualified": 0,
            "output_csv": str(OUTPUT_CSV),
            "started_at": started_at,
            "finished_at": finished_at,
            "errors": [str(exc)],
        }
        SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)
        return 2
    CATALOG_JSON.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    write_header_csv()
    finished_at = utc_now()
    summary = summarize(catalog, started_at, finished_at)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
