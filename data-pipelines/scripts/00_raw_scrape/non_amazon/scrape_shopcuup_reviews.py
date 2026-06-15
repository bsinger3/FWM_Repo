#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = ROOT / "data-pipelines" / "non-amazon" / "data" / "step_1_raw_scraping_data" / "shopcuup"
OUTPUT_CSV = OUTPUT_DIR / "shopcuup_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "shopcuup_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://www.shopcuup.com"
SITEMAP_URL = f"{SITE_ROOT}/sitemap-cuup_product.xml"
TURNTO_SITE_KEY = "AbWKg11ss9tAcFCsite"
TURNTO_CDN_ROOT = "https://cdn-ws.turnto.com/v5/sitedata"
TURNTO_IMAGE_ROOT = f"https://images.turnto.com/media/{TURNTO_SITE_KEY}"
LOCALE = "en_US"
PAGE_SIZE = 100
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"

HEADERS = [
    "created_at_display",
    "id",
    "original_url_display",
    "product_page_url_display",
    "monetized_product_url_display",
    "height_raw",
    "weight_raw",
    "user_comment",
    "date_review_submitted_raw",
    "height_in_display",
    "review_date",
    "source_site_display",
    "status_code",
    "fetched_at",
    "updated_at",
    "brand",
    "waist_raw_display",
    "hips_raw",
    "age_raw",
    "waist_in",
    "hips_in_display",
    "age_years_display",
    "search_fts",
    "weight_display_display",
    "weight_raw_needs_correction",
    "clothing_type_id",
    "reviewer_profile_url",
    "reviewer_name_raw",
    "inseam_inches_display",
    "color_canonical",
    "color_display",
    "size_display",
    "bust_in_number_display",
    "cupsize_display",
    "weight_lbs_display",
    "weight_lbs_raw_issue",
]

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

GENERIC_SIZE_RE = re.compile(
    r"\b("
    r"xxs|xxs/xs|xs|x-small|extra small|small|s|medium|med|m|large|l|xl|x-large|extra large|"
    r"xxl|2xl|xx-large|2x|xxxl|3xl|3x|4xl|4x|5xl|5x|6xl|6x|"
    r"\d{1,2}(?:\s*[A-Z]{1,4})?"
    r")\b",
    re.I,
)
BRA_SIZE_RE = re.compile(
    r"\b(28|30|32|34|36|38|40|42|44|46|48|50|52|54)\s*(AAA|AA|A|B|C|D|DD|DD/?E|DDD|DDD/?F|F|G|H|I|J|K)\b",
    re.I,
)
HEIGHT_RE = re.compile(
    r"(?:(?:i\s*(?:am|'m)|im|i’m|i am)\s*)?"
    r"(\d)\s*(?:ft|feet|foot|['’])\s*(\d{1,2})?\s*(?:in|inches|[\"”])?",
    re.I,
)
WEIGHT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?)\b", re.I)
WAIST_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b", re.I)
HIPS_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
AGE_RE = re.compile(r"\b(?:i\s*(?:am|'m)|im|i’m|age)\s*(\d{1,2})(?:\s*years?\s*old)?\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)\s*inseam\b", re.I)


@dataclass(frozen=True)
class Product:
    sku: str
    product_url: str
    title: str


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch_text(url: str, retries: int = 6) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
        except URLError as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 20))
    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def fetch_json(url: str, retries: int = 6) -> Dict[str, object]:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Origin": SITE_ROOT,
                "Referer": f"{SITE_ROOT}/",
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
        except (URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 20))
    if last_error:
        raise RuntimeError(f"Failed JSON request for {url}: {last_error}") from last_error
    raise RuntimeError(f"Failed JSON request for {url}")


def get_products() -> List[Product]:
    root = ET.fromstring(fetch_text(SITEMAP_URL))
    products: List[Product] = []
    seen_skus = set()
    for loc in root.findall(".//sm:url/sm:loc", NS):
        product_url = normalize_whitespace(loc.text or "")
        match = re.search(r"/products/[^/]+/(\d+)\.html", product_url)
        if not match:
            continue
        sku = match.group(1)
        if sku in seen_skus:
            continue
        seen_skus.add(sku)
        title_slug = product_url.rstrip("/").split("/")[-2]
        products.append(
            Product(
                sku=sku,
                product_url=product_url,
                title=normalize_whitespace(title_slug.replace("---", " - ").replace("-", " ").title()),
            )
        )
    return products


def classify_clothing_type(product_title: str, product_url: str) -> str:
    value = f"{product_title} {product_url}".lower()
    if "bralette" in value:
        return "bralette"
    if "bra" in value or "balconette" in value or "demi" in value or "plunge" in value:
        return "bra"
    if any(token in value for token in ("panty", "brief", "thong", "bikini", "cheeky", "underwear")):
        return "underwear"
    if any(token in value for token in ("bodysuit", "body suit")):
        return "bodysuit"
    if any(token in value for token in ("cami", "tank", "top")):
        return "top"
    return ""


def normalize_bra_size(value: str) -> str:
    collapsed = normalize_whitespace(value).upper().replace(" ", "")
    if collapsed == "DDE":
        return "DD/E"
    if collapsed == "DDDF":
        return "DDD/F"
    return collapsed


def normalize_generic_size(value: str) -> str:
    size = normalize_whitespace(value).lower()
    mapping = {
        "x-small": "x-small",
        "extra small": "x-small",
        "xs": "x-small",
        "s": "small",
        "small": "small",
        "med": "medium",
        "m": "medium",
        "medium": "medium",
        "l": "large",
        "large": "large",
        "x-large": "x-large",
        "extra large": "x-large",
        "xl": "x-large",
        "xxl": "xx-large",
        "2xl": "xx-large",
        "2x": "xx-large",
        "xx-large": "xx-large",
        "xxxl": "xxx-large",
        "3xl": "xxx-large",
        "3x": "xxx-large",
        "4xl": "4x-large",
        "4x": "4x-large",
        "5xl": "5x-large",
        "5x": "5x-large",
        "6xl": "6x-large",
        "6x": "6x-large",
    }
    return mapping.get(size, value.strip())


def extract_size_from_text(text: str) -> str:
    explicit_patterns = [
        r"\b(?:ordered|bought|purchased|got|wear|wearing|picked|choose|chose|went with)\s+(?:the\s+)?(?:a\s+)?size\s+([a-z0-9\-/ ]+?)(?:[.,;]|$)",
        r"\bsize\s+([a-z0-9\-/ ]+?)(?:\s+fits|\s+fit|[.,;]|$)",
        r"\b(?:i\s+)?(?:usually\s+)?wear(?:ing)?\s+(?:a\s+)?((?:28|30|32|34|36|38|40|42|44|46|48|50|52|54)\s*(?:AAA|AA|A|B|C|D|DD|DD/?E|DDD|DDD/?F|F|G|H|I|J|K))\b",
        r"\b(?:ordered|bought|purchased|got|picked|choose|chose|went with)\s+(?:a\s+)?((?:28|30|32|34|36|38|40|42|44|46|48|50|52|54)\s*(?:AAA|AA|A|B|C|D|DD|DD/?E|DDD|DDD/?F|F|G|H|I|J|K))\b",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        candidate = normalize_whitespace(match.group(1))
        bra = BRA_SIZE_RE.search(candidate)
        if bra:
            return normalize_bra_size(bra.group(0))
        generic = GENERIC_SIZE_RE.search(candidate)
        if generic:
            return normalize_generic_size(generic.group(1))
        if candidate:
            return candidate

    bra_match = BRA_SIZE_RE.search(text)
    if bra_match:
        return normalize_bra_size(bra_match.group(0))

    generic_match = GENERIC_SIZE_RE.search(text)
    if generic_match:
        return normalize_generic_size(generic_match.group(1))
    return ""


def extract_numeric_field(pattern: re.Pattern[str], text: str) -> Tuple[str, str]:
    match = pattern.search(text)
    if not match:
        return "", ""
    raw = normalize_whitespace(match.group(0))
    return raw, match.group(1)


def extract_height(text: str) -> Tuple[str, str]:
    match = HEIGHT_RE.search(text)
    if not match:
        return "", ""
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    return f"{feet}'{inches}\"", str(feet * 12 + inches)


def extract_height_from_value(value: str) -> Tuple[str, str]:
    normalized = normalize_whitespace(value)
    if not normalized:
        return "", ""
    if " - " in normalized:
        return normalized, ""
    return extract_height(normalized)


def extract_weight(text: str) -> Tuple[str, str]:
    return extract_numeric_field(WEIGHT_RE, text)


def extract_waist(text: str) -> Tuple[str, str]:
    return extract_numeric_field(WAIST_RE, text)


def extract_hips(text: str) -> Tuple[str, str]:
    return extract_numeric_field(HIPS_RE, text)


def extract_age(text: str) -> Tuple[str, str]:
    return extract_numeric_field(AGE_RE, text)


def extract_inseam(text: str) -> str:
    _, value = extract_numeric_field(INSEAM_RE, text)
    return value


def format_review_dates(timestamp_ms: object) -> Tuple[str, str]:
    if timestamp_ms in (None, ""):
        return "", ""
    dt = datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc)
    return dt.strftime("%B %d, %Y").replace(" 0", " "), dt.date().isoformat()


def search_fts(parts: Sequence[str]) -> str:
    return normalize_whitespace(" ".join(part for part in parts if part))


def get_dimension_value(review: Dict[str, object], label: str) -> str:
    for dimension in review.get("dimensions") or []:
        if normalize_whitespace(str(dimension.get("dimensionLabel") or "")).lower() != label.lower():
            continue
        value_labels = dimension.get("valueLabels") or []
        value_index = dimension.get("value")
        if isinstance(value_index, int) and 0 <= value_index < len(value_labels):
            return normalize_whitespace(str(value_labels[value_index] or ""))
    return ""


def get_profile_custom_map(review: Dict[str, object]) -> Dict[str, str]:
    custom_map: Dict[str, str] = {}
    profile = review.get("profileAttributes") or {}
    for item in profile.get("custom") or []:
        label = normalize_whitespace(str(item.get("label") or ""))
        value = normalize_whitespace(str(item.get("value") or ""))
        if label and value:
            custom_map[label] = value
    return custom_map


def reviewer_name(review: Dict[str, object]) -> str:
    user = review.get("user") or {}
    first = normalize_whitespace(str(user.get("firstName") or ""))
    last = normalize_whitespace(str(user.get("lastName") or ""))
    return normalize_whitespace(f"{first} {last}")


def build_media_url(media_item: Dict[str, object]) -> str:
    image_id = normalize_whitespace(str(media_item.get("imageId") or ""))
    image_type = normalize_whitespace(str(media_item.get("imageType") or ""))
    if not image_id or not image_type:
        return ""
    return f"{TURNTO_IMAGE_ROOT}/{quote(image_id)}.{quote(image_type)}"


def build_row(product: Product, review: Dict[str, object], media_item: Dict[str, object], fetched_at: str) -> Dict[str, str]:
    review_title = normalize_whitespace(str(review.get("title") or ""))
    review_text = normalize_whitespace(str(review.get("text") or ""))
    combined_text = normalize_whitespace(" ".join(part for part in [review_title, review_text] if part))

    profile_custom = get_profile_custom_map(review)
    band_size = normalize_whitespace(profile_custom.get("Band/Underbust Size", ""))
    cup_size = normalize_whitespace(profile_custom.get("Bra Cup Size", ""))
    bra_size = normalize_bra_size(f"{band_size}{cup_size}") if band_size and cup_size else ""
    size_purchased = get_dimension_value(review, "Size Purchased")
    size_display = bra_size or size_purchased or extract_size_from_text(combined_text)

    height_raw, height_in = extract_height_from_value(profile_custom.get("Height", "")) if profile_custom.get("Height") else extract_height(combined_text)
    weight_raw, weight_lbs = extract_weight(combined_text)
    waist_raw, waist_in = extract_waist(combined_text)
    hips_raw, hips_in = extract_hips(combined_text)

    age_raw = normalize_whitespace(profile_custom.get("Age", ""))
    age_years = ""
    if age_raw and age_raw.isdigit():
        age_years = age_raw
    elif not age_raw:
        age_raw, age_years = extract_age(combined_text)

    inseam_in = extract_inseam(combined_text)
    submitted_raw, review_date = format_review_dates(review.get("dateCreatedMillis"))
    image_url = build_media_url(media_item)
    color_display = get_dimension_value(review, "Color Purchased")

    return {
        "created_at_display": "",
        "id": str(review.get("id") or ""),
        "original_url_display": image_url,
        "product_page_url_display": normalize_whitespace(str((review.get("catItem") or {}).get("url") or product.product_url)),
        "monetized_product_url_display": "",
        "height_raw": height_raw,
        "weight_raw": weight_raw,
        "user_comment": combined_text,
        "date_review_submitted_raw": submitted_raw,
        "height_in_display": height_in,
        "review_date": review_date,
        "source_site_display": f"{SITE_ROOT}/",
        "status_code": "200",
        "fetched_at": fetched_at,
        "updated_at": fetched_at,
        "brand": normalize_whitespace(str((review.get("catItem") or {}).get("brand") or "CUUP")),
        "waist_raw_display": waist_raw,
        "hips_raw": hips_raw,
        "age_raw": age_raw,
        "waist_in": waist_in,
        "hips_in_display": hips_in,
        "age_years_display": age_years,
        "search_fts": search_fts([product.title, review_title, review_text, reviewer_name(review), size_display, band_size, cup_size]),
        "weight_display_display": weight_raw,
        "weight_raw_needs_correction": "",
        "clothing_type_id": classify_clothing_type(product.title, product.product_url),
        "reviewer_profile_url": "",
        "reviewer_name_raw": reviewer_name(review),
        "inseam_inches_display": inseam_in,
        "color_canonical": color_display,
        "color_display": color_display,
        "size_display": size_display,
        "bust_in_number_display": band_size,
        "cupsize_display": normalize_bra_size(cup_size) if cup_size else "",
        "weight_lbs_display": weight_lbs,
        "weight_lbs_raw_issue": "",
    }


def reviews_url(sku: str, offset: int, limit: int) -> str:
    filters = quote("{}", safe="")
    return (
        f"{TURNTO_CDN_ROOT}/{TURNTO_SITE_KEY}/{sku}/d/review/{LOCALE}/"
        f"{offset}/{limit}/{filters}/RECENT/false/true/?"
    )


def fetch_reviews_with_images(sku: str) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    offset = 0
    total: Optional[int] = None

    while total is None or offset < total:
        payload = fetch_json(reviews_url(sku, offset, PAGE_SIZE))
        batch = payload.get("reviews") or []
        if not isinstance(batch, list) or not batch:
            break
        total = int(payload.get("total") or 0)
        rows.extend(batch)
        offset += len(batch)
        if len(batch) < PAGE_SIZE:
            break

    return rows


def process_product(product: Product, fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    try:
        reviews = fetch_reviews_with_images(product.sku)
    except Exception as exc:
        return [], {
            "product_url": product.product_url,
            "product_id": product.sku,
            "title": product.title,
            "matching_review_images": 0,
            "matching_reviews": 0,
            "total_reviews_seen": 0,
            "error": str(exc),
        }

    rows: List[Dict[str, str]] = []
    matching_reviews = set()
    for review in reviews:
        review_media = review.get("media") or []
        if not isinstance(review_media, list):
            continue
        for media_item in review_media:
            if int(media_item.get("type") or 0) != 0:
                continue
            image_url = build_media_url(media_item)
            if not image_url:
                continue
            rows.append(build_row(product, review, media_item, fetched_at))
            matching_reviews.add(str(review.get("id") or ""))

    return rows, {
        "product_url": product.product_url,
        "product_id": product.sku,
        "title": product.title,
        "matching_review_images": len(rows),
        "matching_reviews": len([review_id for review_id in matching_reviews if review_id]),
        "total_reviews_seen": len(reviews),
    }


def scrape(
    product_url: Optional[str] = None,
    limit_products: Optional[int] = None,
    max_workers: int = 8,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    products = get_products()
    if product_url:
        normalized_target = product_url.split("?")[0]
        products = [product for product in products if product.product_url.split("?")[0] == normalized_target]
    if limit_products is not None:
        products = products[:limit_products]

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    summary: Dict[str, object] = {
        "scraped_at": fetched_at,
        "site_root": SITE_ROOT,
        "products_seen": 0,
        "products_with_matching_rows": 0,
        "review_images_exported": 0,
        "review_ids_exported": 0,
        "product_summaries": [],
    }
    rows: List[Dict[str, str]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(process_product, product, fetched_at): product for product in products}
        for index, future in enumerate(as_completed(future_map), start=1):
            product_rows, product_summary = future.result()
            rows.extend(product_rows)
            if product_rows:
                summary["products_with_matching_rows"] = int(summary["products_with_matching_rows"]) + 1
            summary["products_seen"] = index
            summary["product_summaries"].append(product_summary)
            print(
                f"[{index}/{len(products)}] {product_summary.get('title') or future_map[future].product_url} -> "
                f"{product_summary['matching_review_images']} matching image rows"
                + (f" (error: {product_summary['error']})" if product_summary.get("error") else ""),
                flush=True,
            )

    deduped_rows: List[Dict[str, str]] = []
    seen_row_keys = set()
    for row in rows:
        row_key = (row["id"], row["product_page_url_display"], row["original_url_display"])
        if row_key in seen_row_keys:
            continue
        seen_row_keys.add(row_key)
        deduped_rows.append(row)

    summary["review_images_exported"] = len(deduped_rows)
    summary["review_ids_exported"] = len({row["id"] for row in deduped_rows if row.get("id")})
    summary["product_summaries"].sort(key=lambda item: int(item.get("matching_review_images", 0) or 0), reverse=True)
    return deduped_rows, summary


def write_csv(rows: Iterable[Dict[str, str]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in HEADERS})


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape ShopCuup image reviews into the Amazon schema.")
    parser.add_argument("--product-url", type=str, default=None, help="Only scrape one product URL.")
    parser.add_argument("--limit-products", type=int, default=None, help="Only scrape the first N products from the sitemap.")
    parser.add_argument("--max-workers", type=int, default=8, help="Number of product requests to run in parallel.")
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV, help="CSV output path.")
    args = parser.parse_args(argv)

    rows, summary = scrape(product_url=args.product_url, limit_products=args.limit_products, max_workers=args.max_workers)
    write_csv(rows, args.output)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote {len(rows)} rows to {args.output}")
    print(f"Products scanned: {summary['products_seen']}")
    print(f"Products with matches: {summary['products_with_matching_rows']}")
    print(f"Unique reviews exported: {summary['review_ids_exported']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
