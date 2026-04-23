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
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = ROOT / "data-pipelines" / "non-amazon" / "data" / "step_1_raw_scraping_data" / "bloomchic"
OUTPUT_CSV = OUTPUT_DIR / "bloomchic_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "bloomchic_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://bloomchic.com"
SITEMAP_INDEX_URL = f"{SITE_ROOT}/sitemap.xml"
API_ROOT = "https://app-backend-api-prod.bloomeverybody.com/web/2025-10/comment-list"
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

NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "image": "http://www.google.com/schemas/sitemap-image/1.1",
}

GENERIC_SIZE_RE = re.compile(
    r"\b("
    r"xxs|xxs/xs|xs|x-small|extra small|small|s|medium|med|m|large|l|xl|x-large|extra large|"
    r"xxl|2xl|xx-large|2x|xxxl|3xl|3x|4xl|4x|5xl|5x|6xl|6x|"
    r"\d{1,2}(?:-\d{1,2})?/\d+x"
    r")\b",
    re.I,
)
HEIGHT_TEXT_RE = re.compile(
    r"(?:(?:i\s*(?:am|'m)|im|i’m|i am)\s*)?"
    r"(\d)\s*(?:ft|feet|foot|['’])\s*(\d{1,2})?\s*(?:in|inches|[\"”])?",
    re.I,
)
WEIGHT_TEXT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?)\b", re.I)
WAIST_TEXT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b", re.I)
HIPS_TEXT_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b", re.I)
AGE_RE = re.compile(r"\b(?:i\s*(?:am|'m)|im|i’m|age)\s*(\d{1,2})(?:\s*years?\s*old)?\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)\s*inseam\b", re.I)


@dataclass(frozen=True)
class Product:
    handle: str
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


def fetch_json(url: str, product_url: str, retries: int = 6) -> Dict[str, object]:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Origin": SITE_ROOT,
                "Referer": product_url,
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


def humanize_handle(handle: str) -> str:
    return normalize_whitespace(handle.replace("-", " ").replace("_", " ").title())


def clean_sitemap_title(title: str, fallback_handle: str) -> str:
    cleaned = normalize_whitespace(title)
    if " - " in cleaned:
        cleaned = cleaned.split(" - ", 1)[1]
    return cleaned or humanize_handle(fallback_handle)


def get_products() -> List[Product]:
    root = ET.fromstring(fetch_text(SITEMAP_INDEX_URL))
    sitemap_urls = [
        loc.text.strip()
        for loc in root.findall(".//sm:loc", NS)
        if loc.text and "sitemap_products_" in loc.text
    ]
    products: List[Product] = []
    seen_handles = set()
    for sitemap_url in sitemap_urls:
        sitemap_root = ET.fromstring(fetch_text(sitemap_url))
        for entry in sitemap_root.findall(".//sm:url", NS):
            loc_text = normalize_whitespace(entry.findtext("sm:loc", default="", namespaces=NS))
            if "/products/" not in loc_text:
                continue
            handle = urlparse(loc_text).path.rstrip("/").split("/")[-1]
            if not handle or handle in seen_handles:
                continue
            seen_handles.add(handle)
            image_title = normalize_whitespace(entry.findtext("image:image/image:title", default="", namespaces=NS))
            products.append(
                Product(
                    handle=handle,
                    product_url=loc_text,
                    title=clean_sitemap_title(image_title, handle),
                )
            )
    return products


def classify_clothing_type(product_title: str, product_url: str) -> str:
    value = f"{product_title} {product_url}".lower()
    if "bralette" in value:
        return "bralette"
    if "bra" in value:
        return "bra"
    if any(token in value for token in ("panty", "brief", "thong", "underwear", "boyshort")):
        return "underwear"
    if "bodysuit" in value:
        return "bodysuit"
    if any(token in value for token in ("tank", "cami", "top", "tee", "shirt", "blouse")):
        return "top"
    if any(token in value for token in ("pants", "jeans", "leggings", "jogger", "skirt", "shorts")):
        return "bottom"
    if any(token in value for token in ("dress", "jumpsuit", "romper")):
        return "dress"
    if "swim" in value or "bikini" in value or "tankini" in value:
        return "swimwear"
    return ""


def extract_size_from_text(text: str) -> str:
    explicit_patterns = [
        r"\b(?:ordered|bought|purchased|got|wear|wearing|picked|choose|chose|went with)\s+(?:the\s+)?(?:a\s+)?size\s+([a-z0-9\-/ ]+?)(?:[.,;]|$)",
        r"\bsize\s+([a-z0-9\-/ ]+?)(?:\s+fits|\s+fit|[.,;]|$)",
        r"\b(?:i\s+)?(?:usually\s+)?wear(?:ing)?\s+(?:a\s+)?([0-9]{1,2}(?:-[0-9]{1,2})?/\d+x|xxs|xs|x-small|extra small|small|medium|med|large|xl|x-large|extra large|xxl|2xl|2x|xx-large|xxxl|3xl|3x|4xl|4x|5xl|5x|6xl|6x)\b",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            candidate = normalize_whitespace(match.group(1))
            generic = GENERIC_SIZE_RE.search(candidate)
            if generic:
                return generic.group(1)
            if candidate:
                return candidate
    generic_match = GENERIC_SIZE_RE.search(text)
    return generic_match.group(1) if generic_match else ""


def extract_numeric_field(pattern: re.Pattern[str], text: str) -> Tuple[str, str]:
    match = pattern.search(text)
    if not match:
        return "", ""
    raw = normalize_whitespace(match.group(0))
    return raw, match.group(1)


def extract_height_from_text(text: str) -> Tuple[str, str]:
    match = HEIGHT_TEXT_RE.search(text)
    if not match:
        return "", ""
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    return f"{feet}'{inches}\"", str(feet * 12 + inches)


def extract_height_inches(raw_value: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)", raw_value)
    if not match:
        return ""
    return str(int(round(float(match.group(1)))))


def extract_plain_number(raw_value: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)", raw_value)
    if not match:
        return ""
    number = float(match.group(1))
    return str(int(round(number))) if abs(number - round(number)) < 1e-9 or number.is_integer() else str(number)


def extract_age(text: str) -> Tuple[str, str]:
    return extract_numeric_field(AGE_RE, text)


def extract_inseam(text: str) -> str:
    _, value = extract_numeric_field(INSEAM_RE, text)
    return value


def format_epoch_date(epoch_value: object) -> Tuple[str, str]:
    if epoch_value in (None, ""):
        return "", ""
    timestamp = int(epoch_value)
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return dt.strftime("%B %d, %Y").replace(" 0", " "), dt.date().isoformat()


def search_fts(parts: Sequence[str]) -> str:
    return normalize_whitespace(" ".join(part for part in parts if part))


def parse_json_field(raw_value: object) -> object:
    if not raw_value:
        return {}
    if isinstance(raw_value, (dict, list)):
        return raw_value
    try:
        return json.loads(str(raw_value))
    except json.JSONDecodeError:
        return {}


def parse_selected_options(raw_value: object) -> Dict[str, str]:
    parsed = parse_json_field(raw_value)
    options: Dict[str, str] = {}
    if not isinstance(parsed, list):
        return options
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = normalize_whitespace(str(item.get("name") or "")).lower()
        value = normalize_whitespace(str(item.get("value") or ""))
        if name and value:
            options[name] = value
    return options


def image_urls_from_review(review: Dict[str, object]) -> List[str]:
    urls: List[str] = []
    medias = review.get("medias") or []
    if isinstance(medias, list):
        for media in medias:
            if not isinstance(media, dict):
                continue
            url = normalize_whitespace(str(media.get("url") or ""))
            if url and url not in urls:
                urls.append(url)
    return urls


def build_row(product: Product, review: Dict[str, object], image_url: str, fetched_at: str) -> Dict[str, str]:
    review_title = normalize_whitespace(str(review.get("title") or ""))
    review_text = normalize_whitespace(str(review.get("body") or ""))
    selected_options = parse_selected_options(review.get("selected_options"))
    body_metrics_new = review.get("body_metrics_new") or {}
    if not isinstance(body_metrics_new, dict):
        body_metrics_new = {}

    size_display = selected_options.get("size") or extract_size_from_text(review_text)
    color_display = selected_options.get("color") or ""

    height_raw = normalize_whitespace(str((body_metrics_new.get("height") or {}).get("ft_value") or ""))
    height_in = extract_height_inches(str((body_metrics_new.get("height") or {}).get("inch_int_value") or ""))
    if not height_raw:
        height_raw, height_in = extract_height_from_text(review_text)

    weight_lbs = extract_plain_number(str((body_metrics_new.get("weight") or {}).get("lbs_value") or ""))
    weight_raw = f"{weight_lbs}lbs" if weight_lbs else ""
    if not weight_raw:
        weight_raw, weight_lbs = extract_numeric_field(WEIGHT_TEXT_RE, review_text)

    waist_in = extract_plain_number(str((body_metrics_new.get("waist") or {}).get("inch_int_value") or ""))
    waist_raw = f'{waist_in}"' if waist_in else ""
    if not waist_raw:
        waist_raw, waist_in = extract_numeric_field(WAIST_TEXT_RE, review_text)

    hips_in = extract_plain_number(str((body_metrics_new.get("hips") or {}).get("inch_int_value") or ""))
    hips_raw = f'{hips_in}"' if hips_in else ""
    if not hips_raw:
        hips_raw, hips_in = extract_numeric_field(HIPS_TEXT_RE, review_text)

    bust_in = extract_plain_number(str((body_metrics_new.get("bust") or {}).get("inch_int_value") or ""))
    age_raw, age_years = extract_age(review_text)
    inseam_in = extract_inseam(review_text)
    submitted_raw, review_date = format_epoch_date(review.get("created_at"))

    return {
        "created_at_display": "",
        "id": str(review.get("id") or ""),
        "original_url_display": image_url,
        "product_page_url_display": product.product_url,
        "monetized_product_url_display": "",
        "height_raw": height_raw,
        "weight_raw": weight_raw,
        "user_comment": normalize_whitespace(" ".join(part for part in [review_title, review_text] if part)),
        "date_review_submitted_raw": submitted_raw,
        "height_in_display": height_in,
        "review_date": review_date,
        "source_site_display": f"{SITE_ROOT}/",
        "status_code": "200",
        "fetched_at": fetched_at,
        "updated_at": fetched_at,
        "brand": "BloomChic",
        "waist_raw_display": waist_raw,
        "hips_raw": hips_raw,
        "age_raw": age_raw,
        "waist_in": waist_in,
        "hips_in_display": hips_in,
        "age_years_display": age_years,
        "search_fts": search_fts([product.title, review_title, review_text, color_display, size_display]),
        "weight_display_display": weight_raw,
        "weight_raw_needs_correction": "",
        "clothing_type_id": classify_clothing_type(product.title, product.product_url),
        "reviewer_profile_url": "",
        "reviewer_name_raw": normalize_whitespace(str(review.get("reviewer_name") or "")),
        "inseam_inches_display": inseam_in,
        "color_canonical": color_display,
        "color_display": color_display,
        "size_display": size_display,
        "bust_in_number_display": bust_in,
        "cupsize_display": "",
        "weight_lbs_display": weight_lbs,
        "weight_lbs_raw_issue": "",
    }


def fetch_image_reviews(product: Product) -> List[Dict[str, object]]:
    reviews: List[Dict[str, object]] = []
    seen_review_ids = set()
    page = 1
    total_count = None

    while True:
        params = {
            "product_handle": product.handle,
            "page": page,
            "page_size": PAGE_SIZE,
            "sort_key": "MEDIA_FIRST",
            "reverse": 1,
        }
        payload = fetch_json(f"{API_ROOT}?{urlencode(params)}", product.product_url)
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            break
        items = data.get("items") or []
        if total_count is None:
            count_value = data.get("count")
            total_count = int(count_value) if isinstance(count_value, int) or str(count_value).isdigit() else None
        if not isinstance(items, list) or not items:
            break

        page_count = 0
        for review in items:
            review_id = str(review.get("id") or "")
            if not review_id or review_id in seen_review_ids:
                continue
            if not image_urls_from_review(review):
                continue
            seen_review_ids.add(review_id)
            reviews.append(review)
            page_count += 1

        if len(items) < PAGE_SIZE:
            break
        if total_count is not None and page * PAGE_SIZE >= total_count:
            break
        if page_count == 0 and page > 1:
            break
        page += 1

    return reviews


def process_product(product: Product, fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    try:
        reviews = fetch_image_reviews(product)
    except Exception as exc:
        return [], {
            "product_url": product.product_url,
            "handle": product.handle,
            "title": product.title,
            "matching_review_images": 0,
            "matching_reviews": 0,
            "error": str(exc),
        }

    rows: List[Dict[str, str]] = []
    review_ids = set()
    for review in reviews:
        review_ids.add(str(review.get("id") or ""))
        for image_url in image_urls_from_review(review):
            rows.append(build_row(product, review, image_url, fetched_at))

    return rows, {
        "product_url": product.product_url,
        "handle": product.handle,
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
        target_path = urlparse(product_url).path.rstrip("/").lower()
        products = [product for product in products if urlparse(product.product_url).path.rstrip("/").lower() == target_path]
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
    parser = argparse.ArgumentParser(description="Scrape BloomChic image reviews into the Amazon schema.")
    parser.add_argument("--product-url", type=str, default=None, help="Only scrape one product URL.")
    parser.add_argument("--limit-products", type=int, default=None, help="Only scrape the first N product URLs.")
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
