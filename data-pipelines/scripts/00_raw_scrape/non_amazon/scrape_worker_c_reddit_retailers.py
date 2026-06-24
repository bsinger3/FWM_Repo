#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from typing import Dict, Iterable, List, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
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
    validate_rows,
    write_intake_csv,
)


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
PRESSURE_STATUS_CODES = {401, 403, 407, 423, 429, 430, 503}
BLOCK_RE = re.compile(
    r"\b(?:access denied|captcha|cloudflare|datadome|perimeterx|akamai|"
    r"verify you are human|attention required|temporarily blocked)\b",
    re.I,
)
APPAREL_RE = re.compile(
    r"\b("
    r"bra|bralette|dress|top|tee|shirt|tank|jean|pant|trouser|legging|shorts?|"
    r"skirt|bodysuit|underwear|brief|swim|jacket|coat|sweater|hoodie|cardigan"
    r")\b",
    re.I,
)
NON_APPAREL_RE = re.compile(r"\b(gift\s*card|wash|detergent|shipping|membership)\b", re.I)


class StopScrape(RuntimeError):
    pass


def fetch_text(url: str, *, accept: str = "text/html,application/json,*/*", referer: str = "", timeout: int = 45) -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            body = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code in PRESSURE_STATUS_CODES:
            raise StopScrape(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
        raise
    except URLError as exc:
        raise StopScrape(f"network_error: {url}: {exc}") from exc
    if status in PRESSURE_STATUS_CODES:
        raise StopScrape(f"blocked_or_rate_limited_http_{status}: {url}")
    if BLOCK_RE.search(body[:50_000]):
        raise StopScrape(f"blocked_or_challenged_response: {url}")
    return body


def fetch_json(url: str, *, referer: str = "") -> Dict[str, object]:
    return json.loads(fetch_text(url, accept="application/json,text/plain,*/*", referer=referer))


def metric_summary(rows: Sequence[Dict[str, str]]) -> Dict[str, int]:
    return {
        "rows_written": len(rows),
        "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
        "distinct_products": len({row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}),
        "customer_review_image_rows": sum(1 for row in rows if row.get("image_source_type") == "customer_review_image"),
        "product_image_probe_rows": sum(1 for row in rows if row.get("image_source_type") == "product_image"),
        "rows_with_image_product_and_comment": sum(
            1
            for row in rows
            if row.get("original_url_display") and row.get("product_page_url_display") and row.get("user_comment")
        ),
    }


def write_outputs(slug: str, rows: Sequence[Dict[str, str]], summary: Dict[str, object]) -> Tuple[str, str]:
    output_csv, summary_json = output_paths(slug)
    write_intake_csv(rows, output_csv)
    validation = validate_rows(rows)
    summary = {
        **summary,
        "output_csv": str(output_csv),
        "summary_json": str(summary_json),
        "validation": validation,
        "metrics": metric_summary(rows),
    }
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(output_csv), str(summary_json)


def clean_image_url(value: object) -> str:
    url = normalize_whitespace(value)
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    return url


def apparel_product(product: Dict[str, object]) -> bool:
    text = " ".join(
        normalize_whitespace(part)
        for part in [
            product.get("title"),
            product.get("handle"),
            product.get("product_type"),
            product.get("type"),
            product.get("vendor"),
        ]
        if part
    )
    return bool(APPAREL_RE.search(text)) and not bool(NON_APPAREL_RE.search(text))


def enell_rows(max_products: int, max_images_per_product: int, fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    products: List[Dict[str, object]] = []
    pages_scanned = 0
    for page in range(1, 20):
        payload = fetch_json(f"https://enell.com/products.json?{urlencode({'limit': 250, 'page': page})}", referer="https://enell.com/")
        page_products = [item for item in payload.get("products") or [] if isinstance(item, dict)]
        pages_scanned += 1
        if not page_products:
            break
        for product in page_products:
            if apparel_product(product):
                products.append(product)
            if len(products) >= max_products:
                break
        if len(products) >= max_products:
            break
        time.sleep(0.15)

    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    for product in products:
        handle = normalize_whitespace(product.get("handle"))
        product_url = f"https://enell.com/products/{handle}"
        context = ProductContext(
            url=product_url,
            title=normalize_whitespace(product.get("title")),
            description=strip_tags(product.get("body_html")),
            category=normalize_whitespace(product.get("product_type")),
            brand="Enell",
            product_id=normalize_whitespace(product.get("id")),
            handle=handle,
            shop_domain="enell.com",
            provider_hints="public Shopify products.json; product images only",
        )
        images = [img for img in product.get("images") or [] if isinstance(img, dict)]
        product_summaries.append({"product_url": product_url, "title": context.title, "images_found": len(images)})
        for index, image in enumerate(images[:max_images_per_product], start=1):
            image_url = clean_image_url(image.get("src"))
            if not image_url:
                continue
            review = ReviewImage(
                image_url=image_url,
                review_id=f"enell-product-{context.product_id}-{index}",
                review_title=context.title,
                review_body="Public product image probe; no public customer review image feed was identified.",
                extra={
                    "image_source_type": "product_image",
                    "image_source_detail": "public Shopify product image, not a customer review photo",
                },
            )
            rows.append(build_intake_row(context, review, fetched_at))

    rows = dedupe_rows(rows)
    summary = {
        "site": "enell.com",
        "retailer": "enell_com",
        "adapter": "worker_c_enell_shopify_product_image_probe",
        "review_platform_provider": "not_identified",
        "access_policy": "public Shopify products.json and CDN product images only; no DB writes",
        "products_json_pages_scanned": pages_scanned,
        "products_scanned": len(products),
        "product_summaries": product_summaries,
        "blockers": [
            "No public customer review image endpoint identified from the safe file-first probe; rows are product-image probes."
        ],
    }
    return rows, summary


def uniqlo_product_context(product_id: str, color_code: str) -> Tuple[ProductContext, List[str], Dict[str, object]]:
    api_url = (
        f"https://www.uniqlo.com/us/api/commerce/v5/en/products/{product_id}"
        f"?{urlencode({'withPrices': 'true', 'withStocks': 'true'})}"
    )
    payload = fetch_json(api_url, referer=f"https://www.uniqlo.com/us/en/products/{product_id}/{color_code}")
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    breadcrumbs = result.get("breadcrumbs") if isinstance(result.get("breadcrumbs"), dict) else {}
    category = " > ".join(
        normalize_whitespace((breadcrumbs.get(key) or {}).get("locale"))
        for key in ["gender", "class", "category", "subcategory"]
        if isinstance(breadcrumbs.get(key), dict) and normalize_whitespace((breadcrumbs.get(key) or {}).get("locale"))
    )
    images: List[str] = []
    image_root = result.get("images") if isinstance(result.get("images"), dict) else {}
    main_images = image_root.get("main") if isinstance(image_root.get("main"), dict) else {}
    for item in main_images.values():
        if isinstance(item, dict):
            images.append(clean_image_url(item.get("image")))
    for item in image_root.get("sub") or []:
        if isinstance(item, dict):
            images.append(clean_image_url(item.get("image")))
    images = list(dict.fromkeys(url for url in images if url))
    context = ProductContext(
        url=f"https://www.uniqlo.com/us/en/products/{product_id}/{color_code}",
        title=normalize_whitespace(result.get("name")),
        description=strip_tags(result.get("longDescription") or result.get("shortDescription")),
        detail=strip_tags(result.get("composition")),
        category=category,
        brand="Uniqlo",
        color=normalize_whitespace(((result.get("representative") or {}).get("color") or {}).get("name"))
        if isinstance(result.get("representative"), dict)
        else "",
        product_id=normalize_whitespace(result.get("productId")),
        shop_domain="www.uniqlo.com",
        provider_hints="public Uniqlo commerce product API; product images and aggregate rating only",
    )
    return context, images, result


def uniqlo_rows(max_images_per_product: int, fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    # Seed from the public homepage/PDP probe; enough to verify product/rating and image availability without bypassing.
    seeds = [("E487962-000", "00")]
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    blockers: List[str] = []
    for product_id, color_code in seeds:
        context, images, result = uniqlo_product_context(product_id, color_code)
        rating = result.get("rating") if isinstance(result.get("rating"), dict) else {}
        product_summaries.append(
            {
                "product_url": context.url,
                "title": context.title,
                "aggregate_review_count": rating.get("count"),
                "images_found": len(images),
            }
        )
        for index, image_url in enumerate(images[:max_images_per_product], start=1):
            review = ReviewImage(
                image_url=image_url,
                review_id=f"uniqlo-product-{context.product_id}-{index}",
                review_title=context.title,
                review_body=(
                    "Public product image probe; product API exposes aggregate review count but no public "
                    "customer review image feed was identified."
                ),
                extra={
                    "image_source_type": "product_image",
                    "image_source_detail": "public Uniqlo product image, not a customer review photo",
                },
            )
            rows.append(build_intake_row(context, review, fetched_at))
        blockers.append(
            "PDP/product API exposed aggregate reviews but no review-image payload; Bazaarvoice-style BFD probes returned 401."
        )
    summary = {
        "site": "www.uniqlo.com/us/en",
        "retailer": "uniqlo_com",
        "adapter": "worker_c_uniqlo_product_api_review_image_probe",
        "review_platform_provider": "internal_or_undisclosed_bazaarvoice",
        "access_policy": "public Uniqlo PDP and commerce product API only; no auth, browser bypass, or DB writes",
        "products_scanned": len(seeds),
        "product_summaries": product_summaries,
        "blockers": blockers,
    }
    return dedupe_rows(rows), summary


def blocked_site(slug: str, site_url: str, retailer_name: str, fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    blockers: List[str] = []
    try:
        fetch_text(site_url)
        blockers.append("Home page did not block in this run, but no public product/review-image probe was implemented.")
    except StopScrape as exc:
        blockers.append(str(exc))
    summary = {
        "site": site_url,
        "retailer": slug,
        "adapter": "worker_c_access_wall_probe",
        "review_platform_provider": "not_probed_due_to_access_wall",
        "access_policy": "single public page probe only; stopped on WAF/access-denied; no bypass attempted",
        "products_scanned": 0,
        "blockers": blockers,
        "finished_at": fetched_at,
        "brand": retailer_name,
    }
    return [], summary


def run(args: argparse.Namespace) -> Dict[str, object]:
    fetched_at = utc_now()
    jobs = {
        "enell_com": lambda: enell_rows(args.max_products, args.max_images_per_product, fetched_at),
        "uniqlo_com": lambda: uniqlo_rows(args.max_images_per_product, fetched_at),
        "levi_com": lambda: blocked_site("levi_com", "https://www.levi.com/US/en_US/", "Levi's", fetched_at),
        "ae_com": lambda: blocked_site("ae_com", "https://www.ae.com/us/en", "Aerie / American Eagle", fetched_at),
    }
    requested = args.slug or list(jobs)
    overall: Dict[str, object] = {"started_at": fetched_at, "results": {}}
    for slug in requested:
        rows, summary = jobs[slug]()
        output_csv, summary_json = write_outputs(slug, rows, summary)
        overall["results"][slug] = {
            "rows": len(rows),
            "output_csv": output_csv,
            "summary_json": summary_json,
            "blockers": summary.get("blockers", []),
        }
        print(f"[{slug}] rows={len(rows)} summary={summary_json}", flush=True)
    overall["finished_at"] = utc_now()
    return overall


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", choices=["enell_com", "levi_com", "uniqlo_com", "ae_com"], action="append")
    parser.add_argument("--max-products", type=int, default=20)
    parser.add_argument("--max-images-per-product", type=int, default=6)
    return parser.parse_args()


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
