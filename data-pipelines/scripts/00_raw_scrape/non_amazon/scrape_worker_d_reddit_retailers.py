#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin

PIPELINE_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from scrape_p0_lead_reviews import JudgeMeAdapter, build_url, unique  # noqa: E402
from step1_intake_utils import (  # noqa: E402
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    discover_shopify_product_urls,
    extract_product_context,
    fetch_json,
    fetch_text,
    hydrate_shopify_context,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    write_intake_csv,
    write_summary,
)


ACCESS_POLICY = (
    "public_product_and_review_pages_only; file_first_outputs; "
    "no_db_writes; stop_on_waf_captcha_429_auth_walls"
)
REVIEWS_IO_API_URL = "https://api.reviews.io/product/review"
BLOCK_TEXT_RE = re.compile(
    r"\b(?:access denied|captcha|cloudflare|datadome|verify you are human|forbidden|akamai)\b",
    re.I,
)


@dataclass(frozen=True)
class RetailerTarget:
    slug: str
    name: str
    site_root: str
    adapter: str


TARGETS = [
    RetailerTarget("madewell_com", "Madewell", "https://www.madewell.com", "blocked-probe"),
    RetailerTarget("americantall_com", "American Tall", "https://americantall.com", "reviews-io"),
    RetailerTarget("alexanderjaneboutique_com", "Alexander Jane", "https://alexanderjane.com", "judgeme"),
]


def detect_wall(text: str, url: str) -> Optional[str]:
    if BLOCK_TEXT_RE.search(text[:10000]):
        return f"challenge_or_access_denied_body at {url}"
    return None


def safe_fetch_text(url: str, *, referer: str = "", retries: int = 2) -> Tuple[str, Optional[str]]:
    try:
        text = fetch_text(url, referer=referer, retries=retries)
    except HTTPError as exc:
        if exc.code in {401, 403, 429}:
            return "", f"HTTP {exc.code} wall at {url}"
        return "", f"HTTP {exc.code} at {url}"
    except URLError as exc:
        return "", f"URL error at {url}: {exc}"
    except Exception as exc:
        return "", f"fetch failed at {url}: {exc}"
    wall = detect_wall(text, url)
    return text, wall


def write_blocked_or_empty_summary(
    target: RetailerTarget,
    *,
    started_at: str,
    adapter: str,
    errors: Sequence[str],
    product_summaries: Sequence[Dict[str, object]] = (),
    products_scanned: int = 0,
) -> Dict[str, object]:
    output_csv, summary_json = output_paths(target.slug)
    rows: List[Dict[str, str]] = []
    write_intake_csv(rows, output_csv)
    write_summary(
        summary_json,
        site=target.site_root,
        retailer=target.slug,
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=utc_now(),
        products_scanned=products_scanned,
        adapter=adapter,
        product_summaries=product_summaries,
        errors=errors,
    )
    enrich_summary(
        summary_json,
        target,
        {
            "access_policy": ACCESS_POLICY,
            "manual_check_note": "accepts pictures, public image rows not observed"
            if not errors
            else "blocked before public image-row discovery completed",
            "blocked": bool(errors),
        },
    )
    return {"output_csv": str(output_csv), "summary_json": str(summary_json), "rows": 0, "errors": list(errors)}


def enrich_summary(summary_json: Path, target: RetailerTarget, extra: Dict[str, object]) -> None:
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    payload.update(
        {
            "retailer_name": target.name,
            "retailer_slug_requested": target.slug,
            "site_root_corrected": target.site_root,
            **extra,
        }
    )
    summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def product_contexts_from_shopify_json(
    target: RetailerTarget,
    *,
    max_products: Optional[int],
) -> Tuple[List[ProductContext], List[Dict[str, object]], List[str]]:
    contexts: List[ProductContext] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    root = target.site_root.rstrip("/")
    seen_handles = set()
    index = 0
    for page in range(1, 10000):
        if max_products is not None and len(contexts) >= max_products:
            break
        url = f"{root}/products.json?limit=250&page={page}"
        try:
            payload = fetch_json(url, referer=root, retries=2)
        except HTTPError as exc:
            if exc.code in {401, 403, 429}:
                errors.append(f"Stopped on HTTP {exc.code} from {url}")
                break
            errors.append(f"Product catalog page {page} failed: HTTP {exc.code}")
            break
        except Exception as exc:
            errors.append(f"Product catalog page {page} failed: {exc}")
            break
        products = payload.get("products")
        if not isinstance(products, list) or not products:
            break
        for product in products:
            if max_products is not None and len(contexts) >= max_products:
                break
            if not isinstance(product, dict):
                continue
            handle = normalize_whitespace(product.get("handle"))
            if not handle or handle in seen_handles:
                continue
            seen_handles.add(handle)
            variants = product.get("variants") if isinstance(product.get("variants"), list) else []
            first_variant = next((item for item in variants if isinstance(item, dict)), {})
            sku_parts = reviews_io_sku_parts(handle, product, variants)
            index += 1
            context = ProductContext(
                url=f"{root}/products/{handle}",
                title=normalize_whitespace(product.get("title")),
                description=strip_tags(product.get("body_html")),
                category=normalize_whitespace(product.get("product_type")),
                brand=normalize_whitespace(product.get("vendor")) or target.name,
                product_id=normalize_whitespace(product.get("id")),
                handle=handle,
                shop_domain=root.removeprefix("https://"),
                provider_hints="Reviews.io",
                color=normalize_whitespace(first_variant.get("option1") if isinstance(first_variant, dict) else ""),
                variant=normalize_whitespace(first_variant.get("title") if isinstance(first_variant, dict) else ""),
            )
            context.raw_html = ";".join(sku_parts)
            contexts.append(context)
            product_summaries.append(
                {
                    "product_url": context.url,
                    "product_title": context.title,
                    "provider_hints": context.provider_hints,
                    "adapter_used": "reviews-io-product",
                    "matching_review_images": 0,
                    "product_index": index,
                    "lookup_sku_count": len(sku_parts),
                }
            )
        if len(products) < 250:
            break
    return contexts, product_summaries, errors


def reviews_io_sku_parts(handle: str, product: Dict[str, object], variants: Sequence[object]) -> List[str]:
    parts = [handle, normalize_whitespace(product.get("id"))]
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        parts.append(normalize_whitespace(variant.get("sku")))
        parts.append(normalize_whitespace(variant.get("id")))
    return unique(part for part in parts if part)


def extract_reviews_io_images(item: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    for key in ["images", "media", "photos"]:
        value = item.get(key)
        if isinstance(value, str):
            urls.extend(re.findall(r"https?://[^'\"\s,<>]+\.(?:jpg|jpeg|png|webp)(?:\?[^'\"\s,<>]*)?", value, re.I))
        elif isinstance(value, list):
            for entry in value:
                if isinstance(entry, str):
                    urls.append(entry)
                elif isinstance(entry, dict):
                    for image_key in ["url", "image_url", "large", "src", "thumbnail", "full_size_url"]:
                        candidate = normalize_whitespace(entry.get(image_key))
                        if candidate:
                            urls.append(candidate)
        elif isinstance(value, dict):
            for candidate in value.values():
                if isinstance(candidate, str):
                    urls.append(candidate)
    return unique(f"https:{url}" if url.startswith("//") else url for url in urls if url)


def scrape_reviews_io(
    target: RetailerTarget,
    *,
    max_products: Optional[int],
    max_review_pages_per_product: int,
) -> Dict[str, object]:
    started_at = utc_now()
    contexts, product_summaries, errors = product_contexts_from_shopify_json(target, max_products=max_products)
    fetched_at = utc_now()
    rows: List[Dict[str, str]] = []
    total_review_records_scanned = 0
    summaries_by_url = {str(item["product_url"]): item for item in product_summaries}

    for index, context in enumerate(contexts, start=1):
        lookup = context.raw_html
        if not lookup:
            continue
        product_rows = 0
        review_records = 0
        for page in range(1, max_review_pages_per_product + 1):
            params = {
                "store": "americantall-com",
                "sku": lookup,
                "per_page": 100,
                "page": page,
            }
            try:
                payload = fetch_json(f"{REVIEWS_IO_API_URL}?{urlencode(params)}", referer=context.url, retries=2)
            except HTTPError as exc:
                if exc.code in {401, 403, 429}:
                    errors.append(f"Stopped on HTTP {exc.code} from Reviews.io for {context.url}")
                    break
                errors.append(f"Reviews.io page {page} failed for {context.url}: HTTP {exc.code}")
                break
            except Exception as exc:
                errors.append(f"Reviews.io page {page} failed for {context.url}: {exc}")
                break
            reviews = payload.get("reviews") if isinstance(payload.get("reviews"), dict) else {}
            items = reviews.get("data") if isinstance(reviews, dict) else []
            if not isinstance(items, list) or not items:
                break
            review_records += len(items)
            total_review_records_scanned += len(items)
            for item in items:
                if not isinstance(item, dict):
                    continue
                image_urls = extract_reviews_io_images(item)
                if not image_urls:
                    continue
                reviewer = item.get("reviewer") if isinstance(item.get("reviewer"), dict) else {}
                for image_url in image_urls:
                    review = ReviewImage(
                        image_url=image_url,
                        review_id=normalize_whitespace(item.get("product_review_id") or item.get("id")),
                        review_title=normalize_whitespace(item.get("title")),
                        review_body=normalize_whitespace(item.get("review") or item.get("comments")),
                        reviewer_name=normalize_whitespace(
                            " ".join(
                                part
                                for part in [
                                    reviewer.get("first_name") if isinstance(reviewer, dict) else "",
                                    reviewer.get("last_name") if isinstance(reviewer, dict) else "",
                                ]
                                if part
                            )
                        ),
                        date_raw=normalize_whitespace(item.get("date_created")),
                        rating=normalize_whitespace(item.get("rating")),
                        extra={
                            "product_url": context.url,
                            "product_title": context.title,
                            "image_source_detail": "reviews.io product review image",
                        },
                    )
                    rows.append(build_intake_row(context, review, fetched_at))
                    product_rows += 1
            last_page = int(reviews.get("last_page") or page) if isinstance(reviews, dict) else page
            if page >= last_page:
                break
            time.sleep(0.15)
        summary = summaries_by_url.get(context.url)
        if summary is not None:
            summary["matching_review_images"] = product_rows
            summary["review_records_scanned"] = review_records
        print(
            f"[{target.slug} {index}/{len(contexts)}] {context.title or context.url} -> "
            f"{product_rows} image rows from {review_records} reviews",
            flush=True,
        )
        if errors and errors[-1].startswith("Stopped on HTTP"):
            break

    rows = dedupe_rows(rows)
    output_csv, summary_json = output_paths(target.slug)
    write_intake_csv(rows, output_csv)
    write_summary(
        summary_json,
        site=target.site_root,
        retailer=target.slug,
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=utc_now(),
        products_scanned=len(contexts),
        adapter="reviews-io",
        product_summaries=product_summaries,
        errors=errors,
    )
    enrich_summary(
        summary_json,
        target,
        {
            "access_policy": ACCESS_POLICY,
            "reviews_io_store": "americantall-com",
            "review_records_scanned": total_review_records_scanned,
            "manual_check_note": "Reviews.io widget accepts/displays review media; no public image rows found"
            if not rows
            else "Reviews.io public review images found",
            "max_review_pages_per_product": max_review_pages_per_product,
            "max_products": max_products,
        },
    )
    return {"output_csv": str(output_csv), "summary_json": str(summary_json), "rows": len(rows), "errors": errors}


def scrape_judgeme(
    target: RetailerTarget,
    *,
    max_products: Optional[int],
    aggregate_only: bool,
) -> Dict[str, object]:
    started_at = utc_now()
    root = target.site_root.rstrip("/")
    product_urls = discover_shopify_product_urls(root, [])
    if max_products is not None:
        product_urls = product_urls[:max_products]
    if not product_urls:
        return write_blocked_or_empty_summary(
            target,
            started_at=started_at,
            adapter="judgeme",
            errors=["No public Shopify product URLs discovered"],
        )
    seed_context = hydrate_shopify_context(extract_product_context(product_urls[0]))
    if "judge" not in seed_context.provider_hints.lower():
        seed_context.provider_hints = "; ".join(unique([seed_context.provider_hints, "Judge.me"]))
    fetched_at = utc_now()
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    adapter = JudgeMeAdapter()

    if aggregate_only:
        try:
            reviews = adapter._all_reviews(seed_context)
        except Exception as exc:
            reviews = []
            errors.append(f"Judge.me aggregate feed failed: {exc}")
        rows = dedupe_rows([build_intake_row(seed_context, review, fetched_at) for review in reviews if review.image_url])
        product_summaries.append(
            {
                "product_url": seed_context.url,
                "product_title": seed_context.title,
                "provider_hints": seed_context.provider_hints,
                "adapter_used": "judgeme-aggregate",
                "matching_review_images": len(rows),
                "product_index": 1,
            }
        )
    else:
        for index, product_url in enumerate(product_urls, start=1):
            try:
                context = hydrate_shopify_context(extract_product_context(product_url))
                if "judge" not in context.provider_hints.lower():
                    context.provider_hints = "; ".join(unique([context.provider_hints, "Judge.me"]))
                # Avoid Judge.me's aggregate fallback here: product-pass rows must
                # stay anchored to the product being scanned.
                reviews = adapter._widget_reviews(context)
            except Exception as exc:
                errors.append(f"{product_url}: Judge.me product scrape failed: {exc}")
                reviews = []
                context = ProductContext(url=product_url, brand=target.name, provider_hints="Judge.me")
            product_rows = [build_intake_row(context, review, fetched_at) for review in reviews if review.image_url]
            rows.extend(product_rows)
            product_summaries.append(
                {
                    "product_url": context.url,
                    "product_title": context.title,
                    "provider_hints": context.provider_hints,
                    "adapter_used": "judgeme-product",
                    "matching_review_images": len(product_rows),
                    "product_index": index,
                }
            )
            print(f"[{target.slug} {index}/{len(product_urls)}] {context.title or product_url} -> {len(product_rows)} rows", flush=True)
    rows = dedupe_rows(rows)
    output_csv, summary_json = output_paths(target.slug)
    write_intake_csv(rows, output_csv)
    write_summary(
        summary_json,
        site=target.site_root,
        retailer=target.slug,
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=utc_now(),
        products_scanned=len(product_urls),
        adapter="judgeme-aggregate" if aggregate_only else "judgeme",
        product_summaries=product_summaries,
        errors=errors,
    )
    enrich_summary(
        summary_json,
        target,
        {
            "access_policy": ACCESS_POLICY,
            "manual_check_note": "Judge.me accepts pictures/videos; no public image rows found"
            if not rows
            else "Judge.me public review images found",
            "aggregate_only": aggregate_only,
            "max_products": max_products,
        },
    )
    return {"output_csv": str(output_csv), "summary_json": str(summary_json), "rows": len(rows), "errors": errors}


def probe_blocked(target: RetailerTarget) -> Dict[str, object]:
    started_at = utc_now()
    errors: List[str] = []
    product_summaries: List[Dict[str, object]] = []
    for url in [target.site_root.rstrip("/") + "/", target.site_root.rstrip("/") + "/sitemap.xml"]:
        text, wall = safe_fetch_text(url, retries=1)
        if wall:
            errors.append(wall)
            product_summaries.append({"probe_url": url, "status": "blocked", "detail": wall})
            break
        product_summaries.append({"probe_url": url, "status": "reachable", "bytes": len(text)})
    if not errors:
        errors.append("Madewell did not expose a public review-image endpoint in this file-first probe")
    return write_blocked_or_empty_summary(
        target,
        started_at=started_at,
        adapter="blocked-probe",
        errors=errors,
        product_summaries=product_summaries,
        products_scanned=0,
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Worker D file-first probes for three Reddit-recommended retailers.")
    parser.add_argument("--slug", action="append", choices=[target.slug for target in TARGETS], help="Run only this slug; repeatable.")
    parser.add_argument("--max-products", type=int, default=None, help="Limit product pages per Shopify retailer.")
    parser.add_argument("--reviews-io-pages", type=int, default=3, help="Max Reviews.io review pages per product.")
    parser.add_argument("--judgeme-product-pass", action="store_true", help="Use product-level Judge.me scan instead of aggregate media feed.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    wanted = set(args.slug or [target.slug for target in TARGETS])
    overall: Dict[str, object] = {}
    exit_code = 0
    for target in TARGETS:
        if target.slug not in wanted:
            continue
        try:
            if target.adapter == "blocked-probe":
                result = probe_blocked(target)
            elif target.adapter == "reviews-io":
                result = scrape_reviews_io(
                    target,
                    max_products=args.max_products,
                    max_review_pages_per_product=args.reviews_io_pages,
                )
            elif target.adapter == "judgeme":
                result = scrape_judgeme(
                    target,
                    max_products=args.max_products,
                    aggregate_only=not args.judgeme_product_pass,
                )
            else:
                raise RuntimeError(f"Unknown adapter {target.adapter}")
            overall[target.slug] = result
        except Exception as exc:
            overall[target.slug] = {"error": str(exc)}
            print(f"ERROR {target.slug}: {exc}", file=sys.stderr, flush=True)
            exit_code = 1
    print(json.dumps(overall, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
