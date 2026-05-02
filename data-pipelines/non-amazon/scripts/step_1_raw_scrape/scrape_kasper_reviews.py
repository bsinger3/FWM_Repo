#!/usr/bin/env python3
from __future__ import annotations

import csv
from datetime import datetime, timezone
import html
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "kasper_com"
OUTPUT_CSV = OUTPUT_DIR / "kasper_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "kasper_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://www.kasper.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
JUNIP_STORE_KEY = "3oq4pZLqF9RW9GN1JZKKkDPE"
JUNIP_API_ROOT = "https://api.juniphq.com/en"
BRAND = "Kasper"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 50
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36"

HEADERS = [
    "created_at_display", "id", "original_url_display", "product_page_url_display", "monetized_product_url_display",
    "height_raw", "weight_raw", "user_comment", "date_review_submitted_raw", "height_in_display", "review_date",
    "source_site_display", "status_code", "content_type", "bytes", "width", "height", "hash_md5", "fetched_at",
    "updated_at", "brand", "waist_raw_display", "hips_raw", "age_raw", "waist_in", "hips_in_display",
    "age_years_display", "search_fts", "weight_display_display", "weight_raw_needs_correction", "clothing_type_id",
    "reviewer_profile_url", "reviewer_name_raw", "inseam_inches_display", "color_canonical", "color_display",
    "size_display", "bust_in_number_display", "cupsize_display", "weight_lbs_display", "weight_lbs_raw_issue",
    "product_title_raw", "product_subtitle_raw", "product_description_raw", "product_detail_raw",
    "product_category_raw", "product_variant_raw",
]

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
HEIGHT_RE = re.compile(r"\b([4-6])\s*(?:ft|feet|foot|['\u2019])\s*(\d{1,2})?\s*(?:in|inches|[\"\u201d])?", re.I)
WEIGHT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?|#)\b", re.I)
WAIST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b", re.I)
HIPS_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*inseam\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
SIZE_TOKEN_RE = re.compile(r"^(?:00|0|[0-9]{1,2}|[0-9]{1,2}w|xxs|xs|s|m|l|xl|xxl|2xl|3xl|ps|pm|pl|pxl|[0-9]{1,2}p)$", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(text: object) -> str:
    return WS_RE.sub(" ", str(text or "")).strip()


def strip_tags(value: object) -> str:
    text = re.sub(r"</p\s*>|<br\s*/?>", " ", str(value or ""), flags=re.I)
    return norm(html.unescape(TAG_RE.sub(" ", text)))


def fetch_text(url: str, retries: int = 5) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        try:
            with urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", "replace")
        except (HTTPError, URLError) as exc:
            last_error = exc
            if isinstance(exc, HTTPError) and exc.code not in {429, 500, 502, 503, 504}:
                raise
        time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"Failed text request for {url}: {last_error}")


def fetch_json(url: str, params: Optional[Dict[str, object]] = None, referer: Optional[str] = None, retries: int = 5) -> Dict[str, object]:
    query_url = f"{url}?{urlencode(params)}" if params else url
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": SITE_ROOT,
            "Referer": referer or SOURCE_SITE,
        }
        if "juniphq.com" in url:
            headers["Junip-Store-Key"] = JUNIP_STORE_KEY
        req = Request(query_url, headers=headers)
        try:
            with urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {400, 429, 500, 502, 503, 504}:
                raise
        except (URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"Failed JSON request for {query_url}: {last_error}")


def product_url_for(product: Dict[str, object]) -> str:
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


def canonicalize_product_url(url: str) -> str:
    return re.sub(r"^https://(?:www\.)?kasper\.com", SITE_ROOT, url).split("?", 1)[0].rstrip("/")


def fetch_products(limit_products: Optional[int] = None) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    products: List[Dict[str, object]] = []
    sources: List[Dict[str, object]] = []
    page = 1
    while True:
        payload = fetch_json(PRODUCTS_JSON_URL, {"limit": PRODUCTS_PER_PAGE, "page": page})
        page_products = [item for item in payload.get("products", []) if isinstance(item, dict)]
        sources.append({"source": "products.json", "page": page, "count": len(page_products)})
        if not page_products:
            break
        products.extend(page_products)
        if len(page_products) < PRODUCTS_PER_PAGE or (limit_products and len(products) >= limit_products):
            break
        page += 1

    sitemap_index = fetch_text(SITEMAP_URL)
    sitemap_urls = [html.unescape(url) for url in re.findall(r"<loc>(https://www\.kasper\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index)]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url)
        urls = sorted(set(re.findall(r"https://www\.kasper\.com/products/[^<\s\"']+", text)))
        urls = [canonicalize_product_url(html.unescape(url)) for url in urls]
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        sitemap_product_urls.extend(urls)

    by_url: Dict[str, Dict[str, object]] = {canonicalize_product_url(product_url_for(product)): product for product in products if product_url_for(product)}
    missing = [url for url in sorted(set(sitemap_product_urls)) if url not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {"id": "", "handle": handle, "title": handle.replace("-", " ").title(), "product_type": "", "body_html": "", "variants": [], "tags": []}
    sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)})
    products_out = list(by_url.values())
    if limit_products:
        products_out = products_out[:limit_products]
    return products_out, sources


def junip_reviews_url(product_id: object) -> str:
    return f"{JUNIP_API_ROOT}/v2/products/remote/{product_id}/reviews"


def review_attachments(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    attachments = review.get("attachments")
    if not isinstance(attachments, list):
        return urls
    for item in attachments:
        if not isinstance(item, dict):
            continue
        if norm(item.get("type")).lower() not in {"", "photo_review_attachment"}:
            continue
        url = norm(item.get("content_url") or item.get("preview_url"))
        if url and url not in urls:
            urls.append(url)
    return urls


def maybe_num(value: Optional[float]) -> str:
    if value is None:
        return ""
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def parse_num(pattern: re.Pattern[str], text: str, max_value: Optional[float] = None) -> Tuple[str, Optional[float]]:
    match = pattern.search(text)
    if not match:
        return "", None
    value = float(match.group(1))
    if max_value is not None and value > max_value:
        return "", None
    return norm(match.group(0)), value


def parse_height(text: str) -> Tuple[str, Optional[float]]:
    cleaned = text.replace("\u2018", "'").replace("\u2019", "'").replace("\u201d", '"')
    match = HEIGHT_RE.search(cleaned)
    if not match:
        bare = re.fullmatch(r"\s*([4-6])\s*\??\s*", cleaned)
        if bare:
            feet = int(bare.group(1))
            return cleaned.strip(), feet * 12
        return "", None
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    if 4 <= feet <= 7 and 0 <= inches <= 11:
        return norm(match.group(0)), feet * 12 + inches
    return "", None


def parse_age(text: str) -> Tuple[str, str]:
    match = AGE_RE.search(text)
    return (norm(match.group(0)), match.group(1) or match.group(2) or "") if match else ("", "")


def survey_text(review: Dict[str, object], name_fragment: str) -> str:
    answers = review.get("survey_answers")
    if not isinstance(answers, list):
        return ""
    for answer in answers:
        if isinstance(answer, dict) and name_fragment.lower() in norm(answer.get("name")).lower():
            return norm(answer.get("value"))
    return ""


def target_variant_parts(review: Dict[str, object]) -> Tuple[str, str, str]:
    target = norm(review.get("target_title"))
    if " - " not in target:
        return "", "", ""
    variant = target.rsplit(" - ", 1)[-1]
    parts = [norm(part) for part in variant.split("/") if norm(part)]
    color = parts[0] if parts else ""
    size = parts[-1] if len(parts) >= 2 and SIZE_TOKEN_RE.fullmatch(parts[-1]) else ""
    return variant, color, size


def variant_detail(product: Dict[str, object]) -> str:
    vals: List[str] = []
    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants[:250]:
            if isinstance(variant, dict):
                title = norm(variant.get("title"))
                if title and title.lower() != "default title" and title not in vals:
                    vals.append(title)
    return " | ".join(vals)


def classify(product: Dict[str, object], review: Optional[Dict[str, object]] = None) -> str:
    review = review or {}
    value = f"{product.get('title') or ''} {product.get('product_type') or ''} {review.get('target_title') or ''}".lower()
    if "dress" in value or "sheath" in value or "fit-and-flare" in value:
        return "dress"
    if "jacket" in value or "blazer" in value:
        return "jacket"
    if "pant" in value or "trouser" in value or "legging" in value:
        return "pants"
    if "skirt" in value:
        return "skirt"
    if "top" in value or "blouse" in value or "shirt" in value or "shell" in value:
        return "top"
    if "suit" in value:
        return "suit"
    return norm(product.get("product_type")).lower() or "womens_clothing"


def output_skip_reason(product: Dict[str, object]) -> str:
    title = norm(product.get("title")).lower()
    product_type = norm(product.get("product_type")).lower()
    if "gift card" in title or "egift card" in title:
        return "out_of_scope_gift_card"
    if product_type in {"accessories", "jewelry", "bags"}:
        return "out_of_scope_accessory"
    if any(term in title for term in ["handbag", " tote", "scarf", "necklace", "earring", "bracelet"]):
        return "out_of_scope_accessory"
    return ""


def fetch_product_reviews(product: Dict[str, object], limit_pages: Optional[int] = None) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    product_url = product_url_for(product)
    meta: Dict[str, object] = {
        "product_url": product_url,
        "product_title": product.get("title"),
        "adapter_used": "junip_product_level",
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "matching_review_images": 0,
        "errors": [],
    }
    product_id = product.get("id")
    if not product_id:
        meta["errors"].append("missing_shopify_product_id")
        return [], meta

    reviews: List[Dict[str, object]] = []
    seen = set()
    page_after = ""
    while True:
        if limit_pages is not None and int(meta["review_pages_scanned"]) >= limit_pages:
            break
        params: Dict[str, object] = {"page_size": REVIEWS_PER_PAGE, "sort_field": "created_at", "sort_order": "desc"}
        if page_after:
            params["page_after"] = page_after
        try:
            payload = fetch_json(junip_reviews_url(product_id), params=params, referer=product_url)
        except Exception as exc:  # noqa: BLE001
            meta["errors"].append(str(exc))
            break
        page_reviews = [item for item in payload.get("data", []) if isinstance(item, dict)]
        if not page_reviews:
            break
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"]) + 1
        for review in page_reviews:
            review_id = norm(review.get("id"))
            if review_id and review_id in seen:
                continue
            seen.add(review_id)
            reviews.append(review)
        page_after = norm((payload.get("meta") or {}).get("after") if isinstance(payload.get("meta"), dict) else "")
        if not page_after:
            break
    meta["review_count_hint"] = len(reviews)
    meta["matching_review_images"] = sum(len(review_attachments(review)) for review in reviews)
    return reviews, meta


def row_for(product: Dict[str, object], review: Dict[str, object], image_url: str, image_index: int, products_by_id: Dict[str, Dict[str, object]], products_by_handle: Dict[str, Dict[str, object]]) -> Dict[str, str]:
    review_product = review.get("product") if isinstance(review.get("product"), dict) else {}
    remote_id = norm(review_product.get("remote_id"))
    remote_handle = norm(review_product.get("remote_handle"))
    row_product = products_by_id.get(remote_id) or products_by_handle.get(remote_handle) or product
    product_url = product_url_for(row_product) or (f"{SITE_ROOT}/products/{quote(remote_handle, safe='/-._~')}" if remote_handle else product_url_for(product))
    variant_name, color_display, size_display = target_variant_parts(review)

    title = strip_tags(review.get("title"))
    body = strip_tags(review.get("body"))
    typical_size = survey_text(review, "typical size")
    height_survey = survey_text(review, "height")
    text = norm(" ".join(part for part in [title, body, f"Typical size: {typical_size}" if typical_size else "", f"Height: {height_survey}" if height_survey else "", f"Variant: {variant_name}" if variant_name else ""] if part))
    height_raw, height_in = parse_height(height_survey or text)
    weight_raw, weight = parse_num(WEIGHT_RE, text, 500)
    waist_raw, waist = parse_num(WAIST_RE, text, 80)
    hips_raw, hips = parse_num(HIPS_RE, text, 90)
    _inseam_raw, inseam = parse_num(INSEAM_RE, text, 50)
    age_raw, age = parse_age(text)
    review_id = norm(review.get("id")) or f"{product.get('id')}-{image_index}"
    fetched = now_iso()
    product_title = norm(review_product.get("title") or row_product.get("title") or product.get("title"))
    customer = review.get("customer") if isinstance(review.get("customer"), dict) else {}
    reviewer_name = norm(" ".join(part for part in [customer.get("first_name"), customer.get("last_name")] if part))
    return {
        "created_at_display": fetched,
        "id": f"{review_id}-{image_index}",
        "original_url_display": image_url,
        "product_page_url_display": canonicalize_product_url(product_url),
        "monetized_product_url_display": canonicalize_product_url(product_url),
        "height_raw": height_raw,
        "weight_raw": weight_raw,
        "user_comment": text,
        "date_review_submitted_raw": norm(review.get("created_at")),
        "height_in_display": maybe_num(height_in),
        "review_date": norm(review.get("created_at"))[:10],
        "source_site_display": SOURCE_SITE,
        "status_code": "",
        "content_type": "",
        "bytes": "",
        "width": "",
        "height": "",
        "hash_md5": "",
        "fetched_at": fetched,
        "updated_at": fetched,
        "brand": BRAND,
        "waist_raw_display": waist_raw,
        "hips_raw": hips_raw,
        "age_raw": age_raw,
        "waist_in": maybe_num(waist),
        "hips_in_display": maybe_num(hips),
        "age_years_display": age,
        "search_fts": norm(" ".join([BRAND, product_title, strip_tags(row_product.get("body_html")), text])),
        "weight_display_display": maybe_num(weight),
        "weight_raw_needs_correction": "",
        "clothing_type_id": classify(row_product, review),
        "reviewer_profile_url": "",
        "reviewer_name_raw": reviewer_name,
        "inseam_inches_display": maybe_num(inseam),
        "color_canonical": color_display.lower(),
        "color_display": color_display,
        "size_display": size_display,
        "bust_in_number_display": "",
        "cupsize_display": "",
        "weight_lbs_display": maybe_num(weight),
        "weight_lbs_raw_issue": "",
        "product_title_raw": product_title,
        "product_subtitle_raw": title,
        "product_description_raw": strip_tags(row_product.get("body_html")),
        "product_detail_raw": variant_detail(row_product),
        "product_category_raw": norm(row_product.get("product_type")),
        "product_variant_raw": variant_name,
    }


def is_measurement_row(row: Dict[str, str]) -> bool:
    fields = ["height_in_display", "weight_lbs_display", "bust_in_number_display", "hips_in_display", "waist_in", "inseam_inches_display"]
    return any(norm(row.get(field)) for field in fields)


def dedupe_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        key = (row.get("id", "").rsplit("-", 1)[0], row.get("original_url_display", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def main(argv: List[str]) -> int:
    limit_products: Optional[int] = None
    limit_pages: Optional[int] = None
    if "--limit-products" in argv:
        limit_products = int(argv[argv.index("--limit-products") + 1])
    if "--limit-pages-per-product" in argv:
        limit_pages = int(argv[argv.index("--limit-pages-per-product") + 1])

    started = now_iso()
    products, product_sources = fetch_products(limit_products=limit_products)
    products_by_id = {norm(product.get("id")): product for product in products if norm(product.get("id"))}
    products_by_handle = {norm(product.get("handle")): product for product in products if norm(product.get("handle"))}
    print(f"Discovered {len(products)} products")
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    total_pages = 0
    total_hint = 0
    products_excluded = 0

    for idx, product in enumerate(products, start=1):
        reviews, meta = fetch_product_reviews(product, limit_pages=limit_pages)
        skip_reason = output_skip_reason(product)
        if skip_reason:
            products_excluded += 1
        total_pages += int(meta.get("review_pages_scanned") or 0)
        total_hint += int(meta.get("review_count_hint") or 0)
        product_rows = 0
        if not skip_reason:
            for review in reviews:
                for image_index, image_url in enumerate(review_attachments(review), start=1):
                    rows.append(row_for(product, review, image_url, image_index, products_by_id, products_by_handle))
                    product_rows += 1
        summary = {
            "product_index": idx,
            "product_id": product.get("id"),
            "product_title": product.get("title"),
            "product_url": product_url_for(product),
            "review_count_hint": meta.get("review_count_hint"),
            "review_pages_scanned": meta.get("review_pages_scanned"),
            "matching_review_images": meta.get("matching_review_images"),
            "rows": product_rows,
            "errors": meta.get("errors"),
            "adapter_used": meta.get("adapter_used"),
            "skipped_from_output": bool(skip_reason),
            "skip_reason": skip_reason,
        }
        product_summaries.append(summary)
        status = f" skipped={skip_reason}" if skip_reason else ""
        print(f"[{idx}/{len(products)}] {product.get('title')} reviews={summary['review_count_hint']} pages={summary['review_pages_scanned']} rows={product_rows}{status}", flush=True)

    deduped = dedupe_rows(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(deduped)

    rows_with_product_url = sum(1 for row in deduped if norm(row.get("product_page_url_display") or row.get("monetized_product_url_display")))
    rows_with_measurement = sum(1 for row in deduped if is_measurement_row(row))
    rows_with_image = sum(1 for row in deduped if norm(row.get("original_url_display")))
    rows_with_size = sum(1 for row in deduped if norm(row.get("size_display")) and norm(row.get("size_display")).lower() != "unknown")
    rows_supabase = sum(
        1
        for row in deduped
        if norm(row.get("original_url_display"))
        and norm(row.get("product_page_url_display") or row.get("monetized_product_url_display"))
        and is_measurement_row(row)
        and norm(row.get("size_display"))
    )
    summary = {
        "site": "kasper.com",
        "adapter": "junip_product_level",
        "junip_store_key": JUNIP_STORE_KEY,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "products_excluded_from_output": products_excluded,
        "exhaustive_review_paging": limit_pages is None,
        "review_pages_scanned": total_pages,
        "product_review_count_hint": total_hint,
        "rows_written": len(deduped),
        "distinct_reviews": len({row["id"].rsplit("-", 1)[0] for row in deduped}),
        "distinct_images": len({row["original_url_display"] for row in deduped}),
        "distinct_products": len({row["product_page_url_display"] for row in deduped}),
        "rows_with_distinct_product_url": len({row["product_page_url_display"] or row["monetized_product_url_display"] for row in deduped if row["product_page_url_display"] or row["monetized_product_url_display"]}),
        "rows_with_product_url": rows_with_product_url,
        "rows_with_any_measurement": rows_with_measurement,
        "rows_with_customer_image": rows_with_image,
        "rows_with_customer_ordered_size": rows_with_size,
        "rows_with_size": rows_with_size,
        "rows_supabase_qualified": rows_supabase,
        "output_csv": str(OUTPUT_CSV),
        "summary_json": str(SUMMARY_JSON),
        "started_at": started,
        "finished_at": now_iso(),
        "product_summaries": product_summaries,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(deduped)} rows to {OUTPUT_CSV}")
    print(f"Supabase-qualified rows: {rows_supabase}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
