#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from step1_intake_utils import INTAKE_HEADERS


RETAILER = "prettylittlething_com_au"
DATA_ROOT = (
    Path(os.environ["FWM_DATA_DIR"]).expanduser()
    if os.environ.get("FWM_DATA_DIR")
    else Path(__file__).resolve().parents[4].parent / "FWM_Data"
)
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://www.prettylittlething.com.au"
SAMPLE_CATEGORY_URL = f"{SITE_ROOT}/categories/womens-tops-shirts"
SAMPLE_PDP_URLS = [
    f"{SITE_ROOT}/product/cotton-oversized-cuff-shirt_plt01115?colour=tan",
    f"{SITE_ROOT}/product/striped-oversized-lightweight-shirt_plt12337?colour=blue",
    f"{SITE_ROOT}/product/plt-label-oversized-collar-button-down-fitted-shirt_plt00599?colour=blue",
]
PREFLIGHT_URLS = [SAMPLE_CATEGORY_URL, *SAMPLE_PDP_URLS]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
WAF_MARKERS = [
    "edge.sdk.awswaf.com",
    "challenge.js",
    "awswaf",
    "captcha",
    "verify you are human",
    "access denied",
    "attention required",
    "datadome",
    "perimeterx",
]
PRESSURE_STATUS_CODES = {401, 403, 407, 423, 429, 430, 503}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch(url: str) -> Dict[str, object]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read(1_500_000)
            text = body.decode("utf-8", errors="replace")
            lower = text.lower()
            title = ""
            title_start = lower.find("<title>")
            title_end = lower.find("</title>")
            if title_start >= 0 and title_end > title_start:
                title = text[title_start : title_end + len("</title>")]
            return {
                "url": url,
                "status": response.status,
                "content_type": response.headers.get("content-type", ""),
                "bytes_sampled": len(body),
                "waf_markers": [marker for marker in WAF_MARKERS if marker in lower],
                "title_hint": title,
            }
    except HTTPError as exc:
        body = exc.read(200_000).decode("utf-8", errors="replace")
        lower = body.lower()
        return {
            "url": url,
            "status": exc.code,
            "content_type": exc.headers.get("content-type", ""),
            "bytes_sampled": len(body),
            "waf_markers": [marker for marker in WAF_MARKERS if marker in lower],
            "error": str(exc),
        }
    except URLError as exc:
        return {"url": url, "status": None, "error": str(exc), "waf_markers": []}


def write_header_only_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INTAKE_HEADERS)
        writer.writeheader()


def build_summary(started_at: str, finished_at: str, preflight: List[Dict[str, object]]) -> Dict[str, object]:
    waf_hits = [entry for entry in preflight if entry.get("waf_markers")]
    hard_stops = [
        entry
        for entry in preflight
        if entry.get("status") in PRESSURE_STATUS_CODES or entry.get("waf_markers")
    ]
    return {
        "site": "prettylittlething.com.au",
        "retailer": RETAILER,
        "adapter": "guarded_au_preflight_bazaarvoice",
        "triage_bucket": "sovrn_first_pass_scrape_candidate",
        "triage_source": "data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv",
        "merchant": "PrettyLittleThing AU",
        "review_platform_provider": "Bazaarvoice",
        "photo_reviews_present": True,
        "shipping_geos": "AU|CA|FR|GB|IE|US",
        "estimated_commission_per_click": "$0.04",
        "access_policy": "public AU category/product pages only; stopped_on_waf_challenge_signal",
        "blocked": bool(hard_stops),
        "block_reason": (
            "Public AU category/PDP HTML includes AWS WAF challenge script markers; "
            "no Bazaarvoice endpoint probing or challenge workaround attempted."
        ),
        "stop_reason": "waf_challenge_signal" if hard_stops else "none",
        "product_sources": {
            "sample_category_pages": 1,
            "sample_product_pages": len(SAMPLE_PDP_URLS),
            "usable_product_sources": 0,
        },
        "products_discovered": 0,
        "products_scanned": 0,
        "products_excluded_from_output": 0,
        "review_pages_scanned": 0,
        "exhaustive_review_paging": False,
        "product_review_count_hint": 0,
        "rows_written": 0,
        "distinct_reviews": 0,
        "distinct_images": 0,
        "rows_with_distinct_product_url": 0,
        "rows_with_any_measurement": 0,
        "rows_with_customer_image": 0,
        "rows_with_customer_ordered_size": 0,
        "rows_supabase_qualified": 0,
        "rows_with_customer_review_image": 0,
        "rows_with_catalog_model_image": 0,
        "output_csv": str(OUTPUT_CSV),
        "started_at": started_at,
        "finished_at": finished_at,
        "preflight": preflight,
        "waf_hits": waf_hits,
        "product_summaries": [],
        "errors": hard_stops,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guarded PrettyLittleThing AU Bazaarvoice preflight.")
    parser.parse_args(argv)
    started_at = utc_now()
    preflight = [fetch(url) for url in PREFLIGHT_URLS]
    finished_at = utc_now()
    write_header_only_csv(OUTPUT_CSV)
    SUMMARY_JSON.write_text(
        json.dumps(build_summary(started_at, finished_at, preflight), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
