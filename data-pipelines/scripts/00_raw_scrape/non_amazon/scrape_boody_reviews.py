#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse, urlsplit, urlunsplit
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


SITE_ROOT = "https://boody.com"
BRAND = "Boody"
YOTPO_APP_KEY = "ygUpOiL7SxhwQ9SJTqklJMvPoD57lERSu47WhSJI"
YOTPO_API_ROOT = f"https://api-cdn.yotpo.com/v1/widget/{YOTPO_APP_KEY}/products"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 150
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
CHALLENGE_RE = re.compile(r"\b(?:captcha|cloudflare|datadome|access denied|attention required|verify you are human)\b", re.I)
BRA_PRODUCT_RE = re.compile(r"\b(?:bra|bralette|bust|crop)\b", re.I)
ACCESSORY_RE = re.compile(r"\b(?:gift card|carbon|ecocart|sock|tote|bag|pad|insert|liner|lint|laundry)\b", re.I)
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
        for match in re.findall(r"<loc>(https://boody\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index, re.I)
    ]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url)
        urls = sorted(set(re.findall(r"https://boody\.com/products/[^<\s\"']+", text, re.I)))
        urls = [url.split("?")[0].rstrip("/") for url in urls]
        sitemap_product_urls.extend(urls)
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})

    missing = [url for url in sorted(set(sitemap_product_urls)) if url not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {"id": "", "handle": handle, "title": handle.replace("-", " ").title(), "vendor": BRAND, "product_type": "", "body_html": "", "variants": []}
    sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)})
    return list(by_url.values()), sources


def variant_detail(product: Dict[str, object]) -> str:
    vals: List[str] = []
    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants[:250]:
            if isinstance(variant, dict):
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
        shop_domain="boodywearus.myshopify.com",
        provider_hints="Yotpo",
    )


def skip_reason(context: ProductContext) -> str:
    text = f"{context.title} {context.category} {context.url}".lower()
    if ACCESSORY_RE.search(text):
        return "out_of_target_accessory_or_non_apparel"
    if not BRA_PRODUCT_RE.search(text):
        return "out_of_target_non_bra_for_sheet_triage"
    return ""


def custom_fields(review: Dict[str, object]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    fields = review.get("custom_fields")
    if not isinstance(fields, dict):
        return out
    for item in fields.values():
        if not isinstance(item, dict):
            continue
        title = normalize_whitespace(item.get("title")).lower()
        value = normalize_whitespace(item.get("value"))
        if title and value:
            out[title] = value
    return out


def size_from_fields(fields: Dict[str, str]) -> str:
    size = normalize_whitespace(fields.get("size"))
    mapping = {
        "XS": "x-small",
        "S": "small",
        "M": "medium",
        "L": "large",
        "XL": "x-large",
        "XXL": "xx-large",
        "XXXL": "xxx-large",
    }
    return mapping.get(size.upper().replace(" ", ""), size.lower())


def band_and_cup(fields: Dict[str, str]) -> Tuple[str, str]:
    band_raw = fields.get("band size", "")
    cup_raw = fields.get("cup size", "")
    band_match = re.search(r"\bUS\s*(\d{2})\b", band_raw, re.I) or re.search(r"\b(2[8-9]|3[0-9]|4[0-8])\b", band_raw)
    cup_match = re.search(r"\b(AA|A|B|C|D|DD|DDD|E|F|G|H|I|J|K)\b", cup_raw, re.I)
    return (band_match.group(1) if band_match else "", cup_match.group(1).upper() if cup_match else "")


def custom_field_text(fields: Dict[str, str]) -> str:
    labels = ["size", "band size", "cup size", "age", "body type", "fit", "comfort", "quality", "product standouts"]
    return " | ".join(f"{label.title()}: {fields[label]}" for label in labels if fields.get(label))


def image_urls(review: Dict[str, object]) -> List[str]:
    images = review.get("images_data")
    if not isinstance(images, list):
        return []
    urls: List[str] = []
    for image in images:
        if isinstance(image, dict):
            url = normalize_whitespace(image.get("original_url") or image.get("thumb_url"))
            if url:
                urls.append(canonical_image_url(url))
    return list(dict.fromkeys(urls))


def fetch_product_reviews(context: ProductContext) -> Tuple[List[ReviewImage], Dict[str, object]]:
    meta: Dict[str, object] = {
        "product_url": context.url,
        "product_title": context.title,
        "adapter_used": "yotpo_product_widget",
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "matching_review_images": 0,
        "errors": [],
    }
    if not context.product_id:
        meta["errors"].append("missing_shopify_product_id")
        return [], meta
    reviews: List[ReviewImage] = []
    total = 0
    for page in range(1, 10000):
        payload = fetch_json(
            f"{YOTPO_API_ROOT}/{context.product_id}/reviews.json",
            {"per_page": REVIEWS_PER_PAGE, "page": page},
            referer=context.url,
        )
        response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
        pagination = response.get("pagination") if isinstance(response.get("pagination"), dict) else {}
        total = int(pagination.get("total") or total or 0)
        page_reviews = [item for item in response.get("reviews", []) if isinstance(item, dict)]
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"]) + 1
        for review in page_reviews:
            fields = custom_fields(review)
            body = " | ".join(part for part in [custom_field_text(fields), normalize_whitespace(review.get("content"))] if part)
            for image_url in image_urls(review):
                reviews.append(
                    ReviewImage(
                        image_url=image_url,
                        review_id=normalize_whitespace(review.get("id")),
                        review_title=normalize_whitespace(review.get("title")),
                        review_body=body,
                        reviewer_name=normalize_whitespace((review.get("user") or {}).get("display_name") if isinstance(review.get("user"), dict) else ""),
                        date_raw=normalize_whitespace(review.get("created_at")),
                        size_raw=size_from_fields(fields),
                        extra={
                            "product_url": context.url,
                            "product_title": context.title,
                            "product_description": context.description,
                            "product_detail": context.detail,
                            "product_category": context.category,
                            "image_source_type": "customer_review_image",
                            "image_source_detail": "Yotpo review image",
                            "band_size": band_and_cup(fields)[0],
                            "cup_size": band_and_cup(fields)[1],
                        },
                    )
                )
        if not page_reviews or page * REVIEWS_PER_PAGE >= total:
            break
        time.sleep(0.1)
    meta["review_count_hint"] = total
    meta["matching_review_images"] = len(reviews)
    return reviews, meta


def postprocess_row(row: Dict[str, str], review: ReviewImage) -> Dict[str, str]:
    row = dict(row)
    if row.get("weight_lbs_display"):
        row["weight_display_display"] = row["weight_lbs_display"]
    elif row.get("weight_display_display") and not re.fullmatch(r"\d+(?:\.\d+)?", row["weight_display_display"]):
        row["weight_display_display"] = ""
    if review.extra.get("band_size"):
        row["bust_in_number_display"] = review.extra["band_size"]
    if review.extra.get("cup_size"):
        row["cupsize_display"] = review.extra["cup_size"]
    return row


def dedupe_yotpo_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    out: List[Dict[str, str]] = []
    for row in rows:
        key = (row.get("id") or "", canonical_image_url(row.get("original_url_display") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


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
            product_summaries.append({
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
            })
            continue
        reviews, meta = fetch_product_reviews(context)
        review_pages_scanned += int(meta.get("review_pages_scanned") or 0)
        total_review_count_hint += int(meta.get("review_count_hint") or 0)
        if meta.get("errors"):
            errors.extend(str(error) for error in meta["errors"])
        product_rows = [postprocess_row(build_intake_row(context, review, fetched_at), review) for review in reviews]
        rows.extend(product_rows)
        product_summaries.append({
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
        })
        print(f"[{index}/{len(products)}] {context.title} reviews={meta.get('review_count_hint')} pages={meta.get('review_pages_scanned')} rows={len(product_rows)}", flush=True)

    rows = dedupe_yotpo_rows(dedupe_rows(rows))
    output_csv, summary_json = output_paths("boody.com")
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    write_summary(
        summary_json,
        site=SITE_ROOT,
        retailer="boody.com",
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=finished_at,
        products_scanned=len(products),
        adapter="yotpo_product_widget_bra_target",
        product_summaries=product_summaries,
        errors=errors,
    )
    strict_measurement_rows = sum(1 for row in rows if any(row.get(field) for field in STRICT_MEASUREMENT_FIELDS))
    strict_qualified_rows = sum(
        1
        for row in rows
        if row.get("original_url_display")
        and row.get("product_page_url_display")
        and row.get("size_display")
        and any(row.get(field) for field in STRICT_MEASUREMENT_FIELDS)
    )
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    summary.update({
        "yotpo_app_key": YOTPO_APP_KEY,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "products_target_scanned": sum(1 for item in product_summaries if not item.get("skipped_from_output")),
        "target_scope": "bra products from verified sheet target",
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
    })
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    summary = scrape()
    print(json.dumps({"boody_com": summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
