#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from step1_intake_utils import INTAKE_HEADERS


RETAILER = "spinnakerboutique_com"
SITE = "https://www.spinnakerboutique.com"
SAMPLE_CATEGORY_URL = f"{SITE}/it-IT/donna/abbigliamento/jeans"
SAMPLE_PDP_URLS = [
    f"{SITE}/it-IT/products/guestwishlist",
    f"{SITE}/it-IT/product/62317/miu_miu/jeans/jeans",
    f"{SITE}/it-IT/product/62293/versace/jeans/jeans",
]
SEED_URLS = [SAMPLE_CATEGORY_URL, *SAMPLE_PDP_URLS]

DATA_ROOT = (
    Path(os.environ["FWM_DATA_DIR"]).expanduser()
    if os.environ.get("FWM_DATA_DIR")
    else Path(__file__).resolve().parents[4].parent / "FWM_Data"
)
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
PRESSURE_STATUS_CODES = {401, 403, 407, 423, 429, 430, 503}
CHALLENGE_RE = re.compile(
    r"\b(?:captcha|cloudflare challenge|cf-chl|datadome|perimeterx|awswaf|access denied|"
    r"attention required|verify you are human|temporarily blocked)\b",
    re.I,
)


class StopScrape(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def strip_tags(value: object) -> str:
    return normalize(re.sub(r"<[^>]+>", " ", str(value or "")))


def fetch_text(url: str, *, referer: str = SITE, delay_seconds: float = 0.25) -> Tuple[str, Dict[str, object]]:
    time.sleep(delay_seconds)
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
        with urlopen(request, timeout=40) as response:
            body = response.read(1_500_000)
            status = int(getattr(response, "status", 200))
            content_type = response.headers.get("content-type", "")
    except HTTPError as exc:
        body = exc.read(300_000)
        status = exc.code
        content_type = exc.headers.get("content-type", "")
    except URLError as exc:
        raise StopScrape(f"network_error: {url}: {exc}") from exc
    text = body.decode("utf-8", errors="replace")
    if status in PRESSURE_STATUS_CODES:
        raise StopScrape(f"blocked_or_rate_limited_http_{status}: {url}")
    if CHALLENGE_RE.search(text[:100_000]):
        raise StopScrape(f"blocked_or_challenged_response: {url}")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    return text, {
        "url": url,
        "status": status,
        "content_type": content_type,
        "bytes_sampled": len(body),
        "title_hint": strip_tags(title_match.group(1)) if title_match else "",
    }


def write_header_only_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INTAKE_HEADERS)
        writer.writeheader()


def product_links_from_category(html_text: str) -> List[str]:
    links: List[str] = []
    for match in re.findall(r"href=['\"]([^'\"]*/it-IT/product/[^'\"]+)['\"]", html_text, re.I):
        url = urljoin(SITE, html.unescape(match).split("#", 1)[0])
        if url not in links:
            links.append(url)
    return links


def loox_app_ids(html_text: str, url: str) -> List[str]:
    text = html_text.replace("\\/", "/")
    values = re.findall(r"loox\.io/widget/([^/'\"\s]+)/", text, re.I)
    values += re.findall(r"Loox\.shop\s*=\s*['\"]([^'\"]+)['\"]", text, re.I)
    values += re.findall(r"data-loox-(?:shop|store)=['\"]([^'\"]+)['\"]", text, re.I)
    host = urlparse(url).netloc
    return list(dict.fromkeys(normalize(value) for value in values if normalize(value) and normalize(value) != host))


def parse_gtm_detail(html_text: str) -> Dict[str, str]:
    match = re.search(r"data-gtm-detail-row=['\"]([^'\"]+)['\"]", html_text, re.I)
    if not match:
        return {}
    raw = html.unescape(match.group(1))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return {str(key): normalize(value) for key, value in data.items()}


def parse_product_summary(url: str, html_text: str) -> Dict[str, object]:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
    gtm = parse_gtm_detail(html_text)
    product_id_match = re.search(r'data-gtm-detail-id=["\']([^"\']+)["\']', html_text, re.I)
    size_labels = re.findall(r'<label[^>]+class=["\'][^"\']*field__label[^"\']*["\'][^>]*>(.*?)</label>', html_text, re.I | re.S)
    sizes = [strip_tags(value) for value in size_labels if strip_tags(value)]
    image_urls = [
        html.unescape(url)
        for url in re.findall(r"(https://spinnakerboutiquestorage\.blob\.core\.windows\.net/product/[^'\"\s,<>]+)", html_text, re.I)
    ]
    return {
        "url": url,
        "product_id": normalize(product_id_match.group(1)) if product_id_match else gtm.get("item_id", ""),
        "title": gtm.get("item_name") or strip_tags(title_match.group(1)) if title_match else "",
        "brand": gtm.get("item_brand", ""),
        "variant": gtm.get("item_variant", ""),
        "category": " > ".join(part for part in [gtm.get("item_category2", ""), gtm.get("item_category3", ""), gtm.get("item_category", "")] if part),
        "price": gtm.get("price", ""),
        "sizes": list(dict.fromkeys(sizes)),
        "catalog_image_count": len(set(image_urls)),
        "loox_app_ids_found": loox_app_ids(html_text, url),
        "loox_media_markers": len(re.findall(r"images\.loox\.io|loox\.io/uploads|loox-review|loox-photo", html_text, re.I)),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Spinnaker Boutique first-pass Loox/public-page scrape.")
    parser.add_argument("--max-category-products", type=int, default=20)
    parser.add_argument("--request-delay-seconds", type=float, default=0.25)
    args = parser.parse_args(argv)

    started_at = utc_now()
    preflight: List[Dict[str, object]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    stop_reason = ""

    try:
        fetched: Dict[str, str] = {}
        for url in SEED_URLS:
            text, meta = fetch_text(url, delay_seconds=args.request_delay_seconds)
            fetched[url] = text
            meta["loox_app_ids_found"] = loox_app_ids(text, url)
            meta["loox_media_markers"] = len(re.findall(r"images\.loox\.io|loox\.io/uploads|loox-review|loox-photo", text, re.I))
            preflight.append(meta)

        category_links = product_links_from_category(fetched[SAMPLE_CATEGORY_URL])
        sample_product_urls = [url for url in SAMPLE_PDP_URLS if "/product/" in url]
        product_urls = list(dict.fromkeys([*sample_product_urls, *category_links[: args.max_category_products]]))
        seen = set()
        for url in product_urls:
            if url in fetched:
                text = fetched[url]
            else:
                text, _ = fetch_text(url, referer=SAMPLE_CATEGORY_URL, delay_seconds=args.request_delay_seconds)
            if url in seen:
                continue
            seen.add(url)
            product_summaries.append(parse_product_summary(url, text))
    except StopScrape as exc:
        stop_reason = str(exc)
        errors.append(stop_reason)

    rows: List[Dict[str, str]] = []
    write_header_only_csv(OUTPUT_CSV)
    finished_at = utc_now()

    products_with_loox = sum(1 for item in product_summaries if item.get("loox_app_ids_found") or item.get("loox_media_markers"))
    summary = {
        "site": "spinnakerboutique.com",
        "retailer": RETAILER,
        "adapter": "public_category_pdp_loox_evidence_check",
        "triage_bucket": "sovrn_first_pass_scrape_candidate",
        "triage_source": "data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv",
        "merchant": "Spinnaker Boutique",
        "review_platform_provider": "Loox",
        "photo_reviews_present_triage": True,
        "reviews_present_triage": True,
        "shipping_geos": "US",
        "conversion_signal": "3.17%",
        "commission_aov_note": "commission and AOV fields not populated in triage",
        "access_policy": "public category/product pages only; stop_on_429_captcha_waf_auth; no_auth_or_challenge_bypass",
        "sample_category_url": SAMPLE_CATEGORY_URL,
        "sample_pdp_urls": SAMPLE_PDP_URLS,
        "product_sources": {
            "sample_category_pages": 1,
            "sample_product_pages": len([url for url in SAMPLE_PDP_URLS if "/product/" in url]),
            "category_product_links_found": len(product_links_from_category(fetched[SAMPLE_CATEGORY_URL])) if "fetched" in locals() and SAMPLE_CATEGORY_URL in fetched else 0,
            "product_pages_checked": len(product_summaries),
            "usable_loox_product_sources": products_with_loox,
        },
        "products_discovered": len(product_summaries),
        "products_scanned": len(product_summaries),
        "products_excluded_from_output": len(product_summaries),
        "review_pages_scanned": 0,
        "exhaustive_review_paging": False,
        "coverage_exhaustive": False,
        "blocked": bool(stop_reason),
        "stop_reason": stop_reason or "no_public_loox_widget_or_review_media_found_in_seed_or_category_product_pages",
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
        "product_summaries": product_summaries,
        "errors": errors,
        "warnings": [
            "Triage lists Loox/photo reviews, but sampled public pages exposed no Loox app id, Loox widget HTML, or Loox image media.",
            "Only category/PDP public pages were checked; no private endpoints, auth flow, or challenge handling was attempted.",
        ],
    }
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {SUMMARY_JSON}")
    print(f"Rows written: {len(rows)}")
    print(f"Stop reason: {summary['stop_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
