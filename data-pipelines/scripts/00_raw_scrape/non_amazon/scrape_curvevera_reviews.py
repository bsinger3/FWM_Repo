#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from step1_intake_utils import (
    INTAKE_HEADERS,
    ProductContext,
    ReviewImage,
    build_intake_row,
    canonical_product_url,
    dedupe_rows,
    normalize_whitespace,
    strip_tags,
    utc_now,
    write_intake_csv,
)

try:
    from step1_intake_utils import STEP1_OUTPUT_ROOT
except ImportError:  # pragma: no cover
    STEP1_OUTPUT_ROOT = Path(__file__).resolve().parents[4] / "data-pipelines" / "non-amazon" / "data" / "step_1_raw_scraping_data"


SITE_ROOT = "https://curvevera.com"
SOURCE_SITE = f"{SITE_ROOT}/"
RETAILER = "curvevera_com"
SITEMAP_URL = f"{SITE_ROOT}/sitemap.xml"
LOOX_ROOT = "https://loox.io"
LOOX_CLIENT_ID = "8bWI6_5y-z"
SHOPIFY_DOMAIN = "ty7zmn-a6.myshopify.com"
PRODUCTS_PER_PAGE = 250
REVIEWS_PER_PAGE = 20

OUTPUT_DIR = STEP1_OUTPUT_ROOT / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.csv"
PRODUCT_TAXONOMY_JSON = OUTPUT_DIR / f"{RETAILER}_product_taxonomy_signals.json"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 FWM"
)
PRESSURE_STATUS_CODES = {401, 403, 407, 408, 409, 423, 429, 430, 503}
BLOCK_MARKERS = [
    "Just a moment...",
    "challenges.cloudflare.com",
    "cf-chl",
    "datadome",
    "Please verify you are a human",
    "verify you are human",
    "Access denied",
]

REVIEW_CARD_RE = re.compile(
    r"(<div[^>]+data-id=[\"'][^\"']+[\"'][^>]+class=[\"'][^\"']*grid-item-wrap[^\"']*[\"'][\s\S]*?)"
    r"(?=<div[^>]+data-id=[\"'][^\"']+[\"'][^>]+class=[\"'][^\"']*grid-item-wrap|</div><div[^>]+style=[\"']text-align:center;padding:20px)",
    re.I,
)


class PressureStop(RuntimeError):
    pass


@dataclass
class ProductTaxonomySignals:
    product_url: str
    normalized_product_page_url: str
    source_site: str
    shopify_product_id: str = ""
    handle: str = ""
    brand: str = ""
    product_title_raw: str = ""
    product_description_raw: str = ""
    product_category_raw: str = ""
    product_tags_raw: str = ""
    category_breadcrumb_path: str = ""
    title: str = ""
    breadcrumb: str = ""
    url_slug: str = ""
    json_ld_product_core: str = ""
    json_ld_product_description: str = ""
    description: str = ""
    loox_review_count_hint: int = 0
    loox_rating_value_hint: str = ""
    loox_hash: str = ""
    fetched_at: str = ""
    raw_signal_notes: List[str] = field(default_factory=list)


def request_text(
    url: str,
    *,
    accept: str = "text/html,application/xml;q=0.9,*/*;q=0.8",
    referer: str = SOURCE_SITE,
    retries: int = 4,
    timeout: int = 45,
) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        req = Request(
            iri_to_uri(url),
            headers={
                "User-Agent": USER_AGENT,
                "Accept": accept,
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": referer,
            },
        )
        try:
            with urlopen(req, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                text = response.read().decode("utf-8-sig", "replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code in PRESSURE_STATUS_CODES:
                raise PressureStop(f"blocked_or_rate_limited_http_{exc.code}: {url}") from exc
            if exc.code not in {408, 500, 502, 504}:
                raise
            time.sleep(min(2 ** attempt, 12))
            continue
        except URLError as exc:
            last_error = exc
            time.sleep(min(2 ** attempt, 12))
            continue
        if status in PRESSURE_STATUS_CODES:
            raise PressureStop(f"blocked_or_rate_limited_http_{status}: {url}")
        lower = text[:8000].lower()
        if any(marker.lower() in lower for marker in BLOCK_MARKERS):
            raise PressureStop(f"blocked_or_challenged_response: {url}")
        return text
    raise RuntimeError(f"failed_request: {url}: {last_error}")


def request_json(url: str, *, referer: str = SOURCE_SITE) -> Dict[str, object]:
    text = request_text(url, accept="application/json,text/plain,*/*", referer=referer)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise PressureStop(f"unexpected_json_response: {url}")
    return payload


def iri_to_uri(url: str) -> str:
    parts = urlsplit(url)
    netloc = parts.netloc.encode("idna").decode("ascii") if parts.netloc else ""
    path = quote(parts.path, safe="/%:@")
    query = quote(parts.query, safe="=&?/:;+,%@")
    fragment = quote(parts.fragment, safe="=&?/:;+,%@")
    return urlunsplit((parts.scheme, netloc, path, query, fragment))


def discover_product_urls(limit: Optional[int] = None) -> Tuple[List[str], Dict[str, object]]:
    sitemap_index = request_text(SITEMAP_URL)
    sitemap_urls = [
        unescape(url).replace("&amp;", "&")
        for url in re.findall(r"<loc>(.*?)</loc>", sitemap_index, flags=re.I)
        if "sitemap_products_" in url and "/products/" not in url and re.match(r"https://curvevera\.com/sitemap_products_", unescape(url))
    ]
    if not sitemap_urls:
        sitemap_urls = [f"{SITE_ROOT}/sitemap_products_1.xml"]

    seen: set[str] = set()
    products: List[str] = []
    pages: List[Dict[str, object]] = []
    for sitemap_url in sitemap_urls:
        xml = request_text(sitemap_url)
        urls = [
            canonical_product_url(unescape(url))
            for url in re.findall(r"<loc>(https://curvevera\.com/products/[^<]+)</loc>", xml, flags=re.I)
        ]
        pages.append({"url": sitemap_url, "product_urls": len(urls)})
        for product_url in urls:
            if product_url in seen:
                continue
            seen.add(product_url)
            products.append(product_url)
            if limit and len(products) >= limit:
                return products, {"sitemap_index": SITEMAP_URL, "product_sitemaps": pages, "unique_product_urls": len(products)}
    return products, {"sitemap_index": SITEMAP_URL, "product_sitemaps": pages, "unique_product_urls": len(products)}


def product_json_url(product_url: str) -> str:
    parsed = urlparse(product_url)
    return urljoin(f"{parsed.scheme}://{parsed.netloc}", f"{parsed.path.rstrip('/')}.json")


def product_handle(product_url: str) -> str:
    path = urlparse(product_url).path
    if "/products/" not in path:
        return ""
    return path.split("/products/", 1)[1].split("/", 1)[0].removesuffix(".json").removesuffix(".js")


def first_match(patterns: Sequence[str], text: str, flags: int = re.I | re.S) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return normalize_whitespace(unescape(match.group(1)))
    return ""


def meta_content(html_text: str, key: str, value: str) -> str:
    patterns = [
        rf"<meta[^>]+{key}=[\"']{re.escape(value)}[\"'][^>]+content=[\"']([^\"']+)[\"']",
        rf"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+{key}=[\"']{re.escape(value)}[\"']",
    ]
    return first_match(patterns, html_text)


def extract_json_ld_blocks(html_text: str) -> List[object]:
    blocks: List[object] = []
    for block in re.findall(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>([\s\S]*?)</script>", html_text, re.I):
        try:
            blocks.append(json.loads(unescape(block.strip())))
        except json.JSONDecodeError:
            continue
    return blocks


def iter_json_objects(value: object) -> Iterable[Dict[str, object]]:
    if isinstance(value, dict):
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from iter_json_objects(item)
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from iter_json_objects(item)


def json_ld_product(html_text: str) -> Dict[str, object]:
    for block in extract_json_ld_blocks(html_text):
        for item in iter_json_objects(block):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(type_name).lower() in {"product", "productgroup"} for type_name in types):
                return item
    return {}


def json_ld_breadcrumb(html_text: str) -> str:
    for block in extract_json_ld_blocks(html_text):
        for item in iter_json_objects(block):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if not any(str(type_name).lower() == "breadcrumblist" for type_name in types):
                continue
            elements = item.get("itemListElement")
            if not isinstance(elements, list):
                continue
            names: List[str] = []
            for element in elements:
                if not isinstance(element, dict):
                    continue
                name = normalize_whitespace(element.get("name"))
                if name:
                    names.append(name)
            if names:
                return " > ".join(names)
    return ""


def html_breadcrumb(html_text: str) -> str:
    chunks = re.findall(
        r"<(?:nav|ol|ul|div)[^>]+(?:breadcrumb|breadcrumbs)[^>]*>([\s\S]*?)</(?:nav|ol|ul|div)>",
        html_text,
        flags=re.I,
    )
    for chunk in chunks:
        parts = [strip_tags(part) for part in re.findall(r"<a[^>]*>([\s\S]*?)</a>|<span[^>]*>([\s\S]*?)</span>|<li[^>]*>([\s\S]*?)</li>", chunk, re.I)]
        flattened: List[str] = []
        for part in parts:
            if isinstance(part, tuple):
                text = next((value for value in part if value), "")
            else:
                text = part
            text = normalize_whitespace(text)
            if text and len(text) <= 100 and text.lower() not in {"home", "/"}:
                flattened.append(text)
        if flattened:
            return " > ".join(dict.fromkeys(flattened))
    return ""


def product_text_from_shopify_json(payload: Dict[str, object]) -> Tuple[str, str, str, str, str, str]:
    product = payload.get("product")
    if not isinstance(product, dict):
        product = payload
    title = normalize_whitespace(product.get("title"))
    description = strip_tags(product.get("body_html") or product.get("description"))
    brand = normalize_whitespace(product.get("vendor"))
    if brand.lower() in {"mysite", "my site", "site"}:
        brand = "Curvevera"
    category = normalize_whitespace(product.get("product_type"))
    tags_value = product.get("tags")
    if isinstance(tags_value, list):
        tags = " > ".join(normalize_whitespace(tag) for tag in tags_value if normalize_whitespace(tag))
    else:
        tags = normalize_whitespace(tags_value)
    product_id = normalize_whitespace(product.get("id"))
    return product_id, title, description, brand, category, tags


def brand_from_json_ld(product: Dict[str, object]) -> str:
    brand = product.get("brand")
    if isinstance(brand, dict):
        return normalize_whitespace(brand.get("name"))
    return normalize_whitespace(brand)


def product_core_from_json_ld(product: Dict[str, object]) -> str:
    parts: List[str] = []
    for key in ["name", "category", "sku"]:
        value = normalize_whitespace(product.get(key))
        if value:
            parts.append(value)
    brand = brand_from_json_ld(product)
    if brand:
        parts.append(brand)
    return " | ".join(dict.fromkeys(parts))


def loox_hash_from_html(html_text: str) -> str:
    return first_match([r"loox_global_hash\s*=\s*[\"']?([^\"';<]+)"], html_text)


def loox_review_count_from_html(html_text: str) -> Tuple[int, str]:
    match = re.search(r"[\"']reviewCount[\"']\s*:\s*(\d+)", html_text)
    review_count = int(match.group(1)) if match else 0
    rating = first_match([r"[\"']ratingValue[\"']\s*:\s*[\"']([^\"']+)"], html_text)
    return review_count, rating


def extract_product_taxonomy(product_url: str, html_text: str, json_payload: Dict[str, object], fetched_at: str) -> ProductTaxonomySignals:
    json_product = json_ld_product(html_text)
    json_id, json_title, json_description, json_brand, json_category, json_tags = product_text_from_shopify_json(json_payload)
    title = (
        json_title
        or normalize_whitespace(json_product.get("name"))
        or meta_content(html_text, "property", "og:title")
        or first_match([r"<title[^>]*>([\s\S]*?)</title>"], html_text)
    )
    description = (
        json_description
        or normalize_whitespace(json_product.get("description"))
        or meta_content(html_text, "property", "og:description")
        or meta_content(html_text, "name", "description")
    )
    breadcrumb = json_ld_breadcrumb(html_text) or html_breadcrumb(html_text)
    loox_count, loox_rating = loox_review_count_from_html(html_text)
    parsed = urlparse(product_url)
    slug = product_handle(product_url).replace("-", " ")
    json_ld_description = normalize_whitespace(json_product.get("description"))
    return ProductTaxonomySignals(
        product_url=product_url,
        normalized_product_page_url=canonical_product_url(product_url),
        source_site=SOURCE_SITE,
        shopify_product_id=json_id or first_match([r'"rid"\s*:\s*(\d+)', r"data-product-id=[\"'](\d+)[\"']"], html_text),
        handle=product_handle(product_url),
        brand=json_brand or brand_from_json_ld(json_product) or "Curvevera",
        product_title_raw=title,
        product_description_raw=description,
        product_category_raw=json_category or json_tags,
        product_tags_raw=json_tags,
        category_breadcrumb_path=breadcrumb,
        title=title,
        breadcrumb=breadcrumb,
        url_slug=slug,
        json_ld_product_core=product_core_from_json_ld(json_product),
        json_ld_product_description=json_ld_description,
        description=description,
        loox_review_count_hint=loox_count,
        loox_rating_value_hint=loox_rating,
        loox_hash=loox_hash_from_html(html_text),
        fetched_at=fetched_at,
        raw_signal_notes=[
            "taxonomy signals captured at product-page intake per data-pipelines/docs/scrape_required_fields_for_product_pages.md",
            "category_breadcrumb_path is empty when Curvevera exposes no visible/JSON-LD breadcrumb",
        ],
    )


def product_context_from_taxonomy(signals: ProductTaxonomySignals) -> ProductContext:
    return ProductContext(
        url=signals.normalized_product_page_url,
        title=signals.product_title_raw,
        description=signals.product_description_raw,
        detail=" | ".join(part for part in [signals.json_ld_product_core, signals.product_tags_raw] if part),
        category=signals.category_breadcrumb_path or signals.product_category_raw,
        brand=signals.brand,
        product_id=signals.shopify_product_id,
        handle=signals.handle,
        shop_domain=SHOPIFY_DOMAIN,
        provider_hints="Loox product iframe reviews; Shopify product JSON and page taxonomy signals captured at intake",
    )


def loox_reviews_url(product_id: str, loox_hash: str, page: int = 1, total: int = 0) -> str:
    query: Dict[str, object] = {"h": loox_hash}
    if page > 1:
        query.update({"total": total, "variant": "visible", "language": "en", "page": page})
    return f"{LOOX_ROOT}/widget/{LOOX_CLIENT_ID}/reviews/{product_id}?{urlencode(query)}"


def attr(block: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}=[\"']([^\"']*)[\"']", block)
    return normalize_whitespace(unescape(match.group(1))) if match else ""


def data_testid_text(block: str, review_id: str, suffix: str) -> str:
    match = re.search(
        rf"data-testid=[\"']review-{re.escape(review_id)}-{suffix}[\"'][^>]*>([\s\S]*?)</div>",
        block,
        flags=re.I,
    )
    return strip_tags(match.group(1)) if match else ""


def reviewer_name(block: str, review_id: str) -> str:
    raw = data_testid_text(block, review_id, "title")
    return normalize_whitespace(re.sub(r"\bVerified\b", "", raw, flags=re.I))


def review_rating(block: str, review_id: str) -> str:
    stars = re.search(
        rf"data-testid=[\"']review-{re.escape(review_id)}-stars[\"'][\s\S]*?aria-label=[\"'][^\"']*?(\d+(?:\.\d+)?)\s*/\s*5",
        block,
        flags=re.I,
    )
    return stars.group(1) if stars else ""


def review_date_from_time_ms(time_ms: str) -> str:
    if not time_ms:
        return ""
    try:
        return datetime.fromtimestamp(int(time_ms) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def absolute_url(raw_url: str, base: str = SITE_ROOT) -> str:
    raw_url = normalize_whitespace(unescape(raw_url))
    if raw_url.startswith("//"):
        return f"https:{raw_url}"
    return urljoin(base, raw_url)


def review_images(block: str) -> List[str]:
    urls: List[str] = []
    for raw_url in re.findall(r"<img[^>]+src=[\"']([^\"']+)[\"'][^>]+alt=[\"']Customer photo review", block, flags=re.I):
        url = absolute_url(raw_url, LOOX_ROOT)
        if url not in urls:
            urls.append(url)
    return urls


def parse_review_card(block: str, context: ProductContext) -> List[Dict[str, str]]:
    review_id = attr(block, "data-id")
    if not review_id:
        return []
    reviewer = reviewer_name(block, review_id)
    text = data_testid_text(block, review_id, "text")
    time_ms = first_match([rf"data-time=[\"'](\d+)[\"'][^>]+data-testid=[\"']review-{re.escape(review_id)}-date"], block)
    review_date = review_date_from_time_ms(time_ms)
    rating = review_rating(block, review_id)
    verified = "Verified purchase" in block or ">Verified<" in block
    images = review_images(block)
    if not images:
        images = [""]
    rows: List[Dict[str, str]] = []
    for index, image_url in enumerate(images, start=1):
        fallback = hashlib.md5(f"{context.url}|{review_id}|{text}|{index}".encode("utf-8")).hexdigest()[:12]
        review = ReviewImage(
            image_url=image_url,
            review_id=f"curvevera-loox-{review_id}-{index}" if image_url else f"curvevera-loox-{review_id}-{fallback}",
            review_body=text,
            reviewer_name=reviewer,
            date_raw=review_date,
            review_date=review_date,
            rating=rating,
            extra={
                "image_source_type": "customer_review_image" if image_url else "customer_review_no_image",
                "image_source_detail": "public Loox product review iframe",
                "product_url": context.url,
                "product_title": context.title,
                "product_description": context.description,
                "product_category": context.category,
                "loox_review_id": review_id,
                "loox_verified_purchase": "true" if verified else "false",
                "loox_rating": rating,
            },
        )
        rows.append(build_intake_row(context, review, utc_now()))
    return rows


def next_page_query(html_text: str) -> Dict[str, str]:
    match = re.search(r"id=[\"']loadMore[\"'][^>]+data-url=[\"']([^\"']+)[\"']", html_text, flags=re.I)
    if not match:
        return {}
    query = unescape(match.group(1))
    parsed = parse_qs(query, keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items() if values}


def parse_review_count_from_query(query: Dict[str, str], fallback: int) -> int:
    try:
        return int(query.get("total") or fallback or 0)
    except ValueError:
        return fallback


def fetch_product_reviews(
    product_id: str,
    loox_hash: str,
    context: ProductContext,
    *,
    expected_total: int = 0,
    limit_pages: Optional[int] = None,
    delay_seconds: float = 0.2,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    if not product_id or not loox_hash:
        return [], {"review_pages_scanned": 0, "review_count_hint": expected_total, "errors": ["missing_product_id_or_loox_hash"]}
    rows: List[Dict[str, str]] = []
    page = 1
    total = expected_total
    pages: List[Dict[str, object]] = []
    errors: List[str] = []
    while True:
        if limit_pages and page > limit_pages:
            break
        url = loox_reviews_url(product_id, loox_hash, page=page, total=total)
        try:
            html_text = request_text(url, referer=context.url)
        except Exception as exc:
            errors.append(f"page_{page}: {exc}")
            break
        cards = REVIEW_CARD_RE.findall(html_text)
        page_rows: List[Dict[str, str]] = []
        for card in cards:
            page_rows.extend(parse_review_card(card, context))
        rows.extend(page_rows)
        query = next_page_query(html_text)
        total = parse_review_count_from_query(query, total)
        pages.append({"page": page, "cards": len(cards), "rows": len(page_rows), "bytes": len(html_text), "next_page": query.get("page", "")})
        if not cards or not query.get("page"):
            break
        page = int(query["page"])
        time.sleep(delay_seconds)
    return rows, {
        "review_pages_scanned": len(pages),
        "review_count_hint": total,
        "review_pages": pages,
        "errors": errors,
    }


def is_measurement_row(row: Dict[str, str]) -> bool:
    fields = [
        "height_in_display",
        "weight_lbs_display",
        "bust_in_number_display",
        "bra_band_in_display",
        "hips_in_display",
        "waist_in",
        "inseam_inches_display",
        "age_years_display",
        "weeks_pregnant",
    ]
    return any(normalize_whitespace(row.get(field)) for field in fields)


def invalid_numeric_fields(rows: Sequence[Dict[str, str]]) -> Dict[str, int]:
    numeric_fields = [
        "height_in_display",
        "weight_lbs_display",
        "bust_in_number_display",
        "bra_band_in_display",
        "hips_in_display",
        "waist_in",
        "inseam_inches_display",
        "age_years_display",
        "weeks_pregnant",
    ]
    return {
        field: sum(1 for row in rows if normalize_whitespace(row.get(field)) and not re.fullmatch(r"\d+(?:\.\d+)?", normalize_whitespace(row.get(field))))
        for field in numeric_fields
    }


def write_taxonomy_json(signals: Sequence[ProductTaxonomySignals], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(item) for item in signals], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_review_records_jsonl(rows: Sequence[Dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_review_records_jsonl(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append({str(key): "" if value is None else str(value) for key, value in payload.items()})
    return rows


def read_taxonomy_signals(path: Path) -> List[ProductTaxonomySignals]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    signals: List[ProductTaxonomySignals] = []
    if isinstance(payload, list):
        field_names = set(ProductTaxonomySignals.__dataclass_fields__)
        for item in payload:
            if not isinstance(item, dict):
                continue
            clean = {key: item.get(key) for key in field_names if key in item}
            if isinstance(clean.get("raw_signal_notes"), str):
                clean["raw_signal_notes"] = [clean["raw_signal_notes"]]
            signals.append(ProductTaxonomySignals(**clean))
    return signals


def write_outputs(
    rows: Sequence[Dict[str, str]],
    taxonomy_signals: Sequence[ProductTaxonomySignals],
    summary: Dict[str, object],
) -> None:
    deduped = dedupe_rows(rows)
    write_intake_csv(deduped, OUTPUT_CSV)
    write_taxonomy_json(taxonomy_signals, PRODUCT_TAXONOMY_JSON)
    review_jsonl = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.jsonl"
    write_review_records_jsonl(deduped, review_jsonl)
    summary["rows_written"] = len(deduped)
    summary["output_csv"] = str(OUTPUT_CSV)
    summary["output_jsonl"] = str(review_jsonl)
    summary["product_taxonomy_json"] = str(PRODUCT_TAXONOMY_JSON)
    summary["summary_json"] = str(SUMMARY_JSON)
    summary["finished_at"] = utc_now()
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def process_product(product_url: str, *, limit_review_pages: Optional[int], delay_seconds: float) -> Tuple[List[Dict[str, str]], ProductTaxonomySignals, Dict[str, object]]:
    fetched_at = utc_now()
    html_text = request_text(product_url, referer=SOURCE_SITE)
    json_payload = request_json(product_json_url(product_url), referer=product_url)
    signals = extract_product_taxonomy(product_url, html_text, json_payload, fetched_at)
    context = product_context_from_taxonomy(signals)
    rows, meta = fetch_product_reviews(
        signals.shopify_product_id,
        signals.loox_hash,
        context,
        expected_total=signals.loox_review_count_hint,
        limit_pages=limit_review_pages,
        delay_seconds=delay_seconds,
    )
    return rows, signals, meta


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Curvevera product-level Loox reviews plus taxonomy intake signals.")
    parser.add_argument("--limit-products", type=int, default=0, help="Limit product pages for a smoke run.")
    parser.add_argument("--limit-review-pages-per-product", type=int, default=0, help="Limit Loox review pages per product.")
    parser.add_argument("--delay-seconds", type=float, default=0.2, help="Delay between Loox review page requests.")
    parser.add_argument("--product-delay-seconds", type=float, default=1.0, help="Delay between product pages.")
    parser.add_argument("--resume", action="store_true", help="Skip products already present in the current taxonomy sidecar.")
    return parser.parse_args(argv)


def existing_product_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    urls = set()
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                url = normalize_whitespace(item.get("normalized_product_page_url"))
                if url:
                    urls.add(url)
    return urls


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    started_at = utc_now()
    limit_products = args.limit_products or None
    limit_review_pages = args.limit_review_pages_per_product or None
    product_urls, discovery = discover_product_urls(limit_products)
    skip_urls = existing_product_urls(PRODUCT_TAXONOMY_JSON) if args.resume else set()
    product_urls_to_scan = [url for url in product_urls if canonical_product_url(url) not in skip_urls]

    print(f"Discovered {len(product_urls)} Curvevera products; scanning {len(product_urls_to_scan)}")
    review_jsonl = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema.jsonl"
    all_rows: List[Dict[str, str]] = read_review_records_jsonl(review_jsonl) if args.resume else []
    taxonomy_signals: List[ProductTaxonomySignals] = read_taxonomy_signals(PRODUCT_TAXONOMY_JSON) if args.resume else []
    product_summaries: List[Dict[str, object]] = []
    total_pages = 0
    total_hint = 0
    errors: List[str] = []

    base_summary = {
        "site": "curvevera.com",
        "adapter": "shopify_sitemap_product_pages_loox_product_reviews",
        "review_platform_provider": "Loox",
        "loox_client_id": LOOX_CLIENT_ID,
        "shopify_domain": SHOPIFY_DOMAIN,
        "product_discovery": discovery,
        "products_discovered": len(product_urls),
        "exhaustive_product_scan": limit_products is None,
        "exhaustive_review_paging": limit_review_pages is None,
        "started_at": started_at,
        "access_policy": "public Shopify sitemap/product JSON/product pages and public Loox product review iframes only; no auth bypass; stop on pressure responses",
        "taxonomy_alignment": {
            "source_doc": "data-pipelines/docs/scrape_required_fields_for_product_pages.md",
            "captured_at_intake": [
                "normalized_product_page_url",
                "source_site",
                "brand",
                "product_title_raw",
                "product_description_raw",
                "product_category_raw",
                "category_breadcrumb_path",
                "title",
                "breadcrumb",
                "url_slug",
                "json_ld_product_core",
                "json_ld_product_description",
                "description",
            ],
            "classification_status": "raw taxonomy signals captured; extractTaxonomy classification can run from product_taxonomy_json without refetching Curvevera",
        },
    }

    for index, product_url in enumerate(product_urls_to_scan, start=1):
        try:
            rows, signals, meta = process_product(
                product_url,
                limit_review_pages=limit_review_pages,
                delay_seconds=max(0, args.delay_seconds),
            )
        except PressureStop:
            base_summary.update(
                {
                    "status": "stopped_on_pressure_response",
                    "products_scanned": len(taxonomy_signals),
                    "products_remaining": len(product_urls_to_scan) - index + 1,
                    "products_with_taxonomy_signals": len(taxonomy_signals),
                    "products_with_breadcrumb": sum(1 for item in taxonomy_signals if item.category_breadcrumb_path),
                    "products_with_description": sum(1 for item in taxonomy_signals if item.product_description_raw),
                    "products_with_title": sum(1 for item in taxonomy_signals if item.product_title_raw),
                    "review_pages_scanned": total_pages,
                    "product_review_count_hint": total_hint,
                    "errors": errors + [f"pressure_stop_at_{product_url}"],
                    "product_summaries": product_summaries,
                    "invalid_numeric_fields": invalid_numeric_fields(dedupe_rows(all_rows)),
                }
            )
            write_outputs(all_rows, taxonomy_signals, base_summary)
            raise
        except Exception as exc:
            errors.append(f"{product_url}: {exc}")
            print(f"[{index}/{len(product_urls_to_scan)}] ERROR {product_url}: {exc}", flush=True)
            continue
        all_rows.extend(rows)
        taxonomy_signals.append(signals)
        total_pages += int(meta.get("review_pages_scanned") or 0)
        total_hint += int(meta.get("review_count_hint") or signals.loox_review_count_hint or 0)
        product_summaries.append(
            {
                "product_index": index,
                "product_url": signals.normalized_product_page_url,
                "shopify_product_id": signals.shopify_product_id,
                "title": signals.product_title_raw,
                "breadcrumb": signals.category_breadcrumb_path,
                "description_present": bool(signals.product_description_raw),
                "loox_review_count_hint": meta.get("review_count_hint") or signals.loox_review_count_hint,
                "review_pages_scanned": meta.get("review_pages_scanned"),
                "rows": len(rows),
                "errors": meta.get("errors") or [],
            }
        )
        print(
            f"[{index}/{len(product_urls_to_scan)}] {signals.product_title_raw or product_url} "
            f"reviews={meta.get('review_count_hint') or signals.loox_review_count_hint} "
            f"pages={meta.get('review_pages_scanned')} rows={len(rows)}",
            flush=True,
        )
        checkpoint_summary = {
            **base_summary,
            "status": "running_checkpoint",
            "products_scanned": len(taxonomy_signals),
            "products_remaining": len(product_urls_to_scan) - index,
            "products_with_taxonomy_signals": len(taxonomy_signals),
            "products_with_breadcrumb": sum(1 for item in taxonomy_signals if item.category_breadcrumb_path),
            "products_with_description": sum(1 for item in taxonomy_signals if item.product_description_raw),
            "products_with_title": sum(1 for item in taxonomy_signals if item.product_title_raw),
            "review_pages_scanned": total_pages,
            "product_review_count_hint": total_hint,
            "errors": errors,
            "product_summaries": product_summaries,
            "invalid_numeric_fields": invalid_numeric_fields(dedupe_rows(all_rows)),
        }
        write_outputs(all_rows, taxonomy_signals, checkpoint_summary)
        time.sleep(max(0, args.product_delay_seconds))

    deduped = dedupe_rows(all_rows)

    rows_with_product_url = sum(1 for row in deduped if normalize_whitespace(row.get("product_page_url_display")))
    rows_with_image = sum(1 for row in deduped if normalize_whitespace(row.get("original_url_display")))
    rows_with_size = sum(1 for row in deduped if normalize_whitespace(row.get("size_display")))
    rows_with_measurements = sum(1 for row in deduped if is_measurement_row(row))
    summary = {
        **base_summary,
        "status": "complete",
        "products_discovered": len(product_urls),
        "products_scanned": len(taxonomy_signals),
        "products_remaining": 0,
        "products_with_taxonomy_signals": len(taxonomy_signals),
        "products_with_breadcrumb": sum(1 for item in taxonomy_signals if item.category_breadcrumb_path),
        "products_with_description": sum(1 for item in taxonomy_signals if item.product_description_raw),
        "products_with_title": sum(1 for item in taxonomy_signals if item.product_title_raw),
        "review_pages_scanned": total_pages,
        "product_review_count_hint": total_hint,
        "rows_written": len(deduped),
        "distinct_reviews": len({row.get("id", "").rsplit("-", 1)[0] for row in deduped if row.get("id")}),
        "distinct_products": len({row.get("product_page_url_display") for row in deduped if row.get("product_page_url_display")}),
        "rows_with_product_url": rows_with_product_url,
        "rows_with_customer_image": rows_with_image,
        "rows_with_customer_review_image": sum(1 for row in deduped if row.get("image_source_type") == "customer_review_image"),
        "rows_with_customer_ordered_size": rows_with_size,
        "rows_with_any_measurement": rows_with_measurements,
        "rows_supabase_qualified": sum(
            1
            for row in deduped
            if normalize_whitespace(row.get("original_url_display"))
            and normalize_whitespace(row.get("product_page_url_display"))
            and is_measurement_row(row)
            and normalize_whitespace(row.get("size_display"))
        ),
        "invalid_numeric_fields": invalid_numeric_fields(deduped),
        "errors": errors,
        "product_summaries": product_summaries,
    }
    write_outputs(deduped, taxonomy_signals, summary)
    print(f"Wrote {len(deduped)} rows to {OUTPUT_CSV}")
    print(f"Wrote product taxonomy sidecar: {PRODUCT_TAXONOMY_JSON}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
