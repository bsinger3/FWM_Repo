#!/usr/bin/env python3
from __future__ import annotations
import sys

import argparse
import csv
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, legacy_raw_run_dir, raw_scraped_data_root, reports_root  # noqa: E402
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from step1_intake_utils import INTAKE_HEADERS


SITE_ROOT = "https://www.redrat.co.nz"
WOMENS_CATEGORY_URL = f"{SITE_ROOT}/c/womens"
RETAILER = "redrat_co_nz"

DATA_ROOT = Path(os.environ["FWM_DATA_DIR"]).expanduser() if os.environ.get("FWM_DATA_DIR") else Path(__file__).resolve().parents[4].parent / "FWM_Data"
OUTPUT_DIR = legacy_raw_run_dir(RETAILER)
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"

BLOCK_MARKERS = [
    "cf-chl",
    "just a moment",
    "attention required",
    "verify you are human",
    "please verify you are a human",
    "access denied",
    "datadome",
    "captcha",
]

APPAREL_RE = re.compile(
    r"\b(womens?|hoodie|jacket|vest|top|tee|t-shirt|track\s*pants?|pants?|jeans?|shorts?|skirt|dress|"
    r"sweater|crew|pullover|singlet|tank|shirt|leggings?)\b",
    re.I,
)
OUT_OF_SCOPE_RE = re.compile(
    r"\b(cap|hat|beanie|sock|socks|shoe|shoes|boot|boots|sneaker|slides?|jandal|bag|wallet|belt|"
    r"necklace|earrings?|bracelet|kids?|boys?|girls?|mens?|men's)\b",
    re.I,
)


class StopScrape(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or "")).replace("\xa0", " ")).strip()


def strip_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</\s*(p|li|div)\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return norm(text)


def request_text(url: str, referer: str = "") -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=45) as response:
            status = getattr(response, "status", 200)
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.code in {401, 403, 408, 409, 429, 503}:
            raise StopScrape(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
        raise
    except URLError as exc:
        raise StopScrape(f"network_error: {url}: {exc}") from exc
    if status in {401, 403, 408, 409, 429, 503}:
        raise StopScrape(f"blocked_or_rate_limited_http_{status}: {url}")
    lower = body.lower()
    if any(marker in lower for marker in BLOCK_MARKERS):
        raise StopScrape(f"blocked_or_challenge_marker: {url}")
    return body


def extract_window_json(text: str, name: str) -> Optional[Dict[str, object]]:
    match = re.search(rf"window\.{re.escape(name)}\s*=\s*", text)
    if not match:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[match.end() :])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def category_url(page: int) -> str:
    return WOMENS_CATEGORY_URL if page == 1 else f"{WOMENS_CATEGORY_URL}?p={page}"


def discover_product_urls(limit_pages: int = 0) -> Tuple[List[str], Dict[str, object]]:
    urls: List[str] = []
    first_payload: Dict[str, object] = {}
    total_pages = 1
    for page in range(1, 10_000):
        if limit_pages and page > limit_pages:
            break
        text = request_text(category_url(page), referer=WOMENS_CATEGORY_URL)
        payload = extract_window_json(text, "category")
        if not payload:
            raise StopScrape(f"missing_category_json: {category_url(page)}")
        if page == 1:
            first_payload = payload
            total_pages = int(payload.get("totalpages") or 1)
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            style_colour = item.get("stylecolour") or {}
            if not isinstance(style_colour, dict):
                continue
            url = norm(style_colour.get("url"))
            if not url and style_colour.get("urlkey"):
                url = f"/p/{style_colour.get('urlkey')}"
            if url:
                urls.append(urljoin(SITE_ROOT, url))
        print(f"[category {page}/{total_pages}] products={len(urls)}", flush=True)
        if page >= total_pages:
            break
    return sorted(dict.fromkeys(urls)), first_payload


def image_items(style_colour: Dict[str, object]) -> List[Dict[str, object]]:
    images = style_colour.get("images") or {}
    found: List[Dict[str, object]] = []
    if isinstance(images, dict):
        for group in ["main", "alt", "swatch"]:
            values = images.get(group) or []
            if isinstance(values, list):
                found.extend(item for item in values if isinstance(item, dict))
    primary = style_colour.get("primaryimage")
    if isinstance(primary, dict):
        found.insert(0, primary)
    deduped: List[Dict[str, object]] = []
    seen = set()
    for item in found:
        src = norm(item.get("src"))
        if not src or src in seen:
            continue
        seen.add(src)
        deduped.append(item)
    return deduped


def available_sizes(style_colour: Dict[str, object]) -> str:
    values: List[str] = []
    for variant in style_colour.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        size = norm(variant.get("size"))
        if not size:
            continue
        status = norm(variant.get("status"))
        label = f"{size} ({status})" if status else size
        values.append(label)
    return ", ".join(dict.fromkeys(values))


def review_size(review: Dict[str, object]) -> str:
    for key in ["sizepurchased", "sizePurchased", "sizeworn", "sizeWorn", "size"]:
        value = norm(review.get(key))
        if value:
            return value
    return ""


def review_comment(review: Dict[str, object], fitsizes: Dict[str, object], available_size_text: str) -> str:
    parts = [norm(review.get("title")), norm(review.get("comment") or review.get("review"))]
    fit = norm(review.get("fit"))
    if fit:
        parts.append(f"Fit: {norm(fitsizes.get(fit) or fit)}")
    if review.get("recommend") not in {None, ""}:
        parts.append(f"Recommended: {review.get('recommend')}")
    size_purchased = norm(review.get("sizepurchased") or review.get("sizePurchased"))
    size_worn = norm(review.get("sizeworn") or review.get("sizeWorn"))
    if size_purchased:
        parts.append(f"Size purchased: {size_purchased}")
    if size_worn:
        parts.append(f"Size worn: {size_worn}")
    if available_size_text:
        parts.append(f"Available sizes: {available_size_text}")
    return norm(" ".join(part for part in parts if part))


def classify_product(product: Dict[str, object], product_url: str) -> Tuple[bool, str, str]:
    value = " ".join(
        norm(part)
        for part in [
            product.get("description"),
            product.get("prodgroup"),
            product.get("category"),
            product.get("department"),
            product.get("sizetable"),
            product_url,
        ]
    )
    if OUT_OF_SCOPE_RE.search(value):
        return False, "out_of_scope_footwear_accessory_non_womens_or_non_apparel", ""
    if not APPAREL_RE.search(value):
        return False, "out_of_scope_non_apparel", ""
    lower = value.lower()
    for token, clothing_type in [
        ("jean", "jeans"),
        ("track pant", "pants"),
        ("pant", "pants"),
        ("legging", "leggings"),
        ("short", "shorts"),
        ("skirt", "skirt"),
        ("dress", "dress"),
        ("jacket", "jacket"),
        ("hoodie", "top"),
        ("sweater", "top"),
        ("pullover", "top"),
        ("crew", "top"),
        ("tee", "top"),
        ("t-shirt", "top"),
        ("shirt", "top"),
        ("singlet", "top"),
        ("tank", "top"),
        ("top", "top"),
        ("vest", "top"),
    ]:
        if token in lower:
            return True, "", clothing_type
    return True, "", ""


def product_category(product: Dict[str, object], style_colour: Dict[str, object]) -> str:
    attrs = style_colour.get("attributes") or {}
    if isinstance(attrs, dict):
        category = norm(attrs.get("Web-Category") or attrs.get("category") or attrs.get("Category"))
        if category:
            return category
    breadcrumbs = product.get("breadcrumbs") or []
    if isinstance(breadcrumbs, list):
        labels = [norm(item.get("label")) for item in breadcrumbs if isinstance(item, dict) and item.get("label")]
        if labels:
            return " > ".join(labels)
    return norm(product.get("prodgroup") or product.get("category"))


def build_row(
    product: Dict[str, object],
    product_url: str,
    style_colour: Dict[str, object],
    image: Dict[str, object],
    fetched_at: str,
    clothing_type: str,
    review: Optional[Dict[str, object]] = None,
) -> Dict[str, str]:
    product_id = norm(product.get("productid"))
    style_colour_id = norm(style_colour.get("stylecolourid"))
    image_name = norm(image.get("name"))
    image_src = norm(image.get("src"))
    available_size_text = available_sizes(style_colour)
    review = review or {}
    review_id = norm(review.get("reviewid") or review.get("id") or review.get("submitted") or "")
    row_id_parts = ["redrat", product_id, style_colour_id.replace("|", "-"), re.sub(r"[^a-z0-9]+", "-", image_name.lower()).strip("-")]
    if review_id:
        row_id_parts.append(re.sub(r"[^a-zA-Z0-9]+", "-", review_id).strip("-"))
    row = {header: "" for header in INTAKE_HEADERS}
    comment = review_comment(review, product.get("fitsizes") or {}, available_size_text) if review else (
        f"Catalog product image. Available sizes: {available_size_text}" if available_size_text else "Catalog product image."
    )
    row.update(
        {
            "created_at_display": fetched_at,
            "id": "-".join(part for part in row_id_parts if part),
            "original_url_display": image_src,
            "image_source_type": "catalog_model_image",
            "image_source_detail": "public Red Rat product/catalog image; native Red Rat reviews expose text and fit fields but no public review-photo field",
            "product_page_url_display": product_url,
            "user_comment": comment,
            "date_review_submitted_raw": norm(review.get("submitted")),
            "review_date": norm(review.get("submitted"))[:10],
            "source_site_display": RETAILER,
            "status_code": "200",
            "content_type": "text/html",
            "fetched_at": fetched_at,
            "updated_at": fetched_at,
            "brand": norm(product.get("label")),
            "search_fts": norm(" ".join([norm(product.get("description")), strip_text(product.get("extdescription")), comment, available_size_text])),
            "clothing_type_id": clothing_type,
            "reviewer_name_raw": norm(review.get("name")),
            "color_canonical": norm(style_colour.get("analysiscolour")).lower(),
            "color_display": norm(style_colour.get("colour")),
            "size_display": review_size(review),
            "product_title_raw": norm(product.get("description")),
            "product_description_raw": strip_text(product.get("extdescription")),
            "product_detail_raw": f"Image: {image_name}; available sizes: {available_size_text}",
            "product_category_raw": product_category(product, style_colour),
            "product_variant_raw": norm(style_colour.get("colour")),
        }
    )
    return row


def process_product(product_url: str, fetched_at: str, max_images_per_product: int = 0) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    text = request_text(product_url, referer=WOMENS_CATEGORY_URL)
    product = extract_window_json(text, "product")
    if not product:
        return [], {"product_url": product_url, "rows": 0, "skipped_from_output": True, "skip_reason": "missing_product_json"}
    in_scope, skip_reason, clothing_type = classify_product(product, product_url)
    if not in_scope:
        return [], {
            "product_url": product_url,
            "product_id": product.get("productid"),
            "product_title": product.get("description"),
            "rows": 0,
            "skipped_from_output": True,
            "skip_reason": skip_reason,
        }
    rows: List[Dict[str, str]] = []
    style_colours = product.get("stylecolours") or {}
    reviews = (product.get("reviews") or {}).get("reviews") or []
    native_reviews_with_photos = 0
    images_seen = 0
    if isinstance(style_colours, dict):
        for style_colour in style_colours.values():
            if not isinstance(style_colour, dict):
                continue
            images = image_items(style_colour)
            if max_images_per_product:
                images = images[:max_images_per_product]
            images_seen += len(images)
            if reviews:
                primary = images[:1]
                for image in primary:
                    for review in reviews:
                        if isinstance(review, dict):
                            rows.append(build_row(product, product_url, style_colour, image, fetched_at, clothing_type, review))
            else:
                for image in images:
                    rows.append(build_row(product, product_url, style_colour, image, fetched_at, clothing_type))
    return rows, {
        "product_url": product_url,
        "product_id": product.get("productid"),
        "product_title": product.get("description"),
        "native_reviews_found": len(reviews) if isinstance(reviews, list) else 0,
        "native_reviews_with_photos": native_reviews_with_photos,
        "catalog_images_found": images_seen,
        "rows": len(rows),
        "skipped_from_output": not rows,
        "skip_reason": "" if rows else "no_catalog_images_or_reviews",
    }


def dedupe_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        key = (row.get("id"), row.get("original_url_display"), row.get("product_page_url_display"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def write_csv(rows: Sequence[Dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INTAKE_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in INTAKE_HEADERS})


def metrics(rows: Sequence[Dict[str, str]]) -> Dict[str, int]:
    measurement_fields = [
        "height_in_display",
        "weight_display_display",
        "weight_lbs_display",
        "bust_in_number_display",
        "hips_in_display",
        "waist_in",
        "inseam_inches_display",
    ]
    return {
        "rows_written": len(rows),
        "distinct_reviews": len({row.get("id", "") for row in rows if row.get("reviewer_name_raw") or row.get("date_review_submitted_raw")}),
        "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
        "rows_with_distinct_product_url": len({row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}),
        "rows_with_any_measurement": sum(1 for row in rows if any(row.get(field) for field in measurement_fields)),
        "rows_with_customer_image": sum(1 for row in rows if row.get("image_source_type") == "customer_review_image"),
        "rows_with_catalog_model_image": sum(1 for row in rows if row.get("image_source_type") == "catalog_model_image"),
        "rows_with_customer_ordered_size": sum(1 for row in rows if row.get("size_display")),
        "rows_supabase_qualified": sum(
            1
            for row in rows
            if row.get("original_url_display")
            and row.get("product_page_url_display")
            and row.get("size_display")
            and any(row.get(field) for field in measurement_fields)
        ),
    }


def run(args: argparse.Namespace) -> Dict[str, object]:
    started_at = utc_now()
    urls, category_payload = discover_product_urls(limit_pages=args.limit_category_pages)
    if args.limit_products:
        urls = urls[: args.limit_products]
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    stopped_early = False
    for index, url in enumerate(urls, start=1):
        try:
            product_rows, summary = process_product(url, started_at, max_images_per_product=args.max_images_per_product)
        except StopScrape as exc:
            errors.append(str(exc))
            stopped_early = True
            break
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
            product_rows = []
            summary = {"product_url": url, "rows": 0, "skipped_from_output": True, "skip_reason": "fetch_or_parse_error"}
        rows.extend(product_rows)
        product_summaries.append(summary)
        print(f"[product {index}/{len(urls)}] rows={len(product_rows)} total={len(rows)} {url}", flush=True)
        if args.request_delay_seconds:
            time.sleep(args.request_delay_seconds)
    rows = dedupe_rows(rows)
    write_csv(rows)
    finished_at = utc_now()
    summary_payload: Dict[str, object] = {
        "site": "redrat.co.nz",
        "retailer": RETAILER,
        "adapter": "redrat_native_category_pdp_catalog_images",
        "triage_source": "sovrn_commerce_scrape_triage_candidates.csv",
        "triage_status": "first_pass_scrape_candidate",
        "commercial_terms": "CPA+CPC; payout fields not populated",
        "review_platform_provider": "native Red Rat first-party review component",
        "photo_review_status": "unknown_sample_too_small; no public review-photo field found in sampled/native review implementation",
        "product_sources": {"womens_category_pages": category_payload.get("totalpages"), "womens_category_totalitems": category_payload.get("totalitems")},
        "products_discovered": len(urls),
        "products_scanned": len(product_summaries),
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "native_reviews_found": sum(int(item.get("native_reviews_found") or 0) for item in product_summaries),
        "native_reviews_with_photos": sum(int(item.get("native_reviews_with_photos") or 0) for item in product_summaries),
        "catalog_images_found": sum(int(item.get("catalog_images_found") or 0) for item in product_summaries),
        "coverage_exhaustive": not stopped_early and not args.limit_products and not args.limit_category_pages and not errors,
        "access_policy": "public Red Rat womens category and PDP pages only; stop on 429/captcha/WAF/auth behavior",
        "product_summaries": product_summaries,
        "errors": errors,
        "output_csv": str(OUTPUT_CSV),
        "started_at": started_at,
        "finished_at": finished_at,
    }
    summary_payload.update(metrics(rows))
    SUMMARY_JSON.write_text(json.dumps(summary_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary_payload


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Red Rat public women's category/PDP catalog imagery and native review fit data.")
    parser.add_argument("--limit-category-pages", type=int, default=0)
    parser.add_argument("--limit-products", type=int, default=0)
    parser.add_argument("--max-images-per-product", type=int, default=0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.15)
    args = parser.parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
