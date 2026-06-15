#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    output_paths,
    normalize_whitespace,
    validate_rows,
    write_intake_csv,
)


SITE_ROOT = "https://oldnavy.gap.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCT_SEARCH_URL = "https://api.gap.com/commerce/search/products/v2/cc"
POWERREVIEWS_API_ROOT = "https://display.powerreviews.com"
POWERREVIEWS_MERCHANT_ID = "650520397"
POWERREVIEWS_API_KEY = "96e4b93c-348e-4f21-847b-028497ff9f1c"
RETAILER = "oldnavy_com"
BRAND = "Old Navy"

WOMEN_CATEGORY_IDS = [
    ("1185233", "Women / Shop All"),
    ("5508", "Women / Activewear"),
]

APPAREL_RE = re.compile(
    r"\b("
    r"bra|bralette|dress|jumpsuit|romper|pajamas?|sleep|set|top|tee|t-shirt|shirt|tank|cami|"
    r"sweater|sweatshirt|hoodie|cardigan|jacket|coat|vest|skirt|skort|pant|trouser|jean|legging|"
    r"shorts?|bodysuit|tunic|blouse|activewear|maternity"
    r")\b",
    re.I,
)
NON_APPAREL_RE = re.compile(
    r"\b(sock|socks|shoe|shoes|sandal|boot|hat|cap|bag|tote|belt|scarf|glove|mittens?|gift card)\b",
    re.I,
)
SIZE_RE = re.compile(
    r"\b(?:size|sz)\s*[:\-]?\s*(xxs|xs|s|m|l|xl|xxl|2x|3x|4x|\d{1,2}(?:\s*(?:short|regular|long|tall|petite))?)\b",
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


def fetch_json(url: str, *, headers: Optional[Dict[str, str]] = None, retries: int = 3, delay: float = 0.25) -> Dict[str, object]:
    last_error: Optional[Exception] = None
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        **(headers or {}),
    }
    for attempt in range(retries):
        req = Request(url, headers=request_headers)
        try:
            with urlopen(req, timeout=45) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            if delay > 0:
                time.sleep(delay)
            return payload
        except HTTPError as exc:
            last_error = exc
            if exc.code in {403, 429, 503}:
                raise StopScrapeError(f"stopped_on_http_{exc.code}: {url}") from exc
            if exc.code not in {408, 500, 502, 504}:
                raise
        except (URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"failed_json_request: {url}: {last_error}")


def product_search_url(category_id: str, page_number: int, page_size: int) -> str:
    params = {
        "pageSize": page_size,
        "pageNumber": page_number,
        "ignoreInventory": "false",
        "cid": category_id,
        "includeMarketingFlagsDetails": "true",
        "enableDynamicPhoto": "true",
        "brand": "on",
        "locale": "en_US",
        "market": "us",
    }
    return f"{PRODUCT_SEARCH_URL}?{urlencode(params)}"


def fetch_product_page(category_id: str, page_number: int, page_size: int) -> Dict[str, object]:
    return fetch_json(
        product_search_url(category_id, page_number, page_size),
        headers={"x-client-application-name": "Browse"},
    )


def image_url(path: object) -> str:
    value = normalize_whitespace(path)
    if not value:
        return ""
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("http"):
        return value
    return f"https://www2.assets-gap.com/{value.lstrip('/')}"


def first_customer_choice(product: Dict[str, object]) -> Dict[str, object]:
    colors = product.get("styleColors")
    if isinstance(colors, list):
        for color in colors:
            if isinstance(color, dict) and normalize_whitespace(color.get("ccId")):
                return color
    return {}


def product_url(product: Dict[str, object]) -> str:
    choice = first_customer_choice(product)
    pid = normalize_whitespace(choice.get("ccId")) or normalize_whitespace(product.get("styleId"))
    return f"{SITE_ROOT}/browse/product.do?pid={pid}&vid=1"


def product_detail(product: Dict[str, object]) -> str:
    parts: List[str] = []
    for color in product.get("styleColors") or []:
        if not isinstance(color, dict):
            continue
        color_name = normalize_whitespace(color.get("ccShortDescription") or color.get("ccName"))
        price = normalize_whitespace(color.get("effectivePrice"))
        if color_name:
            parts.append(f"{color_name}{f' (${price})' if price else ''}")
    return " | ".join(parts[:60])


def product_context(product: Dict[str, object], category_name: str) -> ProductContext:
    choice = first_customer_choice(product)
    return ProductContext(
        url=product_url(product),
        title=normalize_whitespace(product.get("styleName")),
        description=normalize_whitespace(product.get("webProductType")),
        detail=product_detail(product),
        category=category_name,
        brand=BRAND,
        color=normalize_whitespace(choice.get("ccShortDescription") or choice.get("ccName")),
        variant=normalize_whitespace(choice.get("ccId")),
        product_id=normalize_whitespace(product.get("styleId")),
        shop_domain="oldnavy.gap.com",
        provider_hints="gap_public_product_search_api; powerreviews_display_api",
    )


def is_apparel(product: Dict[str, object]) -> bool:
    text = " ".join(
        normalize_whitespace(part)
        for part in [product.get("styleName"), product.get("webProductType")]
        if part
    )
    return bool(APPAREL_RE.search(text)) and not (NON_APPAREL_RE.search(text) and not APPAREL_RE.search(text))


def discover_products(max_category_pages: int, page_size: int) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    summaries: List[Dict[str, object]] = []
    seen_style_ids = set()
    for category_id, category_name in WOMEN_CATEGORY_IDS:
        for page_number in range(max_category_pages):
            payload = fetch_product_page(category_id, page_number, page_size)
            page_products = [item for item in payload.get("products") or [] if isinstance(item, dict)]
            pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
            summaries.append(
                {
                    "source": "product_search",
                    "category_id": category_id,
                    "category_name": category_name,
                    "page_number": page_number,
                    "products_returned": len(page_products),
                    "page_number_total": pagination.get("pageNumberTotal"),
                }
            )
            if not page_products:
                break
            for product in page_products:
                style_id = normalize_whitespace(product.get("styleId"))
                if not style_id or style_id in seen_style_ids:
                    continue
                seen_style_ids.add(style_id)
                product["_oldnavy_category_name"] = category_name
                if is_apparel(product):
                    products.append(product)
            try:
                pages_total = int(str(pagination.get("pageNumberTotal") or "0"))
            except ValueError:
                pages_total = 0
            if pages_total and page_number + 1 >= pages_total:
                break
    return products, summaries


def powerreviews_url(style_id: str, *, from_index: int, page_size: int) -> str:
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
    return (
        f"{POWERREVIEWS_API_ROOT}/m/{POWERREVIEWS_MERCHANT_ID}/l/en_US/product/"
        f"{style_id}/reviews?{urlencode(params)}"
    )


def fetch_review_media(style_id: str, *, max_media_pages: int, page_size: int) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    media: List[Dict[str, object]] = []
    seen = set()
    summary: Dict[str, object] = {"style_id": style_id, "media": 0, "review_count": 0, "rating_count": 0, "pages": 0}
    for page in range(max_media_pages):
        payload = fetch_json(powerreviews_url(style_id, from_index=page * page_size, page_size=page_size), delay=0.15)
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
    context = product_context(product, normalize_whitespace(product.get("_oldnavy_category_name")))
    style_id = context.product_id
    media, review_summary = fetch_review_media(style_id, max_media_pages=max_media_pages, page_size=media_page_size)
    rows: List[Dict[str, str]] = []
    for item in media:
        headline = normalize_whitespace(item.get("headline"))
        caption = normalize_whitespace(item.get("caption"))
        comment = normalize_whitespace(" ".join(part for part in [headline, caption] if part))
        date_raw, review_date = date_from_ms(item.get("created_date"))
        review = ReviewImage(
            image_url=image_url(item.get("uri")),
            review_id=f"oldnavy-pr-{style_id}-{normalize_whitespace(item.get('review_id'))}-{normalize_whitespace(item.get('id'))}",
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
        row = build_intake_row(context, review, fetched_at)
        rows.append(row)
    review_summary.update(
        {
            "product_id": style_id,
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
    max_category_pages: int,
    product_page_size: int,
    max_media_pages: int,
    media_page_size: int,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    products, discovery_summaries = discover_products(max_category_pages=max_category_pages, page_size=product_page_size)
    selected_products = products[:max_products] if max_products > 0 else products
    fetched_at = utc_now()
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = list(discovery_summaries)
    errors: List[str] = []
    for index, product in enumerate(selected_products, start=1):
        style_id = normalize_whitespace(product.get("styleId"))
        title = normalize_whitespace(product.get("styleName"))
        print(f"[oldnavy] {index}/{len(selected_products)} style={style_id} {title}", flush=True)
        try:
            product_rows, summary = rows_for_product(product, fetched_at, max_media_pages, media_page_size)
            rows.extend(product_rows)
            product_summaries.append(summary)
        except StopScrapeError:
            raise
        except Exception as exc:
            errors.append(f"{style_id}: {type(exc).__name__}: {exc}")
            product_summaries.append({"product_id": style_id, "product_title": title, "rows": 0, "error": str(exc)})
    rows = dedupe_rows(rows)
    output_csv, summary_json = output_paths(RETAILER)
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    summary = {
        "site": SOURCE_SITE,
        "retailer": RETAILER,
        "adapter": "gap_product_search_powerreviews_media",
        "started_at": started_at,
        "finished_at": finished_at,
        "output_csv": str(output_csv),
        "products_discovered": len(products),
        "products_scanned": len(selected_products),
        "category_pages_scanned": len(discovery_summaries),
        "product_summaries": product_summaries,
        "errors": errors,
        "access_policy": "public_product_search_api_and_powerreviews_display_api_only; stops_on_403_429_503",
    }
    summary.update(validate_rows(rows))
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return rows, summary


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Old Navy PowerReviews customer review images.")
    parser.add_argument("--max-products", type=int, default=120)
    parser.add_argument("--max-category-pages", type=int, default=8)
    parser.add_argument("--product-page-size", type=int, default=40)
    parser.add_argument("--max-media-pages", type=int, default=4)
    parser.add_argument("--media-page-size", type=int, default=25)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    rows, summary = scrape(
        max_products=args.max_products,
        max_category_pages=args.max_category_pages,
        product_page_size=args.product_page_size,
        max_media_pages=args.max_media_pages,
        media_page_size=args.media_page_size,
    )
    print(
        json.dumps(
            {
                "rows_written": len(rows),
                "supabase_qualified_rows": summary.get("supabase_qualified_rows"),
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
