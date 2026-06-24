#!/usr/bin/env python3
"""Discover Amazon ASINs for plus-size women's clothing via plain HTTP search pages.

Outputs a CSV to FWM_Data/00_raw_scraped_data/amazon/asin_discovery/ that can
be fed directly to scripts/scrape_amazon_reviews_direct.mjs as the ASIN list.

Usage:
    python discover_plus_size_asins.py [--max-pages 10] [--output path/to/asins.csv]
    python discover_plus_size_asins.py --category dresses --max-pages 5
    python discover_plus_size_asins.py --dry-run   # print first page of results only
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from typing import Dict, Iterator, List, Optional, Set

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_SCRIPTS_DIR = SCRIPT_DIR.parents[2]
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import raw_scraped_data_root  # noqa: E402

OUTPUT_DIR = raw_scraped_data_root() / "amazon" / "asin_discovery"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Women's plus-size browse categories: (label, search_index, node_id or None)
PLUS_SIZE_CATEGORIES = [
    ("dresses",    "fashion-womens-plus", "1045024"),
    ("tops",       "fashion-womens-plus", "1045026"),
    ("bottoms",    "fashion-womens-plus", "1045032"),
    ("swimwear",   "fashion-womens-plus", "1045040"),
    ("intimates",  "fashion-womens-plus", "1045044"),
    ("outerwear",  "fashion-womens-plus", "1045036"),
    ("jumpsuits",  "fashion-womens-plus", "1045028"),
    ("all",        "fashion-womens-plus", None),
]

ASIN_RE = re.compile(r'\bdata-asin="([A-Z0-9]{10})"')
TOTAL_RESULTS_RE = re.compile(r'"totalResultCount"\s*:\s*(\d+)', re.I)


def search_url(search_index: str, node_id: Optional[str], page: int, sort: str = "review-rank") -> str:
    params: Dict[str, str] = {
        "i": search_index,
        "s": sort,
        "page": str(page),
        "ref": f"sr_pg_{page}",
    }
    if node_id:
        params["rh"] = f"n:{node_id}"
    return "https://www.amazon.com/s?" + urlencode(params)


def fetch_html(url: str, retries: int = 4, sleep_base: float = 2.0) -> Optional[str]:
    for attempt in range(retries):
        req = Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        try:
            with urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
        except URLError:
            pass
        time.sleep(sleep_base * (2 ** attempt))
    return None


def looks_blocked(html: str) -> bool:
    return bool(re.search(
        r"enter the characters you see|robot|captcha|ap_login_form",
        html, re.I,
    ))


def parse_asins(html: str) -> List[str]:
    return list(dict.fromkeys(ASIN_RE.findall(html)))  # preserve order, dedupe


def iter_category_asins(
    label: str,
    search_index: str,
    node_id: Optional[str],
    max_pages: int,
    sleep_ms: int,
    seen: Set[str],
) -> Iterator[Dict[str, str]]:
    discovered_at = datetime.now(timezone.utc).isoformat()
    for page in range(1, max_pages + 1):
        url = search_url(search_index, node_id, page)
        html = fetch_html(url)
        if not html:
            print(f"  [{label}] page {page}: fetch failed, stopping", file=sys.stderr)
            break
        if looks_blocked(html):
            print(f"  [{label}] page {page}: bot-blocked, stopping", file=sys.stderr)
            break

        asins = parse_asins(html)
        new_asins = [a for a in asins if a not in seen]
        print(f"  [{label}] page {page}: {len(asins)} ASINs ({len(new_asins)} new)", file=sys.stderr)

        for asin in new_asins:
            seen.add(asin)
            yield {
                "asin": asin,
                "source_category": label,
                "source_node_id": node_id or "",
                "source_page": str(page),
                "discovered_at": discovered_at,
            }

        if not new_asins:
            break

        time.sleep(sleep_ms / 1000)


def load_existing_asins(existing_csv: Optional[Path]) -> Set[str]:
    if not existing_csv or not existing_csv.exists():
        return set()
    with existing_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["asin"].strip().upper() for row in reader if row.get("asin")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover Amazon plus-size ASIN list via search pages.")
    parser.add_argument("--max-pages", type=int, default=10, help="Max search result pages per category (default: 10)")
    parser.add_argument("--sleep-ms", type=int, default=3000, help="Delay between requests in ms (default: 3000)")
    parser.add_argument("--category", choices=[c[0] for c in PLUS_SIZE_CATEGORIES] + ["all"], default=None,
                        help="Scrape a single category instead of all")
    parser.add_argument("--output", type=Path, default=None, help="Output CSV path (default: auto-timestamped in OUTPUT_DIR)")
    parser.add_argument("--existing", type=Path, default=None,
                        help="CSV of ASINs already collected; these will be skipped")
    parser.add_argument("--dry-run", action="store_true", help="Fetch one page per category and print counts, no file written")
    args = parser.parse_args()

    categories = (
        [c for c in PLUS_SIZE_CATEGORIES if c[0] == args.category]
        if args.category and args.category != "all"
        else PLUS_SIZE_CATEGORIES
    )

    seen: Set[str] = load_existing_asins(args.existing)
    print(f"Starting with {len(seen)} pre-known ASINs to skip", file=sys.stderr)

    rows: List[Dict[str, str]] = []
    for label, search_index, node_id in categories:
        print(f"Category: {label}", file=sys.stderr)
        max_pages = 1 if args.dry_run else args.max_pages
        for row in iter_category_asins(label, search_index, node_id, max_pages, args.sleep_ms, seen):
            rows.append(row)

    if args.dry_run:
        print(json.dumps({"total_new_asins": len(rows), "sample": rows[:5]}, indent=2))
        return

    if not rows:
        print("No new ASINs discovered.", file=sys.stderr)
        return

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.output or (OUTPUT_DIR / f"plus_size_asins_{ts}.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["asin", "source_category", "source_node_id", "source_page", "discovered_at"]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "total_asins": len(rows),
        "by_category": {},
        "output": str(output_path),
    }
    for row in rows:
        summary["by_category"].setdefault(row["source_category"], 0)
        summary["by_category"][row["source_category"]] += 1

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
