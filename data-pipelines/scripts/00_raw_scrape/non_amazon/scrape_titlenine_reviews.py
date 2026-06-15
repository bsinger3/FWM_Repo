#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import time
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    normalize_whitespace,
    output_paths,
    strip_tags,
    validate_rows,
    write_intake_csv,
)


SITE_ROOT = "https://www.titlenine.com"
SOURCE_SITE = f"{SITE_ROOT}/"
POWERREVIEWS_API_ROOT = "https://display.powerreviews.com"
POWERREVIEWS_MERCHANT_ID = "854644"
POWERREVIEWS_API_KEY = "355a3156-8a25-4d91-aa51-edbc7c67409b"
RETAILER = "titlenine_com"
BRAND = "Title Nine"

CATEGORY_URLS = [
    ("https://www.titlenine.com/womens-shorts/?prefn1=isOutletProduct&prefv1=false&start=0&sz=48", "Apparel & Gear / Bottoms / Shorts"),
    ("https://www.titlenine.com/womens-pants/?prefn1=isOutletProduct&prefv1=false&start=0&sz=48", "Apparel & Gear / Bottoms / Pants"),
    ("https://www.titlenine.com/dresses/?prefn1=isOutletProduct&prefv1=false&start=0&sz=48", "Apparel & Gear / Dresses"),
    ("https://www.titlenine.com/womens-tops/?prefn1=isOutletProduct&prefv1=false&start=0&sz=48", "Apparel & Gear / Tops"),
    ("https://www.titlenine.com/womens-athletic-swimwear/?prefn1=isOutletProduct&prefv1=false&start=0&sz=48", "Swim"),
    ("https://www.titlenine.com/womens-corduroy-shorts-pants/?prefn1=isOutletProduct&prefv1=false&start=0&sz=48", "Apparel & Gear / Bottoms / Corduroy Shorts"),
]

APPAREL_RE = re.compile(
    r"\b("
    r"bra|bralette|bikini|bottom|capri|dress|jumpsuit|legging|one piece|pant|rash guard|"
    r"romper|shirt|short|skirt|skort|sweater|swim|swimsuit|tank|tee|tight|top|trouser|tunic"
    r")\b",
    re.I,
)
NON_APPAREL_RE = re.compile(r"\b(bag|belt|bottle|cap|gift card|hat|pack|sandal|shoe|sock|sunglasses)\b", re.I)
SIZE_RE = re.compile(
    r"\b(?:size|sz)\s*[:\-]?\s*("
    r"xxs|xs|s|m|l|xl|xxl|2x|3x|\d{1,2}(?:\s*(?:short|regular|long|tall|petite))?"
    r")\b",
    re.I,
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)


class StopScrapeError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_text(url: str, *, accept: str = "text/html,application/json,*/*", referer: str = "", delay: float = 0.2) -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=45) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.code in {403, 429, 503}:
            raise StopScrapeError(f"stopped_on_http_{exc.code}: {url}") from exc
        raise
    except URLError:
        raise
    if delay > 0:
        time.sleep(delay)
    return text


def fetch_json(url: str, *, referer: str = "", delay: float = 0.2) -> Dict[str, object]:
    return json.loads(fetch_text(url, accept="application/json,text/plain,*/*", referer=referer, delay=delay))


def first_group(pattern: str, text: str, flags: int = re.I | re.S) -> str:
    match = re.search(pattern, text, flags)
    return normalize_whitespace(html.unescape(match.group(1))) if match else ""


def image_url(value: object) -> str:
    url = normalize_whitespace(value)
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    return urljoin(SITE_ROOT, html.unescape(url))


def parse_gtm_product(attr_value: str) -> Dict[str, object]:
    try:
        payload = json.loads(html.unescape(attr_value))
    except json.JSONDecodeError:
        return {}
    ecommerce = payload.get("ecommerce") if isinstance(payload, dict) else {}
    items = ecommerce.get("items") if isinstance(ecommerce, dict) else []
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return {}
    return items[0]


def is_apparel(item: Dict[str, object]) -> bool:
    text = " ".join(
        normalize_whitespace(value)
        for value in [
            item.get("item_name"),
            item.get("item_category"),
            item.get("item_category2"),
            item.get("item_category3"),
            item.get("brand"),
        ]
        if value
    )
    return bool(APPAREL_RE.search(text)) and not (NON_APPAREL_RE.search(text) and not APPAREL_RE.search(text))


def extract_product_description(quickview_html: str) -> Tuple[str, str]:
    description = strip_tags(first_group(r"<div[^>]+class=['\"][^'\"]*product-long-description[^'\"]*['\"][^>]*>(.*?)</div>", quickview_html))
    detail_block = first_group(r"<div[^>]+class=['\"][^'\"]*attributes-container[^'\"]*['\"][^>]*>(.*?)</div>", quickview_html)
    detail_items = []
    for item in re.findall(r"<li[^>]*>(.*?)</li>", detail_block, re.I | re.S):
        clean = strip_tags(item)
        if clean:
            detail_items.append(clean)
    return description, " | ".join(dict.fromkeys(detail_items[:30]))


def fetch_quickview(product: Dict[str, object]) -> Tuple[str, str]:
    variant = normalize_whitespace(product.get("variant"))
    master_id = normalize_whitespace(product.get("item_id"))
    if not variant or not master_id:
        return "", ""
    url = f"{SITE_ROOT}/on/demandware.store/Sites-titlenine_us-Site/default/Product-ShowQuickView?{urlencode({'pid': variant, 'listingSource': 'PLP'})}"
    try:
        payload = fetch_json(url, referer=normalize_whitespace(product.get("_product_url")))
    except Exception:
        return "", ""
    rendered = payload.get("renderedTemplate")
    if not isinstance(rendered, str):
        return "", ""
    return extract_product_description(html.unescape(rendered))


def discover_products(category_limit: int) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    summaries: List[Dict[str, object]] = []
    seen_master_ids = set()
    for category_url, category_name in CATEGORY_URLS[:category_limit]:
        try:
            html_text = fetch_text(category_url, referer=SOURCE_SITE)
        except HTTPError as exc:
            summaries.append(
                {
                    "source": "category_page",
                    "category_url": category_url,
                    "category_name": category_name,
                    "products_found": 0,
                    "error": f"http_{exc.code}",
                }
            )
            continue
        found = 0
        for match in re.finditer(r"<a\b[^>]*\bhref=['\"]([^'\"]+)['\"][^>]*\bdata-gtm=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", html_text, re.I | re.S):
            href, gtm, anchor_text = match.groups()
            item = parse_gtm_product(gtm)
            master_id = normalize_whitespace(item.get("item_id"))
            if not master_id or master_id in seen_master_ids:
                continue
            name = normalize_whitespace(item.get("item_name")) or strip_tags(anchor_text)
            if not name:
                continue
            item["item_name"] = name
            if not is_apparel(item):
                continue
            seen_master_ids.add(master_id)
            product_url = urljoin(SITE_ROOT, html.unescape(href))
            item["_product_url"] = product_url
            item["_source_category"] = category_name
            products.append(item)
            found += 1
        summaries.append({"source": "category_page", "category_url": category_url, "category_name": category_name, "products_found": found})
    return products, summaries


def product_context(product: Dict[str, object], description: str, detail: str) -> ProductContext:
    category_parts = [
        product.get("_source_category"),
        product.get("item_category"),
        product.get("item_category2"),
        product.get("item_category3"),
    ]
    category = " / ".join(dict.fromkeys(normalize_whitespace(part) for part in category_parts if normalize_whitespace(part)))
    color = normalize_whitespace(product.get("variant_color"))
    price = normalize_whitespace(product.get("price"))
    detail_parts = [detail]
    if price:
        detail_parts.append(f"PLP price: ${price}")
    review_count = normalize_whitespace(product.get("product_review_quantity"))
    rating = normalize_whitespace(product.get("product_rating_score"))
    if review_count or rating:
        detail_parts.append(f"PLP reviews: {review_count}; rating: {rating}")
    return ProductContext(
        url=normalize_whitespace(product.get("_product_url")),
        title=normalize_whitespace(product.get("item_name")),
        description=description,
        detail=" | ".join(part for part in detail_parts if part),
        category=category,
        brand=normalize_whitespace(product.get("brand")) or BRAND,
        color=color,
        variant=normalize_whitespace(product.get("variant")),
        product_id=normalize_whitespace(product.get("item_id")),
        shop_domain="www.titlenine.com",
        provider_hints="demandware_plp_quickview; powerreviews_display_api",
    )


def powerreviews_url(product_id: str, *, from_index: int, page_size: int) -> str:
    params = {
        "apikey": POWERREVIEWS_API_KEY,
        "paging.from": from_index,
        "paging.size": page_size,
        "filters": "",
        "search": "",
        "sort": "Newest",
        "image_only": "true",
        "page_locale": "en_US",
    }
    return f"{POWERREVIEWS_API_ROOT}/m/{POWERREVIEWS_MERCHANT_ID}/l/en_US/product/{product_id}/reviews?{urlencode(params)}"


def fetch_review_media(product_id: str, *, max_media_pages: int, page_size: int) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    media: List[Dict[str, object]] = []
    seen = set()
    summary: Dict[str, object] = {"product_id": product_id, "media": 0, "review_count": 0, "rating_count": 0, "pages": 0}
    for page in range(max_media_pages):
        payload = fetch_json(powerreviews_url(product_id, from_index=page * page_size, page_size=page_size), referer=SOURCE_SITE, delay=0.15)
        result = next((item for item in payload.get("results") or [] if isinstance(item, dict)), {})
        rollup = result.get("rollup") if isinstance(result.get("rollup"), dict) else {}
        paging = payload.get("paging") if isinstance(payload.get("paging"), dict) else {}
        summary["review_count"] = rollup.get("review_count", summary.get("review_count", 0))
        summary["rating_count"] = rollup.get("rating_count", summary.get("rating_count", 0))
        summary["total_image_results"] = paging.get("total_results", summary.get("total_image_results", 0))
        page_media = [item for item in rollup.get("media") or [] if isinstance(item, dict)]
        for item in page_media:
            media_id = normalize_whitespace(item.get("id"))
            uri = image_url(item.get("uri"))
            key = (media_id, uri)
            if not uri or key in seen:
                continue
            seen.add(key)
            media.append(item)
        summary["pages"] = page + 1
        pages_total = int(paging.get("pages_total") or 0)
        if not page_media or (pages_total and page + 1 >= pages_total):
            break
    summary["media"] = len(media)
    return media, summary


def date_from_ms(value: object) -> Tuple[str, str]:
    raw = normalize_whitespace(value)
    if not raw:
        return "", ""
    try:
        dt = datetime.fromtimestamp(int(float(raw)) / 1000, tz=timezone.utc)
    except (OverflowError, ValueError):
        return raw, ""
    iso = dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return iso, iso[:10]


def size_from_text(text: str) -> str:
    match = SIZE_RE.search(text)
    return normalize_whitespace(match.group(1)) if match else ""


def rows_for_product(product: Dict[str, object], fetched_at: str, max_media_pages: int, media_page_size: int) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    product_id = normalize_whitespace(product.get("item_id"))
    description, detail = fetch_quickview(product)
    context = product_context(product, description, detail)
    media, review_summary = fetch_review_media(product_id, max_media_pages=max_media_pages, page_size=media_page_size)
    rows: List[Dict[str, str]] = []
    for item in media:
        headline = normalize_whitespace(item.get("headline"))
        caption = normalize_whitespace(item.get("caption"))
        comment = normalize_whitespace(" ".join(part for part in [headline, caption] if part))
        date_raw, review_date = date_from_ms(item.get("created_date"))
        review = ReviewImage(
            image_url=image_url(item.get("uri")),
            review_id=f"titlenine-pr-{product_id}-{normalize_whitespace(item.get('review_id'))}-{normalize_whitespace(item.get('id'))}",
            review_title=headline,
            review_body=caption,
            reviewer_name=normalize_whitespace(item.get("nickname")),
            date_raw=date_raw,
            review_date=review_date,
            size_raw=size_from_text(comment),
            rating=normalize_whitespace(item.get("rating")),
            extra={
                "image_source_type": "customer_review_image",
                "image_source_detail": "PowerReviews display API rollup media",
            },
        )
        rows.append(build_intake_row(context, review, fetched_at))
    review_summary.update(
        {
            "product_url": context.url,
            "product_title": context.title,
            "product_category": context.category,
            "rows": len(rows),
        }
    )
    return rows, review_summary


def scrape(
    *,
    max_products: int,
    category_limit: int,
    max_media_pages: int,
    media_page_size: int,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    products, discovery_summaries = discover_products(category_limit=category_limit)
    selected_products = products[:max_products] if max_products > 0 else products
    fetched_at = utc_now()
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = list(discovery_summaries)
    errors: List[str] = []
    for index, product in enumerate(selected_products, start=1):
        product_id = normalize_whitespace(product.get("item_id"))
        title = normalize_whitespace(product.get("item_name"))
        print(f"[titlenine] {index}/{len(selected_products)} product={product_id} {title}", flush=True)
        try:
            product_rows, summary = rows_for_product(product, fetched_at, max_media_pages, media_page_size)
            rows.extend(product_rows)
            product_summaries.append(summary)
        except StopScrapeError:
            raise
        except Exception as exc:
            errors.append(f"{product_id}: {type(exc).__name__}: {exc}")
            product_summaries.append({"product_id": product_id, "product_title": title, "rows": 0, "error": str(exc)})
    rows = dedupe_rows(rows)
    output_csv, summary_json = output_paths(RETAILER)
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    summary = {
        "site": SOURCE_SITE,
        "retailer": RETAILER,
        "adapter": "demandware_plp_powerreviews_media",
        "started_at": started_at,
        "finished_at": finished_at,
        "output_csv": str(output_csv),
        "products_discovered": len(products),
        "products_scanned": len(selected_products),
        "categories_scanned": len(discovery_summaries),
        "product_summaries": product_summaries,
        "errors": errors,
        "access_policy": "public_category_quickview_and_powerreviews_display_api_only; stops_on_403_429_503",
    }
    summary.update(validate_rows(rows))
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return rows, summary


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Title Nine PowerReviews customer review images.")
    parser.add_argument("--max-products", type=int, default=80)
    parser.add_argument("--category-limit", type=int, default=len(CATEGORY_URLS))
    parser.add_argument("--max-media-pages", type=int, default=4)
    parser.add_argument("--media-page-size", type=int, default=25)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    rows, summary = scrape(
        max_products=args.max_products,
        category_limit=args.category_limit,
        max_media_pages=args.max_media_pages,
        media_page_size=args.media_page_size,
    )
    print(
        json.dumps(
            {
                "rows_written": len(rows),
                "supabase_qualified_rows": summary.get("supabase_qualified_rows"),
                "products_discovered": summary.get("products_discovered"),
                "products_scanned": summary.get("products_scanned"),
                "output_csv": summary.get("output_csv"),
                "errors": len(summary.get("errors") or []),
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
