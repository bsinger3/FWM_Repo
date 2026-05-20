#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import http.cookiejar
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from step1_intake_utils import (
    MEASUREMENT_FIELDS,
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    extract_ordered_size,
    normalize_whitespace,
    write_intake_csv,
)


SITE_ROOT = "https://www.missacc.com"
RETAILER = "missacc_com"
SITEMAP_INDEX = f"{SITE_ROOT}/marketing/dress_missacc_us_sitemap_us.xml"
PRODUCT_SITEMAP = f"{SITE_ROOT}/marketing_documents/sitemap/dress_missacc_us_sitemap_us/product.xml.gz"
REVIEW_LIST_ENDPOINT = f"{SITE_ROOT}/rest/v1/review/list"
REVIEW_IMAGES_ENDPOINT = f"{SITE_ROOT}/rest/v1/review/images"

DATA_ROOT = Path(os.environ["FWM_DATA_DIR"]).expanduser() if os.environ.get("FWM_DATA_DIR") else Path(__file__).resolve().parents[4].parent / "FWM_Data"
OUTPUT_DIR = DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data" / RETAILER
OUTPUT_CSV = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema.csv"
SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_amazon_schema_summary.json"
REVIEW_RECORDS_JSONL = OUTPUT_DIR / f"{RETAILER}_review_records.jsonl"
CATALOG_SNAPSHOT_JSON = OUTPUT_DIR / f"{RETAILER}_public_catalog_snapshot.json"
LEGACY_INTAKE_SUMMARY_JSON = OUTPUT_DIR / f"{RETAILER}_reviews_matching_intake_schema_summary.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
STOP_STATUS_CODES = {401, 403, 407, 423, 429, 430, 503}
BLOCK_MARKERS = [
    "just a moment",
    "captcha",
    "verify you are human",
    "access denied",
    "attention required",
    "cloudflare",
    "cf-chl",
    "datadome",
]
SPU_RE = re.compile(r"-([A-Z]{2,5}\d{3,8})\.html(?:$|\?)")
APPAREL_RE = re.compile(
    r"\b(dress|dresses|gown|bridesmaid|bride|wedding|prom|evening|cocktail|mother|jumpsuit|romper|robe)\b",
    re.I,
)
NUMERIC_FIELD_RE = re.compile(r"\d+(?:\.\d+)?")
NUMERIC_NORMALIZED_FIELDS = [
    "height_in_display",
    "weight_display_display",
    "weight_lbs_display",
    "bust_in_display",
    "bra_band_in_display",
    "bust_in_number_display",
    "hips_in_display",
    "waist_in",
    "inseam_inches_display",
    "age_years_display",
]


class PressureStop(RuntimeError):
    pass


class TransientRequestError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_url(url: str) -> str:
    return url.split("#", 1)[0].split("?", 1)[0].strip()


def iri_to_uri(url: str) -> str:
    parts = urlsplit(url)
    netloc = parts.netloc.encode("idna").decode("ascii") if parts.netloc else ""
    path = quote(parts.path, safe="/%:@")
    query = quote(parts.query, safe="=&?/:;+,%@")
    fragment = quote(parts.fragment, safe="=&?/:;+,%@")
    return urlunsplit((parts.scheme, netloc, path, query, fragment))


def spu_from_url(url: str) -> str:
    match = SPU_RE.search(url)
    return match.group(1) if match else ""


def title_from_url(url: str, spu_code: str) -> str:
    path = urlparse(url).path
    slug = path.rsplit("/", 1)[-1].removesuffix(".html")
    if slug.startswith("product-"):
        slug = slug[len("product-") :]
    if spu_code and slug.lower().endswith("-" + spu_code.lower()):
        slug = slug[: -(len(spu_code) + 1)]
    return normalize_whitespace(slug.replace("-", " ")).title()


def category_from_title(title: str) -> str:
    lowered = title.lower()
    if "bridesmaid" in lowered:
        return "BRIDESMAID DRESSES"
    if "prom" in lowered:
        return "PROM DRESSES"
    if "wedding" in lowered and "guest" in lowered:
        return "WEDDING GUEST DRESSES"
    if "wedding" in lowered or "bridal" in lowered:
        return "WEDDING DRESSES"
    if "mother" in lowered:
        return "MOTHER OF THE BRIDE DRESSES"
    if "evening" in lowered:
        return "EVENING DRESSES"
    if "cocktail" in lowered:
        return "COCKTAIL DRESSES"
    if "dress" in lowered or "gown" in lowered:
        return "DRESSES"
    return ""


def clothing_type_from_title(title: str) -> str:
    lowered = title.lower()
    if "jumpsuit" in lowered:
        return "jumpsuit"
    if "romper" in lowered:
        return "romper"
    if "dress" in lowered or "gown" in lowered:
        return "dress"
    return ""


def context_for_product(product: Dict[str, str], api_product: Optional[Dict[str, object]] = None) -> ProductContext:
    api_product = api_product or {}
    title = normalize_whitespace(api_product.get("productName")) or product["title"]
    category = normalize_whitespace(api_product.get("categoryName")) or product["category"]
    image = normalize_whitespace(api_product.get("productImage"))
    detail_parts = []
    if image:
        detail_parts.append(f"product_image={image}")
    if api_product.get("productId"):
        detail_parts.append(f"product_id={api_product.get('productId')}")
    if api_product.get("productFamilyKey"):
        detail_parts.append(f"product_family={api_product.get('productFamilyKey')}")
    return ProductContext(
        url=product["url"],
        title=title,
        description=product.get("description", ""),
        detail=" | ".join(detail_parts),
        category=category,
        brand="Missacc",
        product_id=normalize_whitespace(api_product.get("productId")),
        handle=product["spu_code"],
        provider_hints="Missacc public Nuxt review endpoints",
    )


def normalize_image_url(item: Dict[str, object]) -> str:
    image = normalize_whitespace(item.get("image"))
    video = normalize_whitespace(item.get("video"))
    return image or video


def make_review_record(
    record: Dict[str, object],
    product: Dict[str, str],
    source_endpoint: str,
    page_index: int,
    fetched_at: str,
) -> Dict[str, object]:
    api_product = record.get("product") if isinstance(record.get("product"), dict) else {}
    product_url = product["url"]
    if api_product and api_product.get("seoLink"):
        product_url = f"{SITE_ROOT}/product-{api_product.get('seoLink')}.html"
    image_list = record.get("imageList") if isinstance(record.get("imageList"), list) else []
    if not image_list and isinstance(record.get("image"), dict):
        image_list = [record["image"]]
    attributes = record.get("attributes") if isinstance(record.get("attributes"), list) else []
    attr_text = "; ".join(
        f"{normalize_whitespace(attr.get('attributesName'))}: {normalize_whitespace(attr.get('attributeOptionsValue'))}"
        for attr in attributes
        if isinstance(attr, dict)
    )
    return {
        "source_site": SITE_ROOT,
        "source_endpoint": source_endpoint,
        "source_page_index": page_index,
        "fetched_at": fetched_at,
        "review_id": normalize_whitespace(record.get("reviewId")),
        "reviewer_name": normalize_whitespace(record.get("customerName")),
        "rating": normalize_whitespace(record.get("starRating")),
        "date_raw": normalize_whitespace(record.get("created")),
        "review_title": normalize_whitespace(record.get("title")),
        "review_text": normalize_whitespace(record.get("review")),
        "reply_text": normalize_whitespace(record.get("reply")),
        "fit": normalize_whitespace(record.get("fit")),
        "ordered_size": normalize_whitespace(record.get("productSize")),
        "product_color": normalize_whitespace(record.get("productColor")),
        "attributes_text": attr_text,
        "spu_code": normalize_whitespace(record.get("spuCode")) or product["spu_code"],
        "product_url": clean_url(product_url),
        "product_title": normalize_whitespace(api_product.get("productName")) or product["title"],
        "product_category": normalize_whitespace(api_product.get("categoryName")) or product["category"],
        "product_metadata": api_product,
        "images": image_list,
    }


def row_from_record(review_record: Dict[str, object], image_item: Dict[str, object], image_index: int, fetched_at: str) -> Dict[str, str]:
    product = {
        "url": normalize_whitespace(review_record.get("product_url")),
        "title": normalize_whitespace(review_record.get("product_title")),
        "category": normalize_whitespace(review_record.get("product_category")),
        "spu_code": normalize_whitespace(review_record.get("spu_code")),
        "description": "",
    }
    context = context_for_product(product, review_record.get("product_metadata") if isinstance(review_record.get("product_metadata"), dict) else {})
    context.color = normalize_whitespace(review_record.get("product_color"))
    review_id = normalize_whitespace(review_record.get("review_id"))
    image_url = normalize_image_url(image_item)
    fallback = hashlib.md5(
        f"{review_record.get('product_url')}|{review_id}|{image_url}|{review_record.get('review_text')}".encode("utf-8")
    ).hexdigest()[:16]
    comment_parts = [
        normalize_whitespace(review_record.get("review_title")),
        normalize_whitespace(review_record.get("review_text")),
        normalize_whitespace(review_record.get("attributes_text")),
    ]
    review = ReviewImage(
        image_url=image_url,
        review_id=f"missacc-{review_id}-{image_index}" if review_id else f"missacc-{fallback}-{image_index}",
        review_title="",
        review_body=" ".join(part for part in comment_parts if part),
        reviewer_name=normalize_whitespace(review_record.get("reviewer_name")),
        date_raw=normalize_whitespace(review_record.get("date_raw")),
        size_raw=normalize_whitespace(review_record.get("ordered_size")),
        rating=normalize_whitespace(review_record.get("rating")),
        extra={
            "image_source_type": "customer_review_image",
            "image_source_detail": f"public Missacc {review_record.get('source_endpoint')} review media",
            "product_url": normalize_whitespace(review_record.get("product_url")),
            "product_title": normalize_whitespace(review_record.get("product_title")),
            "product_category": normalize_whitespace(review_record.get("product_category")),
            "product_variant": normalize_whitespace(review_record.get("product_color")),
        },
    )
    row = build_intake_row(context, review, fetched_at)
    if not row.get("size_display"):
        row["size_display"] = extract_ordered_size(row.get("user_comment", ""))
    row["content_type"] = "image/webp" if image_url.endswith(".webp") else ""
    row["width"] = normalize_whitespace(image_item.get("width")) if isinstance(image_item, dict) else ""
    row["height"] = normalize_whitespace(image_item.get("height")) if isinstance(image_item, dict) else ""
    row["clothing_type_id"] = clothing_type_from_title(row.get("product_title_raw", "")) or row.get("clothing_type_id", "")
    sanitize_numeric_fields(row)
    return row


def sanitize_numeric_fields(row: Dict[str, str]) -> None:
    for field in NUMERIC_NORMALIZED_FIELDS:
        value = normalize_whitespace(row.get(field))
        if not value or re.fullmatch(r"\d+(?:\.\d+)?", value):
            continue
        match = NUMERIC_FIELD_RE.search(value)
        row[field] = match.group(0) if match else ""


class MissaccClient:
    def __init__(self, delay_seconds: float = 0.08) -> None:
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookie_jar))
        self.delay_seconds = delay_seconds
        self.client_ip = ""

    def _check_body(self, status: int, body: bytes, url: str) -> None:
        if status in STOP_STATUS_CODES:
            raise PressureStop(f"blocked_or_rate_limited_http_{status}: {url}")
        text_sample = body[:200_000].decode("utf-8", errors="replace").lower()
        if any(marker in text_sample for marker in BLOCK_MARKERS):
            raise PressureStop(f"blocked_or_challenged_response: {url}")

    def _request(self, url: str, *, data: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None) -> bytes:
        req_headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
        req_headers.update({key: normalize_whitespace(value).encode("latin-1", "ignore").decode("latin-1") for key, value in (headers or {}).items()})
        request = Request(iri_to_uri(url), data=data, headers=req_headers, method="POST" if data is not None else "GET")
        try:
            with self.opener.open(request, timeout=60) as response:
                body = response.read()
                self._check_body(getattr(response, "status", 200), body, url)
                return body
        except HTTPError as exc:
            body = exc.read()
            self._check_body(exc.code, body, url)
            raise
        except URLError as exc:
            raise TransientRequestError(f"request_failed: {url}: {exc}") from exc

    def bootstrap(self) -> None:
        body = self._request(SITE_ROOT + "/")
        text = body.decode("utf-8", errors="replace")
        ip_match = re.search(r'"(\d{1,3}(?:\.\d{1,3}){3})"', text)
        self.client_ip = ip_match.group(1) if ip_match else "217.138.206.37"

    def cookie_value(self, name: str) -> str:
        for cookie in self.cookie_jar:
            if cookie.name == name:
                return cookie.value
        return ""

    def auth_headers(self, referer: str) -> Dict[str, str]:
        token = unquote(self.cookie_value("ma-token"))
        uuid = self.cookie_value("ma-uuid")
        referer = iri_to_uri(referer or SITE_ROOT + "/")
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": token,
            "Origin": SITE_ROOT,
            "Referer": referer,
            "uuid": uuid,
            "currency": "USD",
            "domain": "www.missacc.com",
            "languageCode": "en",
            "shipCountryIso": "US",
            "isSupportWebp": "1",
            "clientCountryCode": "US",
            "clientLanguageCode": "",
            "clientIp": self.client_ip,
            "clientUserAgent": USER_AGENT,
        }

    def get_text(self, url: str) -> str:
        time.sleep(self.delay_seconds)
        return self._request(url).decode("utf-8", errors="replace")

    def get_bytes(self, url: str) -> bytes:
        time.sleep(self.delay_seconds)
        return self._request(url)

    def post_json(self, url: str, payload: Dict[str, object], referer: str) -> Dict[str, object]:
        last_transient = ""
        for attempt in range(1, 6):
            time.sleep(self.delay_seconds if attempt == 1 else max(self.delay_seconds, 2.0 * attempt))
            try:
                body = self._request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=self.auth_headers(referer),
                )
            except TransientRequestError as exc:
                last_transient = str(exc)
                continue
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                raise PressureStop(f"non_json_response: {url}: {body[:200].decode('utf-8', errors='replace')}") from exc
            code = data.get("code")
            if code == 40001:
                raise PressureStop(f"auth_challenge_code_40001: {url}")
            if code == 201:
                return data
            if code == 500001 and attempt < 5:
                continue
            raise RuntimeError(f"unexpected_api_code_{code}: {url}: {data.get('msg')}")
        raise RuntimeError(f"transient_request_failed_after_retries: {last_transient}")

    def refresh_and_retry_post(self, url: str, payload: Dict[str, object], referer: str) -> Dict[str, object]:
        try:
            return self.post_json(url, payload, referer)
        except RuntimeError:
            self.bootstrap()
            return self.post_json(url, payload, referer)


def discover_products(client: MissaccClient) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    index_text = client.get_text(SITEMAP_INDEX)
    gz_bytes = client.get_bytes(PRODUCT_SITEMAP)
    xml = gzip.decompress(gz_bytes).decode("utf-8", errors="replace")
    urls = [clean_url(match) for match in re.findall(r"<loc>(.*?)</loc>", xml)]
    products: List[Dict[str, str]] = []
    seen = set()
    for url in urls:
        spu_code = spu_from_url(url)
        if not spu_code or url in seen:
            continue
        seen.add(url)
        title = title_from_url(url, spu_code)
        category = category_from_title(title)
        products.append(
            {
                "url": url,
                "spu_code": spu_code,
                "title": title,
                "category": category,
                "description": f"Public Missacc product URL discovered from product sitemap. Product code {spu_code}.",
                "in_womens_clothing_scope": bool(APPAREL_RE.search(title)),
            }
        )
    return products, {
        "sitemap_index": SITEMAP_INDEX,
        "sitemap_index_bytes": len(index_text.encode("utf-8")),
        "product_sitemap": PRODUCT_SITEMAP,
        "product_sitemap_gzip_bytes": len(gz_bytes),
        "product_urls_in_sitemap": len(urls),
        "unique_product_urls": len(products),
    }


def scrape_product_reviews(
    client: MissaccClient,
    product: Dict[str, str],
    max_pages_per_product: int,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    records: List[Dict[str, object]] = []
    page_requests: List[Dict[str, object]] = []
    pages_total = 0
    for page_index in range(1, max_pages_per_product + 1):
        payload = {
            "spuCode": product["spu_code"],
            "pageIndex": page_index,
            "clientType": "pc",
            "filterType": "",
        }
        data = client.refresh_and_retry_post(REVIEW_LIST_ENDPOINT, payload, product["url"])
        body = data.get("data") if isinstance(data.get("data"), dict) else {}
        page_records = body.get("records") if isinstance(body.get("records"), list) else []
        pages_total = int(body.get("pages") or 0)
        total = int(body.get("total") or 0)
        page_requests.append(
            {
                "page": page_index,
                "records": len(page_records),
                "pages_total": pages_total,
                "total": total,
            }
        )
        fetched_at = utc_now()
        for record in page_records:
            if isinstance(record, dict):
                records.append(make_review_record(record, product, "review/list", page_index, fetched_at))
        if page_index >= pages_total:
            break
    return records, {
        "product_url": product["url"],
        "spu_code": product["spu_code"],
        "product_title": product["title"],
        "product_category": product["category"],
        "review_pages": page_requests,
        "reviews": len(records),
        "image_reviews": sum(1 for record in records if record.get("images")),
        "image_rows": sum(len(record.get("images") or []) for record in records),
        "skipped_from_output": not any(record.get("images") for record in records),
        "skip_reason": "no_customer_review_images_on_product_review_pages"
        if not any(record.get("images") for record in records)
        else "",
    }


def scrape_media_feed(client: MissaccClient, max_pages: int, seed_spu_code: str) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    records: List[Dict[str, object]] = []
    page_requests: List[Dict[str, object]] = []
    placeholder_product = {
        "url": SITE_ROOT + "/",
        "spu_code": "",
        "title": "",
        "category": "",
        "description": "",
        "in_womens_clothing_scope": True,
    }
    for page_index in range(1, max_pages + 1):
        payload = {"spuCode": seed_spu_code, "pageIndex": page_index, "filter": "image", "pageSize": 10}
        data = client.refresh_and_retry_post(REVIEW_IMAGES_ENDPOINT, payload, SITE_ROOT + "/")
        body = data.get("data") if isinstance(data.get("data"), dict) else {}
        page_records = body.get("records") if isinstance(body.get("records"), list) else []
        pages_total = int(body.get("pages") or 0)
        total = int(body.get("total") or 0)
        page_requests.append({"page": page_index, "records": len(page_records), "pages_total": pages_total, "total": total})
        fetched_at = utc_now()
        for record in page_records:
            if not isinstance(record, dict):
                continue
            api_product = record.get("product") if isinstance(record.get("product"), dict) else {}
            product = dict(placeholder_product)
            product["spu_code"] = normalize_whitespace(record.get("spuCode")) or normalize_whitespace(api_product.get("spuCode"))
            product["title"] = normalize_whitespace(api_product.get("productName"))
            product["category"] = normalize_whitespace(api_product.get("categoryName"))
            if api_product.get("seoLink"):
                product["url"] = f"{SITE_ROOT}/product-{api_product.get('seoLink')}.html"
            records.append(make_review_record(record, product, "review/images", page_index, fetched_at))
        if page_index >= pages_total:
            break
    return records, page_requests


def dedupe_review_records(records: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    seen = set()
    deduped = []
    for record in records:
        key = (
            normalize_whitespace(record.get("review_id")),
            normalize_whitespace(record.get("spu_code")),
            normalize_whitespace(record.get("source_endpoint")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def rows_from_records(records: Iterable[Dict[str, object]], fetched_at: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for record in records:
        images = record.get("images") if isinstance(record.get("images"), list) else []
        for index, image_item in enumerate(images, start=1):
            if not isinstance(image_item, dict):
                continue
            if normalize_whitespace(image_item.get("type")) != "image":
                continue
            image_url = normalize_image_url(image_item)
            if not image_url:
                continue
            rows.append(row_from_record(record, image_item, index, fetched_at))
    return dedupe_rows(rows)


def strict_qualified_rows(rows: Sequence[Dict[str, str]]) -> int:
    return sum(
        1
        for row in rows
        if row.get("original_url_display")
        and row.get("image_source_type") == "customer_review_image"
        and (row.get("product_page_url_display") or row.get("monetized_product_url_display"))
        and row.get("size_display")
        and row.get("size_display", "").lower() != "unknown"
        and any(row.get(field) for field in MEASUREMENT_FIELDS)
    )


def write_jsonl(path: Path, records: Iterable[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def write_summary(summary: Dict[str, object]) -> None:
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def scrape(args: argparse.Namespace) -> Tuple[List[Dict[str, str]], Dict[str, object], List[Dict[str, object]]]:
    started_at = utc_now()
    client = MissaccClient(delay_seconds=args.request_delay_seconds)
    errors: List[str] = []
    stop_reason = ""
    stopped_at: Dict[str, object] = {}
    client.bootstrap()
    products, product_source = discover_products(client)
    if args.limit_products:
        products = products[: args.limit_products]
    CATALOG_SNAPSHOT_JSON.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_SNAPSHOT_JSON.write_text(json.dumps({"products": products, "product_sources": product_source}, indent=2), encoding="utf-8")

    all_records: List[Dict[str, object]] = []
    product_summaries: List[Dict[str, object]] = []
    products_scanned = 0
    review_pages_scanned = 0
    try:
        for index, product in enumerate(products, start=1):
            try:
                product_records, product_summary = scrape_product_reviews(client, product, args.max_pages_per_product)
            except RuntimeError as exc:
                errors.append(f"product_review_error: index={index} url={product['url']} error={exc}")
                product_records = []
                product_summary = {
                    "product_url": product["url"],
                    "spu_code": product["spu_code"],
                    "product_title": product["title"],
                    "product_category": product["category"],
                    "review_pages": [],
                    "reviews": 0,
                    "image_reviews": 0,
                    "image_rows": 0,
                    "skipped_from_output": True,
                    "skip_reason": f"product_review_error: {exc}",
                }
            all_records.extend(product_records)
            product_summaries.append(product_summary)
            products_scanned += 1
            review_pages_scanned += len(product_summary["review_pages"])
            if index % args.progress_every == 0:
                print(
                    f"[products] scanned={index}/{len(products)} records={len(all_records)} "
                    f"image_records={sum(1 for record in all_records if record.get('images'))}",
                    flush=True,
                )
    except PressureStop as exc:
        stop_reason = str(exc)
        stopped_at = {"phase": "product_review_paging", "product_index": products_scanned + 1}
        errors.append(stop_reason)

    media_records: List[Dict[str, object]] = []
    media_page_requests: List[Dict[str, object]] = []
    if not stop_reason:
        try:
            seed_spu_code = products[0]["spu_code"] if products else ""
            media_records, media_page_requests = scrape_media_feed(client, args.max_media_pages, seed_spu_code)
            all_records.extend(media_records)
        except PressureStop as exc:
            stop_reason = str(exc)
            stopped_at = {"phase": "media_feed_paging", "page": len(media_page_requests) + 1}
            errors.append(stop_reason)
        except RuntimeError as exc:
            stop_reason = str(exc)
            stopped_at = {"phase": "media_feed_paging", "page": len(media_page_requests) + 1}
            errors.append(stop_reason)

    all_records = dedupe_review_records(all_records)
    rows = rows_from_records(all_records, utc_now())
    finished_at = utc_now()
    rows_with_product_url = sum(1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display"))
    rows_with_measurements = sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS))
    rows_with_customer_image = sum(1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image")
    rows_with_ordered_size = sum(
        1 for row in rows if row.get("size_display") and row.get("size_display", "").lower() != "unknown"
    )
    summary = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "missacc_public_sitemap_product_review_list_and_media_feed",
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": product_source,
        "products_discovered": product_source["unique_product_urls"],
        "products_scanned": products_scanned,
        "products_excluded_from_output": sum(1 for item in product_summaries if item.get("skipped_from_output")),
        "review_pages_scanned": review_pages_scanned,
        "media_pages_scanned": len(media_page_requests),
        "media_page_requests": media_page_requests,
        "exhaustive_review_paging": not stop_reason and products_scanned == len(products),
        "coverage_exhaustive": not stop_reason and products_scanned == len(products),
        "product_summaries": product_summaries,
        "review_records_jsonl": str(REVIEW_RECORDS_JSONL),
        "catalog_snapshot_json": str(CATALOG_SNAPSHOT_JSON),
        "output_csv": str(OUTPUT_CSV),
        "summary_json": str(SUMMARY_JSON),
        "rows_written": len(rows),
        "distinct_reviews": len({normalize_whitespace(record.get("review_id")) for record in all_records if record.get("review_id")}),
        "review_records_written": len(all_records),
        "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
        "distinct_product_urls": len({row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}),
        "rows_with_distinct_product_url": rows_with_product_url,
        "rows_with_any_measurement": rows_with_measurements,
        "rows_with_customer_image": rows_with_customer_image,
        "rows_with_customer_review_image": rows_with_customer_image,
        "rows_with_catalog_model_image": 0,
        "rows_with_customer_ordered_size": rows_with_ordered_size,
        "rows_with_size": rows_with_ordered_size,
        "rows_supabase_qualified": strict_qualified_rows(rows),
        "rows_catalog_model_qualified": 0,
        "access_policy": "public sitemap, public product pages, and anonymous Nuxt review endpoints only; stop on 429/captcha/WAF/auth challenge",
        "stopped_at": stopped_at,
        "stop_reason": stop_reason,
        "errors": errors,
    }
    return rows, summary, all_records


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Missacc public product-level reviews and customer review images.")
    parser.add_argument("--limit-products", type=int, default=0)
    parser.add_argument("--max-pages-per-product", type=int, default=200)
    parser.add_argument("--max-media-pages", type=int, default=500)
    parser.add_argument("--request-delay-seconds", type=float, default=0.08)
    parser.add_argument("--progress-every", type=int, default=250)
    parser.add_argument("--rebuild-from-jsonl", action="store_true")
    args = parser.parse_args(argv)
    if args.rebuild_from_jsonl:
        records = read_jsonl(REVIEW_RECORDS_JSONL)
        rows = rows_from_records(records, utc_now())
        write_intake_csv(rows, OUTPUT_CSV)
        summary_path = SUMMARY_JSON if SUMMARY_JSON.exists() else LEGACY_INTAKE_SUMMARY_JSON
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        rows_with_customer_image = sum(
            1 for row in rows if row.get("original_url_display") and row.get("image_source_type") == "customer_review_image"
        )
        rows_with_ordered_size = sum(
            1 for row in rows if row.get("size_display") and row.get("size_display", "").lower() != "unknown"
        )
        summary.update(
            {
                "rows_written": len(rows),
                "distinct_images": len({row.get("original_url_display", "") for row in rows if row.get("original_url_display")}),
                "distinct_product_urls": len({row.get("product_page_url_display", "") for row in rows if row.get("product_page_url_display")}),
                "rows_with_distinct_product_url": sum(1 for row in rows if row.get("product_page_url_display") or row.get("monetized_product_url_display")),
                "rows_with_any_measurement": sum(1 for row in rows if any(row.get(field) for field in MEASUREMENT_FIELDS)),
                "rows_with_customer_image": rows_with_customer_image,
                "rows_with_customer_review_image": rows_with_customer_image,
                "rows_with_customer_ordered_size": rows_with_ordered_size,
                "rows_with_size": rows_with_ordered_size,
                "rows_supabase_qualified": strict_qualified_rows(rows),
                "rebuilt_from_review_records_jsonl_at": utc_now(),
            }
        )
        write_summary(summary)
        print(f"Rebuilt rows from JSONL: {len(rows)}")
        print(f"CSV: {OUTPUT_CSV}")
        print(f"Summary: {SUMMARY_JSON}")
        return 0
    rows, summary, records = scrape(args)
    write_intake_csv(rows, OUTPUT_CSV)
    write_jsonl(REVIEW_RECORDS_JSONL, records)
    write_summary(summary)
    print(f"Rows written: {len(rows)}")
    print(f"Review records written: {len(records)}")
    print(f"Products discovered: {summary['products_discovered']}")
    print(f"Products scanned: {summary['products_scanned']}")
    print(f"Review pages scanned: {summary['review_pages_scanned']}")
    print(f"Media pages scanned: {summary['media_pages_scanned']}")
    print(f"Stop reason: {summary['stop_reason']}")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"JSONL: {REVIEW_RECORDS_JSONL}")
    print(f"Summary: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
