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
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = ROOT / "data-pipelines" / "non-amazon" / "data" / "step_1_raw_scraping_data" / "shapermint"
OUTPUT_CSV = OUTPUT_DIR / "shapermint_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "shapermint_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://shapermint.com"
PRODUCT_FEED_URL = "https://feeds.datafeedwatch.com/25986/cbdd197d9c7747c13f08f840f8bc76eb350292fc.xml"
STAMPED_API_KEY = "pubkey-bxO8kfv49d8c4w6Z87j3WbwLv908c2"
STAMPED_STORE_ID = "52233"
STAMPED_STORE_URL = "shapermint.myshopify.com"
STAMPED_REVIEWS_URL = "https://stamped.io/api/widget/reviews"
STAMPED_PHOTO_BASE = "https://cdn.stamped.io/uploads/photos/"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
PAGE_SIZE = 100

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

GENERIC_SIZE_RE = re.compile(
    r"\b("
    r"xxs|xxs/xs|xs|x-small|extra small|small|s|medium|med|m|large|l|xl|x-large|extra large|"
    r"xxl|2xl|xx-large|2x|xxxl|3xl|3x|4xl|4x|5xl|5x|6xl|6x"
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
    product_id: str
    product_url: str
    title: str
    brand: str
    color: str
    image_url: str


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
                "Accept": "application/json,text/plain,*/*",
                "Referer": f"{SITE_ROOT}/",
                "Origin": SITE_ROOT,
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
    root = ET.fromstring(fetch_text(PRODUCT_FEED_URL))
    products_by_group: Dict[str, Product] = {}
    for item in root.findall("./channel/item"):
        group_id = normalize_whitespace(item.findtext("{http://base.google.com/ns/1.0}item_group_id") or "")
        link = normalize_whitespace(item.findtext("{http://base.google.com/ns/1.0}link") or "")
        title = normalize_whitespace(item.findtext("{http://base.google.com/ns/1.0}title") or "")
        brand = normalize_whitespace(item.findtext("{http://base.google.com/ns/1.0}brand") or "") or "Shapermint"
        color = normalize_whitespace(item.findtext("{http://base.google.com/ns/1.0}color") or "")
        image_url = normalize_whitespace(item.findtext("{http://base.google.com/ns/1.0}image_link") or "")
        if not group_id or not link or group_id in products_by_group:
            continue
        products_by_group[group_id] = Product(
            product_id=group_id,
            product_url=link,
            title=title,
            brand=brand,
            color=color,
            image_url=image_url,
        )
    return list(products_by_group.values())


def classify_clothing_type(product_title: str, product_url: str) -> str:
    value = f"{product_title} {product_url}".lower()
    if "bralette" in value:
        return "bralette"
    if "bra" in value:
        return "bra"
    if any(token in value for token in ("panty", "brief", "thong", "bikini", "boyshort", "underwear")):
        return "underwear"
    if any(token in value for token in ("bodysuit", "body suit")):
        return "bodysuit"
    if "cami" in value or "tank" in value:
        return "tank"
    if any(token in value for token in ("legging", "short", "brief short")):
        return "bottom"
    return ""


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


def normalize_bra_size(value: str) -> str:
    collapsed = normalize_whitespace(value).upper().replace(" ", "")
    if collapsed == "DDE":
        return "DD/E"
    if collapsed == "DDDE":
        return "DDD/E"
    return collapsed


def extract_size_from_text(text: str) -> str:
    explicit_bra_patterns = [
        r"\b(?:ordered|bought|purchased|got|wear|wearing|picked|choose|chose|went with)\s+(?:the\s+)?(?:a\s+)?((?:28|30|32|34|36|38|40|42|44|46|48|50|52|54)\s*(?:AAA|AA|A|B|C|D|DD|DD/?E|DDD|DDD/?F|F|G|H|I|J|K))\b",
        r"\b(?:i\s+)?(?:usually\s+)?wear(?:ing)?\s+(?:a\s+)?((?:28|30|32|34|36|38|40|42|44|46|48|50|52|54)\s*(?:AAA|AA|A|B|C|D|DD|DD/?E|DDD|DDD/?F|F|G|H|I|J|K))\b",
    ]
    for pattern in explicit_bra_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return normalize_bra_size(match.group(1))

    explicit_patterns = [
        r"\b(?:ordered|bought|purchased|got|wear|wearing|picked|choose|chose|went with)\s+(?:the\s+)?(?:a\s+)?size\s+([a-z0-9\-/ ]+?)(?:[.,;]|$)",
        r"\bsize\s+([a-z0-9\-/ ]+?)(?:\s+fits|\s+fit|[.,;]|$)",
        r"\b(?:i\s+)?(?:usually\s+)?wear(?:ing)?\s+(?:a\s+)?(xxs|xs|x-small|extra small|small|medium|med|large|xl|x-large|extra large|xxl|2xl|2x|xx-large|xxxl|3xl|3x|4xl|4x|5xl|5x|6xl|6x)\b",
        r"\b(?:ordered|bought|purchased|got|picked|choose|chose|went with)\s+(?:a\s+)?(xxs|xs|x-small|extra small|small|medium|med|large|xl|x-large|extra large|xxl|2xl|2x|xx-large|xxxl|3xl|3x|4xl|4x|5xl|5x|6xl|6x)\b",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            candidate = normalize_whitespace(match.group(1))
            bra = BRA_SIZE_RE.search(candidate)
            if bra:
                return normalize_bra_size(bra.group(0))
            if re.fullmatch(r"\d{1,2}", candidate):
                return candidate
            generic = GENERIC_SIZE_RE.search(candidate)
            if generic:
                return normalize_generic_size(generic.group(1))
            if candidate:
                return candidate

    bra_match = BRA_SIZE_RE.search(text)
    if bra_match:
        return normalize_bra_size(bra_match.group(0))
    return ""


def extract_height(text: str) -> Tuple[str, str]:
    match = HEIGHT_RE.search(text)
    if not match:
        return "", ""
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    total_inches = feet * 12 + inches
    display = f"{feet}'{inches}\"" if match.group(2) else f"{feet}'0\""
    return display, str(total_inches)


def extract_numeric_field(pattern: re.Pattern[str], text: str) -> Tuple[str, str]:
    match = pattern.search(text)
    if not match:
        return "", ""
    raw = normalize_whitespace(match.group(0))
    return raw, match.group(1)


def extract_weight(text: str) -> Tuple[str, str]:
    return extract_numeric_field(WEIGHT_RE, text)


def extract_age(text: str) -> Tuple[str, str]:
    return extract_numeric_field(AGE_RE, text)


def extract_waist(text: str) -> Tuple[str, str]:
    return extract_numeric_field(WAIST_RE, text)


def extract_hips(text: str) -> Tuple[str, str]:
    return extract_numeric_field(HIPS_RE, text)


def extract_inseam(text: str) -> str:
    _, value = extract_numeric_field(INSEAM_RE, text)
    return value


def extract_bra_measurement(size_value: str, text: str) -> Tuple[str, str]:
    for source in (size_value, text):
        if not source:
            continue
        match = BRA_SIZE_RE.search(source)
        if match:
            return match.group(1), normalize_bra_size(match.group(2))
    return "", ""


def format_review_dates(timestamp_raw: str) -> Tuple[str, str]:
    if not timestamp_raw:
        return "", ""
    normalized = timestamp_raw.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1]
    if "." in normalized:
        main, frac = normalized.split(".", 1)
        frac_digits = re.sub(r"\D", "", frac)
        normalized = f"{main}.{(frac_digits + '000000')[:6]}"
    dt = datetime.fromisoformat(f"{normalized}+00:00")
    return dt.strftime("%B %d, %Y").replace(" 0", " "), dt.date().isoformat()


def search_fts(parts: Sequence[str]) -> str:
    return normalize_whitespace(" ".join(part for part in parts if part))


def normalize_photo_urls(review_user_photos: str) -> List[str]:
    filenames = [normalize_whitespace(part) for part in (review_user_photos or "").split(",")]
    return [f"{STAMPED_PHOTO_BASE}{name}" for name in filenames if name]


def build_row(product: Product, review: Dict[str, object], image_url: str, fetched_at: str) -> Dict[str, str]:
    review_title = normalize_whitespace(str(review.get("reviewTitle") or ""))
    review_text = normalize_whitespace(str(review.get("reviewMessage") or ""))
    combined_text = normalize_whitespace(" ".join(part for part in [review_title, review_text] if part))

    size_display = extract_size_from_text(combined_text)
    height_raw, height_in = extract_height(combined_text)
    weight_raw, weight_lbs = extract_weight(combined_text)
    waist_raw, waist_in = extract_waist(combined_text)
    hips_raw, hips_in = extract_hips(combined_text)
    age_raw_text, age_years = extract_age(combined_text)
    inseam_in = extract_inseam(combined_text)
    bust_band, cup_size = extract_bra_measurement(size_display, combined_text)
    submitted_raw, review_date = format_review_dates(str(review.get("dateCreated") or ""))

    return {
        "created_at_display": "",
        "id": str(review.get("id") or ""),
        "original_url_display": image_url,
        "product_page_url_display": product.product_url,
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
        "brand": product.brand or "Shapermint",
        "waist_raw_display": waist_raw,
        "hips_raw": hips_raw,
        "age_raw": age_raw_text,
        "waist_in": waist_in,
        "hips_in_display": hips_in,
        "age_years_display": age_years,
        "search_fts": search_fts([product.title, review_title, review_text, product.color, size_display]),
        "weight_display_display": weight_raw,
        "weight_raw_needs_correction": "",
        "clothing_type_id": classify_clothing_type(product.title, product.product_url),
        "reviewer_profile_url": "",
        "reviewer_name_raw": normalize_whitespace(str(review.get("author") or "")),
        "inseam_inches_display": inseam_in,
        "color_canonical": product.color,
        "color_display": product.color,
        "size_display": size_display,
        "bust_in_number_display": bust_band,
        "cupsize_display": cup_size,
        "weight_lbs_display": weight_lbs,
        "weight_lbs_raw_issue": "",
    }


def fetch_photo_reviews(product_id: str) -> List[Dict[str, object]]:
    reviews: List[Dict[str, object]] = []
    seen_review_ids = set()
    page = 1

    while True:
        params = {
            "apiKey": STAMPED_API_KEY,
            "sId": STAMPED_STORE_ID,
            "storeUrl": STAMPED_STORE_URL,
            "productId": product_id,
            "page": page,
            "skip": PAGE_SIZE,
            "minRating": 1,
            "isWithPhotos": "true",
            "type": "widget-carousel-photos",
        }
        payload = fetch_json(f"{STAMPED_REVIEWS_URL}?{urlencode(params)}")
        batch = payload.get("data") or []
        if not isinstance(batch, list) or not batch:
            break

        page_count = 0
        for review in batch:
            review_id = str(review.get("id") or "")
            if not review_id or review_id in seen_review_ids:
                continue
            seen_review_ids.add(review_id)
            reviews.append(review)
            page_count += 1

        if len(batch) < PAGE_SIZE or page_count == 0:
            break
        page += 1

    return reviews


def process_product(product: Product, fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    try:
        reviews = fetch_photo_reviews(product.product_id)
    except Exception as exc:
        return [], {
            "product_url": product.product_url,
            "product_id": product.product_id,
            "title": product.title,
            "matching_review_images": 0,
            "matching_reviews": 0,
            "error": str(exc),
        }

    rows: List[Dict[str, str]] = []
    review_ids = set()
    for review in reviews:
        review_ids.add(str(review.get("id") or ""))
        for image_url in normalize_photo_urls(str(review.get("reviewUserPhotos") or "")):
            rows.append(build_row(product, review, image_url, fetched_at))

    return rows, {
        "product_url": product.product_url,
        "product_id": product.product_id,
        "title": product.title,
        "matching_review_images": len(rows),
        "matching_reviews": len([review_id for review_id in review_ids if review_id]),
    }


def scrape(
    product_url: Optional[str] = None,
    limit_products: Optional[int] = None,
    max_workers: int = 8,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    products = get_products()
    if product_url:
        products = [product for product in products if product.product_url.split("?")[0] == product_url.split("?")[0]]
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
    parser = argparse.ArgumentParser(description="Scrape Shapermint image reviews into the Amazon schema.")
    parser.add_argument("--product-url", type=str, default=None, help="Only scrape one product URL.")
    parser.add_argument("--limit-products", type=int, default=None, help="Only scrape the first N products from the feed.")
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
