#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from step1_intake_utils import (
    INTAKE_HEADERS,
    ReviewImage,
    ProductContext,
    build_intake_row,
    canonical_product_url,
    dedupe_rows,
    normalize_ordered_size,
    normalize_whitespace,
    output_paths,
    review_date_from_raw,
    strip_tags,
    utc_now,
    validate_rows,
    write_intake_csv,
)


SITE = "https://showmeyourmumu.com"
RETAILER = "showmeyourmumu_com"
YOTPO_APP_KEY = "P5pI6DabCb24mXUbic4ZJutDy3NY5pdoqzQtJoKB"
YOTPO_PER_PAGE = 100
BLOCKING_STATUS_CODES = {401, 403, 407, 429}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
WOMENS_CLOTHING_RE = re.compile(
    r"\b("
    r"dress(?:es)?|gowns?|jumpsuits?|rompers?|tops?|tees?|shirts?|blouses?|sweaters?|"
    r"cardigans?|jackets?|coats?|blazers?|skirts?|skorts?|shorts?|pants?|jeans?|"
    r"leggings?|sets?|pajamas?|pj\s*sets?|bikinis?|swimsuits?|sarongs?|coverups?|"
    r"bras?|bralettes?|bodysuits?|tunics?|kimonos?|pullovers?"
    r")\b",
    re.I,
)
NON_OUTPUT_RE = re.compile(
    r"\b("
    r"gift\s*cards?|swatches?|fabric\s*swatches?|sunglasses?|bags?|belts?|"
    r"earrings?|rings?|hoops?|studs?|necklaces?|bracelets?|veils?|clips?|"
    r"heels?|sandals?|shoes?|boots?|slippers?|bow\s*ties?|pocket\s*squares?|"
    r"neck\s*ties?|hats?|caps?"
    r")\b",
    re.I,
)
MODEL_SIZE_RE = re.compile(r"model[-_\s*]*wears[-_\s*]*size[-_\s*]*([a-z0-9]+)", re.I)


@dataclass
class ProductRecord:
    url: str
    handle: str
    product_id: str = ""
    title: str = ""
    vendor: str = ""
    product_type: str = ""
    tags: List[str] = field(default_factory=list)
    description: str = ""
    variant: str = ""
    color: str = ""
    images: List[Dict[str, str]] = field(default_factory=list)
    source_names: set[str] = field(default_factory=set)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Show Me Your Mumu Yotpo review images.")
    parser.add_argument("--max-products", type=int, default=0, help="Debug cap; 0 scans all discovered products.")
    parser.add_argument("--sleep", type=float, default=0.02, help="Sleep between Yotpo product requests.")
    return parser.parse_args()


def curl_fetch_text(url: str, *, referer: str = SITE, accept: str = "*/*", retries: int = 3) -> str:
    last_error = ""
    for attempt in range(retries):
        cmd = [
            "curl",
            "-L",
            "-sS",
            "--fail-with-body",
            "--max-time",
            "60",
            "-A",
            USER_AGENT,
            "-H",
            f"Accept: {accept}",
        ]
        if referer:
            cmd.extend(["-e", referer])
        cmd.append(url)
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode == 0:
            return result.stdout
        last_error = normalize_whitespace(result.stderr or result.stdout)
        if any(f"error: {code}" in last_error.lower() or f" {code}" in last_error for code in BLOCKING_STATUS_CODES):
            raise RuntimeError(f"blocked_or_forbidden_fetch url={url} detail={last_error}")
        time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"fetch_failed url={url} detail={last_error}")


def curl_fetch_json(url: str, *, referer: str = SITE, retries: int = 3) -> Dict[str, object]:
    return json.loads(curl_fetch_text(url, referer=referer, accept="application/json,text/plain,*/*", retries=retries))


def handle_from_url(url: str) -> str:
    parsed = urlparse(url)
    if "/products/" not in parsed.path:
        return ""
    return parsed.path.split("/products/", 1)[1].split("/", 1)[0].removesuffix(".js")


def absolute_shopify_image(url: str) -> str:
    clean = normalize_whitespace(url)
    if clean.startswith("//"):
        return f"https:{clean}"
    if clean.startswith("/"):
        return f"{SITE}{clean}"
    return clean


def product_from_shopify(item: Dict[str, object], source_name: str) -> Optional[ProductRecord]:
    handle = normalize_whitespace(item.get("handle"))
    if not handle:
        return None
    tags_raw = item.get("tags")
    tags = [normalize_whitespace(tag) for tag in tags_raw if normalize_whitespace(tag)] if isinstance(tags_raw, list) else []
    images = []
    for image in item.get("images") or []:
        if not isinstance(image, dict):
            continue
        src = absolute_shopify_image(str(image.get("src") or ""))
        if src:
            images.append({"src": src, "alt": normalize_whitespace(image.get("alt"))})
    variants = item.get("variants") if isinstance(item.get("variants"), list) else []
    variant = ""
    if variants and isinstance(variants[0], dict):
        variant = normalize_whitespace(variants[0].get("title"))
    record = ProductRecord(
        url=f"{SITE}/products/{handle}",
        handle=handle,
        product_id=normalize_whitespace(item.get("id")),
        title=normalize_whitespace(item.get("title")),
        vendor=normalize_whitespace(item.get("vendor")),
        product_type=normalize_whitespace(item.get("product_type") or item.get("type")),
        tags=tags,
        description=strip_tags(item.get("body_html") or item.get("description") or ""),
        variant=variant,
        color=color_from_product(normalize_whitespace(item.get("title")), tags, variant),
        images=images,
        source_names={source_name},
    )
    return record


def merge_product(target: ProductRecord, incoming: ProductRecord) -> None:
    target.source_names.update(incoming.source_names)
    for attr in ["product_id", "title", "vendor", "product_type", "description", "variant", "color"]:
        if not getattr(target, attr) and getattr(incoming, attr):
            setattr(target, attr, getattr(incoming, attr))
    if not target.tags and incoming.tags:
        target.tags = incoming.tags
    seen_images = {image.get("src", "") for image in target.images}
    for image in incoming.images:
        if image.get("src") and image.get("src") not in seen_images:
            seen_images.add(image["src"])
            target.images.append(image)


def color_from_product(title: str, tags: Sequence[str], variant: str = "") -> str:
    for tag in tags:
        if tag.lower().startswith(("color:", "child:")):
            return normalize_whitespace(tag.split(":", 1)[1])
    if "~" in title:
        return normalize_whitespace(title.rsplit("~", 1)[1])
    return normalize_whitespace(variant)


def discover_from_products_json() -> Tuple[List[ProductRecord], Dict[str, object]]:
    products: List[ProductRecord] = []
    pages = 0
    for page in range(1, 10000):
        url = f"{SITE}/products.json?limit=250&page={page}"
        payload = curl_fetch_json(url, referer=SITE, retries=3)
        items = payload.get("products")
        if not isinstance(items, list) or not items:
            break
        pages += 1
        for item in items:
            if isinstance(item, dict):
                record = product_from_shopify(item, "products_json")
                if record:
                    products.append(record)
        if len(items) < 250:
            break
    return products, {"pages": pages, "products": len(products)}


def sitemap_urls() -> List[str]:
    text = curl_fetch_text(f"{SITE}/sitemap.xml", referer=SITE, retries=3)
    root = ET.fromstring(text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = []
    for loc in root.findall(".//sm:loc", ns):
        value = html.unescape(loc.text or "")
        if "sitemap_products_" in value:
            urls.append(value)
    return urls


def discover_from_sitemaps() -> Tuple[List[ProductRecord], Dict[str, object]]:
    products: List[ProductRecord] = []
    sitemap_count = 0
    for sitemap_url in sitemap_urls():
        sitemap_count += 1
        text = curl_fetch_text(sitemap_url, referer=SITE, retries=3)
        root = ET.fromstring(text)
        ns = {
            "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
            "image": "http://www.google.com/schemas/sitemap-image/1.1",
        }
        for url_node in root.findall(".//sm:url", ns):
            loc = url_node.find("sm:loc", ns)
            url = canonical_product_url(html.unescape(loc.text or "")) if loc is not None else ""
            handle = handle_from_url(url)
            if not handle:
                continue
            title = ""
            images = []
            for image_node in url_node.findall("image:image", ns):
                image_loc = image_node.find("image:loc", ns)
                image_title = image_node.find("image:title", ns)
                image_caption = image_node.find("image:caption", ns)
                if image_title is not None and image_title.text and not title:
                    title = normalize_whitespace(image_title.text)
                src = absolute_shopify_image(html.unescape(image_loc.text or "")) if image_loc is not None else ""
                if src:
                    images.append(
                        {
                            "src": src,
                            "alt": normalize_whitespace(image_caption.text if image_caption is not None else ""),
                        }
                    )
            products.append(
                ProductRecord(
                    url=url,
                    handle=handle,
                    title=title,
                    images=images,
                    color=color_from_product(title, []),
                    source_names={"product_sitemap"},
                )
            )
    return products, {"sitemaps": sitemap_count, "products": len(products)}


def discover_products() -> Tuple[List[ProductRecord], Dict[str, object]]:
    by_handle: Dict[str, ProductRecord] = {}
    source_summary: Dict[str, object] = {}
    for source_products, source_stats in [discover_from_products_json(), discover_from_sitemaps()]:
        source_name = next(iter(source_products[0].source_names)) if source_products else "unknown"
        source_summary[source_name] = source_stats
        for product in source_products:
            if product.handle in by_handle:
                merge_product(by_handle[product.handle], product)
            else:
                by_handle[product.handle] = product
    return list(by_handle.values()), source_summary


def product_scope(product: ProductRecord) -> Tuple[bool, str]:
    text = normalize_whitespace(
        " ".join([product.title, product.handle, product.product_type, product.vendor, " ".join(product.tags)])
    )
    lowered = text.lower()
    if re.search(r"\b(?:men|mens|men's|male|boys?|kids?|children|toddler|baby)\b", lowered):
        return False, "outside_current_scope_gender_or_age"
    if NON_OUTPUT_RE.search(text) and not WOMENS_CLOTHING_RE.search(text):
        return False, "outside_current_scope_accessory_or_non_clothing"
    if WOMENS_CLOTHING_RE.search(text):
        return True, ""
    if product.product_type.lower() == "apparel":
        return True, ""
    return False, "outside_current_scope_not_confident_womens_clothing"


def context_for_product(product: ProductRecord) -> ProductContext:
    return ProductContext(
        url=product.url,
        title=product.title,
        description=product.description,
        detail=" | ".join(product.tags[:30]),
        category=product.product_type,
        brand=product.vendor or "Show Me Your Mumu",
        product_id=product.product_id,
        handle=product.handle,
        shop_domain="showmeyourmumu.myshopify.com",
        color=product.color,
        variant=product.variant,
        provider_hints="Yotpo",
    )


def custom_field_map(review: Dict[str, object]) -> Dict[str, str]:
    mapped: Dict[str, str] = {}
    custom_fields = review.get("custom_fields")
    if not isinstance(custom_fields, dict):
        return mapped
    for value in custom_fields.values():
        if not isinstance(value, dict):
            continue
        title = normalize_whitespace(value.get("title"))
        field_value = normalize_whitespace(value.get("value"))
        if title and field_value:
            mapped[title] = field_value
    return mapped


def comment_with_fields(review: Dict[str, object], fields: Dict[str, str]) -> Tuple[str, str]:
    title = normalize_whitespace(review.get("title"))
    body = normalize_whitespace(review.get("content"))
    additions = []
    for label in ["Height", "Body Type", "Bust Size", "Product Fit", "Size Usually Worn", "Size Purchased"]:
        if fields.get(label):
            additions.append(f"{label}: {fields[label]}")
    return title, normalize_whitespace(" ".join([body, " ".join(additions)]))


def yotpo_url(product_id: str, page: int) -> str:
    return (
        f"https://api-cdn.yotpo.com/v1/widget/{YOTPO_APP_KEY}/products/{product_id}/reviews.json"
        f"?page={page}&per_page={YOTPO_PER_PAGE}"
    )


def fetch_yotpo_reviews(product: ProductRecord) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    if not product.product_id:
        return [], {"pages_scanned": 0, "total_reviews_reported": 0, "error": "missing_product_id"}
    reviews: List[Dict[str, object]] = []
    grouping_data: Dict[str, object] = {}
    pages_scanned = 0
    total = 0
    for page in range(1, 10000):
        try:
            payload = curl_fetch_json(yotpo_url(product.product_id, page), referer=product.url, retries=3)
        except HTTPError as exc:
            if exc.code in BLOCKING_STATUS_CODES:
                raise RuntimeError(f"blocked_by_status_{exc.code} product={product.url}") from exc
            raise
        response = payload.get("response") if isinstance(payload, dict) else {}
        if not isinstance(response, dict):
            return reviews, {"pages_scanned": pages_scanned, "total_reviews_reported": total, "error": "bad_yotpo_response"}
        pagination = response.get("pagination") if isinstance(response.get("pagination"), dict) else {}
        total = int(pagination.get("total") or total or 0)
        page_reviews = response.get("reviews") if isinstance(response.get("reviews"), list) else []
        page_grouping = response.get("grouping_data")
        if isinstance(page_grouping, dict):
            grouping_data.update(page_grouping)
        pages_scanned += 1
        reviews.extend([review for review in page_reviews if isinstance(review, dict)])
        if not page_reviews or len(reviews) >= total or len(page_reviews) < YOTPO_PER_PAGE:
            break
    return reviews, {"pages_scanned": pages_scanned, "total_reviews_reported": total, "grouping_data": grouping_data}


def image_urls_from_review(review: Dict[str, object]) -> List[str]:
    urls = []
    images_data = review.get("images_data")
    if isinstance(images_data, list):
        for image in images_data:
            if not isinstance(image, dict):
                continue
            url = normalize_whitespace(image.get("original_url") or image.get("thumb_url"))
            if url:
                urls.append(url)
    return list(dict.fromkeys(urls))


def rows_from_reviews(
    product: ProductRecord,
    reviews: Sequence[Dict[str, object]],
    fetched_at: str,
    product_by_title: Dict[str, ProductRecord],
    grouping_data: Dict[str, object],
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for review in reviews:
        image_urls = image_urls_from_review(review)
        if not image_urls:
            continue
        review_id = normalize_whitespace(review.get("id"))
        grouped = grouping_data.get(review_id) if isinstance(grouping_data, dict) else None
        grouped_name = normalize_whitespace(grouped.get("product_name") if isinstance(grouped, dict) else "")
        grouped_url = normalize_whitespace(grouped.get("product_url") if isinstance(grouped, dict) else "")
        row_product = product_by_title.get(grouped_name.lower(), product) if grouped_name else product
        context = context_for_product(row_product)
        fields = custom_field_map(review)
        title, body = comment_with_fields(review, fields)
        size_raw = normalize_ordered_size(fields.get("Size Purchased", "")) if fields.get("Size Purchased") else ""
        date_raw = normalize_whitespace(review.get("created_at"))
        for index, image_url in enumerate(image_urls, start=1):
            review_image = ReviewImage(
                image_url=image_url,
                review_id=f"showmeyourmumu-yotpo-{review_id}-{index}" if review_id else "",
                review_title=title,
                review_body=body,
                reviewer_name=normalize_whitespace((review.get("user") or {}).get("display_name") if isinstance(review.get("user"), dict) else ""),
                date_raw=date_raw,
                review_date=review_date_from_raw(date_raw),
                size_raw=size_raw,
                rating=normalize_whitespace(review.get("score")),
                extra={
                    "product_url": row_product.url,
                    "product_title": row_product.title or grouped_name,
                    "product_description": row_product.description,
                    "product_detail": " | ".join(row_product.tags[:30]),
                    "product_category": row_product.product_type,
                    "product_variant": row_product.variant,
                    "image_source_type": "customer_review_image",
                    "image_source_detail": normalize_whitespace(
                        f"yotpo_review_id={review_id}; rating={normalize_whitespace(review.get('score'))}; "
                        f"yotpo_group_product_name={grouped_name}; yotpo_group_product_url={grouped_url}"
                    ),
                },
            )
            row = build_intake_row(context, review_image, fetched_at)
            rows.append(row)
    return rows


def model_size_from_alt(alt: str) -> str:
    match = MODEL_SIZE_RE.search(alt or "")
    if not match:
        return ""
    return normalize_ordered_size(match.group(1))


def rows_from_catalog_model(product: ProductRecord, fetched_at: str) -> List[Dict[str, str]]:
    context = context_for_product(product)
    rows: List[Dict[str, str]] = []
    for index, image in enumerate(product.images, start=1):
        src = image.get("src", "")
        alt = image.get("alt", "")
        size = model_size_from_alt(alt)
        if not src or not size:
            continue
        review_image = ReviewImage(
            image_url=src,
            review_id=f"showmeyourmumu-catalog-{product.product_id or product.handle}-{index}",
            review_title="Catalog model image",
            review_body=f"Catalog/model media. Model wears size {size}.",
            reviewer_name="Show Me Your Mumu",
            date_raw="",
            review_date="",
            size_raw=size,
            extra={
                "product_url": product.url,
                "product_title": product.title,
                "product_description": product.description,
                "product_detail": " | ".join(product.tags[:30]),
                "product_category": product.product_type,
                "product_variant": product.variant,
                "image_source_type": "catalog_model_image",
                "image_source_detail": normalize_whitespace(alt),
            },
        )
        rows.append(build_intake_row(context, review_image, fetched_at))
    return rows


def dedupe_showmeyourmumu_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped = []
    seen = set()
    for row in rows:
        row_id = row.get("id", "")
        image_url = row.get("original_url_display", "")
        if row_id.startswith("showmeyourmumu-yotpo-"):
            key = (row_id, image_url)
        else:
            key = (row_id, row.get("product_page_url_display", ""), image_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def write_summary(
    summary_json: Path,
    *,
    output_csv: Path,
    rows: Sequence[Dict[str, str]],
    started_at: str,
    finished_at: str,
    product_sources: Dict[str, object],
    products_discovered: int,
    products_scanned: int,
    products_excluded_from_output: int,
    review_pages_scanned: int,
    product_summaries: Sequence[Dict[str, object]],
    errors: Sequence[str],
) -> None:
    summary = {
        "site": SITE,
        "retailer": RETAILER,
        "adapter": "shopify_products_json_sitemap_yotpo_product_reviews",
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": product_sources,
        "products_discovered": products_discovered,
        "products_scanned": products_scanned,
        "products_excluded_from_output": products_excluded_from_output,
        "review_pages_scanned": review_pages_scanned,
        "exhaustive_review_paging": not errors,
        "product_summaries": list(product_summaries),
        "errors": list(errors),
    }
    metrics = validate_rows(rows)
    summary.update(metrics)
    summary["distinct_reviews"] = len({row.get("id", "").rsplit("-", 1)[0] for row in rows if row.get("id", "").startswith("showmeyourmumu-yotpo-")})
    summary["rows_with_customer_image"] = metrics["rows_with_customer_review_image"]
    summary["rows_supabase_qualified"] = metrics["supabase_qualified_rows"]
    summary["rows_with_distinct_product_url"] = metrics["distinct_products"]
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    started_at = utc_now()
    fetched_at = started_at
    output_csv, summary_json = output_paths(RETAILER)
    errors: List[str] = []
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []

    try:
        products, product_sources = discover_products()
    except (HTTPError, URLError, ET.ParseError, json.JSONDecodeError, RuntimeError) as exc:
        errors.append(f"product_discovery_failed: {exc}")
        write_summary(
            summary_json,
            output_csv=output_csv,
            rows=[],
            started_at=started_at,
            finished_at=utc_now(),
            product_sources={},
            products_discovered=0,
            products_scanned=0,
            products_excluded_from_output=0,
            review_pages_scanned=0,
            product_summaries=[],
            errors=errors,
        )
        return 2

    products_discovered_total = len(products)
    product_by_title = {product.title.lower(): product for product in products if product.title}

    if args.max_products:
        products = products[: args.max_products]

    review_pages_scanned = 0
    products_excluded_from_output = 0
    for product_index, product in enumerate(products, start=1):
        in_scope, skip_reason = product_scope(product)
        try:
            reviews, stats = fetch_yotpo_reviews(product)
        except RuntimeError as exc:
            errors.append(str(exc))
            break
        except Exception as exc:
            errors.append(f"product_review_fetch_failed product={product.url}: {exc}")
            reviews, stats = [], {"pages_scanned": 0, "total_reviews_reported": 0, "error": str(exc)}
        review_pages_scanned += int(stats.get("pages_scanned") or 0)
        review_rows = (
            rows_from_reviews(product, reviews, fetched_at, product_by_title, stats.get("grouping_data") or {})
            if in_scope
            else []
        )
        catalog_rows = rows_from_catalog_model(product, fetched_at) if in_scope and not review_rows else []
        rows.extend(review_rows)
        rows.extend(catalog_rows)
        if not in_scope:
            products_excluded_from_output += 1
        product_summaries.append(
            {
                "product_url": product.url,
                "product_id": product.product_id,
                "product_title": product.title,
                "source_names": sorted(product.source_names),
                "in_scope_for_output": in_scope,
                "skipped_from_output": not in_scope,
                "skip_reason": skip_reason,
                "reviews_reported_by_yotpo": stats.get("total_reviews_reported", 0),
                "review_pages_scanned": stats.get("pages_scanned", 0),
                "reviews_seen": len(reviews),
                "customer_review_image_rows": len(review_rows),
                "catalog_model_image_rows": len(catalog_rows),
            }
        )
        if product_index % 100 == 0:
            print(f"scanned {product_index}/{len(products)} products; rows={len(rows)}", file=sys.stderr)
        if args.sleep:
            time.sleep(args.sleep)

    rows = dedupe_showmeyourmumu_rows(dedupe_rows(rows))
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    write_summary(
        summary_json,
        output_csv=output_csv,
        rows=rows,
        started_at=started_at,
        finished_at=finished_at,
        product_sources=product_sources,
        products_discovered=products_discovered_total,
        products_scanned=len(product_summaries),
        products_excluded_from_output=products_excluded_from_output,
        review_pages_scanned=review_pages_scanned,
        product_summaries=product_summaries,
        errors=errors,
    )
    print(str(output_csv))
    print(str(summary_json))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
