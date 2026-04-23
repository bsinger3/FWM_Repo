#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import html
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = ROOT / "data-pipelines" / "non-amazon" / "data" / "step_1_raw_scraping_data" / "harper_wilde"
OUTPUT_CSV = OUTPUT_DIR / "harper_wilde_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "harper_wilde_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://harperwilde.com"
SITEMAP_INDEX_URL = f"{SITE_ROOT}/sitemap.xml"
JUDGEME_WIDGET_URL = "https://api.judge.me/reviews/reviews_for_widget"

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
USER_AGENT = "Mozilla/5.0 (compatible; CodexHarperWildeScraper/1.0; +https://harperwilde.com)"

GENERIC_SIZE_RE = re.compile(
    r"\b("
    r"xxs|xxs/xs|xs|x-small|extra small|small|s|medium|med|m|large|l|xl|x-large|extra large|"
    r"xxl|2xl|xx-large|2x|xxxl|3xl|3x|"
    r"\d{1,2}"
    r")\b",
    re.I,
)
BRA_SIZE_RE = re.compile(
    r"\b(28|30|32|34|36|38|40|42|44|46|48)\s*(AAA|AA|A|B|C|D|DD/?E|DDD/?F|F|G|H|I|J)\b",
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


@dataclass
class ReviewRecord:
    review_id: str
    product_path: str
    product_title: str
    author: str
    title: str
    body: str
    size_value: str
    timestamp_raw: str
    image_urls: List[str]


def fetch_text(url: str, params: Optional[Dict[str, object]] = None, retries: int = 6) -> str:
    if params:
        url = f"{url}?{urlencode(params)}"
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/json,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        try:
            with urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
        except URLError as exc:
            last_error = exc
        sleep_seconds = min(2 ** attempt, 20)
        time.sleep(sleep_seconds)
    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def fetch_json(url: str, params: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    return json.loads(fetch_text(url, params))


def get_product_sitemap_urls() -> List[str]:
    root = ET.fromstring(fetch_text(SITEMAP_INDEX_URL))
    urls = []
    for loc in root.findall(".//sm:loc", NS):
        value = (loc.text or "").strip()
        if "sitemap_products_" in value:
            urls.append(value)
    return urls


def get_product_urls() -> List[str]:
    product_urls: List[str] = []
    seen = set()
    for sitemap_url in get_product_sitemap_urls():
        root = ET.fromstring(fetch_text(sitemap_url))
        for loc in root.findall(".//sm:url/sm:loc", NS):
            value = (loc.text or "").strip()
            if "/products/" not in value:
                continue
            if value not in seen:
                seen.add(value)
                product_urls.append(value)
    return product_urls


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def strip_tags(fragment: str) -> str:
    cleaned = fragment.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    cleaned = re.sub(r"</p\s*>", "\n", cleaned, flags=re.I)
    cleaned = re.sub(r"<p[^>]*>", "", cleaned, flags=re.I)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = cleaned.replace("\xa0", " ")
    return normalize_whitespace(cleaned)


def find_matching_div_end(html_fragment: str, start_index: int) -> int:
    depth = 0
    for match in re.finditer(r"</?div\b[^>]*>", html_fragment[start_index:], flags=re.I):
        token = match.group(0)
        if token.lower().startswith("</div"):
            depth -= 1
            if depth == 0:
                return start_index + match.end()
        else:
            depth += 1
    return len(html_fragment)


def extract_review_blocks(widget_html: str) -> List[str]:
    blocks: List[str] = []
    marker = "<div class='jdgm-rev jdgm-divider-top'"
    cursor = 0
    while True:
        start = widget_html.find(marker, cursor)
        if start == -1:
            break
        end = find_matching_div_end(widget_html, start)
        blocks.append(widget_html[start:end])
        cursor = end
    return blocks


def parse_review_block(block: str) -> Optional[ReviewRecord]:
    def attr(name: str) -> str:
        match = re.search(rf"{re.escape(name)}='([^']*)'", block)
        return html.unescape(match.group(1)).strip() if match else ""

    title_match = re.search(r"<b class='jdgm-rev__title'>(.*?)</b>", block, flags=re.S)
    body_match = re.search(r"<div class='jdgm-rev__body'>(.*?)</div>", block, flags=re.S)
    author_match = re.search(r"<span class='jdgm-rev__author'>(.*?)</span>", block, flags=re.S)
    size_match = re.search(
        r"<b class='jdgm-rev__cf-ans__title'>\s*Size:\s*</b>\s*<span class='jdgm-rev__cf-ans__value'>(.*?)</span>",
        block,
        flags=re.S | re.I,
    )
    image_urls = []
    for image_match in re.finditer(r"data-mfp-src='([^']+)'", block):
        image_url = html.unescape(image_match.group(1)).replace("&amp;", "&")
        if image_url not in image_urls:
            image_urls.append(image_url)

    review_id = attr("data-review-id")
    product_path = attr("data-product-url")
    if not review_id or not product_path:
        return None

    return ReviewRecord(
        review_id=review_id,
        product_path=product_path,
        product_title=attr("data-product-title"),
        author=strip_tags(author_match.group(1) if author_match else ""),
        title=strip_tags(title_match.group(1) if title_match else ""),
        body=strip_tags(body_match.group(1) if body_match else ""),
        size_value=normalize_whitespace(strip_tags(size_match.group(1))) if size_match else "",
        timestamp_raw=attr("data-content"),
        image_urls=image_urls,
    )


def canonical_color_from_title(title: str) -> Tuple[str, str]:
    if " - " not in title:
        return "", ""
    color = title.rsplit(" - ", 1)[-1].strip()
    return color.lower(), color


def classify_clothing_type(product_title: str, product_type: str) -> str:
    value = f"{product_title} {product_type}".lower()
    if "bralette" in value:
        return "bralette"
    if "bra" in value:
        return "bra"
    if "brief" in value or "thong" in value or "bikini" in value or "hiphugger" in value or "underwear" in value:
        return "underwear"
    if "tank" in value:
        return "tank"
    if "bodysuit" in value:
        return "bodysuit"
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
    }
    return mapping.get(size, value.strip())


def extract_size_from_text(text: str) -> str:
    explicit_patterns = [
        r"\b(?:ordered|bought|purchased|got|wear|wearing|picked|choose|chose)\s+(?:the\s+)?(?:a\s+)?size\s+([a-z0-9\-/ ]+?)(?:[.,;]|$)",
        r"\bsize\s+([a-z0-9\-/ ]+?)(?:\s+fits|\s+fit|[.,;]|$)",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text, re.I)
        if match:
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


def normalize_bra_size(value: str) -> str:
    collapsed = normalize_whitespace(value).upper().replace(" ", "")
    collapsed = collapsed.replace("DDD/E", "DDD/E")
    if collapsed == "DDE":
        return "DD/E"
    if collapsed == "DDDE":
        return "DDD/E"
    return collapsed


def extract_height(text: str) -> Tuple[str, str]:
    match = HEIGHT_RE.search(text)
    if not match:
        return "", ""
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    total_inches = feet * 12 + inches
    return f"{feet}'{inches}\"" if match.group(2) else f"{feet}'0\"", str(total_inches)


def extract_numeric_field(pattern: re.Pattern[str], text: str, suffix: str = "") -> Tuple[str, str]:
    match = pattern.search(text)
    if not match:
        return "", ""
    raw = normalize_whitespace(match.group(0))
    value = match.group(1)
    return raw, value + suffix if suffix else value


def extract_weight(text: str) -> Tuple[str, str]:
    raw, value = extract_numeric_field(WEIGHT_RE, text)
    return raw, value


def extract_age(text: str) -> Tuple[str, str]:
    raw, value = extract_numeric_field(AGE_RE, text)
    return raw, value


def extract_waist(text: str) -> Tuple[str, str]:
    raw, value = extract_numeric_field(WAIST_RE, text)
    return raw, value


def extract_hips(text: str) -> Tuple[str, str]:
    raw, value = extract_numeric_field(HIPS_RE, text)
    return raw, value


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


def has_measurement(data: Dict[str, str]) -> bool:
    keys = [
        "height_raw",
        "weight_raw",
        "waist_raw_display",
        "hips_raw",
        "age_raw",
        "inseam_inches_display",
        "bust_in_number_display",
        "cupsize_display",
    ]
    return any(data.get(key) for key in keys)


def date_fields(timestamp_raw: str) -> Tuple[str, str]:
    if not timestamp_raw:
        return "", ""
    dt = datetime.strptime(timestamp_raw, "%Y-%m-%d %H:%M:%S UTC")
    review_date = dt.date().isoformat()
    submitted = dt.strftime("%B %d, %Y").replace(" 0", " ")
    return submitted, review_date


def search_fts(parts: Sequence[str]) -> str:
    return normalize_whitespace(" ".join(part for part in parts if part))


def build_row(
    product: Dict[str, object],
    product_url: str,
    review: ReviewRecord,
    image_url: str,
    fetched_at: str,
) -> Dict[str, str]:
    body_text = review.body
    size_display = normalize_bra_size(review.size_value) if BRA_SIZE_RE.search(review.size_value) else normalize_whitespace(review.size_value)
    if not size_display:
        size_display = extract_size_from_text(body_text)
    elif not BRA_SIZE_RE.search(size_display):
        size_display = normalize_generic_size(size_display)

    height_raw, height_in = extract_height(body_text)
    weight_raw, weight_lbs = extract_weight(body_text)
    waist_raw, waist_in = extract_waist(body_text)
    hips_raw, hips_in = extract_hips(body_text)
    age_raw, age_years = extract_age(body_text)
    inseam_in = extract_inseam(body_text)
    bust_band, cup_size = extract_bra_measurement(size_display, body_text)
    submitted_raw, review_date = date_fields(review.timestamp_raw)
    resolved_product_url = urljoin(SITE_ROOT, review.product_path or urlparse(product_url).path)
    resolved_product_title = str(review.product_title or product.get("title") or "")
    color_canonical, color_display = canonical_color_from_title(resolved_product_title)

    return {
        "created_at_display": "",
        "id": review.review_id,
        "original_url_display": image_url,
        "product_page_url_display": resolved_product_url,
        "monetized_product_url_display": "",
        "height_raw": height_raw,
        "weight_raw": weight_raw,
        "user_comment": normalize_whitespace(" ".join(part for part in [review.title, body_text] if part)),
        "date_review_submitted_raw": submitted_raw,
        "height_in_display": height_in,
        "review_date": review_date,
        "source_site_display": f"{SITE_ROOT}/",
        "status_code": "200",
        "fetched_at": fetched_at,
        "updated_at": fetched_at,
        "brand": str(product.get("vendor") or "Harper Wilde"),
        "waist_raw_display": waist_raw,
        "hips_raw": hips_raw,
        "age_raw": age_raw,
        "waist_in": waist_in,
        "hips_in_display": hips_in,
        "age_years_display": age_years,
        "search_fts": search_fts([resolved_product_title, review.title, body_text, size_display, color_display]),
        "weight_display_display": weight_raw,
        "weight_raw_needs_correction": "",
        "clothing_type_id": classify_clothing_type(resolved_product_title, str(product.get("type") or "")),
        "reviewer_profile_url": "",
        "reviewer_name_raw": review.author,
        "inseam_inches_display": inseam_in,
        "color_canonical": color_canonical,
        "color_display": color_display,
        "size_display": size_display,
        "bust_in_number_display": bust_band,
        "cupsize_display": cup_size,
        "weight_lbs_display": weight_lbs,
        "weight_lbs_raw_issue": "",
    }


def product_json_url(product_url: str) -> str:
    parsed = urlparse(product_url)
    return urljoin(f"{parsed.scheme}://{parsed.netloc}", f"{parsed.path}.js")


def get_product_json(product_url: str) -> Dict[str, object]:
    return fetch_json(product_json_url(product_url))


def fetch_picture_reviews_for_product(product_url: str, product_id: int) -> List[ReviewRecord]:
    parsed = urlparse(product_url)
    all_reviews: List[ReviewRecord] = []
    seen_review_ids = set()
    for page in range(1, 6):
        payload = fetch_json(
            JUDGEME_WIDGET_URL,
            {
                "url": parsed.netloc,
                "shop_domain": parsed.netloc,
                "platform": "shopify",
                # Judge.me's image-heavy sort stops returning image links when
                # `per_page` is too large. `20` reliably matches the browser UI.
                "per_page": 20,
                "page": page,
                "product_id": product_id,
                "sort_by": "with_pictures",
            },
        )
        widget_html = html.unescape(str(payload.get("html") or ""))
        blocks = extract_review_blocks(widget_html)
        if not blocks:
            break

        page_reviews = 0
        for block in blocks:
            review = parse_review_block(block)
            if not review:
                continue
            if not review.image_urls:
                continue
            if review.review_id in seen_review_ids:
                continue
            seen_review_ids.add(review.review_id)
            all_reviews.append(review)
            page_reviews += 1

        if page_reviews == 0:
            break

    return all_reviews


def review_meets_requirements(row: Dict[str, str]) -> bool:
    return bool(row["original_url_display"])


def process_product(product_url: str, fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    try:
        product = get_product_json(product_url)
        product_reviews = fetch_picture_reviews_for_product(product_url, int(product["id"]))
    except Exception as exc:
        return [], {
            "product_url": product_url,
            "product_id": "",
            "title": "",
            "matching_review_images": 0,
            "matching_reviews": 0,
            "error": str(exc),
        }

    product_rows: List[Dict[str, str]] = []
    product_review_ids = set()

    for review in product_reviews:
        for image_url in review.image_urls:
            row = build_row(product, product_url, review, image_url, fetched_at)
            if not review_meets_requirements(row):
                continue
            product_rows.append(row)
            product_review_ids.add(review.review_id)

    product_summary = {
        "product_url": product_url,
        "product_id": product["id"],
        "title": product.get("title"),
        "matching_review_images": len(product_rows),
        "matching_reviews": len(product_review_ids),
    }
    return product_rows, product_summary


def scrape(limit_products: Optional[int] = None, max_workers: int = 8) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    product_urls = get_product_urls()
    if limit_products is not None:
        product_urls = product_urls[:limit_products]

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows: List[Dict[str, str]] = []

    summary: Dict[str, object] = {
        "scraped_at": fetched_at,
        "site_root": SITE_ROOT,
        "products_seen": 0,
        "products_with_matching_rows": 0,
        "review_images_exported": 0,
        "review_ids_exported": 0,
        "product_summaries": [],
    }

    exported_review_ids = set()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(process_product, product_url, fetched_at): product_url for product_url in product_urls}
        for index, future in enumerate(as_completed(future_map), start=1):
            product_url = future_map[future]
            product_rows, product_summary = future.result()
            rows.extend(product_rows)
            if product_rows:
                summary["products_with_matching_rows"] = int(summary["products_with_matching_rows"]) + 1
            summary["products_seen"] = index
            summary["product_summaries"].append(product_summary)
            for row in product_rows:
                row_key = f"{row['product_page_url_display']}::{row['original_url_display']}::{row['reviewer_name_raw']}::{row['review_date']}"
                exported_review_ids.add(row_key)
            print(
                f"[{index}/{len(product_urls)}] {product_summary.get('title') or product_url} -> {product_summary['matching_review_images']} matching image rows"
                + (f" (error: {product_summary['error']})" if product_summary.get("error") else ""),
                flush=True,
            )

    deduped_rows: List[Dict[str, str]] = []
    seen_row_keys = set()
    for row in rows:
        row_key = (
            row["id"],
            row["product_page_url_display"],
            row["original_url_display"],
        )
        if row_key in seen_row_keys:
            continue
        seen_row_keys.add(row_key)
        deduped_rows.append(row)

    summary["review_images_exported"] = len(deduped_rows)
    summary["review_ids_exported"] = len({row["id"] for row in deduped_rows if row.get("id")})
    return deduped_rows, summary


def write_csv(rows: Iterable[Dict[str, str]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in HEADERS})


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Harper Wilde review-image rows into the Amazon schema.")
    parser.add_argument("--limit-products", type=int, default=None, help="Only scrape the first N product URLs for a quicker test run.")
    parser.add_argument("--max-workers", type=int, default=8, help="Number of product fetches to run in parallel.")
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV, help="CSV output path.")
    args = parser.parse_args(argv)

    rows, summary = scrape(limit_products=args.limit_products, max_workers=args.max_workers)
    write_csv(rows, args.output)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote {len(rows)} rows to {args.output}")
    print(f"Products scanned: {summary['products_seen']}")
    print(f"Products with matches: {summary['products_with_matching_rows']}")
    print(f"Unique reviews exported: {summary['review_ids_exported']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
