#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    write_intake_csv,
    write_summary,
)


SITE_ROOT = "https://branwyn.com"
SHOP_DOMAIN = "branwyn.myshopify.com"
BRAND = "BRANWYN"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 20
JUDGEME_WIDGET_URL = "https://api.judge.me/reviews/reviews_for_widget"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
CHALLENGE_RE = re.compile(r"\b(?:captcha|cloudflare|datadome|access denied|attention required|verify you are human)\b", re.I)
GENERIC_SIZE_RE = re.compile(
    r"^(?:xx-small|x-small|small|medium|large|x-large|xx-large|xxx-large|xxs|xs|s|m|l|xl|xlg|xxl|xxxl|[1-4]x)$",
    re.I,
)
SIZE_TOKEN_RE = (
    r"(?:xxs|xs|s|m|l|xl|xlg|xxl|xxxl|[1-4]x|x-small|small|medium|large|x-large|xx-large|xxx-large)"
)
STRICT_MEASUREMENT_FIELDS = [
    "height_in_display",
    "weight_display_display",
    "weight_lbs_display",
    "bust_in_number_display",
    "hips_in_display",
    "waist_in",
    "inseam_inches_display",
]


class StopScrape(RuntimeError):
    pass


def fetch_text(url: str, *, referer: str = SITE_ROOT, retries: int = 3) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/json,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": referer,
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8", "replace")
                if CHALLENGE_RE.search(body[:5000]):
                    raise StopScrape(f"Stopping on challenge-like response for {url}")
                return body
        except HTTPError as exc:
            last_error = exc
            if exc.code in {403, 429}:
                raise StopScrape(f"Stopping on HTTP {exc.code} for {url}") from exc
            if exc.code not in {408, 500, 502, 503, 504}:
                raise
        except URLError as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"Failed text request for {url}: {last_error}")


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, *, referer: str = SITE_ROOT) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    return json.loads(fetch_text(query_url, referer=referer))


def canonical_image_url(url: str) -> str:
    clean = html.unescape(normalize_whitespace(url))
    if clean.startswith("//"):
        clean = "https:" + clean
    parts = urlsplit(clean)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def unique(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        clean = canonical_image_url(value)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def product_url_for(product: Dict[str, object]) -> str:
    handle = normalize_whitespace(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def discover_products() -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    by_url: Dict[str, Dict[str, object]] = {}
    sources: List[Dict[str, object]] = []
    page = 1
    while True:
        payload = fetch_json(f"{SITE_ROOT}/products.json", {"limit": PRODUCTS_PER_PAGE, "page": page})
        products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        sources.append({"source": "products.json", "page": page, "count": len(products)})
        for product in products:
            url = product_url_for(product)
            if url:
                by_url[url] = product
        if len(products) < PRODUCTS_PER_PAGE:
            break
        page += 1
        time.sleep(0.2)

    sitemap_index = fetch_text(f"{SITE_ROOT}/sitemap.xml")
    sitemap_urls = [
        html.unescape(match)
        for match in re.findall(r"<loc>(https://branwyn\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index, re.I)
    ]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url)
        urls = sorted(set(re.findall(r"https://branwyn\.com/products/[^<\s\"']+", text, re.I)))
        urls = [url.split("?")[0].rstrip("/") for url in urls]
        sitemap_product_urls.extend(urls)
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})

    missing = [url for url in sorted(set(sitemap_product_urls)) if url not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {
            "id": "",
            "handle": handle,
            "title": handle.replace("-", " ").title(),
            "vendor": BRAND,
            "product_type": "",
            "body_html": "",
            "variants": [],
        }
    sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)})
    return list(by_url.values()), sources


def variant_detail(product: Dict[str, object]) -> str:
    vals: List[str] = []
    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants[:250]:
            if not isinstance(variant, dict):
                continue
            title = normalize_whitespace(variant.get("title"))
            if title and title.lower() != "default title" and title not in vals:
                vals.append(title)
    return " | ".join(vals)


def context_from_product(product: Dict[str, object]) -> ProductContext:
    return ProductContext(
        url=product_url_for(product),
        title=normalize_whitespace(product.get("title")),
        description=strip_tags(product.get("body_html")),
        detail=variant_detail(product),
        category=normalize_whitespace(product.get("product_type")),
        brand=normalize_whitespace(product.get("vendor")) or BRAND,
        product_id=normalize_whitespace(product.get("id")),
        handle=normalize_whitespace(product.get("handle")),
        shop_domain=SHOP_DOMAIN,
        provider_hints="Judge.me",
    )


def skip_reason(context: ProductContext) -> str:
    text = f"{context.title} {context.category} {context.url}".lower()
    if "gift card" in text:
        return "out_of_scope_gift_card"
    if any(term in text for term in ["ecocart", "carbon footprint"]):
        return "out_of_scope_carbon_offset"
    if any(term in text for term in ["bra pads", "laundry bag", "lingerie bag", "lint roller"]):
        return "out_of_scope_accessory"
    return ""


def normalize_size(value: str) -> str:
    clean = normalize_whitespace(value).replace("-", " ")
    compact = clean.upper().replace(" ", "")
    mapping = {
        "XXS": "xx-small",
        "XS": "x-small",
        "S": "small",
        "M": "medium",
        "L": "large",
        "XL": "x-large",
        "XLG": "x-large",
        "XXL": "xx-large",
        "XXXL": "xxx-large",
        "XSMALL": "x-small",
        "SMALL": "small",
        "MEDIUM": "medium",
        "LARGE": "large",
        "XLARGE": "x-large",
        "XXLARGE": "xx-large",
        "XXXLARGE": "xxx-large",
        "1X": "x-large",
        "2X": "xx-large",
        "3X": "xxx-large",
    }
    return mapping.get(compact, clean.lower())


def deterministic_size(comment: str, current_value: str) -> str:
    current = normalize_whitespace(current_value)
    normalized_current = normalize_size(current)
    if GENERIC_SIZE_RE.fullmatch(normalized_current):
        return normalized_current
    for pattern in [
        rf"\b(?:ordered|bought|purchased|got|wearing|wear|wore|tried|chose|choose|selected)\s+(?:the\s+|a\s+|an\s+)?(?:size\s+)?(?P<size>{SIZE_TOKEN_RE})\b",
        rf"\b(?:says|tagged|marked)\s+size\s+(?P<size>{SIZE_TOKEN_RE})\b",
        rf"\bsize\s+(?P<size>{SIZE_TOKEN_RE})\b",
    ]:
        match = re.search(pattern, comment, re.I)
        if match:
            return normalize_size(match.group("size"))
    return ""


def postprocess_row(row: Dict[str, str]) -> Dict[str, str]:
    row = dict(row)
    row["size_display"] = deterministic_size(row.get("user_comment", ""), row.get("size_display", ""))
    if row.get("weight_lbs_display"):
        row["weight_display_display"] = row["weight_lbs_display"]
    elif row.get("weight_display_display") and not re.fullmatch(r"\d+(?:\.\d+)?", row["weight_display_display"]):
        row["weight_display_display"] = ""
    return row


def extract_attr(fragment: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}=['\"]([^'\"]*)['\"]", fragment, re.I)
    return normalize_whitespace(html.unescape(match.group(1))) if match else ""


def first_or_blank(patterns: Sequence[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return strip_tags(match.group(1))
    return ""


def split_review_blocks(html_text: str) -> List[str]:
    marker = r"<div[^>]+class=['\"][^'\"]*jdgm-rev\b"
    starts = [match.start() for match in re.finditer(marker, html_text, re.I)]
    blocks: List[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else min(len(html_text), start + 30000)
        blocks.append(html_text[start:end])
    return blocks


def parse_custom_fields(block: str) -> str:
    fields: List[str] = []
    for label, value in re.findall(
        r"jdgm-rev__cf-ans__title[^>]*>(.*?)</b>\s*<span[^>]+class=['\"][^'\"]*jdgm-rev__cf-ans__value[^'\"]*['\"][^>]*>(.*?)</span>",
        block,
        re.I | re.S,
    ):
        clean_label = strip_tags(label).rstrip(":")
        clean_value = strip_tags(value)
        if clean_label and clean_value:
            fields.append(f"{clean_label}: {clean_value}")
    return " | ".join(fields)


def parse_widget_html(widget_html: str, context: ProductContext) -> List[ReviewImage]:
    reviews: List[ReviewImage] = []
    for block in split_review_blocks(widget_html):
        review_id = extract_attr(block, "data-review-id")
        product_url = extract_attr(block, "data-product-url")
        if product_url.startswith("/"):
            product_url = urljoin(SITE_ROOT, product_url)
        title = first_or_blank([r"<b[^>]+class=['\"][^'\"]*jdgm-rev__title[^'\"]*['\"][^>]*>(.*?)</b>"], block)
        body = first_or_blank([r"<div[^>]+class=['\"][^'\"]*jdgm-rev__body[^'\"]*['\"][^>]*>(.*?)</div>"], block)
        author = first_or_blank([r"<span[^>]+class=['\"][^'\"]*jdgm-rev__author[^'\"]*['\"][^>]*>(.*?)</span>"], block)
        date_raw = extract_attr(block, "data-content") or extract_attr(block, "data-created-at")
        custom_fields = parse_custom_fields(block)
        comment_body = " | ".join(part for part in [custom_fields, body] if part)
        image_urls = unique(
            match
            for match in re.findall(
                r"(?:data-mfp-src|data-src|href|src)=['\"]([^'\"]+\.(?:jpg|jpeg|png|webp)(?:\?[^'\"]*)?)['\"]",
                block,
                re.I,
            )
            if "judgeme.imgix.net" in match or "judge.me" in match
        )
        for image_url in image_urls:
            reviews.append(
                ReviewImage(
                    image_url=image_url,
                    review_id=review_id,
                    review_title=title,
                    review_body=comment_body,
                    reviewer_name=author,
                    date_raw=date_raw,
                    extra={
                        "product_url": product_url or context.url,
                        "product_title": context.title,
                        "product_description": context.description,
                        "product_detail": context.detail,
                        "product_category": context.category,
                        "image_source_type": "customer_review_image",
                        "image_source_detail": "Judge.me review image",
                    },
                )
            )
    return reviews


def fetch_product_reviews(context: ProductContext) -> Tuple[List[ReviewImage], Dict[str, object]]:
    meta: Dict[str, object] = {
        "product_url": context.url,
        "product_title": context.title,
        "adapter_used": "judgeme_product_widget",
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "matching_review_images": 0,
        "errors": [],
    }
    if not context.product_id:
        meta["errors"].append("missing_shopify_product_id")
        return [], meta
    reviews: List[ReviewImage] = []
    seen = set()
    for page in range(1, 10000):
        params = {
            "url": urlparse(SITE_ROOT).netloc,
            "shop_domain": SHOP_DOMAIN,
            "platform": "shopify",
            "per_page": REVIEWS_PER_PAGE,
            "page": page,
            "product_id": context.product_id,
            "sort_by": "with_pictures",
        }
        payload = fetch_json(JUDGEME_WIDGET_URL, params, referer=context.url)
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"]) + 1
        meta["review_count_hint"] = max(int(meta["review_count_hint"] or 0), int(payload.get("total_count") or 0))
        widget_html = html.unescape(str(payload.get("html") or ""))
        page_reviews = []
        for review in parse_widget_html(widget_html, context):
            key = (review.review_id, review.image_url)
            if key in seen:
                continue
            seen.add(key)
            page_reviews.append(review)
        reviews.extend(page_reviews)
        if not page_reviews or page * REVIEWS_PER_PAGE >= int(meta["review_count_hint"] or 0):
            break
        time.sleep(0.2)
    meta["matching_review_images"] = len(reviews)
    return reviews, meta


def dedupe_judgeme_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        key = (row.get("id") or "", canonical_image_url(row.get("original_url_display") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def scrape() -> Dict[str, object]:
    started_at = utc_now()
    products, product_sources = discover_products()
    fetched_at = utc_now()
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    review_pages_scanned = 0
    total_review_count_hint = 0

    for index, product in enumerate(products, start=1):
        context = context_from_product(product)
        reason = skip_reason(context)
        if reason:
            product_summaries.append(
                {
                    "product_index": index,
                    "product_id": context.product_id,
                    "product_title": context.title,
                    "product_url": context.url,
                    "adapter_used": "skipped_from_output",
                    "review_pages_scanned": 0,
                    "review_count_hint": 0,
                    "matching_review_images": 0,
                    "rows": 0,
                    "errors": [],
                    "skipped_from_output": True,
                    "skip_reason": reason,
                }
            )
            print(f"[{index}/{len(products)}] {context.title} skipped={reason}", flush=True)
            continue
        reviews, meta = fetch_product_reviews(context)
        review_pages_scanned += int(meta.get("review_pages_scanned") or 0)
        total_review_count_hint += int(meta.get("review_count_hint") or 0)
        if meta.get("errors"):
            errors.extend(str(error) for error in meta["errors"])
        product_rows = [postprocess_row(build_intake_row(context, review, fetched_at)) for review in reviews]
        rows.extend(product_rows)
        product_summaries.append(
            {
                "product_index": index,
                "product_id": context.product_id,
                "product_title": context.title,
                "product_url": context.url,
                "adapter_used": meta.get("adapter_used"),
                "review_pages_scanned": meta.get("review_pages_scanned"),
                "review_count_hint": meta.get("review_count_hint"),
                "matching_review_images": meta.get("matching_review_images"),
                "rows": len(product_rows),
                "errors": meta.get("errors"),
                "skipped_from_output": False,
                "skip_reason": "",
            }
        )
        print(f"[{index}/{len(products)}] {context.title} reviews={meta.get('review_count_hint')} rows={len(product_rows)}", flush=True)

    rows = dedupe_judgeme_rows(dedupe_rows(rows))
    output_csv, summary_json = output_paths("branwyn.com")
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    write_summary(
        summary_json,
        site=SITE_ROOT,
        retailer="branwyn.com",
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=finished_at,
        products_scanned=len(products),
        adapter="judgeme_product_widget",
        product_summaries=product_summaries,
        errors=errors,
    )
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    strict_measurement_rows = sum(1 for row in rows if any(row.get(field) for field in STRICT_MEASUREMENT_FIELDS))
    strict_qualified_rows = sum(
        1
        for row in rows
        if row.get("original_url_display")
        and row.get("product_page_url_display")
        and row.get("size_display")
        and any(row.get(field) for field in STRICT_MEASUREMENT_FIELDS)
    )
    summary.update(
        {
            "product_sources": product_sources,
            "products_discovered": len(products),
            "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
            "review_pages_scanned": review_pages_scanned,
            "product_review_count_hint": total_review_count_hint,
            "exhaustive_review_paging": True,
            "rows_with_distinct_product_url": len({row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}),
            "rows_with_product_url": sum(1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display")),
            "rows_with_any_measurement": strict_measurement_rows,
            "rows_with_image_product_and_measurement": strict_measurement_rows,
            "rows_with_customer_image": sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image"),
            "rows_supabase_qualified": strict_qualified_rows,
            "supabase_qualified_rows": strict_qualified_rows,
            "rows_with_image_product_size_and_measurement": strict_qualified_rows,
            "metric_note": "rows_with_any_measurement and rows_supabase_qualified use strict Step 1 project body-measurement fields, excluding cup-only/raw-only matches.",
        }
    )
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    summary = scrape()
    print(json.dumps({"branwyn_com": summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
