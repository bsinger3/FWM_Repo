#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
    ProductContext,
    ReviewImage,
    build_intake_row,
    canonical_product_url,
    classify_clothing_type,
    dedupe_rows,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    write_intake_csv,
)


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 FWM"
)
STOP_STATUS_CODES = {401, 403, 407, 408, 409, 423, 429, 430, 503}
BLOCK_MARKERS = [
    "just a moment...",
    "please complete the security check",
    "verify you are human",
    "access denied",
    "attention required",
    "cf-chl",
    "datadome",
    "perimeterx",
    "px-captcha",
    "awswaf",
    "challenges.cloudflare.com",
]

BRAVISSIMO_SITE = "https://www.bravissimo.com"
BRAVISSIMO_US = f"{BRAVISSIMO_SITE}/us/"
BRAVISSIMO_YOTPO_APP_KEY = "vPueBNpZC7bseknVIP4P3WaKu6PUzDOvzra1IpWD"
NATORI_YOTPO_APP_KEY = "rbk60r5PMQ50GUNKKSYNCuYi21NeimddtLmEYN2V"


@dataclass(frozen=True)
class ShopifyTarget:
    slug: str
    brand: str
    site: str
    adapter: str


SHOPIFY_TARGETS = {
    "brastop_com": ShopifyTarget("brastop_com", "Brastop", "https://www.brastop.com", "shopify_product_json_plus_jsonld_review_probe"),
    "wacoal_america_com": ShopifyTarget(
        "wacoal_america_com",
        "Wacoal",
        "https://wacoal-america.com",
        "shopify_product_json_plus_bazaarvoice_probe",
    ),
    "natori_com": ShopifyTarget("natori_com", "Natori", "https://www.natori.com", "shopify_product_json_plus_yotpo_reviews"),
}

ALL_SLUGS = ["bravissimo_com", "panache_lingerie_com", "brastop_com", "wacoal_america_com", "natori_com"]


class StopScrape(RuntimeError):
    pass


def request_text(url: str, *, referer: str = "", accept: str = "text/html,application/json,*/*", timeout: int = 35) -> str:
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
        with urlopen(req, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            text = response.read().decode("utf-8-sig", "replace")
    except HTTPError as exc:
        if exc.code in STOP_STATUS_CODES:
            raise StopScrape(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
        raise
    except (TimeoutError, URLError) as exc:
        raise StopScrape(f"request_failed: {url}: {exc}") from exc
    if status in STOP_STATUS_CODES:
        raise StopScrape(f"blocked_or_rate_limited_http_{status}: {url}")
    lower = text[:250_000].lower()
    hits = [marker for marker in BLOCK_MARKERS if marker in lower]
    if hits:
        raise StopScrape(f"blocked_or_challenged_response_{','.join(hits)}: {url}")
    return text


def request_json(url: str, *, referer: str = "") -> Dict[str, object]:
    text = request_text(url, referer=referer, accept="application/json,text/plain,*/*")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StopScrape(f"non_json_response: {url}") from exc
    if not isinstance(payload, dict):
        raise StopScrape(f"unexpected_json_response: {url}")
    return payload


def unique(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        clean = normalize_whitespace(value)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def clean_meta(html_text: str, prop: str) -> str:
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)',
        rf'<meta[^>]+name=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, re.I)
        if match:
            return html.unescape(normalize_whitespace(match.group(1)))
    return ""


def h1_text(html_text: str) -> str:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.I | re.S)
    return strip_tags(match.group(1)) if match else ""


def yotpo_review_url(app_key: str, product_id: str, page: int, per_page: int) -> str:
    return (
        f"https://api-cdn.yotpo.com/v1/widget/{app_key}/products/{product_id}/reviews.json?"
        f"{urlencode({'page': page, 'per_page': per_page})}"
    )


def image_urls_from_yotpo(review: Dict[str, object]) -> List[str]:
    images_data = review.get("images_data")
    if not isinstance(images_data, list):
        return []
    urls: List[str] = []
    for item in images_data:
        if not isinstance(item, dict):
            continue
        for key in ("original_url", "url", "thumb_url", "image_url"):
            value = normalize_whitespace(item.get(key))
            if value.startswith("//"):
                value = f"https:{value}"
            if value.startswith("http"):
                urls.append(value)
                break
    return unique(urls)


def custom_field_value(review: Dict[str, object], wanted_title: str) -> str:
    fields = review.get("custom_fields")
    if not isinstance(fields, dict):
        return ""
    wanted_title = wanted_title.lower()
    for item in fields.values():
        if not isinstance(item, dict):
            continue
        title = normalize_whitespace(item.get("title")).lower()
        if title == wanted_title:
            return normalize_whitespace(item.get("value"))
    return ""


def rows_from_yotpo_reviews(
    *,
    reviews: Sequence[Dict[str, object]],
    context: ProductContext,
    fetched_at: str,
    image_source_detail: str,
    catalog_images: Optional[Sequence[str]] = None,
    catalog_only: bool = False,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        review_id = normalize_whitespace(review.get("id")) or hashlib.md5(
            f"{context.url}|{review.get('title')}|{review.get('content')}".encode("utf-8")
        ).hexdigest()[:16]
        user = review.get("user") if isinstance(review.get("user"), dict) else {}
        review_images = image_urls_from_yotpo(review)
        source_type = "customer_review_image"
        source_detail = image_source_detail
        if not review_images and catalog_only and catalog_images:
            review_images = list(catalog_images)
            source_type = "catalog_product_image"
            source_detail = "public Yotpo review text joined to public Shopify product gallery image; no customer review images exposed"
        for index, image_url in enumerate(review_images, start=1):
            rows.append(
                build_intake_row(
                    context,
                    ReviewImage(
                        image_url=image_url,
                        review_id=f"yotpo-{review_id}-{index}",
                        review_title=normalize_whitespace(review.get("title")),
                        review_body=normalize_whitespace(review.get("content")),
                        reviewer_name=normalize_whitespace(user.get("display_name") if isinstance(user, dict) else ""),
                        date_raw=normalize_whitespace(review.get("created_at")),
                        rating=normalize_whitespace(review.get("score")),
                        size_raw=custom_field_value(review, "Your typical bra size"),
                        extra={
                            "image_source_type": source_type,
                            "image_source_detail": source_detail,
                            "product_url": context.url,
                            "product_title": context.title,
                        },
                    ),
                    fetched_at,
                )
            )
    return rows


def fetch_yotpo_reviews(
    app_key: str,
    product_id: str,
    *,
    site: str,
    max_pages: int,
    per_page: int,
    delay: float,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    reviews: List[Dict[str, object]] = []
    pages: List[Dict[str, object]] = []
    total = 0
    for page in range(1, max_pages + 1):
        payload = request_json(yotpo_review_url(app_key, product_id, page, per_page), referer=site)
        response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
        pagination = response.get("pagination") if isinstance(response.get("pagination"), dict) else {}
        page_reviews = response.get("reviews") if isinstance(response.get("reviews"), list) else []
        total = int(pagination.get("total") or total or 0)
        pages.append({"page": page, "reviews": len(page_reviews), "total_hint": total})
        reviews.extend(review for review in page_reviews if isinstance(review, dict))
        if len(reviews) >= total or not page_reviews:
            break
        if delay:
            time.sleep(delay)
    return reviews, {"product_id": product_id, "total_reviews_hint": total, "pages": pages}


def product_images(product: Dict[str, object]) -> List[str]:
    images = product.get("images") if isinstance(product.get("images"), list) else []
    urls = []
    for image in images:
        src = ""
        if isinstance(image, dict):
            src = normalize_whitespace(image.get("src"))
        elif isinstance(image, str):
            src = normalize_whitespace(image)
        if src.startswith("//"):
            src = f"https:{src}"
        if src.startswith("http"):
            urls.append(src)
    return unique(urls)


def shopify_context(site: str, brand: str, product: Dict[str, object]) -> ProductContext:
    handle = normalize_whitespace(product.get("handle"))
    first_variant = (product.get("variants") or [{}])[0] if isinstance(product.get("variants"), list) else {}
    return ProductContext(
        url=f"{site}/products/{handle}",
        title=normalize_whitespace(product.get("title")),
        description=strip_tags(product.get("body_html")),
        category=normalize_whitespace(product.get("product_type")),
        brand=normalize_whitespace(product.get("vendor")) or brand,
        variant=normalize_whitespace(first_variant.get("title") if isinstance(first_variant, dict) else ""),
        product_id=normalize_whitespace(product.get("id")),
        handle=handle,
        shop_domain=urlparse(site).netloc,
        provider_hints="public Shopify products.json and product page probe",
    )


def fetch_shopify_products(site: str, *, limit: int, max_pages: int, delay: float) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    page_summaries: List[Dict[str, object]] = []
    seen = set()
    for page in range(1, max_pages + 1):
        url = f"{site}/products.json?{urlencode({'limit': limit, 'page': page})}"
        payload = request_json(url, referer=site)
        page_products = payload.get("products") if isinstance(payload.get("products"), list) else []
        page_summaries.append({"page": page, "url": url, "products": len(page_products)})
        if not page_products:
            break
        for product in page_products:
            if not isinstance(product, dict):
                continue
            handle = normalize_whitespace(product.get("handle"))
            if handle and handle not in seen:
                seen.add(handle)
                products.append(product)
        if delay:
            time.sleep(delay)
    return products, page_summaries


def aggregate_rating_from_jsonld(html_text: str) -> Dict[str, object]:
    for match in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html_text, re.I | re.S):
        raw = html.unescape(match.group(1)).strip()
        if "aggregateRating" not in raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates = payload.get("@graph") if isinstance(payload, dict) and isinstance(payload.get("@graph"), list) else [payload]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            rating = item.get("aggregateRating")
            if isinstance(rating, dict):
                return {
                    "rating_value": normalize_whitespace(rating.get("ratingValue")),
                    "review_count": normalize_whitespace(rating.get("reviewCount")),
                }
    return {}


def summarize_rows(rows: Sequence[Dict[str, str]]) -> Dict[str, object]:
    return {
        "rows_written": len(rows),
        "distinct_reviews": len({row.get("id", "") for row in rows if row.get("id")}),
        "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
        "distinct_product_urls": len({row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}),
        "rows_with_any_measurement": sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS)),
        "rows_with_customer_review_image": sum(1 for row in rows if row.get("image_source_type") == "customer_review_image"),
        "rows_with_catalog_product_image": sum(1 for row in rows if row.get("image_source_type") == "catalog_product_image"),
    }


def write_outputs(slug: str, rows: Sequence[Dict[str, str]], summary: Dict[str, object]) -> None:
    output_csv, summary_json = output_paths(slug)
    write_intake_csv(rows, output_csv)
    payload = dict(summary)
    payload.update({"output_csv": str(output_csv), "summary_json": str(summary_json)})
    payload.update(summarize_rows(rows))
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def scrape_bravissimo(args: argparse.Namespace) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    try:
        home = request_text(BRAVISSIMO_US, referer=BRAVISSIMO_US)
        links = [
            urljoin(BRAVISSIMO_SITE, html.unescape(match))
            for match in re.findall(r'href=["\']([^"\']*/us/products/[^"\']+)["\']', home)
        ]
        product_urls = unique(canonical_product_url(link.split("#", 1)[0]) for link in links)
    except StopScrape as exc:
        product_urls = []
        errors.append(str(exc))

    scanned = 0
    for product_url in product_urls[: args.limit_products]:
        try:
            product_html = request_text(product_url, referer=BRAVISSIMO_US)
        except StopScrape as exc:
            errors.append(str(exc))
            break
        scanned += 1
        match = re.search(r'data-yotpo-product-id=["\']([^"\']+)["\']', product_html)
        yotpo_product_id = normalize_whitespace(match.group(1) if match else "")
        context = ProductContext(
            url=product_url,
            title=h1_text(product_html) or clean_meta(product_html, "og:title"),
            description=clean_meta(product_html, "description") or clean_meta(product_html, "og:description"),
            brand="Bravissimo",
            product_id=yotpo_product_id,
            shop_domain="www.bravissimo.com",
            provider_hints="public product HTML data-yotpo-product-id and Yotpo widget JSON",
        )
        reviews: List[Dict[str, object]] = []
        review_meta: Dict[str, object] = {}
        product_rows: List[Dict[str, str]] = []
        if yotpo_product_id:
            reviews, review_meta = fetch_yotpo_reviews(
                BRAVISSIMO_YOTPO_APP_KEY,
                yotpo_product_id,
                site=BRAVISSIMO_US,
                max_pages=args.max_review_pages,
                per_page=args.review_page_size,
                delay=args.request_delay_seconds,
            )
            product_rows = rows_from_yotpo_reviews(
                reviews=reviews,
                context=context,
                fetched_at=started_at,
                image_source_detail="public Bravissimo Yotpo review media",
            )
        rows.extend(product_rows)
        product_summaries.append(
            {
                "product_url": product_url,
                "product_title": context.title,
                "yotpo_product_id": yotpo_product_id,
                "reviews_seen": len(reviews),
                "customer_review_image_rows": len(product_rows),
                "review_meta": review_meta,
                "clothing_type_id": classify_clothing_type(context),
            }
        )
        if args.request_delay_seconds:
            time.sleep(args.request_delay_seconds)
    rows = dedupe_rows(rows)
    return rows, {
        "site": BRAVISSIMO_US,
        "retailer": "bravissimo_com",
        "adapter": "bravissimo_product_html_yotpo_customer_images",
        "started_at": started_at,
        "finished_at": utc_now(),
        "access_policy": "public product HTML plus public Yotpo widget JSON only; stop on 429/captcha/WAF/auth",
        "products_discovered": len(product_urls),
        "products_scanned": scanned,
        "customer_review_feed_used": True,
        "customer_review_images_exposed": bool(rows),
        "catalog_image_strategy": "none; customer review images only",
        "product_summaries": product_summaries,
        "errors": errors,
    }


def probe_panache() -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    errors: List[str] = []
    probes: List[Dict[str, object]] = []
    for url in ["https://www.panache-lingerie.com/us/", "https://www.panache-lingerie.com/us/products.json?limit=5"]:
        try:
            request_text(url, referer="https://www.panache-lingerie.com/us/")
            probes.append({"url": url, "status": "accessible"})
        except StopScrape as exc:
            probes.append({"url": url, "status": "blocked", "detail": str(exc)})
            errors.append(str(exc))
            break
    return [], {
        "site": "https://www.panache-lingerie.com/us/",
        "retailer": "panache_lingerie_com",
        "adapter": "public_endpoint_probe_only",
        "started_at": started_at,
        "finished_at": utc_now(),
        "access_policy": "public product/review endpoints only; stopped on auth/block response",
        "products_discovered": 0,
        "products_scanned": 0,
        "customer_review_feed_used": False,
        "customer_review_images_exposed": False,
        "scrape_scope_status": "blocked_before_public_product_or_review_feed",
        "probes": probes,
        "product_summaries": [],
        "errors": errors,
    }


def scrape_shopify_target(target: ShopifyTarget, args: argparse.Namespace) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    products: List[Dict[str, object]] = []
    catalog_pages: List[Dict[str, object]] = []
    rows: List[Dict[str, str]] = []
    errors: List[str] = []
    product_summaries: List[Dict[str, object]] = []
    try:
        products, catalog_pages = fetch_shopify_products(
            target.site,
            limit=args.catalog_limit,
            max_pages=args.max_catalog_pages,
            delay=args.request_delay_seconds,
        )
    except StopScrape as exc:
        errors.append(str(exc))
    scanned = 0
    for product in products[: args.limit_products]:
        context = shopify_context(target.site, target.brand, product)
        summary: Dict[str, object] = {
            "product_url": context.url,
            "product_title": context.title,
            "shopify_product_id": context.product_id,
            "product_type": context.category,
            "catalog_images": len(product_images(product)),
            "clothing_type_id": classify_clothing_type(context),
        }
        try:
            product_html = request_text(context.url, referer=target.site)
        except StopScrape as exc:
            errors.append(str(exc))
            break
        scanned += 1
        if target.slug == "natori_com":
            reviews, review_meta = fetch_yotpo_reviews(
                NATORI_YOTPO_APP_KEY,
                context.product_id,
                site=target.site,
                max_pages=args.max_review_pages,
                per_page=args.review_page_size,
                delay=args.request_delay_seconds,
            )
            product_rows = rows_from_yotpo_reviews(
                reviews=reviews,
                context=context,
                fetched_at=started_at,
                image_source_detail="public Natori Yotpo review media",
                catalog_images=product_images(product)[: args.max_catalog_images_per_review],
                catalog_only=args.catalog_only_for_zero_image_reviews,
            )
            rows.extend(product_rows)
            summary.update(
                {
                    "reviews_seen": len(reviews),
                    "review_meta": review_meta,
                    "customer_review_images_seen": sum(len(image_urls_from_yotpo(review)) for review in reviews),
                    "rows": len(product_rows),
                }
            )
        elif target.slug == "brastop_com":
            summary.update(
                {
                    "aggregate_rating": aggregate_rating_from_jsonld(product_html),
                    "raw_review_endpoint_found": False,
                    "rows": 0,
                    "finding": "public page exposes aggregate review count/rating but no public raw review body or customer-image feed found",
                }
            )
        elif target.slug == "wacoal_america_com":
            summary.update(
                {
                    "aggregate_rating": aggregate_rating_from_jsonld(product_html),
                    "bazaarvoice_product_id_found": bool(re.search(r'data-bv-product-id=["\']', product_html)),
                    "raw_review_endpoint_found": False,
                    "rows": 0,
                    "finding": "public page loads Bazaarvoice widgets, but unauthenticated Conversations API passkey/static review JSON was not exposed",
                }
            )
        product_summaries.append(summary)
        if args.request_delay_seconds:
            time.sleep(args.request_delay_seconds)
    rows = dedupe_rows(rows)
    return rows, {
        "site": target.site,
        "retailer": target.slug,
        "adapter": target.adapter,
        "started_at": started_at,
        "finished_at": utc_now(),
        "access_policy": "public Shopify products.json, product pages, and public review widget endpoints only; stop on 429/captcha/WAF/auth",
        "product_sources": {"shopify_products_json_pages": catalog_pages, "unique_products": len(products)},
        "products_discovered": len(products),
        "products_scanned": scanned,
        "customer_review_feed_used": target.slug == "natori_com",
        "customer_review_images_exposed": any(row.get("image_source_type") == "customer_review_image" for row in rows),
        "catalog_image_strategy": (
            "catalog-only rows for public Yotpo review text when no review images are exposed"
            if target.slug == "natori_com" and args.catalog_only_for_zero_image_reviews
            else "none"
        ),
        "product_summaries": product_summaries,
        "errors": errors,
    }


def scrape_slug(slug: str, args: argparse.Namespace) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    if slug == "bravissimo_com":
        return scrape_bravissimo(args)
    if slug == "panache_lingerie_com":
        return probe_panache()
    return scrape_shopify_target(SHOPIFY_TARGETS[slug], args)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Worker A file-first probe/scrape for five Reddit recommended bra retailers.")
    parser.add_argument("--slug", action="append", choices=ALL_SLUGS, help="Retailer slug to run; may be repeated.")
    parser.add_argument("--limit-products", type=int, default=3)
    parser.add_argument("--catalog-limit", type=int, default=50)
    parser.add_argument("--max-catalog-pages", type=int, default=1)
    parser.add_argument("--max-review-pages", type=int, default=3)
    parser.add_argument("--review-page-size", type=int, default=25)
    parser.add_argument("--max-catalog-images-per-review", type=int, default=1)
    parser.add_argument("--catalog-only-for-zero-image-reviews", action="store_true")
    parser.add_argument("--request-delay-seconds", type=float, default=0.2)
    args = parser.parse_args(argv)

    slugs = args.slug or ALL_SLUGS
    for slug in slugs:
        print(f"[{slug}] starting", flush=True)
        rows, summary = scrape_slug(slug, args)
        write_outputs(slug, rows, summary)
        output_csv, summary_json = output_paths(slug)
        print(
            f"[{slug}] rows={len(rows)} products_scanned={summary.get('products_scanned')} "
            f"csv={output_csv} summary={summary_json}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
