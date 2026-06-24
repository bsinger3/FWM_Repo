#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = REPO_ROOT.parent
OUTPUT_ROOT = PROJECT_ROOT / "FWM_Data" / "00_raw_scraped_data"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) FWM WorkerB public probe"
FETCH_TIMEOUT_SECONDS = 30
MAX_HTML_BYTES = 2_500_000
PRESSURE_STATUS_CODES = {401, 403, 407, 408, 409, 423, 429, 430, 503}
BLOCK_MARKERS = [
    "Just a moment...",
    "challenges.cloudflare.com",
    "cf-chl",
    "Attention Required! | Cloudflare",
    "datadome",
    "Please verify you are a human",
    "verify you are human",
    "Access denied",
]

PROVIDER_PATTERNS = {
    "Bazaarvoice": [r"bazaarvoice", r"bvseo", r"bv_reviews", r"api\.bazaarvoice\.com"],
    "PowerReviews": [r"powerreviews", r"pr-review", r"ui\.powerreviews\.com"],
    "Yotpo": [r"yotpo", r"staticw2\.yotpo\.com"],
    "Feefo": [r"feefo", r"api\.feefo\.com"],
    "TurnTo": [r"turnto\.com", r"tt-teaser", r"TurnToCmd"],
    "Stamped": [r"stamped\.io", r"stamped-main-widget"],
    "Okendo": [r"okendo", r"okeReviews", r"oke-widget"],
    "Loox": [r"loox", r"looxReviews", r"loox-rating"],
    "Judge.me": [r"judge\.me", r"jdgm-", r"judgeme_product_reviews"],
    "Reviews.io": [r"reviews\.io", r"widget\.reviews\.co\.uk", r"ruk_rating_snippet"],
}

REVIEW_MEDIA_PATTERNS = [
    r"review[^\"'<>]{0,80}(?:image|photo|media)",
    r"(?:image|photo|media)[^\"'<>]{0,80}review",
    r"review-thumbnail",
    r"bv-content-media",
    r"pr-media",
    r"yotpo-review-media",
    r"oke-reviewContent-media",
    r"jdgm-rev__pic",
    r"loox-photo",
]


@dataclass(frozen=True)
class Retailer:
    slug: str
    brand: str
    start_url: str
    category_urls: tuple[str, ...]


RETAILERS = [
    Retailer(
        slug="elomilingerie_com",
        brand="Elomi",
        start_url="https://www.elomilingerie.com/us/en/",
        category_urls=(
            "https://www.elomilingerie.com/us/en/lingerie/bras/c/100/",
            "https://www.elomilingerie.com/us/en/lingerie/panties/c/101/",
        ),
    ),
    Retailer(
        slug="freyalingerie_com",
        brand="Freya",
        start_url="https://www.freyalingerie.com/us/en/",
        category_urls=(
            "https://www.freyalingerie.com/us/en/lingerie/bras/c/100/",
            "https://www.freyalingerie.com/us/en/lingerie/panties/c/102/",
        ),
    ),
    Retailer(
        slug="goddessbra_com",
        brand="Goddess",
        start_url="https://www.goddessbra.com/row/en/",
        category_urls=(
            "https://www.goddessbra.com/row/en/lingerie/bras/c/100/",
            "https://www.goddessbra.com/row/en/lingerie/briefs/c/101/",
        ),
    ),
]


class ProbeStop(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch_html(url: str) -> dict[str, object]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", 200)
            final_url = response.geturl()
            body = response.read(MAX_HTML_BYTES + 1)
    except HTTPError as exc:
        if exc.code in PRESSURE_STATUS_CODES:
            raise ProbeStop(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
        raise
    except (TimeoutError, URLError) as exc:
        raise ProbeStop(f"request_failed: {url}: {exc}") from exc

    text = body[:MAX_HTML_BYTES].decode("utf-8", "replace")
    lower = text.lower()
    if status in PRESSURE_STATUS_CODES:
        raise ProbeStop(f"blocked_or_rate_limited_http_{status}: {url}")
    if any(marker.lower() in lower for marker in BLOCK_MARKERS):
        raise ProbeStop(f"blocked_or_challenged_response: {url}")
    return {
        "requested_url": url,
        "final_url": final_url,
        "http_status": status,
        "bytes_read": min(len(body), MAX_HTML_BYTES),
        "truncated": len(body) > MAX_HTML_BYTES,
        "html": text,
    }


def unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def title_for(html: str) -> str:
    match = re.search(r"<title>([\s\S]*?)</title>", html, re.I)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def hrefs(html: str, base_url: str) -> list[str]:
    links = []
    for match in re.finditer(r"href=[\"']([^\"'#]+)", html, re.I):
        links.append(urljoin(base_url, match.group(1)))
    return unique(links)


def product_links(html: str, base_url: str) -> list[str]:
    return [
        link
        for link in hrefs(html, base_url)
        if re.search(r"/p/[a-z0-9-]+/?$", link, re.I)
    ]


def product_codes(html: str) -> list[str]:
    values = re.findall(r"data-product-code=[\"']([^\"']+)", html, re.I)
    values.extend(re.findall(r'"(?:sku|productID)"\s*:\s*"([^"]+)"', html, re.I))
    return unique(value.upper() for value in values)


def product_media_urls(html: str) -> list[str]:
    urls = re.findall(r"https?://media\.[^\"')\s<>]+", html, re.I)
    return unique(url for url in urls if "productImages" in url or "/medias/" in url)


def provider_hits(html: str) -> list[dict[str, object]]:
    hits = []
    for provider, patterns in PROVIDER_PATTERNS.items():
        matched = [pattern for pattern in patterns if re.search(pattern, html, re.I)]
        if matched:
            hits.append({"provider": provider, "matched_patterns": matched})
    return hits


def review_schema_present(html: str) -> bool:
    json_ld_blocks = re.findall(
        r"<script[^>]+application/ld\+json[^>]*>([\s\S]*?)</script>",
        html,
        re.I,
    )
    return any(re.search(r"AggregateRating|\"Review\"|reviewCount|ratingValue", block, re.I) for block in json_ld_blocks)


def review_media_present(html: str) -> bool:
    return any(re.search(pattern, html, re.I) for pattern in REVIEW_MEDIA_PATTERNS)


def compact_page(page: dict[str, object]) -> dict[str, object]:
    return {
        "requested_url": page["requested_url"],
        "final_url": page["final_url"],
        "http_status": page["http_status"],
        "bytes_read": page["bytes_read"],
        "truncated": page["truncated"],
        "title": title_for(str(page["html"])),
    }


def probe(retailer: Retailer) -> dict[str, object]:
    fetched_pages = []
    all_product_links: list[str] = []
    all_product_codes: list[str] = []
    all_media_urls: list[str] = []
    all_provider_hits: list[dict[str, object]] = []
    schema_review = False
    review_media = False

    urls_to_fetch = [retailer.start_url, *retailer.category_urls]
    for url in urls_to_fetch:
        page = fetch_html(url)
        html = str(page["html"])
        fetched_pages.append(compact_page(page))
        all_product_links.extend(product_links(html, str(page["final_url"])))
        all_product_codes.extend(product_codes(html))
        all_media_urls.extend(product_media_urls(html))
        all_provider_hits.extend(provider_hits(html))
        schema_review = schema_review or review_schema_present(html)
        review_media = review_media or review_media_present(html)
        time.sleep(0.4)

    sampled_product_pages = []
    for url in unique(all_product_links)[:3]:
        page = fetch_html(url)
        html = str(page["html"])
        sampled_product_pages.append(
            {
                **compact_page(page),
                "product_codes": product_codes(html)[:8],
                "product_media_url_count": len(product_media_urls(html)),
                "product_media_url_samples": product_media_urls(html)[:5],
                "review_provider_hits": provider_hits(html),
                "review_schema_present": review_schema_present(html),
                "review_media_present": review_media_present(html),
            }
        )
        all_product_codes.extend(product_codes(html))
        all_media_urls.extend(product_media_urls(html))
        all_provider_hits.extend(provider_hits(html))
        schema_review = schema_review or review_schema_present(html)
        review_media = review_media or review_media_present(html)
        time.sleep(0.4)

    all_product_links = unique(all_product_links)
    all_product_codes = unique(all_product_codes)
    all_media_urls = unique(all_media_urls)
    normalized_provider_hits = []
    for provider in unique(hit["provider"] for hit in all_provider_hits):
        patterns = unique(
            pattern
            for hit in all_provider_hits
            if hit["provider"] == provider
            for pattern in hit["matched_patterns"]
        )
        normalized_provider_hits.append({"provider": provider, "matched_patterns": patterns})

    has_review_path = bool(normalized_provider_hits or schema_review or review_media)
    return {
        "slug": retailer.slug,
        "brand": retailer.brand,
        "probed_at": utc_now(),
        "mode": "file_first_public_probe_no_db_writes",
        "status": "blocked_no_review_surface" if not has_review_path else "review_surface_candidate",
        "catalog_public_available": bool(all_product_links),
        "public_product_page_count_observed": len(all_product_links),
        "product_code_count_observed": len(all_product_codes),
        "public_product_media_available": bool(all_media_urls),
        "product_media_url_count_observed": len(all_media_urls),
        "product_link_samples": all_product_links[:20],
        "product_code_samples": all_product_codes[:20],
        "product_media_url_samples": all_media_urls[:10],
        "review_provider_hits": normalized_provider_hits,
        "review_schema_present": schema_review,
        "review_media_present": review_media,
        "manual_queue_note": "manual check: no reviews",
        "finding": (
            "Public catalog/product pages and product imagery are available, but sampled pages did not expose "
            "review widgets, review/rating schema, or review-media endpoints."
            if not has_review_path
            else "Potential review surface detected; inspect provider hits before scraping."
        ),
        "blockers": [] if has_review_path else ["no_public_review_surface_detected"],
        "fetched_pages": fetched_pages,
        "sampled_product_pages": sampled_product_pages,
    }


def write_summary(summary: dict[str, object]) -> Path:
    output_dir = OUTPUT_ROOT / str(summary["slug"])
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "review_probe_summary.json"
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def main() -> int:
    written = []
    failures = []
    for retailer in RETAILERS:
        try:
            summary = probe(retailer)
            written.append(str(write_summary(summary)))
            print(
                f"{retailer.slug}: {summary['status']} "
                f"products={summary['public_product_page_count_observed']} "
                f"codes={summary['product_code_count_observed']} "
                f"media={summary['product_media_url_count_observed']} "
                f"providers={len(summary['review_provider_hits'])}",
                flush=True,
            )
        except ProbeStop as exc:
            failure = {
                "slug": retailer.slug,
                "brand": retailer.brand,
                "probed_at": utc_now(),
                "mode": "file_first_public_probe_no_db_writes",
                "status": "stopped_on_probe_wall",
                "blockers": [str(exc)],
                "finding": "Stopped before scraping because the public probe hit a block/rate-limit/auth/request wall.",
            }
            written.append(str(write_summary(failure)))
            failures.append(f"{retailer.slug}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{retailer.slug}: unexpected_error: {exc}")

    print("written:")
    for path in written:
        print(path)
    if failures:
        print("failures:", file=sys.stderr)
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
