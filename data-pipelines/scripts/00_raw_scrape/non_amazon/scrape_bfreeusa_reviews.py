#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    classify_clothing_type,
    dedupe_rows,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    write_intake_csv,
    write_summary,
)


SITE_ROOT = "https://www.bfreeusa.com"
SHOP_DOMAIN = "b-free-australia.myshopify.com"
BRAND = "B Free"
PRODUCTS_PER_PAGE = 250
STAMPED_API_KEY = "pubkey-503131bs4fsU32W9jva35iQ3LeZitu"
STAMPED_STORE_ID = "6990"
STAMPED_REVIEWS_URL = "https://stamped.io/api/widget/reviews"
STAMPED_PHOTO_BASE = "https://cdn.stamped.io/uploads/photos/"
USER_AGENT = "Mozilla/5.0"


def get_json(url: str, *, referer: str = SITE_ROOT, retries: int = 3) -> Dict[str, object]:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        request = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": referer,
            },
        )
        try:
            with urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except Exception as exc:
            last_error = exc
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"GET failed for {url}: {last_error}")


def product_url(handle: str) -> str:
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}"


def discover_products() -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    product_sources: List[Dict[str, object]] = []
    page = 1
    seen_handles = set()
    while True:
        api_url = f"{SITE_ROOT}/products.json?limit={PRODUCTS_PER_PAGE}&page={page}"
        payload = get_json(api_url, referer=SITE_ROOT, retries=3)
        batch = [item for item in payload.get("products", []) if isinstance(item, dict)]
        product_sources.append({"source": "products.json", "page": page, "count": len(batch)})
        if not batch:
            break
        for product in batch:
            handle = normalize_whitespace(product.get("handle"))
            if not handle or handle in seen_handles:
                continue
            seen_handles.add(handle)
            products.append(product)
        if len(batch) < PRODUCTS_PER_PAGE:
            break
        page += 1
        time.sleep(0.2)
    return products, product_sources


def context_from_product(product: Dict[str, object]) -> ProductContext:
    title = normalize_whitespace(product.get("title"))
    handle = normalize_whitespace(product.get("handle"))
    body_html = strip_tags(product.get("body_html"))
    tags = product.get("tags") if isinstance(product.get("tags"), list) else []
    category = normalize_whitespace(product.get("product_type") or " ".join(str(tag) for tag in tags))
    return ProductContext(
        url=product_url(handle),
        title=title,
        description=body_html,
        category=category,
        brand=BRAND,
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=SHOP_DOMAIN,
        provider_hints="Stamped",
    )


def is_bfree_womens_scope(context: ProductContext) -> bool:
    title_category = f"{context.title} {context.category}".lower()
    all_text = f"{title_category} {context.description}".lower()
    if any(term in title_category for term in ["baby", "babysuit", "organic cotton bodysuit", "kids", "toddler"]):
        return False
    if any(term in title_category for term in ["magic strap", "bra straps", "nipple cover", "breast lift pack", "liner with wings"]):
        return False
    return bool(classify_clothing_type(context))


def stamped_photo_urls(raw: object) -> List[str]:
    urls: List[str] = []
    for part in normalize_whitespace(raw).split(","):
        clean = normalize_whitespace(part)
        if not clean:
            continue
        urls.append(clean if clean.startswith("http") else f"{STAMPED_PHOTO_BASE}{clean}")
    return urls


def size_from_variant(value: object) -> str:
    variant = normalize_whitespace(value)
    if not variant or variant.lower() == "undefined":
        return ""
    if "/" in variant:
        return normalize_whitespace(variant.rsplit("/", 1)[-1])
    return variant


def scrape_stamped_reviews(context: ProductContext) -> Tuple[List[ReviewImage], Optional[str]]:
    reviews: List[ReviewImage] = []
    seen = set()
    for page in range(1, 10000):
        params = {
            "apiKey": STAMPED_API_KEY,
            "sId": STAMPED_STORE_ID,
            "storeUrl": SHOP_DOMAIN,
            "productId": context.product_id,
            "page": page,
            "skip": 100,
            "minRating": 1,
            "isWithPhotos": "true",
            "type": "widget-carousel-photos",
        }
        url = f"{STAMPED_REVIEWS_URL}?{urlencode(params)}"
        try:
            payload = get_json(url, referer=context.url, retries=1)
        except Exception as exc:
            return reviews, f"{context.url}: stamped failed: {exc}"
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            break
        page_rows = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            review_id = normalize_whitespace(item.get("id"))
            image_urls = stamped_photo_urls(item.get("reviewUserPhotos"))
            if not image_urls:
                continue
            page_rows += len(image_urls)
            for image_url in image_urls:
                key = (review_id, image_url)
                if key in seen:
                    continue
                seen.add(key)
                reviews.append(
                    ReviewImage(
                        image_url=image_url,
                        review_id=review_id,
                        review_title=normalize_whitespace(item.get("reviewTitle")),
                        review_body=normalize_whitespace(item.get("reviewMessage")),
                        reviewer_name=normalize_whitespace(item.get("author")),
                        date_raw=normalize_whitespace(item.get("dateCreated") or item.get("reviewDate")),
                        size_raw=size_from_variant(item.get("productVariantName")),
                        rating=normalize_whitespace(item.get("reviewRating")),
                        extra={
                            "product_url": context.url,
                            "product_title": context.title,
                            "product_description": context.description,
                            "product_category": context.category,
                        },
                    )
                )
        if page_rows == 0:
            break
        time.sleep(0.1)
    return reviews, None


def scrape() -> Dict[str, object]:
    started_at = utc_now()
    products, product_sources = discover_products()
    fetched_at = utc_now()
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []

    for index, product in enumerate(products, start=1):
        context = context_from_product(product)
        if not is_bfree_womens_scope(context):
            product_summaries.append(
                {
                    "product_url": context.url,
                    "product_title": context.title,
                    "provider_hints": context.provider_hints,
                    "adapter_used": "skipped-out-of-scope",
                    "matching_review_images": 0,
                    "product_index": index,
                    "skipped_from_output": True,
                    "skip_reason": "no women's clothing type matched title/category",
                }
            )
            print(f"[bfreeusa.com {index}/{len(products)}] {context.title or context.url} -> skipped out of scope", flush=True)
            continue
        reviews, error = scrape_stamped_reviews(context)
        if error:
            errors.append(error)
        product_rows = [build_intake_row(context, review, fetched_at) for review in reviews]
        rows.extend(product_rows)
        product_summaries.append(
            {
                "product_url": context.url,
                "product_title": context.title,
                "provider_hints": context.provider_hints,
                "adapter_used": "stamped",
                "matching_review_images": len(product_rows),
                "product_index": index,
            }
        )
        print(f"[bfreeusa.com {index}/{len(products)}] {context.title or context.url} -> {len(product_rows)} rows", flush=True)

    rows = dedupe_rows(rows)
    output_csv, summary_json = output_paths("bfreeusa.com")
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    write_summary(
        summary_json,
        site=SITE_ROOT,
        retailer="bfreeusa.com",
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=finished_at,
        products_scanned=len(products),
        adapter="stamped",
        product_summaries=product_summaries,
        errors=errors,
    )
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    summary["product_sources"] = product_sources
    summary["products_discovered"] = len(products)
    summary["products_excluded_from_output"] = sum(1 for item in product_summaries if item.get("skipped_from_output"))
    summary["review_pages_scanned"] = len([item for item in product_summaries if item.get("adapter_used") == "stamped"])
    summary["exhaustive_review_paging"] = True
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    summary = scrape()
    print(json.dumps({summary["retailer"]: summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
