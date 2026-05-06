#!/usr/bin/env python3
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
import html
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

try:
    import requests
except ImportError:  # pragma: no cover - scraper still works through urllib where accepted.
    requests = None


REPO_ROOT = Path(__file__).resolve().parents[4]
FWM_DATA_DIR = os.environ.get("FWM_DATA_DIR")
DATA_ROOT = (
    Path(FWM_DATA_DIR).expanduser() / "non-amazon" / "data"
    if FWM_DATA_DIR
    else REPO_ROOT / "data-pipelines" / "non-amazon" / "data"
).resolve()
STEP1_OUTPUT_ROOT = DATA_ROOT / "step_1_raw_scraping_data"

INTAKE_HEADERS = [
    "created_at_display",
    "id",
    "original_url_display",
    "image_source_type",
    "image_source_detail",
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
    # Extra Step 1 context used by later standardization/classification.
    "product_title_raw",
    "product_subtitle_raw",
    "product_description_raw",
    "product_detail_raw",
    "product_category_raw",
    "product_variant_raw",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

SCRAPE_ACCESS_POLICY = (
    "public_product_and_review_pages_only; "
    "restricted_or_unavailable_pages_are_skipped; polite_retries"
)

BRA_SIZE_RE = re.compile(
    r"\b(28|30|32|34|36|38|40|42|44|46|48|50|52|54)\s*"
    r"(AAA|AA|A|B|C|D|DD|DD/?E|DDD|DDD/?F|F|G|H|I|J|K)\b",
    re.I,
)
HEIGHT_RE = re.compile(
    r"(?:(?:i\s*(?:am|'m)|im|i’m|i am|height)\s*:?\s*)?"
    r"(\d)\s*(?:ft|feet|foot|['’])\s*(\d{1,2})?\s*(?:in|inches|[\"”])?",
    re.I,
)
WEIGHT_RE = re.compile(
    r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?)\b|"
    r"\b(?:weigh(?:t|s|ed|ing)?|weight)\s*(?:is|:)?\s*(\d{2,3}(?:\.\d+)?)\b",
    re.I,
)
WAIST_RE = re.compile(
    r"\bwaist\s*(?:is|:)?\s*(\d{2,3}(?:\.\d+)?)\b|"
    r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ch(?:es)?)?)\s*waist\b",
    re.I,
)
HIPS_RE = re.compile(
    r"\bhips?\s*(?:are|is|:)?\s*(\d{2,3}(?:\.\d+)?)\b|"
    r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ch(?:es)?)?)\s*hips?\b",
    re.I,
)
BUST_RE = re.compile(
    r"\b(?:bust|chest)\s*(?:is|:)?\s*(\d{2,3}(?:\.\d+)?)(?:\s*(?:\"|in(?:ch(?:es)?)?))?\b|"
    r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ch(?:es)?)?)?\s*(?:bust|chest)\b",
    re.I,
)
AGE_RE = re.compile(r"\b(?:age\s*:?\s*(\d{1,2})|(\d{1,2})\s*years?\s*old)\b", re.I)
INSEAM_RE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:\"|in(?:ch(?:es)?)?)\s*inseam\b", re.I)
MEASUREMENT_TRIPLE_RE = re.compile(r"\b(\d{2,3})\s*[-/x]\s*(\d{2,3})\s*[-/x]\s*(\d{2,3})\b", re.I)

GENERIC_SIZE_RE = re.compile(
    r"\b("
    r"xxs|xs|x-small|extra small|small|medium|med|large|xl|x-large|extra large|"
    r"xxl|2xl|2x|xx-large|xxxl|3xl|3x|4xl|4x|5xl|5x|6xl|6x|"
    r"\d{1,2}(?:\.\d)?(?:\s*(?:regular|short|long|tall|petite))?"
    r")\b",
    re.I,
)

MEASUREMENT_FIELDS = [
    "height_raw",
    "weight_raw",
    "waist_raw_display",
    "hips_raw",
    "age_raw",
    "height_in_display",
    "waist_in",
    "hips_in_display",
    "age_years_display",
    "inseam_inches_display",
    "bust_in_number_display",
    "cupsize_display",
    "weight_lbs_display",
]


@dataclass
class ProductContext:
    url: str
    title: str = ""
    subtitle: str = ""
    description: str = ""
    detail: str = ""
    category: str = ""
    brand: str = ""
    color: str = ""
    variant: str = ""
    product_id: str = ""
    handle: str = ""
    shop_domain: str = ""
    provider_hints: str = ""
    raw_html: str = ""


@dataclass
class ReviewImage:
    image_url: str
    review_id: str = ""
    review_title: str = ""
    review_body: str = ""
    reviewer_name: str = ""
    reviewer_profile_url: str = ""
    date_raw: str = ""
    review_date: str = ""
    size_raw: str = ""
    rating: str = ""
    extra: Dict[str, str] = field(default_factory=dict)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def retailer_slug(value: str) -> str:
    slug = re.sub(r"^www\.", "", value.strip().lower())
    slug = slug.split("/")[0].split(":")[0]
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    aliases = {
        "harperwilde_com": "harper_wilde",
        "victoriassecret_com": "vs",
        "babyboofashion_com": "babyboo",
        "universalstandard_com": "universal_standard",
        "missme_com": "miss_me_jeans",
    }
    return aliases.get(slug, slug)


def output_paths(retailer: str) -> Tuple[Path, Path]:
    output_dir = STEP1_OUTPUT_ROOT / retailer_slug(retailer)
    output_csv = output_dir / f"{retailer_slug(retailer)}_reviews_matching_intake_schema.csv"
    summary_json = output_dir / f"{retailer_slug(retailer)}_reviews_matching_intake_schema_summary.json"
    return output_csv, summary_json


def normalize_whitespace(value: object) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def strip_tags(fragment: object) -> str:
    text = "" if fragment is None else str(fragment)
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</\s*p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_whitespace(html.unescape(text))


def unique(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        clean = normalize_whitespace(value)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def iri_to_uri(url: str) -> str:
    """Convert human-readable URLs with symbols/non-ASCII text into request-safe URLs."""
    parts = urlsplit(url)
    netloc = parts.netloc.encode("idna").decode("ascii") if parts.netloc else ""
    path = quote(parts.path, safe="/%:@")
    query = quote(parts.query, safe="=&?/:;+,%@")
    fragment = quote(parts.fragment, safe="=&?/:;+,%@")
    return urlunsplit((parts.scheme, netloc, path, query, fragment))


def fetch_text(
    url: str,
    *,
    accept: str = "text/html,application/json,application/xml;q=0.9,*/*;q=0.8",
    referer: str = "",
    retries: int = 4,
    timeout: int = 45,
) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        }
        if referer:
            headers["Referer"] = referer
        req = Request(iri_to_uri(url), headers=headers)
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
        except URLError as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 12))
    if last_error:
        if isinstance(last_error, HTTPError) and last_error.code == 429 and requests is not None:
            response = requests.get(iri_to_uri(url), headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.text
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def fetch_json(url: str, *, referer: str = "", retries: int = 4) -> Dict[str, object]:
    return json.loads(fetch_text(url, accept="application/json,text/plain,*/*", referer=referer, retries=retries))


def post_json(url: str, payload: Dict[str, object], *, referer: str = "", retries: int = 4) -> Dict[str, object]:
    last_error: Optional[Exception] = None
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(retries):
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if referer:
            headers["Referer"] = referer
            parsed = urlparse(referer)
            if parsed.scheme and parsed.netloc:
                headers["Origin"] = f"{parsed.scheme}://{parsed.netloc}"
        req = Request(iri_to_uri(url), data=body, headers=headers, method="POST")
        try:
            with urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
        except (URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(min(2 ** attempt, 12))
    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to post {url}")


def first_match(patterns: Sequence[str], text: str, flags: int = re.I | re.S) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return normalize_whitespace(html.unescape(match.group(1)))
    return ""


def extract_json_ld_product(html_text: str) -> Dict[str, object]:
    for block in re.findall(r"<script[^>]+type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", html_text, re.I | re.S):
        try:
            payload = json.loads(html.unescape(block.strip()))
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            graph_items = graph if isinstance(graph, list) else [item]
            for graph_item in graph_items:
                if not isinstance(graph_item, dict):
                    continue
                item_type = graph_item.get("@type")
                types = item_type if isinstance(item_type, list) else [item_type]
                if any(str(t).lower() == "product" for t in types):
                    return graph_item
    return {}


def extract_product_context(product_url: str, html_text: Optional[str] = None) -> ProductContext:
    html_text = html_text if html_text is not None else fetch_text(product_url)
    parsed = urlparse(product_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    json_ld = extract_json_ld_product(html_text)
    title = normalize_whitespace(json_ld.get("name") or "") if json_ld else ""
    description = normalize_whitespace(json_ld.get("description") or "") if json_ld else ""
    brand = ""
    if json_ld:
        brand_value = json_ld.get("brand")
        if isinstance(brand_value, dict):
            brand = normalize_whitespace(brand_value.get("name"))
        else:
            brand = normalize_whitespace(brand_value)

    title = title or first_match(
        [
            r"<meta[^>]+property=['\"]og:title['\"][^>]+content=['\"]([^'\"]+)['\"]",
            r"<title[^>]*>(.*?)</title>",
        ],
        html_text,
    )
    description = description or first_match(
        [
            r"<meta[^>]+property=['\"]og:description['\"][^>]+content=['\"]([^'\"]+)['\"]",
            r"<meta[^>]+name=['\"]description['\"][^>]+content=['\"]([^'\"]+)['\"]",
        ],
        html_text,
    )
    shop_domain = first_match(
        [
            r"Shopify\.shop\s*=\s*['\"]([^'\"]+)['\"]",
            r"shop\.permanent_domain\s*=\s*['\"]([^'\"]+)['\"]",
            r"myshopifyDomain['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
            r"shopDomain['\"]?\s*[:=]\s*['\"]([^'\"]+\.myshopify\.com)['\"]",
        ],
        html_text,
    )
    product_id = first_match(
        [
            r"product_id['\"]?\s*[:=]\s*['\"]?(\d+)",
            r"ProductId['\"]?\s*[:=]\s*['\"]?(\d+)",
            r"data-product-id=['\"](\d+)['\"]",
            r'"product"\s*:\s*\{[^}]*"id"\s*:\s*(\d+)',
        ],
        html_text,
    )
    handle = ""
    if "/products/" in parsed.path:
        handle = parsed.path.split("/products/", 1)[1].split("/", 1)[0].removesuffix(".js")
    detail_items = []
    for item in re.findall(r"<li[^>]*>(.*?)</li>", html_text, flags=re.I | re.S):
        clean = strip_tags(item)
        lowered = clean.lower()
        if not clean or len(clean) > 240:
            continue
        if any(token in lowered for token in ["window.", "function(", "shopify", "var ", "const ", "document.", "{", "}"]):
            continue
        detail_items.append(clean)
    detail = " | ".join(dict.fromkeys(detail_items[:20]))

    category_items = []
    for item in re.findall(r"<a[^>]+(?:breadcrumb|breadcrumbs)[^>]*>(.*?)</a>", html_text, flags=re.I | re.S):
        clean = strip_tags(item)
        if clean and len(clean) <= 80:
            category_items.append(clean)
    category = " > ".join(dict.fromkeys(category_items[:8]))
    provider_hints = "; ".join(
        name
        for name, pattern in [
            ("Judge.me", r"judge\.me|jdgm-|judgeme_product_reviews"),
            ("Loox", r"loox|looxReviews|loox-rating"),
            ("Stamped", r"stamped\.io|stamped-main-widget|data-widget-style"),
            ("Yotpo", r"yotpo|staticw2\.yotpo\.com"),
            ("Okendo", r"okendo|okeReviews|oke-widget"),
            ("Ryviu", r"ryviu|ryviu-widget|cdn2\.ryviu\.com"),
        ]
        if re.search(pattern, html_text, re.I)
    )
    return ProductContext(
        url=product_url,
        title=title,
        description=description,
        detail=detail,
        category=category,
        brand=brand,
        product_id=product_id,
        handle=handle,
        shop_domain=shop_domain or parsed.netloc,
        provider_hints=provider_hints,
        raw_html=html_text,
    )


def shopify_product_json_url(product_url: str) -> str:
    parsed = urlparse(product_url)
    return urljoin(f"{parsed.scheme}://{parsed.netloc}", f"{parsed.path.rstrip('/')}.js")


def canonical_product_url(product_url: str) -> str:
    parsed = urlparse(product_url)
    if "/products/" not in parsed.path:
        return product_url
    netloc = re.sub(r"^www\.", "", parsed.netloc, flags=re.I)
    handle = parsed.path.split("/products/", 1)[1].split("/", 1)[0].removesuffix(".js")
    path = f"/products/{handle}"
    return urljoin(f"{parsed.scheme}://{netloc}", path.rstrip("/"))


def hydrate_shopify_context(context: ProductContext) -> ProductContext:
    if not context.handle:
        return context
    try:
        payload = fetch_json(shopify_product_json_url(context.url), referer=context.url, retries=2)
    except Exception:
        return context
    context.product_id = context.product_id or normalize_whitespace(payload.get("id"))
    context.title = normalize_whitespace(payload.get("title")) or context.title
    context.description = strip_tags(payload.get("description")) or context.description
    context.brand = context.brand or normalize_whitespace(payload.get("vendor"))
    context.category = normalize_whitespace(payload.get("type")) or context.category
    variants = payload.get("variants")
    if isinstance(variants, list) and variants:
        first = variants[0]
        if isinstance(first, dict):
            context.variant = normalize_whitespace(first.get("title"))
            context.color = normalize_whitespace(first.get("option1") or first.get("option2") or "")
    return context


OBVIOUS_NON_CLOTHING_PRODUCT_RE = re.compile(
    r"\b("
    r"gift\s*card|e-?gift|shipping\s*(protection|insurance)?|route\s*package|"
    r"subscription|warranty|returns?\s*protection|mystery\s*(box|swimwear)|"
    r"nipple\s*covers?|boob\s*tape|"
    r"fashion\s*tape|bra\s*extenders?|adhesive\s*inserts?|sticky\s*inserts?|"
    r"removable\s*pads?|laundry\s*bag|detergent|hanger|socks?"
    r")\b",
    re.I,
)


def is_obvious_non_clothing_product(product: Dict[str, object], product_url: str = "") -> bool:
    tags = product.get("tags")
    if isinstance(tags, list):
        tags_text = " ".join(str(tag) for tag in tags)
    else:
        tags_text = str(tags or "")
    text = " ".join(
        normalize_whitespace(part)
        for part in [
            product.get("title"),
            product.get("handle"),
            product.get("product_type"),
            product.get("vendor"),
            tags_text,
            product_url,
        ]
        if part
    )
    return bool(OBVIOUS_NON_CLOTHING_PRODUCT_RE.search(text))


def discover_shopify_product_urls(site_root: str, seed_urls: Sequence[str]) -> List[str]:
    seen = set()
    seen_handles = set()
    urls: List[str] = []
    for seed_url in seed_urls:
        canonical = canonical_product_url(seed_url)
        if "/products/" in urlparse(canonical).path and canonical not in seen:
            seen.add(canonical)
            seen_handles.add(urlparse(canonical).path.rstrip("/").rsplit("/", 1)[-1])
            urls.append(canonical)

    root = site_root.rstrip("/")
    for page in range(1, 10000):
        api_url = f"{root}/products.json?limit=250&page={page}"
        try:
            payload = fetch_json(api_url, referer=root, retries=2)
        except Exception:
            break
        products = payload.get("products")
        if not isinstance(products, list) or not products:
            break
        for product in products:
            if not isinstance(product, dict):
                continue
            handle = normalize_whitespace(product.get("handle"))
            if not handle:
                continue
            if handle in seen_handles:
                continue
            product_url = f"{root}/products/{handle}"
            if is_obvious_non_clothing_product(product, product_url):
                continue
            if product_url not in seen:
                seen.add(product_url)
                seen_handles.add(handle)
                urls.append(product_url)
        if len(products) < 250:
            break

    try:
        sitemap_index = fetch_text(f"{root}/sitemap.xml", referer=root, retries=2)
    except Exception:
        sitemap_index = ""
    sitemap_urls = []
    sitemap_seen = set()
    for match in re.findall(r"<loc>([^<]*sitemap_products_[^<]+)</loc>", sitemap_index, re.I):
        sitemap_url = html.unescape(match)
        if sitemap_url not in sitemap_seen:
            sitemap_seen.add(sitemap_url)
            sitemap_urls.append(sitemap_url)
    for sitemap_url in sitemap_urls:
        try:
            sitemap_text = fetch_text(sitemap_url, referer=root, retries=2)
        except Exception:
            continue
        for product_url in re.findall(r"https?://[^<\s\"']+/products/[^<\s\"']+", sitemap_text, re.I):
            canonical = canonical_product_url(html.unescape(product_url))
            parsed = urlparse(canonical)
            root_host = urlparse(root).netloc.lower().removeprefix("www.")
            product_host = parsed.netloc.lower().removeprefix("www.")
            if product_host != root_host or not parsed.path.startswith("/products/"):
                continue
            handle = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            if handle in seen_handles:
                continue
            if canonical not in seen:
                seen.add(canonical)
                seen_handles.add(handle)
                urls.append(canonical)
    return urls


def normalize_bra_size(value: str) -> str:
    collapsed = normalize_whitespace(value).upper().replace(" ", "")
    return {"DDE": "DD/E", "DDDF": "DDD/F", "DDDE": "DDD/E"}.get(collapsed, collapsed)


def normalize_generic_size(value: str) -> str:
    size = normalize_whitespace(value).lower()
    mapping = {
        "xs": "x-small",
        "extra small": "x-small",
        "s": "small",
        "med": "medium",
        "m": "medium",
        "l": "large",
        "xl": "x-large",
        "extra large": "x-large",
        "2xl": "xx-large",
        "2x": "xx-large",
        "3xl": "xxx-large",
        "3x": "xxx-large",
    }
    return mapping.get(size, size)


def extract_size(text: str) -> str:
    for pattern in [
        r"\b(?:ordered|bought|purchased|got|wearing|wear|picked|chose|choose)\s+(?:the\s+)?(?:a\s+)?size\s+([a-z0-9\-/ .]+?)(?:[.,;]|$)",
        r"\bsize\s+([a-z0-9\-/ .]+?)(?:\s+(?:fits?|was|is)|[.,;]|$)",
    ]:
        match = re.search(pattern, text, re.I)
        if match:
            value = normalize_whitespace(match.group(1))
            bra = BRA_SIZE_RE.search(value)
            if bra:
                return normalize_bra_size(bra.group(0))
            generic = GENERIC_SIZE_RE.search(value)
            if generic:
                return normalize_generic_size(generic.group(1))
            return value
    bra = BRA_SIZE_RE.search(text)
    if bra:
        return normalize_bra_size(bra.group(0))
    return ""


def numeric_text(value: Optional[float]) -> str:
    if value is None:
        return ""
    return str(int(value)) if value == int(value) else f"{value:.2f}".rstrip("0").rstrip(".")


def parse_height(text: str) -> Tuple[str, str]:
    match = HEIGHT_RE.search(text)
    if not match:
        return "", ""
    feet = int(match.group(1))
    inches = int(match.group(2) or 0)
    return normalize_whitespace(match.group(0)), str(feet * 12 + inches)


def parse_numeric(pattern: re.Pattern[str], text: str, max_value: Optional[float] = None) -> Tuple[str, str]:
    match = pattern.search(text)
    if not match:
        return "", ""
    value_text = match.group(1) or (match.group(2) if len(match.groups()) > 1 else "")
    try:
        value = float(value_text)
    except ValueError:
        return normalize_whitespace(match.group(0)), value_text
    if max_value is not None and value > max_value:
        return normalize_whitespace(match.group(0)), ""
    return normalize_whitespace(match.group(0)), numeric_text(value)


def extract_measurements(text: str, size_hint: str = "") -> Dict[str, str]:
    height_raw, height_in = parse_height(text)
    weight_raw, weight_lbs = parse_numeric(WEIGHT_RE, text)
    waist_raw, waist_in = parse_numeric(WAIST_RE, text, max_value=80)
    hips_raw, hips_in = parse_numeric(HIPS_RE, text, max_value=90)
    age_raw, age_years = parse_numeric(AGE_RE, text, max_value=99)
    _, inseam_in = parse_numeric(INSEAM_RE, text, max_value=50)
    bust_raw, bust_in = parse_numeric(BUST_RE, text, max_value=80)
    triple = MEASUREMENT_TRIPLE_RE.search(text)
    if triple:
        if not bust_in:
            bust_raw = triple.group(1)
            bust_in = triple.group(1)
        if not waist_in:
            waist_raw = triple.group(2)
            waist_in = triple.group(2)
        if not hips_in:
            hips_raw = triple.group(3)
            hips_in = triple.group(3)
    cup_size = ""
    for source in (size_hint, text):
        match = BRA_SIZE_RE.search(source or "")
        if match:
            bust_in = bust_in or match.group(1)
            cup_size = normalize_bra_size(match.group(2))
            break
    return {
        "height_raw": height_raw,
        "height_in_display": height_in,
        "weight_raw": weight_raw,
        "weight_display_display": weight_raw,
        "weight_lbs_display": weight_lbs,
        "waist_raw_display": waist_raw,
        "waist_in": waist_in,
        "hips_raw": hips_raw,
        "hips_in_display": hips_in,
        "age_raw": age_raw,
        "age_years_display": age_years,
        "inseam_inches_display": inseam_in,
        "bust_in_number_display": bust_in,
        "cupsize_display": cup_size,
    }


def review_date_from_raw(value: str) -> str:
    raw = normalize_whitespace(value)
    if not raw:
        return ""
    if re.fullmatch(r"\d{10,13}", raw):
        timestamp = int(raw)
        if len(raw) == 13:
            timestamp = timestamp // 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    for pattern in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"]:
        try:
            return datetime.strptime(raw.replace("Z", "+0000"), pattern).date().isoformat()
        except ValueError:
            continue
    match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", raw)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return ""


def classify_clothing_type(context: ProductContext) -> str:
    value = f"{context.title} {context.category} {context.url}".lower()
    if re.search(r"\b(?:men|mens|men's|male)\b", value):
        return ""
    if re.search(r"\b(?:boxer\s*briefs?|trunks?|pouch(?:es)?)\b", value):
        return ""
    for pattern, clothing_type in [
        (r"\bjeans?\b", "jeans"),
        (r"\bpants?\b", "pants"),
        (r"\bleggings?\b", "leggings"),
        (r"\bdress(?:es)?\b", "dress"),
        (r"\bjackets?\b", "jacket"),
        (r"\bcoats?\b", "jacket"),
        (r"\bblazers?\b", "jacket"),
        (r"\bvests?\b", "top"),
        (r"\bskirts?\b", "skirt"),
        (r"\bskorts?\b", "skirt"),
        (r"\bshorts?\b", "shorts"),
        (r"\bgirlshorts?\b", "underwear"),
        (r"\bthongs?\b", "underwear"),
        (r"\bpant(?:y|ies)\b", "underwear"),
        (r"\bbriefs?\b", "underwear"),
        (r"\bunderwear\b", "underwear"),
        (r"\bjumpsuits?\b", "jumpsuit"),
        (r"\brompers?\b", "jumpsuit"),
        (r"\bbras?\b", "bra"),
        (r"\bswimsuits?\b", "swimwear"),
        (r"\bbikinis?\b", "swimwear"),
        (r"\btops?\b", "top"),
        (r"\btanks?\b", "top"),
        (r"\bt-?shirts?\b", "top"),
        (r"\bshirts?\b", "top"),
        (r"\bcardigans?\b", "top"),
        (r"\bsweaters?\b", "top"),
        (r"\blong sleeves?\b", "top"),
        (r"\bturtle necks?\b", "top"),
        (r"\bturtlenecks?\b", "top"),
        (r"\bbodysuits?\b", "bodysuit"),
    ]:
        if re.search(pattern, value):
            return clothing_type
    return ""


def build_search_fts(parts: Iterable[str]) -> str:
    return normalize_whitespace(" ".join(part for part in parts if part))


def build_intake_row(context: ProductContext, review: ReviewImage, fetched_at: str) -> Dict[str, str]:
    comment = normalize_whitespace(" ".join(part for part in [review.review_title, review.review_body] if part))
    size_display = normalize_whitespace(review.size_raw) or extract_size(comment)
    if BRA_SIZE_RE.search(size_display):
        size_display = normalize_bra_size(size_display)
    measurements = extract_measurements(comment, size_display)
    if "product_url" in review.extra:
        product_url = normalize_whitespace(review.extra.get("product_url"))
    else:
        product_url = context.url
    if product_url:
        product_url = canonical_product_url(product_url)
    use_context_product = "product_url" not in review.extra or product_url == context.url
    product_title = normalize_whitespace(review.extra.get("product_title")) or (context.title if use_context_product else "")
    product_description = normalize_whitespace(review.extra.get("product_description")) or (
        context.description if use_context_product else ""
    )
    product_detail = normalize_whitespace(review.extra.get("product_detail")) or (context.detail if use_context_product else "")
    product_category = normalize_whitespace(review.extra.get("product_category")) or (context.category if use_context_product else "")
    product_variant = normalize_whitespace(review.extra.get("product_variant")) or (context.variant if use_context_product else "")
    image_source_type = normalize_whitespace(review.extra.get("image_source_type")) or "customer_review_image"
    image_source_detail = normalize_whitespace(review.extra.get("image_source_detail"))
    row = {header: "" for header in INTAKE_HEADERS}
    row.update(
        {
            "id": review.review_id,
            "original_url_display": review.image_url,
            "image_source_type": image_source_type,
            "image_source_detail": image_source_detail,
            "product_page_url_display": product_url,
            "user_comment": comment,
            "date_review_submitted_raw": review.date_raw,
            "review_date": review.review_date or review_date_from_raw(review.date_raw),
            "source_site_display": f"{urlparse(product_url or context.url).scheme}://{urlparse(product_url or context.url).netloc}/",
            "status_code": "200",
            "fetched_at": fetched_at,
            "updated_at": fetched_at,
            "brand": context.brand,
            "search_fts": build_search_fts([context.brand, product_title, product_description, comment, size_display]),
            "clothing_type_id": classify_clothing_type(context),
            "reviewer_profile_url": review.reviewer_profile_url,
            "reviewer_name_raw": review.reviewer_name,
            "color_canonical": context.color.lower(),
            "color_display": context.color,
            "size_display": size_display,
            "product_title_raw": product_title,
            "product_subtitle_raw": context.subtitle,
            "product_description_raw": product_description,
            "product_detail_raw": product_detail,
            "product_category_raw": product_category,
            "product_variant_raw": product_variant,
        }
    )
    row.update(measurements)
    return row


def dedupe_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    deduped: List[Dict[str, str]] = []
    for row in rows:
        review_id = row.get("id") or ""
        image_url = row.get("original_url_display") or ""
        product_url = row.get("product_page_url_display") or ""
        if review_id and image_url and "cdn.stamped.io/uploads/photos/" in image_url:
            stable_key = (review_id, image_url)
        else:
            stable_key = (review_id, product_url, image_url)
        fallback_key = (
            product_url,
            image_url,
        )
        stable_key = stable_key if any(stable_key) else fallback_key
        if stable_key in seen:
            continue
        seen.add(stable_key)
        deduped.append(row)
    return deduped


def write_intake_csv(rows: Iterable[Dict[str, str]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INTAKE_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in INTAKE_HEADERS})


def validate_rows(rows: Sequence[Dict[str, str]]) -> Dict[str, object]:
    numeric_fields = ["height_in_display", "waist_in", "hips_in_display", "inseam_inches_display", "bust_in_number_display"]
    invalid_numeric = {
        field: sum(1 for row in rows if row.get(field) and not re.fullmatch(r"\d+(?:\.\d+)?", str(row[field])))
        for field in numeric_fields
    }
    bra_rows = [
        row
        for row in rows
        if row.get("clothing_type_id") == "bra" or re.search(r"\bbras?|bralettes?\b", row.get("product_title_raw", ""), re.I)
    ]
    return {
        "rows_written": len(rows),
        "distinct_reviews": len({row.get("id", "") for row in rows if row.get("id")}),
        "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
        "distinct_products": len({row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}),
        "rows_with_image_url": sum(1 for row in rows if row.get("original_url_display")),
        "rows_with_customer_review_image": sum(
            1
            for row in rows
            if row.get("original_url_display") and (row.get("image_source_type") or "customer_review_image") == "customer_review_image"
        ),
        "rows_with_catalog_model_image": sum(
            1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "catalog_model_image"
        ),
        "rows_missing_image_url": sum(1 for row in rows if not row.get("original_url_display")),
        "rows_missing_product_url": sum(1 for row in rows if not row.get("product_page_url_display")),
        "rows_with_user_comment": sum(1 for row in rows if row.get("user_comment")),
        "rows_with_size": sum(1 for row in rows if row.get("size_display")),
        "rows_with_customer_ordered_size": sum(1 for row in rows if row.get("size_display")),
        "rows_with_any_measurement": sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS)),
        "rows_for_bra_products": len(bra_rows),
        "rows_for_bra_products_with_customer_bra_size": sum(
            1
            for row in bra_rows
            if (row.get("bust_in_number_display") and row.get("cupsize_display"))
            or BRA_SIZE_RE.search(row.get("size_display", ""))
        ),
        "rows_with_image_and_product_url": sum(
            1 for row in rows if row.get("original_url_display") and row.get("product_page_url_display")
        ),
        "rows_with_image_product_and_measurement": sum(
            1
            for row in rows
            if row.get("original_url_display")
            and row.get("product_page_url_display")
            and any(row.get(field) for field in MEASUREMENT_FIELDS)
        ),
        "supabase_qualified_rows": sum(
            1
            for row in rows
            if row.get("original_url_display")
            and row.get("product_page_url_display")
            and row.get("size_display")
            and any(row.get(field) for field in MEASUREMENT_FIELDS)
        ),
        "rows_with_image_product_size_and_measurement": sum(
            1
            for row in rows
            if row.get("original_url_display")
            and row.get("product_page_url_display")
            and row.get("size_display")
            and any(row.get(field) for field in MEASUREMENT_FIELDS)
        ),
        "rows_with_image_product_and_user_comment": sum(
            1
            for row in rows
            if row.get("original_url_display") and row.get("product_page_url_display") and row.get("user_comment")
        ),
        "rows_with_product_context": sum(
            1 for row in rows if row.get("product_title_raw") or row.get("product_description_raw") or row.get("product_detail_raw")
        ),
        "invalid_numeric_fields": invalid_numeric,
    }


def write_summary(
    summary_json: Path,
    *,
    site: str,
    retailer: str,
    rows: Sequence[Dict[str, str]],
    output_csv: Path,
    started_at: str,
    finished_at: str,
    products_scanned: int,
    adapter: str,
    product_summaries: Sequence[Dict[str, object]],
    errors: Sequence[str],
) -> None:
    summary = {
        "site": site,
        "retailer": retailer_slug(retailer),
        "adapter": adapter,
        "products_scanned": products_scanned,
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": finished_at,
        "access_policy": SCRAPE_ACCESS_POLICY,
        "product_summaries": list(product_summaries),
        "errors": list(errors),
    }
    summary.update(validate_rows(rows))
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
