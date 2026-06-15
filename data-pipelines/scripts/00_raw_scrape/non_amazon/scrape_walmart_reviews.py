#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import html
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = ROOT / "data-pipelines" / "non-amazon" / "data" / "step_1_raw_scraping_data" / "walmart"
OUTPUT_CSV = OUTPUT_DIR / "walmart_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / "walmart_reviews_matching_amazon_schema_summary.json"

SITE_ROOT = "https://www.walmart.com"
BRAND = "Walmart"
SOURCE_SITE = f"{SITE_ROOT}/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)

DEFAULT_SEARCH_QUERIES = [
    "womens jeans",
    "womens pants",
    "womens tops",
    "womens dresses",
    "womens skirts",
    "womens plus size tops",
    "womens plus size jeans",
]

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
    "content_type",
    "bytes",
    "width",
    "height",
    "hash_md5",
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

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>([\s\S]*?)</script>'
)
HEIGHT_RE = re.compile(
    r"(?:(?:i\s*(?:am|'m)|im|i’m|i am)\s*)?"
    r"(\d)\s*(?:ft|feet|foot|['’])\s*(\d{1,2})?\s*(?:in|inches|[\"”])?",
    re.I,
)
WEIGHT_RE = re.compile(r"\b(?:weigh(?:t|s|ed|ing)?\s*)?(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?)?\b(?=\s*(?:lbs?|pounds?|[,.;]|$))", re.I)
WAIST_RE = re.compile(r"\b(?:waist(?:\s*(?:is|:))?\s*)?(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*waist\b|\bwaist\s*(?:is|:)?\s*(\d{2,3}(?:\.\d+)?)\b", re.I)
HIPS_RE = re.compile(r"\b(?:hips?(?:\s*(?:are|is|:))?\s*)?(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)?\s*hips?\b|\bhips?\s*(?:are|is|:)?\s*(\d{2,3}(?:\.\d+)?)\b", re.I)
BUST_RE = re.compile(r"\b(?:bust|chest)\s*(?:is|:)?\s*(\d{2,3})(?:\s*(?:\"|in(?:ches)?))?\b|\b(\d{2,3})\s*(?:\"|in(?:ches)?)?\s*(?:bust|chest)\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ches)?)\s*inseam\b", re.I)
MEASUREMENT_TRIPLE_RE = re.compile(r"\b(\d{2,3})\s*[-/x]\s*(\d{2,3})\s*[-/x]\s*(\d{2,3})\b")
SIZE_RE = re.compile(
    r"\b(?:size|sz|ordered|wear(?:ing)?|got|bought|purchased|in)\s+"
    r"(?:the\s+)?"
    r"((?:xxs|xs|s|m|l|xl|xxl|xxxl|[2-6]x|[0-9]{1,2}(?:w|p|t| short| long| regular)?|[0-9]{2,3}/[0-9]{2,3}|small|medium|large|x-large|plus))\b",
    re.I,
)

WOMENS_SCOPE_RE = re.compile(r"\b(women|women's|womens|woman|ladies|female|plus size|maternity)\b", re.I)
OUT_OF_SCOPE_RE = re.compile(r"\b(men's|mens|boys|girls|kids|toddler|baby|infant|shoe|shoes|sandal|sandals|boot|boots|bag|purse|handbag|jewelry|watch)\b", re.I)

CLOTHING_PATTERNS: Sequence[Tuple[str, str]] = (
    ("jeans", "jeans"),
    ("jegging", "jeans"),
    ("pants", "pants"),
    ("legging", "pants"),
    ("trouser", "pants"),
    ("dress", "dress"),
    ("skirt", "skirt"),
    ("blouse", "top"),
    ("shirt", "top"),
    ("top", "top"),
    ("tee", "top"),
    ("t-shirt", "top"),
    ("sweater", "top"),
    ("sweatshirt", "top"),
    ("cardigan", "top"),
)

COLOR_WORDS = [
    "black",
    "blue",
    "brown",
    "green",
    "grey",
    "gray",
    "ivory",
    "khaki",
    "navy",
    "pink",
    "purple",
    "red",
    "tan",
    "white",
    "yellow",
]


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch_text(url: str, retries: int = 4) -> str:
    # Walmart blocks Python's default TLS/client fingerprint more aggressively
    # than curl. Use curl first because it matches browser-ish probing better.
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-L",
                    "-sS",
                    "--max-time",
                    "45",
                    "-A",
                    USER_AGENT,
                    "-H",
                    "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "-H",
                    "Accept-Language: en-US,en;q=0.9",
                    url,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as exc:
            last_error = exc
        time.sleep(min(2**attempt, 12))
    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def extract_next_data(html_text: str) -> Dict[str, object]:
    match = NEXT_DATA_RE.search(html_text)
    if not match:
        raise ValueError("Could not find __NEXT_DATA__ JSON")
    return json.loads(html.unescape(match.group(1)))


def parse_number(match: Optional[re.Match[str]]) -> str:
    if not match:
        return ""
    for group in match.groups():
        if group:
            return group
    return ""


def parse_height(text: str) -> Tuple[str, str]:
    match = HEIGHT_RE.search(text)
    if not match:
        return "", ""
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    raw = match.group(0)
    if feet < 4 or feet > 7 or inches > 11:
        return raw, ""
    return raw, str(feet * 12 + inches)


def parse_size(text: str) -> str:
    match = SIZE_RE.search(text)
    if match:
        return normalize_size(match.group(1))
    return ""


def normalize_size(size: str) -> str:
    value = normalize_whitespace(size).strip(".,;:!)(")
    lookup = {
        "x-small": "XS",
        "small": "S",
        "medium": "M",
        "large": "L",
        "x-large": "XL",
    }
    return lookup.get(value.lower(), value.upper() if re.fullmatch(r"[a-z0-9]+", value, re.I) else value)


def normalize_review_date(value: str) -> str:
    value = normalize_whitespace(value)
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return value


def classify_clothing_type(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("swimsuit", "swimwear", "bathing suit", "swim dress", "swimdress", "bikini")):
        return ""
    for needle, clothing_type in CLOTHING_PATTERNS:
        if needle in lowered:
            return clothing_type
    return ""


def infer_color(text: str) -> str:
    lowered = text.lower()
    for color in COLOR_WORDS:
        if re.search(rf"\b{re.escape(color)}\b", lowered):
            return color
    return ""


def is_womens_clothing(product: Dict[str, object]) -> bool:
    name = str(product.get("name") or "")
    product_type = str(product.get("type") or "")
    category = " ".join(
        str(item.get("name") or "")
        for item in (((product.get("category") or {}).get("path") or []) if isinstance(product.get("category"), dict) else [])
        if isinstance(item, dict)
    )
    haystack = f"{name} {product_type} {category}"
    return bool(WOMENS_SCOPE_RE.search(haystack)) and not bool(OUT_OF_SCOPE_RE.search(haystack))


def product_url_from_path(path: str) -> str:
    clean_path = path.split("?")[0]
    return urljoin(SITE_ROOT, clean_path)


def discover_products(search_queries: Sequence[str], limit_products: int) -> List[Dict[str, str]]:
    products: List[Dict[str, str]] = []
    seen = set()
    for query in search_queries:
        url = f"{SITE_ROOT}/search?{urlencode({'q': query})}"
        try:
            data = extract_next_data(fetch_text(url))
        except Exception as exc:
            print(f"Search failed for {query!r}: {exc}", file=sys.stderr)
            continue
        initial = ((data.get("props") or {}).get("pageProps") or {}).get("initialData") or {}
        search_result = initial.get("searchResult") or {}
        stacks = search_result.get("itemStacks") or []
        for stack in stacks:
            for item in stack.get("items") or []:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("usItemId") or "")
                name = str(item.get("name") or "")
                canonical = str(item.get("canonicalUrl") or "")
                if not item_id or not canonical or item_id in seen:
                    continue
                if not WOMENS_SCOPE_RE.search(name) or OUT_OF_SCOPE_RE.search(name):
                    continue
                seen.add(item_id)
                products.append(
                    {
                        "item_id": item_id,
                        "name": name,
                        "product_page_url": product_url_from_path(canonical),
                        "search_query": query,
                        "review_count": str(item.get("numberOfReviews") or ""),
                    }
                )
                if len(products) >= limit_products:
                    return products
    return products


def product_seed(item_id: str) -> Dict[str, str]:
    return {
        "item_id": item_id,
        "name": "",
        "product_page_url": f"{SITE_ROOT}/ip/{item_id}",
        "search_query": "seeded product id",
        "review_count": "",
    }


def parse_review_page(item_id: str, page: int) -> Tuple[Dict[str, object], Dict[str, object]]:
    query = {"filter": "withPhotos"}
    if page > 1:
        query["page"] = str(page)
    url = f"{SITE_ROOT}/reviews/product/{item_id}?{urlencode(query)}"
    data = extract_next_data(fetch_text(url))
    initial = ((data.get("props") or {}).get("pageProps") or {}).get("initialData") or {}
    page_data = initial.get("data") or {}
    return page_data.get("product") or {}, page_data.get("reviews") or {}


def row_from_review(
    product: Dict[str, object],
    review: Dict[str, object],
    media: Dict[str, object],
    fetched_at: str,
) -> Optional[Dict[str, str]]:
    image_url = str(media.get("normalUrl") or media.get("thumbnailUrl") or "")
    if not image_url or str(media.get("mediaType") or "").upper() != "IMAGE":
        return None

    product_name = str(product.get("name") or "")
    product_url = product_url_from_path(str(product.get("canonicalUrl") or ""))
    review_title = normalize_whitespace(str(review.get("reviewTitle") or ""))
    review_text = normalize_whitespace(str(review.get("reviewText") or ""))
    combined_review = normalize_whitespace(f"{review_title} {review_text}")
    if not combined_review:
        return None

    height_raw, height_in = parse_height(combined_review)
    weight = parse_number(WEIGHT_RE.search(combined_review))
    waist = parse_number(WAIST_RE.search(combined_review))
    hips = parse_number(HIPS_RE.search(combined_review))
    bust = parse_number(BUST_RE.search(combined_review))
    triple = MEASUREMENT_TRIPLE_RE.search(combined_review)
    if triple:
        bust = bust or triple.group(1)
        waist = waist or triple.group(2)
        hips = hips or triple.group(3)
    age = parse_number(AGE_RE.search(combined_review))
    inseam = parse_number(INSEAM_RE.search(combined_review))
    size = parse_size(combined_review)

    review_date_raw = normalize_whitespace(str(review.get("reviewSubmissionTime") or ""))
    color = infer_color(f"{product_name} {combined_review}")
    clothing_type = classify_clothing_type(product_name)
    user_comment = combined_review
    row_id = f"walmart-{review.get('reviewId') or review.get('reviewReferenceId')}-{media.get('id') or abs(hash(image_url))}"

    return {
        "created_at_display": "",
        "id": row_id,
        "original_url_display": image_url,
        "product_page_url_display": product_url,
        "monetized_product_url_display": "",
        "height_raw": height_raw,
        "weight_raw": weight,
        "user_comment": user_comment,
        "date_review_submitted_raw": review_date_raw,
        "height_in_display": height_in,
        "review_date": normalize_review_date(review_date_raw),
        "source_site_display": SOURCE_SITE,
        "status_code": "200",
        "content_type": "",
        "bytes": "",
        "width": "",
        "height": "",
        "hash_md5": "",
        "fetched_at": fetched_at,
        "updated_at": fetched_at,
        "brand": BRAND,
        "waist_raw_display": waist,
        "hips_raw": hips,
        "age_raw": age,
        "waist_in": waist,
        "hips_in_display": hips,
        "age_years_display": age,
        "search_fts": normalize_whitespace(f"{product_name} {product.get('type') or ''} {user_comment}"),
        "weight_display_display": weight,
        "weight_raw_needs_correction": "",
        "clothing_type_id": clothing_type,
        "reviewer_profile_url": "",
        "reviewer_name_raw": normalize_whitespace(str(review.get("userNickname") or "")),
        "inseam_inches_display": inseam,
        "color_canonical": color,
        "color_display": color,
        "size_display": size,
        "bust_in_number_display": bust,
        "cupsize_display": "",
        "weight_lbs_display": weight,
        "weight_lbs_raw_issue": "",
    }


def scrape(
    search_queries: Sequence[str],
    limit_products: int,
    review_pages: int,
    product_ids: Sequence[str] = (),
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = datetime.now(timezone.utc).isoformat()
    fetched_at = started_at
    products: List[Dict[str, str]] = []
    seen_product_ids = set()
    for item_id in product_ids:
        clean_id = normalize_whitespace(item_id)
        if not clean_id or clean_id in seen_product_ids:
            continue
        seen_product_ids.add(clean_id)
        products.append(product_seed(clean_id))

    remaining_limit = max(limit_products - len(products), 0)
    if remaining_limit:
        for product in discover_products(search_queries, remaining_limit):
            item_id = product["item_id"]
            if item_id in seen_product_ids:
                continue
            seen_product_ids.add(item_id)
            products.append(product)
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    seen_rows = set()

    for index, discovered in enumerate(products, start=1):
        item_id = discovered["item_id"]
        product_rows = 0
        reviews_seen = 0
        media_seen = 0
        errors: List[str] = []
        product_name = discovered["name"]
        total_media_count = None
        total_review_count = None

        for page in range(1, review_pages + 1):
            try:
                product, reviews_data = parse_review_page(item_id, page)
            except Exception as exc:
                errors.append(f"page {page}: {exc}")
                continue
            if product:
                product_name = str(product.get("name") or product_name)
                product_url = product_url_from_path(str(product.get("canonicalUrl") or ""))
                if product_url != SITE_ROOT:
                    discovered["product_page_url"] = product_url
            if product and not is_womens_clothing(product):
                errors.append("skipped: product metadata is outside women's clothing scope")
                break
            total_media_count = reviews_data.get("totalMediaCount", total_media_count)
            total_review_count = reviews_data.get("totalReviewCount", total_review_count)
            customer_reviews = reviews_data.get("customerReviews") or []
            if not customer_reviews:
                break
            for review in customer_reviews:
                if not isinstance(review, dict):
                    continue
                reviews_seen += 1
                media_items = review.get("media") or review.get("photos") or []
                for media in media_items:
                    if not isinstance(media, dict):
                        continue
                    media_seen += 1
                    row = row_from_review(product, review, media, fetched_at)
                    if not row:
                        continue
                    key = (row["id"], row["original_url_display"])
                    if key in seen_rows:
                        continue
                    seen_rows.add(key)
                    rows.append(row)
                    product_rows += 1

        product_summaries.append(
            {
                "item_id": item_id,
                "name": product_name,
                "product_page_url": discovered["product_page_url"],
                "search_query": discovered["search_query"],
                "listed_review_count": discovered.get("review_count", ""),
                "total_review_count": total_review_count,
                "total_media_count": total_media_count,
                "reviews_seen": reviews_seen,
                "media_seen": media_seen,
                "rows_written": product_rows,
                "errors": errors,
            }
        )
        print(
            f"[{index}/{len(products)}] {item_id}: {product_rows} rows from {media_seen} media "
            f"({product_name[:80]})",
            flush=True,
        )

    summary = {
        "site": SITE_ROOT,
        "scope": "women's clothing only",
        "search_queries": list(search_queries),
        "seed_product_ids": list(product_ids),
        "products_scanned": len(products),
        "review_pages_per_product": review_pages,
        "rows_written": len(rows),
        "distinct_reviews": len({row["id"].rsplit("-", 1)[0] for row in rows}),
        "distinct_images": len({row["original_url_display"] for row in rows}),
        "output_csv": str(OUTPUT_CSV),
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "product_summaries": product_summaries,
    }
    return rows, summary


def write_csv(rows: Iterable[Dict[str, str]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in HEADERS})


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Walmart women's clothing photo reviews into the Amazon schema.")
    parser.add_argument("--query", action="append", dest="queries", help="Walmart search query. May be repeated.")
    parser.add_argument("--product-id", action="append", dest="product_ids", help="Walmart product ID to scan directly. May be repeated.")
    parser.add_argument("--limit-products", type=int, default=35, help="Maximum discovered products to scan.")
    parser.add_argument("--review-pages", type=int, default=3, help="Photo-review pages to scan per product.")
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV, help="CSV output path.")
    args = parser.parse_args(argv)

    queries = args.queries or DEFAULT_SEARCH_QUERIES
    rows, summary = scrape(queries, args.limit_products, args.review_pages, args.product_ids or [])
    write_csv(rows, args.output)
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote {len(rows)} rows to {args.output}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
