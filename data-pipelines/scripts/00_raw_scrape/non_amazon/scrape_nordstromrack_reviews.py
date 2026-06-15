#!/usr/bin/env python3
from __future__ import annotations
import sys

import argparse
import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, legacy_raw_run_dir, raw_scraped_data_root, reports_root  # noqa: E402
from typing import Dict, List, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from step1_intake_utils import INTAKE_HEADERS


RETAILER = "nordstromrack_com"
SITE = "nordstromrack.com"
SITE_ROOT = "https://www.nordstromrack.com"
SAMPLE_PDP = (
    "https://www.nordstromrack.com/s/calvin-klein-scuba-crepe-fit-flare-dress/7881634"
    "?origin=category-personalizedsort&breadcrumb=Home%2FWomen%2FClothing%2FDresses&color=419"
)
WOMENS_CATEGORY_SEED = "https://www.nordstromrack.com/shop/trend/women/bold-colors"

DATA_ROOT = (
    Path(os.environ["FWM_DATA_DIR"]).expanduser()
    if os.environ.get("FWM_DATA_DIR")
    else Path(__file__).resolve().parents[4].parent / "FWM_Data"
)
OUTPUT_DIR = legacy_raw_run_dir(RETAILER)
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
PRESSURE_STATUS_CODES = {401, 403, 407, 423, 429, 430, 503}
CHALLENGE_MARKERS = [
    "istlwashere",
    "istl-response",
    "captcha",
    "datadome",
    "access denied",
    "attention required",
    "verify you are human",
    "cloudflare challenge",
    "cf-chl",
    "perimeterx",
    "blocked",
    "waf",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_header_only_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INTAKE_HEADERS)
        writer.writeheader()


def fetch_preflight(url: str) -> Dict[str, object]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{SITE_ROOT}/",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read(500_000)
            text = body.decode("utf-8", errors="replace")
            headers = {key.lower(): value for key, value in response.headers.items()}
            status = int(getattr(response, "status", 200))
    except HTTPError as exc:
        body = exc.read(200_000)
        text = body.decode("utf-8", errors="replace")
        headers = {key.lower(): value for key, value in exc.headers.items()}
        status = exc.code
    except URLError as exc:
        return {
            "url": url,
            "status": None,
            "error": str(exc),
            "bytes_sampled": 0,
            "content_type": "",
            "challenge_markers": [],
            "title_hint": "",
        }

    lower = text[:80_000].lower()
    header_blob = " ".join(f"{key}: {value}" for key, value in headers.items()).lower()
    markers = sorted({marker for marker in CHALLENGE_MARKERS if marker in lower or marker in header_blob})
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    return {
        "url": url,
        "status": status,
        "content_type": headers.get("content-type", ""),
        "bytes_sampled": len(body),
        "challenge_markers": markers,
        "title_hint": re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else "",
        "has_normal_app_data": bool(
            re.search(r"__NEXT_DATA__|application/ld\+json|window\.__INITIAL_STATE__|product", text, re.I)
        ),
    }


def build_summary(started_at: str, finished_at: str, preflight: List[Dict[str, object]]) -> Dict[str, object]:
    hard_stops = [
        entry
        for entry in preflight
        if entry.get("status") in PRESSURE_STATUS_CODES or entry.get("challenge_markers")
    ]
    return {
        "site": SITE,
        "retailer": RETAILER,
        "adapter": "guarded_womens_category_preflight",
        "scope": "approved category-specific Sovrn scrape; Nordstrom Rack women's clothing only",
        "sample_pdp": SAMPLE_PDP,
        "category_seed": WOMENS_CATEGORY_SEED,
        "access_policy": "public pages/endpoints only; stopped on WAF/challenge behavior; no auth/challenge bypass",
        "blocked": bool(hard_stops),
        "block_reason": (
            "Public Nordstrom Rack HTML returned Imperva/ISTL interstitial markers "
            "instead of normal product or category app data."
            if hard_stops
            else ""
        ),
        "stop_reason": "waf_challenge_signal" if hard_stops else "none",
        "product_sources": {
            "sample_pdp_preflight": 1,
            "category_seed_available_from_triage": 1,
            "usable_product_sources": 0 if hard_stops else None,
        },
        "products_discovered": 0,
        "products_scanned": 0,
        "products_excluded_from_output": 0,
        "review_pages_scanned": 0,
        "exhaustive_review_paging": False,
        "coverage_exhaustive": False,
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
        "product_summaries": [],
        "errors": hard_stops,
        "warnings": [
            "No product discovery, review endpoint probing, or customer media paging was attempted after the WAF signal.",
            "Revisit only if a normal public endpoint or page path is documented without challenge handling.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guarded Nordstrom Rack women's-category preflight.")
    parser.add_argument(
        "--include-category-preflight",
        action="store_true",
        help="Also fetch the triage women's category seed if the sample PDP does not hit a hard stop.",
    )
    args = parser.parse_args(argv)

    started_at = utc_now()
    preflight = [fetch_preflight(SAMPLE_PDP)]
    sample_hard_stop = preflight[0].get("status") in PRESSURE_STATUS_CODES or preflight[0].get("challenge_markers")
    if args.include_category_preflight and not sample_hard_stop:
        preflight.append(fetch_preflight(WOMENS_CATEGORY_SEED))
    finished_at = utc_now()

    write_header_only_csv(OUTPUT_CSV)
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    summary = build_summary(started_at, finished_at, preflight)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {SUMMARY_JSON}")
    print(f"Stop reason: {summary['stop_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
