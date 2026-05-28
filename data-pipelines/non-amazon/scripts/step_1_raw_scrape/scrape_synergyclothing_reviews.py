#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Dict, List
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from step1_intake_utils import output_paths, utc_now, validate_rows, write_intake_csv


SITE_ROOT = "https://www.synergyclothing.com"
RETAILER = "synergyclothing_com"
SEED_CATEGORY = f"{SITE_ROOT}/category/shop-organic/womens-collection/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 FWM"
PRESSURE_STATUS_CODES = {401, 403, 407, 408, 409, 423, 429, 430, 503}
BLOCK_MARKERS = [
    "captcha",
    "verify you are human",
    "access denied",
    "too many requests",
    "attention required",
    "datadome",
    "cf-chl",
    "challenges.cloudflare.com",
]

PROVIDER_MARKERS = [
    "yotpo",
    "judge.me",
    "judgeme",
    "loox",
    "stamped",
    "okendo",
    "bazaarvoice",
    "powerreviews",
    "reviews.io",
    "trustpilot",
    "woocommerce-review",
    "commentlist",
    "review-rating",
]


class PressureStop(RuntimeError):
    pass


def fetch(url: str, *, accept: str = "text/html,application/json,*/*") -> Dict[str, object]:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": SITE_ROOT,
        },
    )
    try:
        with urlopen(req, timeout=30) as response:
            status = getattr(response, "status", 200)
            body = response.read().decode("utf-8", errors="replace")
            content_type = response.headers.get("content-type", "")
    except HTTPError as exc:
        if exc.code in PRESSURE_STATUS_CODES:
            raise PressureStop(f"pressure status {exc.code} for {url}") from exc
        body = exc.read().decode("utf-8", errors="replace")
        return {"url": url, "status": exc.code, "content_type": exc.headers.get("content-type", ""), "body": body}
    except URLError as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc

    if status in PRESSURE_STATUS_CODES:
        raise PressureStop(f"pressure status {status} for {url}")
    lower = body[:20000].lower()
    if any(marker in lower for marker in BLOCK_MARKERS):
        raise PressureStop(f"block marker in response for {url}")
    return {"url": url, "status": status, "content_type": content_type, "body": body}


def wp_rest_url(path: str, params: Dict[str, object] | None = None) -> str:
    query = f"?{urlencode(params or {})}" if params else ""
    return f"{SITE_ROOT}/wp-json/wp/v2/{path}{query}"


def html_links(html: str) -> List[str]:
    links = []
    for match in re.finditer(r"""href=["']([^"']+)["']""", html, flags=re.I):
        href = match.group(1)
        if href.startswith("/"):
            href = SITE_ROOT + href
        if href.startswith(SITE_ROOT):
            links.append(href)
    return sorted(set(links))


def classify_live_site(seed_html: str, category_posts: List[object], search_results: List[object], product_path_checks: List[Dict[str, object]]) -> Dict[str, object]:
    links = html_links(seed_html)
    lower = seed_html.lower()
    provider_hits = [marker for marker in PROVIDER_MARKERS if marker in lower]
    product_like_links = [
        link
        for link in links
        if re.search(r"/(?:product|products|shop|collections?)/", link, flags=re.I)
        and not re.search(r"/wp-content/|/wp-includes/", link, flags=re.I)
    ]
    commerce_path_statuses = {item["url"]: item["status"] for item in product_path_checks}
    return {
        "seed_category": SEED_CATEGORY,
        "seed_status": 200,
        "seed_links_found": len(links),
        "seed_product_like_links": product_like_links[:50],
        "provider_marker_hits": provider_hits,
        "wp_rest_category_posts_count": len(category_posts),
        "wp_rest_search_results_count": len(search_results),
        "wp_rest_search_result_types": sorted(set(str(item.get("subtype", "")) for item in search_results if isinstance(item, dict))),
        "commerce_path_statuses": commerce_path_statuses,
        "current_site_classification": "wordpress_elementor_content_site_no_public_product_or_review_surface",
    }


def run() -> Dict[str, object]:
    started_at = utc_now()
    output_csv, summary_json = output_paths(RETAILER)

    seed = fetch(SEED_CATEGORY)
    seed_html = str(seed["body"])

    category_posts_raw = fetch(wp_rest_url("posts", {"categories": 28, "per_page": 20, "_embed": 1}), accept="application/json")
    try:
        category_posts = json.loads(str(category_posts_raw["body"]))
    except json.JSONDecodeError:
        category_posts = []

    search_raw = fetch(wp_rest_url("search", {"search": "dress", "per_page": 20}), accept="application/json")
    try:
        search_results = json.loads(str(search_raw["body"]))
    except json.JSONDecodeError:
        search_results = []

    path_checks = []
    for path in ["/shop/", "/products.json", "/product-category/womens-collection/"]:
        response = fetch(SITE_ROOT + path)
        path_checks.append({"url": SITE_ROOT + path, "status": response["status"], "content_type": response["content_type"]})

    rows: List[Dict[str, str]] = []
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()

    site_probe = classify_live_site(seed_html, category_posts, search_results, path_checks)
    summary = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "wordpress_elementor_public_surface_probe",
        "provider_identified": "none on current public site; triage provider unknown/photo_reviews=yes could not be reproduced from live public pages",
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": finished_at,
        "products_discovered": 0,
        "products_scanned": 0,
        "review_pages_scanned": 0,
        "exhaustive_review_paging": False,
        "site_probe": site_probe,
        "errors": [],
        "access_policy": "public Synergy Clothing pages, sitemap, and WordPress REST endpoints only; stop on 429/captcha/WAF/auth behavior.",
        "stop_reason": "live seed category is a WordPress/Elementor content category with no public product cards, no category posts, no product/review provider markers, and common commerce paths returned 404.",
        "sovrn_triage_source": {
            "source_file": "data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv",
            "target": RETAILER,
            "status": "first-pass candidate",
            "pricing_model": "CPC",
            "cpc_amount": "not_populated",
            "reviews_present": "yes",
            "photo_reviews": "yes",
            "shipping_countries": "US",
            "provider": "unknown",
            "evidence_url": SEED_CATEGORY,
        },
    }
    summary.update(validate_rows(rows))
    summary["rows_with_customer_image"] = summary.get("rows_with_customer_review_image", 0)
    summary["rows_with_catalog_model_image"] = 0
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe Synergy Clothing public review/product surface and write step 1 outputs.")
    parser.parse_args()
    payload = run()
    print(f"Rows: {payload.get('rows_written', 0)}")
    print(f"Products discovered: {payload.get('products_discovered', 0)}")
    print(f"Stop reason: {payload.get('stop_reason')}")
    print(f"Output: {payload.get('output_csv')}")


if __name__ == "__main__":
    main()
