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

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.environ.get("FWM_DATA_DIR", ROOT.parent / "FWM_Data"))
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / "mbmswim_com"
OUTPUT_CSV = OUTPUT_DIR / "mbmswim_com_reviews_matching_intake_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "mbmswim_com_reviews_matching_intake_schema_summary.json"

SITE_ROOT = "https://mbmswim.com"
SOURCE_SITE = f"{SITE_ROOT}/"
PRODUCTS_JSON_URL = f"{SITE_ROOT}/products.json"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
LOOX_CLIENT_ID = "VJWi6coNCD"
LOOX_HASH = "1777507737217"
LOOX_ROOT = f"https://loox.io/widget/{LOOX_CLIENT_ID}/reviews"
BRAND = "MBM Swim"
PRODUCTS_PER_PAGE = 250
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
BRA_RE = re.compile(r"\b((?:2[8-9]|3[0-9]|4[0-8])\s*(?:aa|a|b|c|d|dd|ddd|e|f|g|h|i|j|k))\b", re.I)
ITEM_TYPE_RE = re.compile(r"\bItem type:\s*(.+)$", re.I | re.S)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm(value: object) -> str:
    return WS_RE.sub(" ", str(value or "")).strip()


def strip_tags(value: object) -> str:
    return norm(html.unescape(TAG_RE.sub(" ", str(value or ""))))


def fetch_text(url: str, referer: Optional[str] = None, retries: int = 5) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/json,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": referer or SOURCE_SITE,
            },
        )
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
    return json.loads(fetch_text(query_url, referer=referer, retries=retries))


def product_url_for(product: Dict[str, object]) -> str:
    handle = norm(product.get("handle"))
    return f"{SITE_ROOT}/products/{quote(handle, safe='/-._~')}" if handle else ""


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
    sitemap_urls = [html.unescape(url) for url in re.findall(r"<loc>(https://mbmswim\.com/[^<]*sitemap_products_[^<]+)</loc>", sitemap_index)]
    sitemap_product_urls: List[str] = []
    for sitemap_url in sitemap_urls:
        text = fetch_text(sitemap_url)
        urls = sorted(set(re.findall(r"https://mbmswim\.com/products/[^<\s\"']+", text)))
        sources.append({"source": "product_sitemap", "url": sitemap_url, "count": len(urls)})
        sitemap_product_urls.extend(urls)

    by_url: Dict[str, Dict[str, object]] = {product_url_for(product): product for product in products if product_url_for(product)}
    missing = [url for url in sorted(set(sitemap_product_urls)) if url not in by_url]
    for url in missing:
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        by_url[url] = {"id": "", "handle": handle, "title": handle.replace("-", " ").title(), "product_type": "", "body_html": "", "variants": []}
    sources.append({"source": "reconciled_products", "count": len(by_url), "sitemap_missing_from_products_json": len(missing)})
    products_out = list(by_url.values())
    if limit_products:
        products_out = products_out[:limit_products]
    return products_out, sources


def output_skip_reason(product: Dict[str, object]) -> str:
    value = f"{product.get('title') or ''} {product.get('product_type') or ''}".lower()
    if "shipping protection" in value or "insurance" in value:
        return "out_of_scope_shipping_protection"
    return ""


def canonical_name(value: object) -> str:
    text = norm(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return norm(text)


def product_lookup(products: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    out: Dict[str, Dict[str, object]] = {}
    for product in products:
        title = norm(product.get("title"))
        if title:
            out[canonical_name(title)] = product
            out[canonical_name(title.replace("MBM Swim", ""))] = product
    return out


def loox_url(product_id: object) -> str:
    return f"{LOOX_ROOT}/{product_id}?h={LOOX_HASH}"


def next_page_url(soup: BeautifulSoup, current_url: str) -> str:
    button = soup.select_one("#loadMore")
    if not button:
        return ""
    data_url = html.unescape(norm(button.get("data-url")))
    if not data_url:
        return ""
    path = current_url.split("?", 1)[0]
    return f"{path}?{data_url}"


def review_id_for(card) -> str:
    media = card.select_one("[data-testid$='-media']")
    testid = norm(media.get("data-testid") if media else "")
    match = re.search(r"review-([^-]+)-media", testid)
    if match:
        return match.group(1)
    any_testid = card.select_one("[data-testid^='review-']")
    testid = norm(any_testid.get("data-testid") if any_testid else "")
    match = re.search(r"review-([^-]+)-", testid)
    return match.group(1) if match else ""


def parse_card(card, current_product: Dict[str, object], lookup: Dict[str, Dict[str, object]]) -> List[Dict[str, object]]:
    image_urls: List[str] = []
    image_alts: List[str] = []
    for img in card.select("img"):
        src = norm(img.get("src"))
        if not src or src.startswith("data:") or "images.loox.io" not in src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        image_urls.append(src)
        image_alts.append(norm(img.get("alt")))
    image_urls = list(dict.fromkeys(image_urls))
    if not image_urls:
        return []

    text_el = card.select_one("[data-testid$='-text']")
    text = norm(text_el.get_text(" ", strip=True) if text_el else "")
    all_text = norm(card.get_text(" ", strip=True))
    item_type = ""
    match = ITEM_TYPE_RE.search(all_text)
    if match:
        item_type = norm(match.group(1))
        text = norm(text.replace(f"Item type: {item_type}", ""))
    parts = [part.strip() for part in item_type.split("/") if part.strip()]
    color = parts[0] if parts else ""
    size = parts[1] if len(parts) >= 2 else ""
    item_name = parts[-1] if parts else ""
    product = lookup.get(canonical_name(item_name)) or current_product

    title_el = card.select_one("[data-testid$='-title']")
    reviewer = ""
    if title_el:
        reviewer = norm(title_el.get_text(" ", strip=True)).lstrip("+0123456789 ").strip()
    date_el = card.select_one("[data-testid$='-date']")
    review_date = norm(date_el.get_text(" ", strip=True) if date_el else "")
    review_id = review_id_for(card)
    return [
        {
            "review_id": review_id,
            "image_url": image_url,
            "image_index": idx,
            "reviewer": reviewer,
            "review_date": review_date,
            "text": text,
            "all_text": all_text,
            "product": product,
            "item_type": item_type,
            "color": color,
            "size": size,
            "image_alt": image_alts[idx - 1] if idx - 1 < len(image_alts) else "",
        }
        for idx, image_url in enumerate(image_urls, start=1)
    ]


def fetch_product_reviews(product: Dict[str, object], lookup: Dict[str, Dict[str, object]], limit_pages: Optional[int] = None) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    product_url = product_url_for(product)
    meta: Dict[str, object] = {
        "product_url": product_url,
        "product_title": product.get("title"),
        "adapter_used": "loox_product_iframe",
        "review_pages_scanned": 0,
        "review_count_hint": 0,
        "matching_review_images": 0,
        "errors": [],
    }
    product_id = product.get("id")
    if not product_id:
        meta["errors"].append("missing_shopify_product_id")
        return [], meta

    url = loox_url(product_id)
    rows: List[Dict[str, object]] = []
    while url:
        if limit_pages is not None and int(meta["review_pages_scanned"]) >= limit_pages:
            break
        try:
            text = fetch_text(url, referer=product_url)
        except Exception as exc:  # noqa: BLE001
            meta["errors"].append(str(exc))
            break
        soup = BeautifulSoup(text, "html.parser")
        if not meta["review_count_hint"]:
            button = soup.select_one("#loadMore")
            data_url = html.unescape(norm(button.get("data-url") if button else ""))
            match = re.search(r"(?:^|&)total=(\d+)", data_url)
            if match:
                meta["review_count_hint"] = int(match.group(1))
        meta["review_pages_scanned"] = int(meta["review_pages_scanned"]) + 1
        for card in soup.select(".grid-item-wrap"):
            rows.extend(parse_card(card, product, lookup))
        url = next_page_url(soup, url)
    if not meta["review_count_hint"]:
        meta["review_count_hint"] = len({norm(row.get("review_id")) for row in rows if norm(row.get("review_id"))})
    meta["matching_review_images"] = len(rows)
    return rows, meta


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
    match = HEIGHT_RE.search(text)
    if not match:
        return "", None
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    if 4 <= feet <= 7 and 0 <= inches <= 11:
        return norm(match.group(0)), feet * 12 + inches
    return "", None


def parse_age(text: str) -> Tuple[str, str]:
    match = AGE_RE.search(text)
    return (norm(match.group(0)), match.group(1) or match.group(2) or "") if match else ("", "")


def parse_bra(text: str) -> Tuple[str, str]:
    match = BRA_RE.search(text)
    if not match:
        return "", ""
    compact = re.sub(r"\s+", "", match.group(1)).upper()
    band = re.match(r"(\d{2})", compact)
    cup = re.search(r"[A-Z]+$", compact)
    return (band.group(1) if band else "", cup.group(0) if cup else "")


def classify(product: Dict[str, object]) -> str:
    value = f"{product.get('title') or ''} {product.get('product_type') or ''}".lower()
    if "bikini" in value or "swim" in value or "one piece" in value:
        return "swimwear"
    if "dress" in value:
        return "dress"
    if "skirt" in value:
        return "skirt"
    if "pant" in value:
        return "pants"
    if "blouse" in value or "top" in value:
        return "top"
    return "womens_clothing"


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


def row_for(item: Dict[str, object]) -> Dict[str, str]:
    product = item["product"] if isinstance(item.get("product"), dict) else {}
    text = norm(item.get("text"))
    combined = norm(f"{text} {item.get('item_type') or ''}")
    height_raw, height_in = parse_height(combined)
    weight_raw, weight = parse_num(WEIGHT_RE, combined, 500)
    waist_raw, waist = parse_num(WAIST_RE, combined, 80)
    hips_raw, hips = parse_num(HIPS_RE, combined, 90)
    inseam_raw, inseam = parse_num(INSEAM_RE, combined, 50)
    age_raw, age = parse_age(combined)
    bust, cup = parse_bra(combined)
    fetched = now_iso()
    review_id = norm(item.get("review_id")) or f"{product.get('id')}-{item.get('image_index')}"
    product_url = product_url_for(product)
    return {
        "created_at_display": fetched,
        "id": f"{review_id}-{item.get('image_index')}",
        "original_url_display": norm(item.get("image_url")),
        "product_page_url_display": product_url,
        "monetized_product_url_display": product_url,
        "height_raw": height_raw,
        "weight_raw": weight_raw,
        "user_comment": text,
        "date_review_submitted_raw": norm(item.get("review_date")),
        "height_in_display": maybe_num(height_in),
        "review_date": norm(item.get("review_date")),
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
        "search_fts": combined,
        "weight_display_display": maybe_num(weight),
        "weight_raw_needs_correction": "",
        "clothing_type_id": classify(product),
        "reviewer_profile_url": "",
        "reviewer_name_raw": norm(item.get("reviewer")),
        "inseam_inches_display": maybe_num(inseam),
        "color_canonical": canonical_name(item.get("color")),
        "color_display": norm(item.get("color")),
        "size_display": norm(item.get("size")),
        "bust_in_number_display": bust,
        "cupsize_display": cup,
        "weight_lbs_display": maybe_num(weight),
        "weight_lbs_raw_issue": "",
        "product_title_raw": norm(product.get("title")),
        "product_subtitle_raw": norm(item.get("image_alt")),
        "product_description_raw": strip_tags(product.get("body_html")),
        "product_detail_raw": variant_detail(product),
        "product_category_raw": norm(product.get("product_type")),
        "product_variant_raw": norm(item.get("item_type")),
    }


def is_measurement_row(row: Dict[str, str]) -> bool:
    return any(norm(row.get(field)) for field in ["height_in_display", "weight_lbs_display", "bust_in_number_display", "hips_in_display", "waist_in", "inseam_inches_display"])


def main(argv: List[str]) -> int:
    limit_products: Optional[int] = None
    limit_pages: Optional[int] = None
    if "--limit-products" in argv:
        limit_products = int(argv[argv.index("--limit-products") + 1])
    if "--limit-pages-per-product" in argv:
        limit_pages = int(argv[argv.index("--limit-pages-per-product") + 1])

    started = now_iso()
    products, product_sources = fetch_products(limit_products=limit_products)
    lookup = product_lookup(products)
    print(f"Discovered {len(products)} products")
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    total_pages = 0
    total_hint = 0

    for idx, product in enumerate(products, start=1):
        skip_reason = output_skip_reason(product)
        items: List[Dict[str, object]] = []
        meta: Dict[str, object] = {
            "review_pages_scanned": 0,
            "review_count_hint": 0,
            "matching_review_images": 0,
            "errors": [],
            "adapter_used": "loox_product_iframe",
        }
        if not skip_reason:
            items, meta = fetch_product_reviews(product, lookup, limit_pages=limit_pages)
        total_pages += int(meta.get("review_pages_scanned") or 0)
        total_hint += int(meta.get("review_count_hint") or 0)
        product_rows = 0
        if not skip_reason:
            for item in items:
                rows.append(row_for(item))
                product_rows += 1
        product_summaries.append({
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
        })
        skip_note = f" skipped={skip_reason}" if skip_reason else ""
        print(f"[{idx}/{len(products)}] {product.get('title')} reviews={meta.get('review_count_hint')} pages={meta.get('review_pages_scanned')} rows={product_rows}{skip_note}")

    seen = set()
    deduped: List[Dict[str, str]] = []
    for row in rows:
        key = (row["id"], row["original_url_display"], row["product_page_url_display"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

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
        "site": "mbmswim.com",
        "adapter": "loox_product_iframe",
        "loox_client_id": LOOX_CLIENT_ID,
        "product_sources": product_sources,
        "products_discovered": len(products),
        "products_scanned": len(products),
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
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
