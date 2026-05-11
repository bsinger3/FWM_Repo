#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from step1_intake_utils import INTAKE_HEADERS


DATA_ROOT = Path(
    __import__("os").environ.get("FWM_DATA_DIR", "/Users/briannasinger/Projects/FWM_Data")
)
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "karenmillen_com"
OUTPUT_CSV = OUTPUT_DIR / "karenmillen_com_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "karenmillen_com_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://www.karenmillen.com"
PREFLIGHT_URLS = [
    f"{SITE_ROOT}/",
    f"{SITE_ROOT}/us/categories/womens-dresses",
    f"{SITE_ROOT}/us/sitemap.xml",
    f"{SITE_ROOT}/products.json?limit=1",
]
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
WAF_MARKERS = [
    "edge.sdk.awswaf.com",
    "challenge.js",
    "awswaf",
    "captcha",
    "verify you are human",
    "access denied",
    "attention required",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch(url: str) -> Dict[str, object]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read(1_000_000)
            text = body.decode("utf-8", errors="replace")
            return {
                "url": url,
                "status": response.status,
                "content_type": response.headers.get("content-type", ""),
                "bytes_sampled": len(body),
                "waf_markers": [marker for marker in WAF_MARKERS if marker in text.lower()],
                "title_hint": text[text.lower().find("<title>") : text.lower().find("</title>") + 8]
                if "<title>" in text.lower()
                else "",
            }
    except HTTPError as exc:
        body = exc.read(200_000).decode("utf-8", errors="replace")
        return {
            "url": url,
            "status": exc.code,
            "content_type": exc.headers.get("content-type", ""),
            "bytes_sampled": len(body),
            "waf_markers": [marker for marker in WAF_MARKERS if marker in body.lower()],
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
        if entry.get("status") in {403, 429}
        or entry.get("waf_markers")
        or ("404 Resource Not Found" in str(entry.get("title_hint", "")) and "sitemap" in str(entry.get("url", "")))
    ]
    return {
        "site": "karenmillen.com",
        "retailer": "karenmillen_com",
        "adapter": "guarded_preflight_bazaarvoice",
        "triage_bucket": "build adapter / API inspect",
        "review_platform_provider": "Bazaarvoice",
        "access_policy": "stopped_on_waf_challenge_signal",
        "blocked": bool(hard_stops),
        "block_reason": "Public HTML includes AWS WAF challenge script; sitemap/products probes returned rendered 404 HTML rather than usable public feeds.",
        "product_sources": {
            "homepage": 1,
            "category_probe": 1,
            "sitemap_probe": 1,
            "products_json_probe": 1,
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
    parser = argparse.ArgumentParser(description="Guarded Karen Millen Bazaarvoice preflight.")
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
