#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    normalize_whitespace,
    strip_tags,
    validate_rows,
    write_intake_csv,
)


RETAILER = "dickies_com"
SITE_ROOT = "https://www.dickies.com"
SOURCE_SITE = f"{SITE_ROOT}/"
BRAND = "Dickies"
SHOP_DOMAIN = "dickies.myshopify.com"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
YOTPO_APP_KEY = "ckQamCtpnMhLDfMYxtBc5SvDmtKKmMWz4Mq0gpaj"
YOTPO_API_ROOT = f"https://api-cdn.yotpo.com/v1/widget/{YOTPO_APP_KEY}/products"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 100
DEFAULT_REQUEST_DELAY_SECONDS = 0.15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema_summary.json"
ROWS_CHECKPOINT_JSONL = OUTPUT_DIR / f"{RETAILER}_rows_checkpoint.jsonl"
PRODUCTS_CHECKPOINT_JSONL = OUTPUT_DIR / f"{RETAILER}_product_summaries_checkpoint.jsonl"

BLOCK_TEXT_RE = re.compile(
    r"cf-chl|cloudflare challenge|access denied|temporarily blocked|bot protection|"
    r"unusual traffic|attention required|verify you are human|captcha|perimeterx|datadome|awswaf",
    re.I,
)
WOMENS_RE = re.compile(r"\b(women|women's|womens|woman|ladies|female)\b|women-", re.I)
NON_WOMENS_RE = re.compile(r"\b(men|men's|mens|boys?|girls?|kids?|toddler|infant|baby)\b|men-|kids-", re.I)
NON_CLOTHING_RE = re.compile(
    r"\b(gift\s*card|hat|cap|beanie|sock|belt|bag|backpack|wallet|sticker|patch|"
    r"shoe|boot|laces|insole|shipping|returns?\s*protection|warranty|insurance)\b",
    re.I,
)
MEASUREMENT_FIELDS = [
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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def polite_pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def request_url(url: str, *, accept: str, referer: str, delay: float) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        },
    )
    try:
        with urlopen(req, timeout=60) as resp:
            body = resp.read()
            content_type = resp.headers.get("content-type", "")
    except HTTPError as exc:
        if exc.code in {403, 409, 418, 429}:
            raise StopScrape(f"Stopped after HTTP {exc.code} for {url}") from exc
        raise
    except URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc
    if "json" in content_type or "html" in content_type or "xml" in content_type or not content_type:
        preview = body[:100000].decode("utf-8", "replace")
        if BLOCK_TEXT_RE.search(preview):
            raise StopScrape(f"Stopped after captcha/WAF-like content for {url}")
    polite_pause(delay)
    return body


def fetch_text(url: str, *, referer: str = SOURCE_SITE, delay: float = DEFAULT_REQUEST_DELAY_SECONDS) -> str:
    return request_url(
        url,
        accept="text/html,application/xml,text/xml,*/*",
        referer=referer,
        delay=delay,
    ).decode("utf-8", "replace")


def fetch_json(
    url: str,
    params: Optional[Dict[str, object]] = None,
    *,
    referer: str = SOURCE_SITE,
    delay: float = DEFAULT_REQUEST_DELAY_SECONDS,
) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    body = request_url(query_url, accept="application/json,text/plain,*/*", referer=referer, delay=delay)
    return json.loads(body.decode("utf-8", "replace"))


def clean_url(value: object) -> str:
    text = html.unescape(normalize_whitespace(value)).replace("&amp;", "&")
    if not text:
        return ""
    if text.startswith("//"):
        text = "https:" + text
    parts = urlsplit(text)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def product_url_for(product: Dict[str, object]) -> str:
    handle = normalize_whitespace(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def product_text(product: Dict[str, object]) -> str:
    tags = product.get("tags")
    tags_text = " ".join(str(tag) for tag in tags) if isinstance(tags, list) else normalize_whitespace(tags)
    return " ".join(
        normalize_whitespace(part)
        for part in [
            product.get("title"),
            product.get("handle"),
            product.get("product_type"),
            product.get("vendor"),
            tags_text,
            product_url_for(product),
        ]
        if part
    )


def skip_reason(product: Dict[str, object]) -> str:
    text = product_text(product)
    category = normalize_whitespace(product.get("product_type")).lower()
    title = normalize_whitespace(product.get("title")).lower()
    handle = normalize_whitespace(product.get("handle")).lower()
    if category.startswith(("men-", "kids-", "boys-", "girls-", "accessories-")):
        return "out_of_scope_product_type"
    if ("mens-" in handle or "men-s-" in handle or "boys-" in handle or "girls-" in handle) and "women" not in title:
        return "out_of_scope_non_womens_product"
    if NON_CLOTHING_RE.search(text):
        return "out_of_scope_accessory_or_non_clothing"
    if NON_WOMENS_RE.search(text) and not WOMENS_RE.search(text):
        return "out_of_scope_non_womens_product"
    if not WOMENS_RE.search(text):
        return "out_of_scope_no_womens_signal"
    return ""


def variant_detail(product: Dict[str, object]) -> str:
    values: List[str] = []
    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants[:300]:
            if not isinstance(variant, dict):
                continue
            title = normalize_whitespace(variant.get("title"))
            sku = normalize_whitespace(variant.get("sku"))
            pieces = [piece for piece in [title, sku] if piece and piece.lower() != "default title"]
            value = " / ".join(pieces)
            if value and value not in values:
                values.append(value)
    return " | ".join(values[:120])


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
        provider_hints="Yotpo; PowerReviews",
    )


def fetch_products(delay: float, limit_products: Optional[int] = None) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    sources: List[Dict[str, object]] = []
    for page in range(1, 10000):
        payload = fetch_json(PRODUCTS_JSON_URL, {"limit": PRODUCTS_PER_PAGE, "page": page}, delay=delay)
        page_products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        sources.append({"source": "products.json", "page": page, "count": len(page_products)})
        if not page_products:
            break
        products.extend(page_products)
        print(f"[catalog page {page}] products={len(page_products)} total={len(products)}", flush=True)
        if len(page_products) < PRODUCTS_PER_PAGE:
            break

    sitemap_product_urls: List[str] = []
    sitemap_index = fetch_text(SITEMAP_URL, delay=delay)
    sitemap_urls = [
        html.unescape(match)
        for match in re.findall(r"<loc>(https://www\.dickies\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index, re.I)
        if "/fr" not in match and "/en-ca" not in match and "/fr-ca" not in match
    ]
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url, delay=delay)
        urls = sorted({clean_url(url) for url in re.findall(r"https://www\.dickies\.com/products/[^<\s\"']+", text, re.I)})
        sitemap_product_urls.extend(urls)
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})

    by_url: Dict[str, Dict[str, object]] = {}
    for product in products:
        url = product_url_for(product)
        if url:
            by_url[clean_url(url)] = product
    missing = [url for url in sorted(set(sitemap_product_urls)) if clean_url(url) not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[clean_url(url)] = {
            "id": "",
            "handle": handle,
            "title": handle.replace("-", " ").title(),
            "product_type": "",
            "body_html": "",
            "vendor": BRAND,
            "tags": [],
            "variants": [],
        }
    sources.append(
        {
            "source": "reconciled_products",
            "count": len(by_url),
            "sitemap_missing_from_products_json": len(missing),
            "duplicates_removed": len(products) + len(set(sitemap_product_urls)) - len(by_url),
        }
    )
    reconciled = list(by_url.values())
    if limit_products is not None:
        reconciled = reconciled[:limit_products]
        sources.append({"source": "limit_products_debug", "count": len(reconciled)})
    return reconciled, sources


def yotpo_reviews_url(product_id: str) -> str:
    return f"{YOTPO_API_ROOT}/{quote(product_id)}/reviews.json"


def response_reviews(payload: Dict[str, object]) -> List[Dict[str, object]]:
    response = payload.get("response")
    if isinstance(response, dict):
        reviews = response.get("reviews")
        if isinstance(reviews, list):
            return [review for review in reviews if isinstance(review, dict)]
    return []


def response_total(payload: Dict[str, object]) -> int:
    response = payload.get("response")
    if not isinstance(response, dict):
        return 0
    bottomline = response.get("bottomline")
    if isinstance(bottomline, dict):
        try:
            return int(bottomline.get("total_review") or 0)
        except (TypeError, ValueError):
            return 0
    pagination = response.get("pagination")
    if isinstance(pagination, dict):
        try:
            return int(pagination.get("total") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def custom_field_map(review: Dict[str, object]) -> Dict[str, str]:
    fields = review.get("custom_fields")
    out: Dict[str, str] = {}
    if isinstance(fields, dict):
        for key, value in fields.items():
            if isinstance(value, dict):
                raw = value.get("value") or value.get("label") or value.get("title")
            else:
                raw = value
            clean = normalize_whitespace(raw)
            if clean:
                out[normalize_whitespace(key).lower()] = clean
    elif isinstance(fields, list):
        for item in fields:
            if not isinstance(item, dict):
                continue
            key = normalize_whitespace(item.get("name") or item.get("key") or item.get("title")).lower()
            value = normalize_whitespace(item.get("value") or item.get("label"))
            if key and value:
                out[key] = value
    return out


def ordered_size(review: Dict[str, object]) -> str:
    fields = custom_field_map(review)
    for key, value in fields.items():
        if re.search(r"\b(size|ordered|fit)\b", key, re.I):
            return value
    return ""


def review_images(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    images = review.get("images_data")
    if isinstance(images, list):
        for image in images:
            if not isinstance(image, dict):
                continue
            image_url = normalize_whitespace(image.get("original_url") or image.get("url") or image.get("thumb_url"))
            if image_url:
                urls.append(clean_url(image_url))
    return list(dict.fromkeys(urls))


def review_to_images(review: Dict[str, object], context: ProductContext) -> List[ReviewImage]:
    review_id = normalize_whitespace(review.get("id"))
    title = normalize_whitespace(review.get("title"))
    body = normalize_whitespace(review.get("content"))
    date_raw = normalize_whitespace(review.get("created_at"))
    user = review.get("user")
    reviewer = ""
    if isinstance(user, dict):
        reviewer = normalize_whitespace(user.get("display_name"))
    size = ordered_size(review)
    out: List[ReviewImage] = []
    for image_url in review_images(review):
        out.append(
            ReviewImage(
                image_url=image_url,
                review_id=review_id,
                review_title=title,
                review_body=body,
                reviewer_name=reviewer,
                date_raw=date_raw,
                size_raw=size,
                rating=normalize_whitespace(review.get("score")),
                extra={
                    "image_source_type": "customer_review_image",
                    "image_source_detail": "yotpo_images_data",
                    "product_url": context.url,
                    "product_title": context.title,
                    "product_description": context.description,
                    "product_detail": context.detail,
                    "product_category": context.category,
                },
            )
        )
    return out


def fetch_product_reviews(
    context: ProductContext,
    *,
    delay: float,
    limit_review_pages: Optional[int] = None,
) -> Tuple[List[ReviewImage], Dict[str, object]]:
    meta: Dict[str, object] = {
        "adapter_used": "yotpo_product_widget",
        "shopify_product_id": context.product_id,
        "product_url": context.url,
        "product_title": context.title,
        "product_type": context.category,
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "reviews_seen": 0,
        "matching_review_image_rows": 0,
        "matching_review_image_reviews": 0,
        "errors": [],
    }
    if not context.product_id:
        meta["errors"] = ["missing_shopify_product_id_for_yotpo"]
        return [], meta

    images: List[ReviewImage] = []
    image_review_ids = set()
    for page in range(1, 10000):
        if limit_review_pages is not None and page > limit_review_pages:
            meta["limited_review_pages"] = limit_review_pages
            break
        payload = fetch_json(
            yotpo_reviews_url(context.product_id),
            {"per_page": REVIEWS_PER_PAGE, "page": page},
            referer=context.url or SOURCE_SITE,
            delay=delay,
        )
        reviews = response_reviews(payload)
        total = response_total(payload)
        meta["review_count_hint"] = max(int(meta["review_count_hint"] or 0), total)
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"] or 0) + 1
        meta["reviews_seen"] = int(meta["reviews_seen"] or 0) + len(reviews)
        for review in reviews:
            review_images_out = review_to_images(review, context)
            if review_images_out:
                image_review_ids.add(normalize_whitespace(review.get("id")))
                images.extend(review_images_out)
        if not reviews or len(reviews) < REVIEWS_PER_PAGE:
            break
    meta["matching_review_image_rows"] = len(images)
    meta["matching_review_image_reviews"] = len([item for item in image_review_ids if item])
    return images, meta


def append_jsonl(path: Path, item: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    items: List[Dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                items.append(payload)
    return items


def reset_checkpoints() -> None:
    for path in [ROWS_CHECKPOINT_JSONL, PRODUCTS_CHECKPOINT_JSONL]:
        if path.exists():
            path.unlink()


def rows_with_distinct_product_url(rows: Sequence[Dict[str, str]]) -> int:
    return len(
        {
            row.get("product_page_url_display") or row.get("monetized_product_url_display")
            for row in rows
            if row.get("product_page_url_display") or row.get("monetized_product_url_display")
        }
    )


def strict_metrics(rows: Sequence[Dict[str, str]]) -> Dict[str, int]:
    return {
        "rows_with_distinct_product_url": rows_with_distinct_product_url(rows),
        "rows_with_any_measurement": sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS)),
        "rows_with_customer_image": sum(
            1
            for row in rows
            if row.get("original_url_display") and (row.get("image_source_type") or "customer_review_image") == "customer_review_image"
        ),
        "rows_with_customer_ordered_size": sum(
            1 for row in rows if row.get("size_display") and row.get("size_display", "").lower() != "unknown"
        ),
        "rows_supabase_qualified": sum(
            1
            for row in rows
            if row.get("original_url_display")
            and (row.get("product_page_url_display") or row.get("monetized_product_url_display"))
            and row.get("size_display")
            and row.get("size_display", "").lower() != "unknown"
            and any(row.get(field) for field in MEASUREMENT_FIELDS)
        ),
    }


def product_summary_scope_reason(summary: Dict[str, object]) -> str:
    category = normalize_whitespace(summary.get("product_type")).lower()
    title = normalize_whitespace(summary.get("product_title")).lower()
    url = normalize_whitespace(summary.get("product_url")).lower()
    if category.startswith(("men-", "kids-", "boys-", "girls-", "accessories-")):
        return "out_of_scope_product_type"
    if re.search(r"/products/(?:mens?|boys?|girls?)-", url) and "women" not in title:
        return "out_of_scope_non_womens_product"
    return ""


def row_scope_reason(row: Dict[str, str]) -> str:
    category = normalize_whitespace(row.get("product_category_raw")).lower()
    title = normalize_whitespace(row.get("product_title_raw")).lower()
    url = normalize_whitespace(row.get("product_page_url_display")).lower()
    if category.startswith(("men-", "kids-", "boys-", "girls-", "accessories-")):
        return "out_of_scope_product_type"
    if re.search(r"/products/(?:mens?|boys?|girls?)-", url) and "women" not in title:
        return "out_of_scope_non_womens_product"
    return ""


def scrape(
    limit_products: Optional[int],
    limit_review_pages: Optional[int],
    delay: float,
    *,
    resume: bool,
) -> Dict[str, object]:
    started_at = utc_now()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not resume:
        reset_checkpoints()
    products, product_sources = fetch_products(delay, limit_products=limit_products)
    fetched_at = utc_now()
    checkpoint_rows = read_jsonl(ROWS_CHECKPOINT_JSONL) if resume else []
    checkpoint_summaries = read_jsonl(PRODUCTS_CHECKPOINT_JSONL) if resume else []
    rows: List[Dict[str, str]] = [{str(k): "" if v is None else str(v) for k, v in row.items()} for row in checkpoint_rows]
    product_summaries: List[Dict[str, object]] = list(checkpoint_summaries)
    completed_indexes = {
        int(summary.get("index"))
        for summary in checkpoint_summaries
        if str(summary.get("index") or "").isdigit()
    }
    errors: List[str] = []
    for item in product_summaries:
        scope_reason = product_summary_scope_reason(item)
        if scope_reason:
            item["skipped_from_output"] = True
            item["skip_reason"] = scope_reason
    products_excluded = sum(1 for item in product_summaries if item.get("skipped_from_output"))
    review_products_scanned = sum(1 for item in product_summaries if not item.get("skipped_from_output"))
    total_review_pages_scanned = sum(int(item.get("review_pages_scanned") or 0) for item in product_summaries)
    product_review_count_hint = sum(int(item.get("review_count_hint") or 0) for item in product_summaries)

    for index, product in enumerate(products, 1):
        if index in completed_indexes:
            continue
        context = context_from_product(product)
        reason = skip_reason(product)
        if reason:
            products_excluded += 1
            summary_item = {
                "index": index,
                "product_url": context.url,
                "product_title": context.title,
                "product_type": context.category,
                "shopify_product_id": context.product_id,
                "skipped_from_output": True,
                "skip_reason": reason,
                "review_pages_scanned": 0,
                "review_count_hint": 0,
                "matching_review_image_rows": 0,
            }
            product_summaries.append(summary_item)
            append_jsonl(PRODUCTS_CHECKPOINT_JSONL, summary_item)
            continue

        try:
            reviews, meta = fetch_product_reviews(context, delay=delay, limit_review_pages=limit_review_pages)
        except StopScrape:
            raise
        except Exception as exc:
            meta = {
                "adapter_used": "yotpo_product_widget",
                "shopify_product_id": context.product_id,
                "product_url": context.url,
                "product_title": context.title,
                "product_type": context.category,
                "review_pages_scanned": 0,
                "review_count_hint": 0,
                "matching_review_image_rows": 0,
                "errors": [str(exc)],
            }
            reviews = []
            errors.append(f"{context.url}: {exc}")
        review_products_scanned += 1
        total_review_pages_scanned += int(meta.get("review_pages_scanned") or 0)
        product_review_count_hint += int(meta.get("review_count_hint") or 0)
        product_rows = [build_intake_row(context, review, fetched_at) for review in reviews if review.image_url]
        rows.extend(product_rows)
        for row in product_rows:
            append_jsonl(ROWS_CHECKPOINT_JSONL, row)
        summary_item = {
            "index": index,
            **meta,
            "skipped_from_output": False,
            "skip_reason": "",
        }
        product_summaries.append(summary_item)
        append_jsonl(PRODUCTS_CHECKPOINT_JSONL, summary_item)
        if index % 50 == 0 or reviews:
            print(
                f"[product {index}/{len(products)}] {context.title[:70]} reviews={meta.get('reviews_seen')} "
                f"image_rows={len(reviews)}",
                flush=True,
            )

    rows_before_scope_filter = len(rows)
    rows = [row for row in rows if not row_scope_reason(row)]
    rows_filtered_out_of_scope = rows_before_scope_filter - len(rows)
    rows = dedupe_rows(rows)
    products_excluded = sum(1 for item in product_summaries if item.get("skipped_from_output"))
    review_products_scanned = sum(1 for item in product_summaries if not item.get("skipped_from_output"))
    write_intake_csv(rows, OUTPUT_CSV)
    finished_at = utc_now()
    validation = validate_rows(rows)
    standard = strict_metrics(rows)
    summary: Dict[str, object] = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_sitemap_yotpo_product_reviews",
        "yotpo_app_key": YOTPO_APP_KEY,
        "provider_hints": ["Yotpo", "PowerReviews"],
        "access_policy": (
            "public Shopify products.json/product sitemap and public Yotpo widget JSON only; "
            "no product-page HTML crawling because robots.txt disallows /products/; stop on 429/captcha/WAF"
        ),
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "review_products_scanned": review_products_scanned,
        "products_excluded_from_output": products_excluded,
        "rows_filtered_out_of_scope": rows_filtered_out_of_scope,
        "review_pages_scanned": total_review_pages_scanned,
        "exhaustive_review_paging": limit_review_pages is None,
        "product_review_count_hint": product_review_count_hint,
        "rows_written": len(rows),
        "output_csv": str(OUTPUT_CSV),
        "summary_json": str(SUMMARY_JSON),
        "started_at": started_at,
        "finished_at": finished_at,
        "product_summaries": product_summaries,
        "errors": errors,
    }
    summary.update(validation)
    summary.update(standard)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Dickies public Yotpo customer review images.")
    parser.add_argument("--limit-products", type=int, default=None)
    parser.add_argument("--limit-review-pages", type=int, default=None)
    parser.add_argument("--request-delay-seconds", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS)
    parser.add_argument("--resume", action="store_true", help="Resume from JSONL checkpoints in the Dickies output folder.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = scrape(
            args.limit_products,
            args.limit_review_pages,
            args.request_delay_seconds,
            resume=args.resume,
        )
    except StopScrape as exc:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stopped_at = utc_now()
        summary = {
            "site": SITE_ROOT,
            "retailer": RETAILER,
            "adapter": "shopify_products_json_sitemap_yotpo_product_reviews",
            "stopped": True,
            "stop_reason": str(exc),
            "finished_at": stopped_at,
            "output_csv": str(OUTPUT_CSV),
            "summary_json": str(SUMMARY_JSON),
        }
        SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)
        return 2
    print(json.dumps({k: summary.get(k) for k in [
        "products_discovered",
        "products_scanned",
        "review_products_scanned",
        "products_excluded_from_output",
        "review_pages_scanned",
        "rows_written",
        "distinct_reviews",
        "distinct_images",
        "rows_with_customer_image",
        "rows_with_distinct_product_url",
        "rows_with_customer_ordered_size",
        "rows_with_any_measurement",
        "rows_supabase_qualified",
        "output_csv",
        "summary_json",
    ]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
