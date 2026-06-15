#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import html
import json
import re
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlparse

import requests

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    classify_clothing_type,
    dedupe_rows,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    write_intake_csv,
    write_summary,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


SITE = "https://www.quince.com"
RETAILER = "quince.com"
SITEMAP_URL = f"{SITE}/sitemap_us.xml"
REVIEW_API = "https://api.onequince.com/review-system/reviews/external/fetch-reviews"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
JSON_HEADERS = {
    **HEADERS,
    "Accept": "application/json,text/plain,*/*",
    "Origin": SITE,
}
NEXT_BUILD_ID = ""
STOP_STATUS_CODES = {401, 403, 407, 423, 429, 430, 503}
BLOCK_MARKERS = [
    "captcha",
    "verify you are human",
    "access denied",
    "attention required",
    "cloudflare",
    "cf-chl",
    "datadome",
    "perimeterx",
    "px-captcha",
    "akamai",
    "awswaf",
    "challenge.js",
]

EXCLUDED_PATH_PARTS = {
    "account",
    "accounts",
    "baby",
    "baby-&-kids",
    "beauty",
    "beauty-&-wellness",
    "beauty-and-wellness",
    "boys",
    "business",
    "gifts",
    "home",
    "how-it-works",
    "jewelry",
    "kids",
    "men",
    "mens",
    "murad",
    "partner-offers",
    "pets",
    "referral-program-terms-and-conditions",
    "toddler-boy",
    "toddler-girl",
    "travel",
    "wellness",
}
EXCLUDED_PATH_PREFIXES = (
    "baby-",
    "boy",
    "boys",
    "girl",
    "girls",
    "kid",
    "kids",
    "toddler-",
)
OUT_OF_SCOPE_PRODUCT_RE = re.compile(
    r"\b("
    r"boys?|girls?|kids?|dog|puppy|"
    r"bags?|totes?|satchels?|crossbod(?:y|ies)|wallets?|"
    r"sneakers?|sandals?|shoes?|boots?|flats?|loafers?|"
    r"sunglasses|necklaces?|rings?|bracelets?|earrings?|hoops?|diamond"
    r")\b",
    re.I,
)


class StopScrape(RuntimeError):
    pass


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def assert_public_response(response: requests.Response, url: str) -> None:
    if response.status_code in STOP_STATUS_CODES:
        raise StopScrape(f"stopped_on_http_{response.status_code}: {url}")
    content_type = response.headers.get("content-type", "")
    if "text" in content_type or "html" in content_type or "json" in content_type:
        lower = response.text[:250_000].lower()
        hits = [marker for marker in BLOCK_MARKERS if marker in lower]
        if hits:
            raise StopScrape(f"stopped_on_block_marker_{','.join(hits)}: {url}")


def fetch_text(session: requests.Session, url: str, *, timeout: int = 45) -> str:
    response = session.get(url, timeout=timeout)
    assert_public_response(response, url)
    response.raise_for_status()
    return response.text


def clean_url(url: str) -> str:
    return html.unescape(normalize_whitespace(url)).split("#", 1)[0]


def discover_urls(limit: Optional[int] = None) -> List[str]:
    text = fetch_text(make_session(), SITEMAP_URL)
    locs = [clean_url(match) for match in re.findall(r"<loc>(.*?)</loc>", text, re.I | re.S)]
    sitemap_urls = [url for url in locs if re.search(r"/sitemap_[^/]+\.xml$", url)]
    urls: List[str] = []
    if sitemap_urls:
        session = make_session()
        for sitemap_url in sitemap_urls:
            if "pdp" not in sitemap_url.lower():
                continue
            sitemap_text = fetch_text(session, sitemap_url)
            urls.extend(clean_url(match) for match in re.findall(r"<loc>(.*?)</loc>", sitemap_text, re.I | re.S))
    else:
        urls = locs
    urls = [url for url in urls if is_candidate_url(url)]
    seen = set()
    out: List[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if limit and len(out) >= limit:
            break
    return out


def is_candidate_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "www.quince.com":
        return False
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if not parts:
        return False
    lowered = [part.lower() for part in parts]
    if any(part in EXCLUDED_PATH_PARTS or part.startswith(EXCLUDED_PATH_PREFIXES) for part in lowered):
        return False
    return True


def discover_next_build_id(session: requests.Session, sample_product_url: str) -> str:
    global NEXT_BUILD_ID
    if NEXT_BUILD_ID:
        return NEXT_BUILD_ID
    text = fetch_text(session, sample_product_url)
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', text, re.S)
    if match:
        payload = json.loads(match.group(1))
        NEXT_BUILD_ID = normalize_whitespace(payload.get("buildId"))
    if not NEXT_BUILD_ID:
        match = re.search(r"/_next/static/([^/]+)/_buildManifest\.js", text)
        if match:
            NEXT_BUILD_ID = normalize_whitespace(match.group(1))
    if not NEXT_BUILD_ID:
        raise StopScrape(f"stopped_unable_to_discover_next_build_id: {sample_product_url}")
    return NEXT_BUILD_ID


def next_data_url(product_url: str, build_id: str) -> str:
    parsed = urlparse(product_url)
    path = parsed.path.strip("/")
    return f"{SITE}/_next/data/{build_id}/{quote(path)}.json?slug={quote(path)}"


def find_product_payload(payload: Dict[str, object]) -> Optional[Dict[str, object]]:
    try:
        page_data = payload["pageProps"]["pageData"]["context"]["pageDataJson"]  # type: ignore[index]
    except (KeyError, TypeError):
        return None
    if isinstance(page_data, dict) and isinstance(page_data.get("product"), dict):
        return page_data["product"]  # type: ignore[return-value]
    return None


def text_from_value(value: object) -> str:
    if isinstance(value, str):
        return strip_tags(value)
    if isinstance(value, list):
        return normalize_whitespace(" ".join(text_from_value(item) for item in value))
    if isinstance(value, dict):
        text_parts = []
        for key in ("text", "value", "description", "title", "displayTitle", "body"):
            if key in value:
                text_parts.append(text_from_value(value.get(key)))
        return normalize_whitespace(" ".join(text_parts))
    return ""


def product_context_from_payload(product_url: str, product: Dict[str, object]) -> ProductContext:
    details = []
    for key in ("description", "details", "sizeAndFit", "careAndMaintenance"):
        details.append(text_from_value(product.get(key)))
    hierarchy = product.get("hierarchy")
    category = ""
    if isinstance(hierarchy, list):
        category = " > ".join(
            normalize_whitespace(item.get("displayName") or item.get("name") or item.get("pageHandle"))
            for item in hierarchy
            if isinstance(item, dict)
        )
    color = ""
    colors = product.get("productColors")
    if isinstance(colors, list) and colors:
        first = colors[0]
        if isinstance(first, dict):
            color = normalize_whitespace(first.get("name") or first.get("value") or first.get("colorName"))
    return ProductContext(
        url=product_url,
        title=normalize_whitespace(product.get("title")),
        description=text_from_value(product.get("description")),
        detail=normalize_whitespace(" ".join(details)),
        category=category,
        brand="Quince",
        color=color,
        product_id=str(product.get("id") or ""),
        handle=normalize_whitespace(product.get("slug")),
    )


def quince_in_scope(context: ProductContext) -> bool:
    value = f"{context.title} {context.category} {context.url}"
    if OUT_OF_SCOPE_PRODUCT_RE.search(value):
        return False
    return bool(classify_clothing_type(context))


def review_product_ids(product: Dict[str, object]) -> List[str]:
    ids = []
    primary = str(product.get("id") or "")
    if primary:
        ids.append(primary)
    child_spids = {str(value) for value in product.get("childSpids") or []}
    variants = product.get("variants") or []
    if isinstance(variants, list) and child_spids:
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            if str(variant.get("spid") or "") in child_spids and variant.get("productId"):
                ids.append(str(variant.get("productId")))
    seen = set()
    out = []
    for value in ids:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def parse_created_date(value: object) -> Tuple[str, str]:
    if value in (None, ""):
        return "", ""
    try:
        timestamp = float(str(value))
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"), dt.date().isoformat()
    except (OSError, ValueError, OverflowError):
        raw = normalize_whitespace(value)
        return raw, ""


def attribute_display(review: Dict[str, object], name: str) -> str:
    attrs = review.get("reviewAttributes") or []
    if not isinstance(attrs, list):
        return ""
    for attr in attrs:
        if not isinstance(attr, dict):
            continue
        if normalize_whitespace(attr.get("attributeName")).lower() == name.lower():
            return normalize_whitespace(attr.get("displayName") or attr.get("value"))
    return ""


def review_attribute_suffix(review: Dict[str, object]) -> str:
    attrs = review.get("reviewAttributes") or []
    if not isinstance(attrs, list):
        return ""
    parts = []
    for attr in attrs:
        if not isinstance(attr, dict):
            continue
        name = normalize_whitespace(attr.get("attributeName"))
        value = normalize_whitespace(attr.get("displayName") or attr.get("value"))
        if name and value and name in {"Typical Size", "Size Purchased", "Fit", "Length"}:
            parts.append(f"{name}: {value}")
    return "; ".join(parts)


def review_images_from_payload(payload: Dict[str, object]) -> List[ReviewImage]:
    reviews = payload.get("content") or []
    if not isinstance(reviews, list):
        return []
    out: List[ReviewImage] = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        medias = review.get("reviewMedias") or []
        if not isinstance(medias, list):
            continue
        date_raw, review_date = parse_created_date(review.get("createdDate"))
        size_raw = attribute_display(review, "Size Purchased") or attribute_display(review, "Typical Size")
        suffix = review_attribute_suffix(review)
        body = normalize_whitespace(review.get("text"))
        if suffix:
            body = normalize_whitespace(f"{body} {suffix}")
        for index, media in enumerate(medias):
            if not isinstance(media, dict) or media.get("mediaType") != "IMAGE":
                continue
            image_url = normalize_whitespace(media.get("mediaUrl"))
            if not image_url:
                continue
            out.append(
                ReviewImage(
                    image_url=image_url,
                    review_id=f"quince-{review.get('id')}-{index}",
                    review_title=normalize_whitespace(review.get("title")),
                    review_body=body,
                    reviewer_name=normalize_whitespace(review.get("author")),
                    date_raw=date_raw,
                    review_date=review_date,
                    size_raw=size_raw,
                    rating=str(review.get("rating") or ""),
                )
            )
    return out


def fetch_review_images(session: requests.Session, product_ids: Sequence[str], referer: str) -> Tuple[List[ReviewImage], Dict[str, object]]:
    if not product_ids:
        return [], {"review_ids": [], "media_review_count_hint": 0, "review_pages_scanned": 0}
    rows: List[ReviewImage] = []
    pages = 0
    total = 0
    pagination_warning = ""
    for page in range(0, 1000):
        params = {
            "quinceProductIds": ",".join(product_ids),
            "containsMedia": "true",
            "sortBy": "createdDate",
            "sortDirection": "DESC",
            "pageSize": "1000",
            "pageNumber": str(page),
        }
        headers = {**JSON_HEADERS, "Referer": referer}
        response = session.get(REVIEW_API, headers=headers, params=params, timeout=45)
        if response.status_code >= 400 and response.status_code not in STOP_STATUS_CODES and page > 0:
            pagination_warning = f"stopped_at_page_{page}_status_{response.status_code}"
            break
        assert_public_response(response, response.url)
        response.raise_for_status()
        payload = response.json()
        pages += 1
        total = int(payload.get("totalElements") or total or 0)
        batch = review_images_from_payload(payload)
        rows.extend(batch)
        if not payload.get("hasNext"):
            break
    return rows, {
        "review_ids": list(product_ids),
        "media_review_count_hint": total,
        "review_pages_scanned": pages,
        "pagination_warning": pagination_warning,
    }


def fetch_product(session: requests.Session, url: str) -> Tuple[Optional[ProductContext], Optional[Dict[str, object]], str]:
    try:
        build_id = discover_next_build_id(session, url)
        response = session.get(next_data_url(url, build_id), timeout=45)
        assert_public_response(response, response.url)
        if response.status_code == 404:
            return None, None, "not-product"
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return None, None, f"product-fetch-error: {exc}"
    product = find_product_payload(payload)
    if not product:
        return None, None, "not-product"
    context = product_context_from_payload(url, product)
    if not quince_in_scope(context):
        return context, product, "out-of-scope"
    return context, product, "ok"


def scrape_one(url: str) -> Tuple[List[Dict[str, str]], Dict[str, object], Optional[str]]:
    session = make_session()
    context, product, status = fetch_product(session, url)
    summary: Dict[str, object] = {"url": url, "status": status, "rows": 0}
    if not context or not product or status != "ok":
        if context:
            summary["title"] = context.title
        return [], summary, None
    product_ids = review_product_ids(product)
    try:
        reviews, meta = fetch_review_images(session, product_ids, url)
    except Exception as exc:
        summary.update({"title": context.title, "review_ids": product_ids})
        return [], summary, f"{url}: review-fetch-error: {exc}"
    fetched_at = utc_now()
    rows = [build_intake_row(context, review, fetched_at) for review in reviews if review.image_url]
    summary.update(
        {
            "title": context.title,
            "clothing_type": classify_clothing_type(context),
            "review_ids": product_ids,
            "rows": len(rows),
            **meta,
        }
    )
    return rows, summary, None


def scrape(limit_urls: Optional[int], workers: int) -> Tuple[List[Dict[str, str]], List[Dict[str, object]], List[str]]:
    urls = discover_urls(limit_urls)
    print(f"candidate_urls={len(urls)}", flush=True)
    rows: List[Dict[str, str]] = []
    summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(scrape_one, url): url for url in urls}
        for index, future in enumerate(as_completed(futures), 1):
            url = futures[future]
            try:
                product_rows, summary, error = future.result()
            except Exception as exc:
                product_rows, summary, error = [], {"url": url, "status": "unexpected-error", "rows": 0}, f"{url}: {exc}"
            rows.extend(product_rows)
            summaries.append(summary)
            if error:
                errors.append(error)
            if product_rows or index % 100 == 0:
                print(
                    f"[{index}/{len(urls)}] status={summary.get('status')} rows={len(product_rows)} "
                    f"title={summary.get('title', '')}",
                    flush=True,
                )
    return dedupe_rows(rows), summaries, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Quince public product media reviews into Step 1 intake schema.")
    parser.add_argument("--limit-urls", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    started_at = utc_now()
    output_csv, summary_json = output_paths(RETAILER)
    rows, product_summaries, errors = scrape(args.limit_urls, args.workers)
    finished_at = utc_now()
    write_intake_csv(rows, output_csv)
    write_summary(
        summary_json,
        site=SITE,
        retailer=RETAILER,
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=finished_at,
        products_scanned=len(product_summaries),
        adapter="quince-review-system-product-media",
        product_summaries=product_summaries,
        errors=errors,
    )
    print(f"wrote {len(rows)} rows -> {output_csv}", flush=True)
    print(f"summary -> {summary_json}", flush=True)


if __name__ == "__main__":
    main()
