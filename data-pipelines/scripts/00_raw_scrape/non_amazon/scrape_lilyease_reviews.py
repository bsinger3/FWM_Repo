#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import re
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

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


SITE = "https://www.lilyease.com"
RETAILER = "lilyease.com"
PRODUCT_SITEMAP = f"{SITE}/sitemap/sitemap_product_en_1.xml"
ADAPTER = "lilyease_magento_inline_product_reviews"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
OUT_OF_SCOPE_RE = re.compile(
    r"\b(gift\s*card|shipping|returns?|insurance|cover\s*up|hat|bag|tote|scarf|sunglasses|jewelry)\b",
    re.I,
)
BRA_SIZE_RE = re.compile(
    r"\b(28|30|32|34|36|38|40|42|44|46|48|50|52|54)\s*"
    r"(AAA|AA|A|B|C|D|DD|DDD|F|G|H|I|J|K)\b",
    re.I,
)
ORDERED_SIZE_TOKEN_RE = re.compile(
    r"\b("
    r"xxs|xs|s|m|l|xl|xxl|xxxl|"
    r"x-small|small|medium|large|x-large|xx-large|xxx-large|"
    r"1x|2x|3x|4x|5x|6x|1xl|2xl|3xl|4xl|5xl|6xl|"
    r"\d{1,2}(?:w|wp|p|t| regular| short| long| tall| petite)?"
    r")\b",
    re.I,
)
ORDERED_SIZE_CONTEXT_RE = re.compile(
    r"\b(?:ordered|bought|purchased|got|wearing|wear|wears|picked|chose|choose|sized\s+up\s+to|went\s+with)"
    r"\s+(?:the\s+)?(?:a|an)?\s*(?:size\s+)?"
    + ORDERED_SIZE_TOKEN_RE.pattern,
    re.I,
)
SIZE_PHRASE_RE = re.compile(r"\bsize\s+" + ORDERED_SIZE_TOKEN_RE.pattern, re.I)


def clean_url(value: str) -> str:
    return html.unescape(normalize_whitespace(value)).split("#", 1)[0]


def fetch_text(url: str, *, referer: str = SITE, timeout: int = 45, retries: int = 4) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            response = requests.get(url, headers={**HEADERS, "Referer": referer}, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            status = getattr(exc.response, "status_code", None)
            if status and status not in {408, 429, 500, 502, 503, 504}:
                raise
            time.sleep(min(2 ** attempt, 12))
    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def discover_product_urls(limit: Optional[int] = None) -> List[str]:
    text = fetch_text(PRODUCT_SITEMAP, referer=SITE)
    urls: List[str] = []
    seen = set()
    for match in re.findall(r"<loc>(.*?)</loc>", text, re.I | re.S):
        url = clean_url(match)
        parsed = urlparse(url)
        if parsed.netloc.lower() != "www.lilyease.com" or not parsed.path.endswith(".html"):
            continue
        if OUT_OF_SCOPE_RE.search(parsed.path.replace("-", " ")):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if limit and len(urls) >= limit:
            break
    return urls


def meta_content(soup: BeautifulSoup, *, property_name: str = "", name: str = "") -> str:
    attrs = {"property": property_name} if property_name else {"name": name}
    tag = soup.find("meta", attrs=attrs)
    return normalize_whitespace(tag.get("content")) if tag and tag.get("content") else ""


def product_context(product_url: str, soup: BeautifulSoup, html_text: str) -> ProductContext:
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = strip_tags(str(h1))
    title = title or meta_content(soup, property_name="og:title")
    description = meta_content(soup, name="description") or meta_content(soup, property_name="og:description")
    product_id = ""
    for pattern in (r'"productId":"(\d+)"', r"review/product/form/id/(\d+)/", r"productId['\"]?\s*[:=]\s*['\"]?(\d+)"):
        match = re.search(pattern, html_text, re.I)
        if match:
            product_id = match.group(1)
            break
    crumbs = []
    for crumb in soup.select(".breadcrumbs a, .breadcrumbs li, .breadcrumb a, .breadcrumb li"):
        clean = strip_tags(str(crumb))
        if clean and clean.lower() not in {"home", "lilyease"}:
            crumbs.append(clean)
    details = []
    for selector in (".short-description", ".std", ".product-shop", ".product-collateral"):
        node = soup.select_one(selector)
        if not node:
            continue
        clean = strip_tags(str(node))
        if clean:
            details.append(clean[:3000])
    color = ""
    color_match = re.search(r"\b(black|white|blue|green|red|pink|purple|brown|navy|floral|striped|leopard)\b", title, re.I)
    if color_match:
        color = color_match.group(1)
    return ProductContext(
        url=product_url,
        title=title,
        description=description,
        detail=normalize_whitespace(" | ".join(details)),
        category=" > ".join(dict.fromkeys(crumbs[:8])),
        brand="LilyEase",
        color=color,
        product_id=product_id,
        shop_domain="www.lilyease.com",
        provider_hints=ADAPTER,
        raw_html=html_text,
    )


def text_from_one(node) -> str:
    return strip_tags(str(node)) if node else ""


def rating_from_review(review_node) -> str:
    rating = review_node.select_one(".rating")
    if not rating:
        return ""
    style = normalize_whitespace(rating.get("style"))
    match = re.search(r"width\s*:\s*(\d+(?:\.\d+)?)%", style, re.I)
    if not match:
        return ""
    value = float(match.group(1)) / 20.0
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def reviewer_from_review(review_node) -> str:
    name_node = review_node.select_one(".name-cust")
    if not name_node:
        return ""
    for verified in name_node.select("span"):
        verified.decompose()
    return text_from_one(name_node)


def normalize_ordered_size(value: str) -> str:
    size = normalize_whitespace(value).lower()
    mapping = {
        "s": "small",
        "m": "medium",
        "l": "large",
        "xs": "x-small",
        "xl": "x-large",
        "xxl": "xx-large",
        "xxxl": "xxx-large",
        "1xl": "1x",
        "2xl": "2x",
        "3xl": "3x",
        "4xl": "4x",
        "5xl": "5x",
        "6xl": "6x",
    }
    return mapping.get(size, size)


def strict_ordered_size(text: str) -> str:
    clean = normalize_whitespace(text)
    for pattern in (ORDERED_SIZE_CONTEXT_RE, SIZE_PHRASE_RE):
        match = pattern.search(clean)
        if match:
            return normalize_ordered_size(match.group(match.lastindex or 1))
    bra = BRA_SIZE_RE.search(clean)
    if bra:
        return f"{bra.group(1)}{bra.group(2).upper()}"
    return ""


def review_images_from_product(context: ProductContext, soup: BeautifulSoup) -> List[ReviewImage]:
    reviews: List[ReviewImage] = []
    for item in soup.select(".review-list-cust"):
        popup = item.select_one("[id^='review-'].white-popup")
        if not popup:
            continue
        review_id_match = re.search(r"review-(\d+)", normalize_whitespace(popup.get("id")))
        review_id = review_id_match.group(1) if review_id_match else ""
        body = text_from_one(popup.select_one(".review-detail-content"))
        title = text_from_one(popup.select_one(".review-rating-title"))
        date_raw = text_from_one(item.select_one(".date-cust .date, small.date"))
        reviewer = reviewer_from_review(item)
        rating = rating_from_review(item)
        ordered_size = strict_ordered_size(f"{title} {body}")
        image_nodes = popup.select("img.gallery-thumbnail-image")
        if not image_nodes:
            image_nodes = item.select("img.gallery-thumbnail-image")
        seen_images = set()
        for image_index, image_node in enumerate(image_nodes, start=1):
            image_url = normalize_whitespace(image_node.get("data-zoom-image") or image_node.get("src"))
            if not image_url or "media/reviewimages-normal/" not in image_url:
                continue
            image_url = urljoin(SITE, image_url)
            if image_url in seen_images:
                continue
            seen_images.add(image_url)
            reviews.append(
                ReviewImage(
                    image_url=image_url,
                    review_id=f"lilyease-{review_id or context.product_id}-{image_index}",
                    review_title=title,
                    review_body=body,
                    reviewer_name=reviewer,
                    date_raw=date_raw,
                    size_raw=ordered_size,
                    rating=rating,
                )
            )
    return reviews


def scrape_product(product_url: str) -> Tuple[List[Dict[str, str]], Dict[str, object], Optional[str]]:
    try:
        html_text = fetch_text(product_url, referer=SITE)
        soup = BeautifulSoup(html_text, "html.parser")
        context = product_context(product_url, soup, html_text)
        if not context.title or OUT_OF_SCOPE_RE.search(" ".join([context.title, context.category])):
            return [], {"url": product_url, "status": "out-of-scope", "rows": 0}, None
        reviews = review_images_from_product(context, soup)
        fetched_at = utc_now()
        rows = []
        for review in reviews:
            row = build_intake_row(context, review, fetched_at)
            if not review.size_raw:
                row["size_display"] = ""
            rows.append(row)
        summary = {
            "url": product_url,
            "status": "ok",
            "product_id": context.product_id,
            "title": context.title,
            "clothing_type_id": classify_clothing_type(context),
            "review_images": len(reviews),
            "rows": len(rows),
        }
        return rows, summary, None
    except Exception as exc:
        return [], {"url": product_url, "status": "error", "rows": 0}, f"{product_url}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape LilyEase product-page inline customer review images.")
    parser.add_argument("--limit-products", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    started_at = utc_now()
    output_csv, summary_json = output_paths(RETAILER)
    product_urls = discover_product_urls(args.limit_products)
    print(f"[{RETAILER}] discovered {len(product_urls)} product URLs", flush=True)

    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(scrape_product, url): url for url in product_urls}
        for index, future in enumerate(as_completed(futures), start=1):
            product_rows, product_summary, error = future.result()
            rows.extend(product_rows)
            product_summaries.append(product_summary)
            if error:
                errors.append(error)
            if index % 25 == 0 or index == len(product_urls):
                print(
                    f"[{RETAILER}] scanned {index}/{len(product_urls)} products; rows={len(rows)} errors={len(errors)}",
                    flush=True,
                )

    rows = dedupe_rows(rows)
    write_intake_csv(rows, output_csv)
    write_summary(
        summary_json,
        site=SITE,
        retailer=RETAILER,
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=utc_now(),
        products_scanned=len(product_urls),
        adapter=ADAPTER,
        product_summaries=product_summaries,
        errors=errors,
    )
    print(f"[{RETAILER}] wrote {len(rows)} rows to {output_csv}", flush=True)
    print(f"[{RETAILER}] summary {summary_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
