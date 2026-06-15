#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import math
import re
import subprocess
import time
from datetime import datetime
from typing import Dict, Iterable, List, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    dedupe_rows,
    normalize_whitespace,
    output_paths,
    strip_tags,
    utc_now,
    validate_rows,
    write_intake_csv,
)


SITE_ROOT = "https://www.lascana.com"
DOMAIN = "lascana.com"
RETAILER = "lascana_com"
SEED_CATEGORY = f"{SITE_ROOT}/Dresses"
YOTPO_APP_KEY = "z5nqCCZx5sob1D0y0wgZH55CqrZ8Pb41zH9Hx5mS"
YOTPO_WIDGET_INSTANCE_ID = "981742"
YOTPO_PER_PAGE = 100
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 FWM"
PRESSURE_STATUS_CODES = {401, 403, 407, 408, 409, 423, 429, 430, 503}
BLOCK_MARKERS = [
    "captcha",
    "verify you are human",
    "access denied",
    "too many requests",
    "attention required",
    "datadome",
    "cf-chl",
    "challenges.cloudflare.com",
]
APPAREL_RE = re.compile(r"\b(dress|swim|bikini|bra|top|shirt|pants?|leggings?|skirt|tunic|jumpsuit|romper)\b", re.I)
ACCESSORY_RE = re.compile(r"\b(sandal|shoe|bag|hat|jewelry|necklace|earrings?)\b", re.I)


class PressureStop(RuntimeError):
    pass


def request_text(url: str, *, accept: str = "text/html,application/json,*/*", referer: str = SITE_ROOT) -> str:
    if "lascana.com" in urlparse(url).netloc:
        cmd = [
            "curl.exe",
            "-L",
            "-sS",
            "--max-time",
            "45",
            "-w",
            "\n__HTTP_STATUS__:%{http_code}",
            "-A",
            USER_AGENT,
            "-H",
            f"Accept: {accept}",
            "-H",
            "Accept-Language: en-US,en;q=0.9",
            "-e",
            referer,
            url,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        text = result.stdout.decode("utf-8", errors="replace")
        marker = "\n__HTTP_STATUS__:"
        status = 0
        if marker in text:
            text, status_raw = text.rsplit(marker, 1)
            try:
                status = int(status_raw.strip()[:3])
            except ValueError:
                status = 0
        if status in PRESSURE_STATUS_CODES:
            raise PressureStop(f"pressure status {status} for {url}")
        if status >= 400:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"fetch_failed status={status} url={url} detail={normalize_whitespace(stderr)}")
        lower = text[:20000].lower()
        if any(marker_text in lower for marker_text in BLOCK_MARKERS):
            raise PressureStop(f"block marker in response for {url}")
        return text

    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        },
    )
    try:
        with urlopen(req, timeout=45) as response:
            status = getattr(response, "status", 200)
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.code in PRESSURE_STATUS_CODES:
            raise PressureStop(f"pressure status {exc.code} for {url}") from exc
        raise
    except URLError as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc
    if status in PRESSURE_STATUS_CODES:
        raise PressureStop(f"pressure status {status} for {url}")
    lower = body[:20000].lower()
    if any(marker in lower for marker in BLOCK_MARKERS):
        raise PressureStop(f"block marker in response for {url}")
    return body


def request_json(url: str, *, referer: str = SITE_ROOT) -> Dict[str, object]:
    return json.loads(request_text(url, accept="application/json,text/plain,*/*", referer=referer))


def discover_category_products(html_text: str, limit: int) -> List[Dict[str, str]]:
    products: List[Dict[str, str]] = []
    seen = set()
    for match in re.finditer(
        r'data-producturl="(?P<href>[^"]+ThumbProductID=[^"]+)"[^>]*data-thumb-productid="(?P<thumb>[^"]*)"[^>]*data-thumb-colorid="(?P<color>[^"]*)"[^>]*data-productimage="(?P<image>[^"]*)"',
        html_text,
        flags=re.I,
    ):
        href = html.unescape(match.group("href"))
        url = urljoin(SITE_ROOT, href)
        key = urlparse(url).path
        if key in seen:
            continue
        if not APPAREL_RE.search(url) or ACCESSORY_RE.search(url):
            continue
        seen.add(key)
        title = normalize_whitespace(urlparse(url).path.rsplit("/", 1)[-1].split(",", 1)[0].replace("-", " "))
        products.append(
            {
                "url": url,
                "title": title,
                "sku_hint": "",
                "catalog_image": html.unescape(match.group("image")),
                "catalog_image_alt": title,
                "rating_hint": "",
            }
        )
        if limit and len(products) >= limit:
            return products
    pattern = re.compile(
        r'<a[^>]+class="product-listing"[^>]+href="(?P<href>[^"]+)"(?P<body>.*?)</a>',
        re.I | re.S,
    )
    for match in pattern.finditer(html_text):
        href = html.unescape(match.group("href"))
        body = match.group("body")
        swatch_match = re.search(r'data-producturl="([^"]+ThumbProductID=[^"]+)"', body, re.I)
        if swatch_match:
            href = html.unescape(swatch_match.group(1))
        title_match = re.search(r'class="product-name">([^<]+)<', body, re.I)
        image_match = re.search(r'<img[^>]+src="(?P<src>https://photo\.lascana\.com/[^"]+)"[^>]+alt="(?P<alt>[^"]*)"', body, re.I)
        sku_match = re.search(r"item_id&quot;:&quot;([^&]+)&quot;", body)
        rating_match = re.search(r'aria-label="([0-9.]+) star rating out of 5 stars"', body, re.I)
        url = urljoin(SITE_ROOT, href)
        key = urlparse(url).path
        if key in seen:
            continue
        title = normalize_whitespace(html.unescape(title_match.group(1))) if title_match else ""
        if not APPAREL_RE.search(f"{title} {url}") or ACCESSORY_RE.search(f"{title} {url}"):
            continue
        seen.add(key)
        products.append(
            {
                "url": url,
                "title": title,
                "sku_hint": normalize_whitespace(sku_match.group(1)) if sku_match else "",
                "catalog_image": image_match.group("src") if image_match else "",
                "catalog_image_alt": html.unescape(image_match.group("alt")) if image_match else "",
                "rating_hint": rating_match.group(1) if rating_match else "",
            }
        )
        if limit and len(products) >= limit:
            break
    return products


def extract_json_object_after(html_text: str, marker: str) -> Dict[str, object]:
    start = html_text.find(marker)
    if start == -1:
        return {}
    start = html_text.find("{", start)
    if start == -1:
        return {}
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(html_text)):
        char = html_text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html_text[start : index + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def selected_product(page_data: Dict[str, object]) -> Dict[str, object]:
    products = page_data.get("ProductList") if isinstance(page_data, dict) else []
    if not isinstance(products, list) or not products:
        return {}
    thumb_id = page_data.get("ThumbProductID")
    for product in products:
        if isinstance(product, dict) and product.get("ID") == thumb_id:
            return product
    return products[0] if isinstance(products[0], dict) else {}


def yotpo_option_id(product: Dict[str, object], selected_color: str) -> str:
    options = product.get("ProductOptions") or product.get("AlternateColorsAndSizes") or []
    candidates = [opt for opt in options if isinstance(opt, dict) and normalize_whitespace(opt.get("ColorID")) == selected_color]
    if not candidates:
        candidates = [opt for opt in options if isinstance(opt, dict)]
    for option in candidates:
        sku = normalize_whitespace(option.get("OptionSku"))
        if sku:
            return sku
    sku = normalize_whitespace(product.get("ProductSKU") or product.get("StyleNumber"))
    return sku


def size_summary(product: Dict[str, object], selected_color: str) -> str:
    values = []
    for option in product.get("ProductOptions") or product.get("AlternateColorsAndSizes") or []:
        if not isinstance(option, dict):
            continue
        if selected_color and normalize_whitespace(option.get("ColorID")) != selected_color:
            continue
        size = normalize_whitespace(option.get("SizeName") or option.get("SizeID") or option.get("AnalyticsProductSize"))
        if size and size not in values:
            values.append(size)
    return ", ".join(values)


def product_images(product: Dict[str, object], selected_color: str) -> List[str]:
    sku = normalize_whitespace(product.get("ProductSKU") or product.get("StyleNumber"))
    ids = [selected_color]
    for option in product.get("ProductOptions") or product.get("AlternateColorsAndSizes") or []:
        color = normalize_whitespace(option.get("ColorID")) if isinstance(option, dict) else ""
        if color and color not in ids:
            ids.append(color)
    images = []
    for color in ids:
        if not sku or not color:
            continue
        images.extend(
            [
                f"https://photo.lascana.com/im/{sku}_{color}.jpg?preset=product",
                f"https://photo.lascana.com/im/{sku}.{color}.1.jpg?preset=product",
                f"https://photo.lascana.com/im/{sku}.{color}.1.A.jpg?preset=product",
            ]
        )
    return list(dict.fromkeys(images))


def context_for_product(product_url: str, page_data: Dict[str, object], product: Dict[str, object]) -> ProductContext:
    selected_color = normalize_whitespace(page_data.get("ThumbProductColorID") or page_data.get("ProductColorID"))
    color_name = ""
    for option in product.get("ProductOptions") or product.get("AlternateColorsAndSizes") or []:
        if isinstance(option, dict) and normalize_whitespace(option.get("ColorID")) == selected_color:
            color_name = normalize_whitespace(option.get("ColorName") or option.get("AnalyticsProductColor"))
            break
    sizes = size_summary(product, selected_color)
    descriptions = product.get("Descriptions") if isinstance(product.get("Descriptions"), list) else []
    detail_bits = [strip_tags(value) for value in descriptions]
    if sizes:
        detail_bits.append(f"Available sizes for {selected_color}: {sizes}")
    return ProductContext(
        url=product_url,
        title=normalize_whitespace(product.get("NameProperCase") or product.get("Name")),
        description=strip_tags(product.get("MainDescription")),
        detail=normalize_whitespace(" | ".join(bit for bit in detail_bits if bit)),
        category=normalize_whitespace(page_data.get("DepartmentName") or product.get("AnalyticsProductCategory") or "Dresses"),
        brand="LASCANA",
        color=color_name or selected_color,
        variant=f"{selected_color}; sizes: {sizes}" if sizes else selected_color,
        product_id=yotpo_option_id(product, selected_color),
        handle=normalize_whitespace(product.get("ProductSKU") or product.get("StyleNumber")),
        shop_domain=DOMAIN,
        provider_hints=f"Yotpo widget app key {YOTPO_APP_KEY}; widget instance {YOTPO_WIDGET_INSTANCE_ID}",
    )


def yotpo_reviews_url(product_id: str, page: int) -> str:
    params = urlencode({"per_page": YOTPO_PER_PAGE, "page": page})
    return f"https://api-cdn.yotpo.com/v1/widget/{YOTPO_APP_KEY}/products/{quote(product_id, safe='')}/reviews.json?{params}"


def yotpo_response(payload: Dict[str, object]) -> Dict[str, object]:
    response = payload.get("response")
    return response if isinstance(response, dict) else {}


def fetch_yotpo_reviews(product_id: str, product_url: str, limit_pages: int, delay: float) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    reviews: List[Dict[str, object]] = []
    pages_scanned = 0
    total = 0
    for page in range(1, (limit_pages or 10) + 1):
        payload = request_json(yotpo_reviews_url(product_id, page), referer=product_url)
        response = yotpo_response(payload)
        pagination = response.get("pagination") if isinstance(response.get("pagination"), dict) else {}
        total = int(pagination.get("total") or total or 0)
        batch = response.get("reviews") if isinstance(response.get("reviews"), list) else []
        pages_scanned += 1
        reviews.extend(review for review in batch if isinstance(review, dict))
        per_page = int(pagination.get("per_page") or YOTPO_PER_PAGE)
        if not total or page >= math.ceil(total / max(per_page, 1)) or not batch:
            break
        if delay:
            time.sleep(delay)
    return reviews, {"yotpo_product_id": product_id, "review_pages_scanned": pages_scanned, "review_total": total}


def custom_field_value(review: Dict[str, object], title: str) -> str:
    fields = review.get("custom_fields")
    if not isinstance(fields, dict):
        return ""
    for field in fields.values():
        if isinstance(field, dict) and normalize_whitespace(field.get("title")).lower() == title.lower():
            return normalize_whitespace(field.get("value"))
    return ""


def parse_yotpo_date(value: object) -> str:
    raw = normalize_whitespace(value)
    for pattern in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, pattern).date().isoformat()
        except ValueError:
            continue
    return ""


def review_images_from_product(context: ProductContext, reviews: Iterable[Dict[str, object]], fallback_images: List[str], fetched_at: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    fallback = fallback_images[0] if fallback_images else ""
    for review in reviews:
        images = review.get("images_data") if isinstance(review.get("images_data"), list) else []
        for index, image in enumerate(images, start=1):
            if not isinstance(image, dict):
                continue
            image_url = normalize_whitespace(image.get("original_url") or image.get("thumb_url"))
            if not image_url:
                continue
            body_bits = [
                normalize_whitespace(review.get("content")),
                f"Sizing: {custom_field_value(review, 'Sizing')}" if custom_field_value(review, "Sizing") else "",
                f"Body Type: {custom_field_value(review, 'Body Type')}" if custom_field_value(review, "Body Type") else "",
            ]
            user = review.get("user") if isinstance(review.get("user"), dict) else {}
            review_image = ReviewImage(
                image_url=image_url,
                review_id=f"lascana-yotpo-{review.get('id')}-{image.get('id') or index}",
                review_title=normalize_whitespace(review.get("title")),
                review_body=normalize_whitespace(" ".join(bit for bit in body_bits if bit)),
                reviewer_name=normalize_whitespace(user.get("display_name")),
                date_raw=normalize_whitespace(review.get("created_at")),
                review_date=parse_yotpo_date(review.get("created_at")),
                size_raw=custom_field_value(review, "Sizing"),
                rating=normalize_whitespace(review.get("score")),
                extra={
                    "product_url": context.url,
                    "product_title": context.title,
                    "product_description": context.description,
                    "product_detail": context.detail,
                    "product_category": context.category,
                    "product_variant": context.variant,
                    "image_source_type": "customer_review_image",
                    "image_source_detail": "yotpo_images_data",
                },
            )
            rows.append(build_intake_row(context, review_image, fetched_at))
    if not rows and fallback:
        return []
    return rows


def dedupe_lascana_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        stable_key = (row.get("id") or "", row.get("original_url_display") or "")
        if stable_key in seen:
            continue
        seen.add(stable_key)
        deduped.append(row)
    return deduped


def process_product(product_ref: Dict[str, str], limit_review_pages: int, delay: float, fetched_at: str) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    product_url = product_ref["url"]
    html_text = request_text(product_url, referer=SEED_CATEGORY)
    page_data = extract_json_object_after(html_text, "var PageLevelData")
    product = selected_product(page_data)
    if not page_data or not product:
        return [], {"url": product_url, "rows": 0, "error": "missing_PageLevelData_product"}
    context = context_for_product(product_url, page_data, product)
    yotpo_id = context.product_id
    reviews, review_meta = fetch_yotpo_reviews(yotpo_id, product_url, limit_review_pages, delay)
    rows = review_images_from_product(context, reviews, product_images(product, normalize_whitespace(page_data.get("ThumbProductColorID"))), fetched_at)
    summary = {
        "url": product_url,
        "title": context.title,
        "sku": context.handle,
        "yotpo_product_id": yotpo_id,
        "review_total": review_meta.get("review_total", 0),
        "review_pages_scanned": review_meta.get("review_pages_scanned", 0),
        "reviews_with_images": sum(1 for review in reviews if review.get("images_data")),
        "rows": len(rows),
        "image_source_type": "customer_review_image" if rows else "none",
    }
    return rows, summary


def run(max_products: int, limit_review_pages: int, delay: float) -> Dict[str, object]:
    started_at = utc_now()
    fetched_at = started_at
    output_csv, summary_json = output_paths(RETAILER)
    category_html = request_text(SEED_CATEGORY, referer=SITE_ROOT)
    products = discover_category_products(category_html, max_products)
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    for product_ref in products:
        try:
            product_rows, summary = process_product(product_ref, limit_review_pages, delay, fetched_at)
            rows.extend(product_rows)
            product_summaries.append(summary)
            if delay:
                time.sleep(delay)
        except PressureStop:
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{product_ref.get('url')}: {exc}")
            product_summaries.append({"url": product_ref.get("url"), "rows": 0, "error": str(exc)})
    rows = dedupe_lascana_rows(dedupe_rows(rows))
    write_intake_csv(rows, output_csv)
    finished_at = utc_now()
    summary = {
        "site": SITE_ROOT,
        "retailer": RETAILER,
        "adapter": "lascana_category_pdp_yotpo_customer_images",
        "provider_identified": "Yotpo product widget",
        "yotpo_app_key": YOTPO_APP_KEY,
        "yotpo_widget_instance_id": YOTPO_WIDGET_INSTANCE_ID,
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": finished_at,
        "category_url": SEED_CATEGORY,
        "products_discovered": len(products),
        "products_scanned": len(product_summaries),
        "review_pages_scanned": sum(int(item.get("review_pages_scanned") or 0) for item in product_summaries),
        "exhaustive_review_paging": False,
        "product_summaries": product_summaries,
        "errors": errors,
        "access_policy": "public LASCANA category/PDP pages and public Yotpo widget API only; stop on 429/captcha/WAF/auth behavior.",
        "domain_confirmation": "Sovrn merchant domain is lascana.at; scrape target confirmed from triage evidence as www.lascana.com US storefront.",
        "sovrn_triage_source": {
            "source_file": "data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv",
            "target": "lascana_com",
            "merchant_domain": "lascana.at",
            "status": "first-pass candidate",
            "pricing_model": "CPC",
            "cpc_amount": "not_populated",
            "reviews_present": "yes",
            "photo_reviews": "yes",
            "shipping_countries": "DE|US",
            "provider": "Yotpo",
        },
    }
    summary.update(validate_rows(rows))
    summary["rows_with_customer_image"] = summary.get("rows_with_customer_review_image", 0)
    summary["rows_with_catalog_model_image"] = sum(1 for row in rows if row.get("image_source_type") == "catalog_model_image")
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Scrape LASCANA public Yotpo review images.")
    parser.add_argument("--max-products", type=int, default=30)
    parser.add_argument("--limit-review-pages", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.25)
    args = parser.parse_args(argv)
    payload = run(args.max_products, args.limit_review_pages, args.delay)
    print(f"Rows: {payload.get('rows_written', 0)}")
    print(f"Customer image rows: {payload.get('rows_with_customer_review_image', 0)}")
    print(f"Products scanned: {payload.get('products_scanned', 0)}")
    print(f"Output: {payload.get('output_csv')}")


if __name__ == "__main__":
    main()
