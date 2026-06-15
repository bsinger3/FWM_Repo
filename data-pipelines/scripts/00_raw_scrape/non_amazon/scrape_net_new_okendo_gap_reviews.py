#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    canonical_product_url,
    dedupe_rows,
    discover_shopify_product_urls,
    extract_product_context,
    fetch_json,
    fetch_text,
    hydrate_shopify_context,
    normalize_whitespace,
    output_paths,
    retailer_slug,
    strip_tags,
    utc_now,
    validate_rows,
    write_intake_csv,
)


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
PIPELINE_SCRIPTS_DIR = REPO_ROOT / "data-pipelines" / "scripts"
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import reports_root  # noqa: E402

DEFAULT_MEASUREMENT_REPORT_ROOT = reports_root() / "measurement_coverage"
DEFAULT_CANDIDATE_CSV = (
    DEFAULT_MEASUREMENT_REPORT_ROOT
    / "20260609_human_labeled_approved_only"
    / "net_new_site_research_candidates.csv"
)
DEFAULT_DOMAINS = ["glamorise.com", "knix.com", "honeylove.com"]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
PRESSURE_STATUS_CODES = {401, 403, 407, 423, 429, 430, 503}
BLOCK_RE = re.compile(
    r"\b(?:captcha|cloudflare challenge|cf-chl|datadome|perimeterx|awswaf|access denied|"
    r"attention required|verify you are human|temporarily blocked)\b",
    re.I,
)
OKENDO_REVIEW_RE = re.compile(
    r"https://api\.okendo\.io/v1/stores/([^/]+)/products/shopify-(\d+)/reviews",
    re.I,
)
SHOPIFY_ID_RE = re.compile(
    r"shopify[-_/](\d{8,14})|"
    r"gid://shopify/Product/(\d{8,14})|"
    r"productId[\"']?\s*[:=]\s*[\"']?(?:shopify-)?(\d{8,14})|"
    r"ProductID[\"']?\s*[:=]\s*[\"']?(\d{8,14})|"
    r"data-product-id=[\"'](\d{8,14})[\"']",
    re.I,
)
SUBSCRIBER_ID_RE = re.compile(
    r"subscriberId[\"']?\s*[:=]\s*[\"']([0-9a-f-]{36})|"
    r"api\.okendo\.io/v1/stores/([0-9a-f-]{36})|"
    r"OkendoApi\.init\([\"']([0-9a-f-]{36})[\"']",
    re.I,
)
PRODUCT_ALLOW_RE = re.compile(
    r"\b("
    r"bra|bralette|wireless|underwire|plunge|balconette|sports\s*bra|"
    r"shapewear|shape\s*wear|bodysuit|body\s*suit|brief|short|thong|panty|underwear|"
    r"legging|dress|swim|swimsuit|bikini|one\s*piece|tankini|jean|pant|trouser|"
    r"jacket|coat|shirt|top|tee|tank|skirt"
    r")\b",
    re.I,
)
PRODUCT_BLOCK_RE = re.compile(
    r"\b("
    r"gift\s*card|shipping\s*(protection|insurance)?|route\s*package|"
    r"detergent|laundry\s*bag|hanger|tape|boob\s*tape|nipple\s*covers?|"
    r"extender|removable\s*pads?|insert|membership|sample"
    r")\b",
    re.I,
)


@dataclass
class Candidate:
    domain: str
    site_url: str
    evidence_url: str
    target_gap_tags: str
    category: str
    review_provider: str
    notes: str = ""


@dataclass
class ScrapeConfig:
    candidate: Candidate
    subscriber_id: str = ""
    seed_product_ids: List[str] = field(default_factory=list)
    seed_product_urls: List[str] = field(default_factory=list)


class StopScrape(RuntimeError):
    pass


def norm(value: object) -> str:
    return normalize_whitespace(html.unescape(str(value or "")))


def polite_fetch_text(url: str, *, referer: str = "", delay: float = 0.25, accept: str = "text/html,application/json,*/*") -> str:
    time.sleep(delay)
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        },
    )
    try:
        with urlopen(request, timeout=45) as response:
            status = int(getattr(response, "status", 200))
            text = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code in PRESSURE_STATUS_CODES:
            raise StopScrape(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
        raise
    except URLError as exc:
        raise StopScrape(f"network_error: {url}: {exc}") from exc
    if status in PRESSURE_STATUS_CODES:
        raise StopScrape(f"blocked_or_rate_limited_http_{status}: {url}")
    if BLOCK_RE.search(text[:120_000]):
        raise StopScrape(f"blocked_or_challenged_response: {url}")
    return text


def polite_fetch_json(url: str, *, referer: str, delay: float) -> Dict[str, object]:
    text = polite_fetch_text(url, referer=referer, delay=delay, accept="application/json,text/plain,*/*")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise StopScrape(f"unexpected_json_response: {url}")
    return payload


def read_candidates(path: Path, domains: Sequence[str]) -> List[Candidate]:
    wanted = {domain.lower().removeprefix("www.") for domain in domains}
    candidates: List[Candidate] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            domain = norm(row.get("domain")).lower().removeprefix("www.")
            if domain not in wanted:
                continue
            provider = norm(row.get("review_provider"))
            status = norm(row.get("api_status")).lower()
            if "okendo" not in provider.lower() and "okendo" not in norm(row.get("evidence_url")).lower():
                continue
            if "ready" not in status:
                continue
            candidates.append(
                Candidate(
                    domain=domain,
                    site_url=norm(row.get("site_url")) or f"https://{domain}/",
                    evidence_url=norm(row.get("evidence_url")),
                    target_gap_tags=norm(row.get("target_gap_tags")),
                    category=norm(row.get("category")),
                    review_provider=provider,
                    notes=norm(row.get("notes")),
                )
            )
    return candidates


def ids_from_text(pattern: re.Pattern[str], text: str) -> List[str]:
    values: List[str] = []
    for match in pattern.finditer(text):
        for group in match.groups():
            if group:
                values.append(norm(group))
    return list(dict.fromkeys(values))


def seed_config(candidate: Candidate) -> ScrapeConfig:
    subscriber_id = ""
    product_ids: List[str] = []
    evidence_match = OKENDO_REVIEW_RE.search(candidate.evidence_url)
    if evidence_match:
        subscriber_id = norm(evidence_match.group(1))
        product_ids.append(norm(evidence_match.group(2)))
    return ScrapeConfig(candidate=candidate, subscriber_id=subscriber_id, seed_product_ids=list(dict.fromkeys(product_ids)))


def current_existing_outputs() -> List[str]:
    root = output_paths("placeholder")[0].parents[0]
    if not root.exists():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir())


def catalog_contexts_from_products_json(config: ScrapeConfig, max_products: int) -> Tuple[List[ProductContext], List[str]]:
    candidate = config.candidate
    site_root = candidate.site_url.rstrip("/")
    contexts: List[ProductContext] = []
    errors: List[str] = []
    seen_handles = set()
    for page in range(1, 10000):
        if len(contexts) >= max_products:
            break
        api_url = f"{site_root}/products.json?limit=250&page={page}"
        try:
            payload = fetch_json(api_url, referer=site_root, retries=2)
        except Exception as exc:
            if page == 1:
                errors.append(f"products_json_discovery_failed: {type(exc).__name__}: {exc}")
            break
        products = payload.get("products")
        if not isinstance(products, list) or not products:
            break
        for product in products:
            if len(contexts) >= max_products:
                break
            if not isinstance(product, dict):
                continue
            handle = norm(product.get("handle"))
            product_id = norm(product.get("id"))
            if not handle or not product_id or handle in seen_handles:
                continue
            product_url = f"{site_root}/products/{handle}"
            tags = product.get("tags")
            tags_text = " ".join(str(tag) for tag in tags) if isinstance(tags, list) else str(tags or "")
            product_text = " ".join(
                norm(part)
                for part in [
                    product.get("title"),
                    product.get("body_html"),
                    product.get("product_type"),
                    product.get("vendor"),
                    tags_text,
                    product_url,
                ]
                if part
            )
            if PRODUCT_BLOCK_RE.search(product_text) or not PRODUCT_ALLOW_RE.search(product_text):
                continue
            seen_handles.add(handle)
            variants = product.get("variants")
            variant = ""
            color = ""
            if isinstance(variants, list) and variants and isinstance(variants[0], dict):
                variant = norm(variants[0].get("title"))
                color = norm(variants[0].get("option1") or variants[0].get("option2"))
            contexts.append(
                ProductContext(
                    url=canonical_product_url(product_url),
                    title=norm(product.get("title")),
                    description=strip_tags(product.get("body_html")),
                    category=norm(product.get("product_type")) or candidate.category,
                    brand=norm(product.get("vendor")) or candidate.domain,
                    color=color,
                    variant=variant,
                    product_id=product_id,
                    handle=handle,
                    shop_domain=urlparse(site_root).netloc,
                    provider_hints="Okendo; Shopify products.json",
                    raw_html="",
                )
            )
        if len(products) < 250:
            break
    return contexts, errors


def discover_candidate_products(config: ScrapeConfig, max_products: int, delay: float) -> Tuple[List[ProductContext], List[Dict[str, object]], List[str]]:
    candidate = config.candidate
    errors: List[str] = []
    product_summaries: List[Dict[str, object]] = []
    product_urls: List[str] = []
    site_root = candidate.site_url.rstrip("/")
    contexts: List[ProductContext] = []
    seen_product_ids = set()

    for product_id in config.seed_product_ids:
        if len(contexts) >= max_products:
            break
        if product_id in seen_product_ids:
            continue
        seen_product_ids.add(product_id)
        contexts.append(
            ProductContext(
                url=site_root,
                title="",
                category=candidate.category,
                brand=candidate.domain,
                product_id=product_id,
                shop_domain=urlparse(site_root).netloc,
                provider_hints="Okendo",
                raw_html="",
            )
        )
        product_summaries.append(
            {
                "url": site_root,
                "product_id": product_id,
                "title": "",
                "category": candidate.category,
                "subscriber_id": config.subscriber_id,
                "source": "candidate_evidence_url",
                "skip_reason": "",
            }
        )

    catalog_contexts, catalog_errors = catalog_contexts_from_products_json(config, max_products)
    errors.extend(catalog_errors)
    for context in catalog_contexts:
        if len(contexts) >= max_products:
            break
        if context.product_id in seen_product_ids:
            continue
        seen_product_ids.add(context.product_id)
        contexts.append(context)
        product_summaries.append(
            {
                "url": context.url,
                "product_id": context.product_id,
                "title": context.title,
                "category": context.category,
                "subscriber_id": config.subscriber_id,
                "source": "products_json",
                "skip_reason": "",
            }
        )
    if len(contexts) >= max_products:
        return contexts, product_summaries, errors

    if config.seed_product_urls:
        product_urls.extend(config.seed_product_urls)

    try:
        discovered = discover_shopify_product_urls(site_root, product_urls)
        product_urls.extend(discovered)
    except Exception as exc:
        errors.append(f"product_url_discovery_failed: {type(exc).__name__}: {exc}")

    if not product_urls:
        try:
            home = polite_fetch_text(site_root, referer=site_root, delay=delay)
            links = re.findall(r"href=[\"']([^\"']*/products/[^\"'#?]+)", home, re.I)
            product_urls.extend(urljoin(site_root, html.unescape(link)) for link in links)
        except Exception as exc:
            errors.append(f"homepage_product_link_discovery_failed: {type(exc).__name__}: {exc}")

    product_urls = list(dict.fromkeys(canonical_product_url(url) for url in product_urls if "/products/" in url))
    for product_url in product_urls[: max_products * 3]:
        if len(contexts) >= max_products:
            break
        summary: Dict[str, object] = {"url": product_url, "skip_reason": ""}
        try:
            html_text = polite_fetch_text(product_url, referer=site_root, delay=delay)
            context = hydrate_shopify_context(extract_product_context(product_url, html_text))
        except Exception as exc:
            summary["skip_reason"] = f"product_context_fetch_failed: {type(exc).__name__}: {exc}"
            product_summaries.append(summary)
            continue

        subscriber_ids = ids_from_text(SUBSCRIBER_ID_RE, context.raw_html)
        product_ids = [context.product_id, *ids_from_text(SHOPIFY_ID_RE, context.raw_html)]
        product_ids = [pid for pid in dict.fromkeys(norm(pid) for pid in product_ids if pid)]
        if not config.subscriber_id and subscriber_ids:
            config.subscriber_id = subscriber_ids[0]
        if not product_ids:
            summary["skip_reason"] = "missing_product_id"
            product_summaries.append(summary)
            continue
        context.product_id = product_ids[0]
        text = " ".join([context.title, context.description, context.detail, context.category, product_url])
        if PRODUCT_BLOCK_RE.search(text) or (not PRODUCT_ALLOW_RE.search(text) and "/products/" in product_url):
            summary["skip_reason"] = "non_gap_relevant_product"
            product_summaries.append(summary)
            continue
        if context.product_id in seen_product_ids:
            summary["skip_reason"] = "duplicate_product_id"
            product_summaries.append(summary)
            continue
        seen_product_ids.add(context.product_id)
        summary.update(
            {
                "product_id": context.product_id,
                "title": context.title,
                "category": context.category,
                "subscriber_id": config.subscriber_id,
            }
        )
        product_summaries.append(summary)
        contexts.append(context)

    return contexts, product_summaries, errors


def media_urls(value: object) -> List[str]:
    urls: List[str] = []
    if isinstance(value, str):
        urls.extend(re.findall(r"(?:https?:)?//[^'\"\s,<>]+\.(?:jpg|jpeg|png|webp)(?:\?[^'\"\s,<>]*)?", value, re.I))
    elif isinstance(value, list):
        for item in value:
            urls.extend(media_urls(item))
    elif isinstance(value, dict):
        for key in ["url", "mediaUrl", "imageUrl", "fullSizeUrl", "largeUrl", "thumbnailUrl", "src"]:
            if value.get(key):
                urls.append(str(value[key]))
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                urls.extend(media_urls(nested))
    normalized = [f"https:{url}" if url.startswith("//") else url for url in urls]
    normalized = [
        url
        for url in normalized
        if re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", url, re.I)
        and "crop=center" not in url.lower()
    ]
    by_image: Dict[str, str] = {}
    for url in normalized:
        if "d=120x120" in url.lower():
            continue
        key = url.split("?", 1)[0]
        current = by_image.get(key)
        if not current:
            by_image[key] = url
            continue
        current_score = 1 if "d=3200x3200" in current else 0
        new_score = 1 if "d=3200x3200" in url else 0
        if new_score > current_score:
            by_image[key] = url
    return list(dict.fromkeys(by_image.values()))


def review_profile_blob(review: Dict[str, object]) -> Tuple[str, str]:
    parts: List[str] = []
    size = ""
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    attrs = reviewer.get("attributes") if isinstance(reviewer.get("attributes"), list) else []
    for attr in attrs:
        if not isinstance(attr, dict):
            continue
        label = norm(attr.get("title") or attr.get("name") or attr.get("label"))
        raw_value = attr.get("value")
        if isinstance(raw_value, dict):
            value = norm(raw_value.get("name") or raw_value.get("label") or raw_value.get("countryName") or json.dumps(raw_value))
        else:
            value = norm(raw_value)
        if not label or not value:
            continue
        parts.append(f"{label}: {value}")
        if not size and re.search(r"\b(size|size bought|usual size|bra size)\b", label, re.I):
            size = value
    variant = norm(review.get("productVariantName"))
    if not size and variant:
        size = variant.rsplit("/", 1)[-1].strip()
    return size, "; ".join(parts)


def fetch_okendo_reviews(
    subscriber_id: str,
    product_id: str,
    product_url: str,
    *,
    delay: float,
    max_pages: int,
) -> Tuple[List[Dict[str, object]], int, str]:
    reviews: List[Dict[str, object]] = []
    pages = 0
    params = {"limit": 100, "orderBy": "has_media desc"}
    url = f"https://api.okendo.io/v1/stores/{subscriber_id}/products/shopify-{product_id}/reviews?{urlencode(params)}"
    seen_pages = set()
    stop_reason = ""
    while url and url not in seen_pages and pages < max_pages:
        seen_pages.add(url)
        try:
            payload = polite_fetch_json(url, referer=product_url, delay=delay)
        except Exception as exc:
            stop_reason = f"review_fetch_failed: {type(exc).__name__}: {exc}"
            break
        pages += 1
        items = payload.get("reviews") or payload.get("data") or []
        if not isinstance(items, list) or not items:
            stop_reason = "no_more_reviews"
            break
        reviews.extend(item for item in items if isinstance(item, dict))
        page_media = sum(1 for item in items if media_urls(item.get("media") or item.get("images") or []))
        if page_media == 0:
            stop_reason = "review_page_had_no_media"
            break
        next_url = norm(payload.get("nextUrl") or payload.get("reviewsNextUrl"))
        url = f"https://api.okendo.io/v1{next_url}" if next_url.startswith("/") else next_url
    if pages >= max_pages and url:
        stop_reason = f"max_review_pages_reached_{max_pages}"
    return reviews, pages, stop_reason or "completed_review_paging"


def related_okendo_contexts(
    reviews: Iterable[Dict[str, object]],
    candidate: Candidate,
    seen_product_ids: set[str],
) -> List[ProductContext]:
    contexts: List[ProductContext] = []
    site_root = candidate.site_url.rstrip("/")
    for review in reviews:
        product_id = norm(review.get("productId")).removeprefix("shopify-")
        if not product_id or product_id in seen_product_ids:
            continue
        product_url = norm(review.get("productUrl"))
        if product_url.startswith("//"):
            product_url = "https:" + product_url
        if product_url:
            parsed = urlparse(product_url)
            product_url = f"{urlparse(site_root).scheme}://{parsed.netloc}{parsed.path}" if parsed.netloc else urljoin(site_root, product_url)
        else:
            product_url = site_root
        context = ProductContext(
            url=canonical_product_url(product_url),
            title=norm(review.get("productName")),
            category=candidate.category,
            brand=candidate.domain,
            variant=norm(review.get("productVariantName")),
            product_id=product_id,
            shop_domain=urlparse(site_root).netloc,
            provider_hints="Okendo related product from review payload",
            raw_html="",
        )
        seen_product_ids.add(product_id)
        contexts.append(context)
    return contexts


def rows_from_reviews(context: ProductContext, reviews: Iterable[Dict[str, object]], fetched_at: str, retailer: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for review in reviews:
        image_urls = media_urls(review.get("media") or review.get("images") or [])
        product_image = norm(review.get("productImageUrl"))
        image_urls = [url for url in image_urls if url != product_image]
        if not image_urls:
            continue
        size, attrs_blob = review_profile_blob(review)
        body = norm(review.get("body") or review.get("reviewBody"))
        if attrs_blob:
            body = norm(f"{body} {attrs_blob}")
        product_url = norm(review.get("productUrl")) or context.url
        if product_url.startswith("//"):
            product_url = "https:" + product_url
        product_title = norm(review.get("productName")) or context.title
        product_variant = norm(review.get("productVariantName")) or context.variant
        reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
        review_id = norm(review.get("reviewId") or review.get("id"))
        for index, image_url in enumerate(image_urls, start=1):
            digest = hashlib.md5(image_url.encode("utf-8")).hexdigest()[:8]
            rows.append(
                build_intake_row(
                    context,
                    ReviewImage(
                        image_url=image_url,
                        review_id=f"{retailer}-okendo-{review_id or 'review'}-{index}-{digest}",
                        review_title=norm(review.get("title")),
                        review_body=body,
                        reviewer_name=norm(reviewer.get("displayName") or review.get("reviewerDisplayName") or review.get("name")),
                        date_raw=norm(review.get("dateCreated") or review.get("createdAt")),
                        size_raw=size,
                        rating=norm(review.get("rating")),
                        extra={
                            "product_url": product_url,
                            "product_title": product_title,
                            "product_variant": product_variant,
                            "image_source_type": "customer_review_image",
                            "image_source_detail": "okendo_review_media",
                        },
                    ),
                    fetched_at,
                )
            )
    return rows


def scrape_candidate(candidate: Candidate, max_products: int, max_review_pages: int, delay: float, dry_run: bool) -> Dict[str, object]:
    started_at = utc_now()
    config = seed_config(candidate)
    retailer = retailer_slug(candidate.domain)
    output_csv, summary_json = output_paths(retailer)
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    rows: List[Dict[str, str]] = []
    review_pages_scanned = 0

    contexts, discovery_summaries, discovery_errors = discover_candidate_products(config, max_products, delay)
    product_summaries.extend(discovery_summaries)
    errors.extend(discovery_errors)

    if not config.subscriber_id:
        errors.append("missing_okendo_subscriber_id")
    elif not dry_run:
        seen_scan_product_ids = {context.product_id for context in contexts if context.product_id}
        scan_index = 0
        while scan_index < len(contexts) and len([c for c in contexts if c.product_id]) <= max_products:
            context = contexts[scan_index]
            scan_index += 1
            matching_summary = next(
                (item for item in product_summaries if item.get("product_id") == context.product_id and not item.get("skip_reason")),
                {},
            )
            reviews, pages, stop_reason = fetch_okendo_reviews(
                config.subscriber_id,
                context.product_id,
                context.url,
                delay=delay,
                max_pages=max_review_pages,
            )
            review_pages_scanned += pages
            product_rows = rows_from_reviews(context, reviews, started_at, retailer)
            matching_summary.update(
                {
                    "reviews_seen": len(reviews),
                    "review_pages_scanned": pages,
                    "customer_media_rows": len(product_rows),
                    "review_stop_reason": stop_reason,
                }
            )
            rows.extend(product_rows)
            for related in related_okendo_contexts(reviews, candidate, seen_scan_product_ids):
                if len(contexts) >= max_products:
                    break
                contexts.append(related)
                product_summaries.append(
                    {
                        "url": related.url,
                        "product_id": related.product_id,
                        "title": related.title,
                        "category": related.category,
                        "subscriber_id": config.subscriber_id,
                        "source": "okendo_related_product",
                        "skip_reason": "",
                    }
                )
            print(
                f"[{candidate.domain} {scan_index}/{len(contexts)}] product_id={context.product_id} reviews={len(reviews)} rows={len(product_rows)}",
                flush=True,
            )

    rows = dedupe_rows(rows)
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    validation = validate_rows(rows)
    summary = {
        "site": candidate.domain,
        "retailer": retailer,
        "adapter": "net_new_gap_okendo_public_reviews",
        "candidate_source": str(DEFAULT_CANDIDATE_CSV),
        "candidate_target_gap_tags": candidate.target_gap_tags,
        "candidate_category": candidate.category,
        "candidate_notes": candidate.notes,
        "review_platform_provider": "Okendo",
        "okendo_subscriber_id": config.subscriber_id,
        "seed_product_ids": config.seed_product_ids,
        "products_discovered": len(contexts),
        "products_scanned": 0 if dry_run else len(contexts),
        "review_pages_scanned": review_pages_scanned,
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": finished_at,
        "dry_run": dry_run,
        "access_policy": "public product pages and public Okendo review JSON only; stop_on_429_captcha_waf_auth",
        "product_summaries": product_summaries,
        "errors": errors,
    }
    summary.update(validation)
    summary["rows_with_distinct_product_url"] = validation.get("distinct_products", 0)
    summary["rows_with_customer_image"] = validation.get("rows_with_customer_review_image", 0)
    summary["rows_with_customer_ordered_size"] = validation.get("rows_with_customer_ordered_size", 0)
    summary["rows_supabase_qualified"] = validation.get("supabase_qualified_rows", 0)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {output_csv}")
    print(f"Wrote {summary_json}")
    print(
        f"{candidate.domain}: rows={len(rows)} products={summary['products_scanned']} "
        f"qualified={summary['rows_supabase_qualified']} measurements={summary['rows_with_any_measurement']}",
        flush=True,
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape net-new public Okendo review images for measurement gap candidates.")
    parser.add_argument("--candidate-csv", type=Path, default=DEFAULT_CANDIDATE_CSV)
    parser.add_argument("--domains", nargs="+", default=DEFAULT_DOMAINS)
    parser.add_argument("--max-products", type=int, default=60)
    parser.add_argument("--max-review-pages", type=int, default=3)
    parser.add_argument("--request-delay-seconds", type=float, default=0.25)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    candidates = read_candidates(args.candidate_csv, args.domains)
    if not candidates:
        raise SystemExit(f"No ready Okendo candidates found in {args.candidate_csv} for {args.domains}")

    summaries = []
    for candidate in candidates:
        summaries.append(
            scrape_candidate(
                candidate,
                max_products=args.max_products,
                max_review_pages=args.max_review_pages,
                delay=args.request_delay_seconds,
                dry_run=args.dry_run,
            )
        )
    print(json.dumps({item["site"]: {"rows": item["rows_written"], "qualified": item["rows_supabase_qualified"]} for item in summaries}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
