#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import html
import json
import re
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

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


SITE = "https://www.rotita.com"
RETAILER = "rotita.com"
SITEMAP_URL = f"{SITE}/sitemap/sitemap-products-1.xml.gz"
ADAPTER = "rotita_product_page_dynamic_reviews"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
OUT_OF_SCOPE_RE = re.compile(
    r"\b(necklace|earrings?|bracelet|ring|jewelry|pendant|chain|watch|bag|purse|wallet|shoes?|sandals?)\b",
    re.I,
)
PRODUCT_ID_RE = re.compile(r"-g(\d+)\.html", re.I)
INCH_FROM_METRIC_RE = re.compile(r"/\s*(\d+(?:\.\d+)?)\s*(?:in|inch|inches)\b", re.I)
LBS_FROM_METRIC_RE = re.compile(r"/\s*(\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)\b", re.I)


def fetch(url: str, *, referer: str = SITE, timeout: int = 45) -> requests.Response:
    response = requests.get(url, headers={**HEADERS, "Referer": referer}, timeout=timeout)
    response.raise_for_status()
    return response


def discover_urls(limit: Optional[int] = None) -> List[str]:
    response = fetch(SITEMAP_URL)
    text = gzip.decompress(response.content).decode("utf-8", errors="replace")
    urls: List[str] = []
    seen = set()
    for match in re.findall(r"<loc>(.*?)</loc>", text, re.I | re.S):
        url = html.unescape(normalize_whitespace(match))
        if "/rotita-" not in url or not PRODUCT_ID_RE.search(url):
            continue
        if OUT_OF_SCOPE_RE.search(url.replace("-", " ")):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if limit and len(urls) >= limit:
            break
    return urls


def post_dynamic(data: Dict[str, str], *, referer: str) -> Dict[str, object]:
    response = requests.post(
        f"{SITE}/dynamic.php",
        params={"act": "batch_insert"} if data.get("inserts") else None,
        data=data,
        headers={
            **HEADERS,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": SITE,
            "Referer": referer,
        },
        timeout=45,
    )
    response.raise_for_status()
    return response.json()


def batch_review_payload(goods_id: str, product_url: str) -> Dict[str, object]:
    inserts = [
        {"func": "new_comments", "paras": {"goods_id": goods_id, "type": 1}, "is_html": 0},
    ]
    return post_dynamic(
        {
            "inserts": json.dumps(inserts, separators=(",", ":")),
            "Pagegroup2": "Product_Details",
            "Pagegroup1": "Product_Details",
        },
        referer=product_url,
    )


def comments_page_payload(goods_id: str, page: int, product_url: str) -> Dict[str, object]:
    return post_dynamic(
        {
            "inserts": "comments",
            "paras": goods_id,
            "type": "1",
            "page": str(page),
            "sort_type": "4",
            "is_jump": "1",
        },
        referer=product_url,
    )


def photo_comment_payload(goods_id: str, comment_id: str, field: str, product_url: str) -> Dict[str, object]:
    return post_dynamic(
        {
            "inserts": "photo_comments",
            "paras": goods_id,
            "comment_id": comment_id,
            "row_sn": field,
            "show_comment": "1",
        },
        referer=product_url,
    )


def extract_product_context(product_url: str, html_text: str) -> ProductContext:
    title = normalize_whitespace(re.search(r'var goods_name\s*=\s*"([^"]+)"', html_text).group(1)) if re.search(r'var goods_name\s*=\s*"([^"]+)"', html_text) else ""
    title = title or normalize_whitespace(re.search(r"<title>(.*?)</title>", html_text, re.I | re.S).group(1)) if re.search(r"<title>(.*?)</title>", html_text, re.I | re.S) else title
    description = ""
    desc_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html_text, re.I)
    if desc_match:
        description = html.unescape(desc_match.group(1))
    goods_id = ""
    match = re.search(r'var goods_id\s*=\s*["\']?(\d+)', html_text)
    if match:
        goods_id = match.group(1)
    else:
        url_match = PRODUCT_ID_RE.search(product_url)
        goods_id = url_match.group(1) if url_match else ""
    return ProductContext(
        url=product_url,
        title=title,
        description=normalize_whitespace(description),
        category="",
        brand="Rotita",
        product_id=goods_id,
        shop_domain="www.rotita.com",
        provider_hints=ADAPTER,
        raw_html=html_text,
    )


def inch_value(value: object) -> str:
    match = INCH_FROM_METRIC_RE.search(normalize_whitespace(value))
    return match.group(1) if match else ""


def lbs_value(value: object) -> str:
    match = LBS_FROM_METRIC_RE.search(normalize_whitespace(value))
    return match.group(1) if match else ""


def height_feet_inches(value: object) -> str:
    inches_text = inch_value(value)
    if not inches_text:
        return ""
    inches = round(float(inches_text))
    return f"{inches // 12}'{inches % 12}\""


def measurement_sentence(item: Dict[str, object]) -> str:
    parts = []
    height = height_feet_inches(item.get("height"))
    weight_lbs = lbs_value(item.get("weight"))
    waist = inch_value(item.get("waist"))
    hips = inch_value(item.get("hips"))
    bust = inch_value(item.get("bust_size"))
    if height:
        parts.append(f"Height: {height}.")
    if weight_lbs:
        parts.append(f"Weight: {weight_lbs} lbs.")
    if waist:
        parts.append(f"Waist: {waist} in.")
    if hips:
        parts.append(f"Hips: {hips} in.")
    if bust:
        parts.append(f"Bust: {bust} in.")
    age = normalize_whitespace(item.get("user_age"))
    if age and age != "None":
        parts.append(f"Age: {age}.")
    return " ".join(parts)


def size_from_attr(value: object) -> str:
    text = strip_tags(value)
    match = re.search(r"\bSize:\s*([A-Z0-9]+)\b", text, re.I)
    if match:
        return match.group(1).upper()
    return normalize_whitespace(value)


def image_urls_from_piclist(value: object) -> List[str]:
    urls: List[str] = []
    if isinstance(value, dict):
        for raw in value.values():
            text = normalize_whitespace(raw)
            if text.startswith("http"):
                urls.append(text.replace("\\/", "/"))
    elif isinstance(value, list):
        for item in value:
            urls.extend(image_urls_from_piclist(item))
    return list(dict.fromkeys(urls))


def review_from_structured(item: Dict[str, object], image_url: str, context: ProductContext) -> ReviewImage:
    product_url = urljoin(SITE + "/", normalize_whitespace(item.get("url")))
    body = normalize_whitespace(" ".join([strip_tags(item.get("content")), measurement_sentence(item)]))
    return ReviewImage(
        image_url=image_url,
        review_id=f"rotita-{normalize_whitespace(item.get('id'))}",
        review_title=normalize_whitespace(item.get("title")),
        review_body=body,
        reviewer_name=normalize_whitespace(item.get("username")),
        date_raw=normalize_whitespace(item.get("add_time")),
        size_raw=size_from_attr(item.get("goods_attr")),
        rating=normalize_whitespace(item.get("rank") or item.get("comment_rank")),
        extra={
            "product_url": product_url or context.url,
            "product_title": normalize_whitespace(item.get("goods_name")) or context.title,
            "product_description": context.description,
            "product_category": context.category,
        },
    )


def structured_comments(data: Dict[str, object]) -> Dict[str, Dict[str, object]]:
    try:
        comments = data["insert_new_comments"]["data"]["cmt"]["comments"]  # type: ignore[index]
    except (KeyError, TypeError):
        return {}
    return {key: value for key, value in comments.items() if isinstance(value, dict)} if isinstance(comments, dict) else {}


def comment_images(data: Dict[str, object]) -> List[Dict[str, str]]:
    try:
        images = data["insert_new_comments"]["data"]["cmt"]["comment_images"]  # type: ignore[index]
    except (KeyError, TypeError):
        return []
    out = []
    if isinstance(images, list):
        for image in images:
            if isinstance(image, dict):
                url = normalize_whitespace(image.get("img_src")).replace("\\/", "/")
                if url:
                    out.append(
                        {
                            "goods_id": normalize_whitespace(image.get("goods_id")),
                            "comment_id": normalize_whitespace(image.get("comment_id")),
                            "field": normalize_whitespace(image.get("field")) or "pic_path",
                            "image_url": url,
                        }
                    )
    return out


def page_count(data: Dict[str, object]) -> int:
    try:
        cmt = data["insert_new_comments"]["data"]["cmt"]  # type: ignore[index]
        return int(cmt.get("page_count") or 1) if isinstance(cmt, dict) else 1
    except (KeyError, TypeError, ValueError):
        return 1


def parse_photo_comment(detail: Dict[str, object], image_url: str, comment_id: str, context: ProductContext) -> ReviewImage:
    try:
        content = detail["insert_photo_comments"]["content"]  # type: ignore[index]
    except (KeyError, TypeError):
        content = ""
    soup = BeautifulSoup(str(content), "html.parser")
    text_parts = []
    for node in soup.select(".c-photos_rank"):
        text_parts.append(strip_tags(str(node)))
    for div in soup.find_all("div"):
        text = strip_tags(str(div))
        if len(text) > 25 and "Image/Video in this review" not in text:
            text_parts.append(text)
            break
    date_raw = ""
    rank_text = strip_tags(str(soup.select_one(".c-photos_rank") or ""))
    date_match = re.search(r"([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})", rank_text)
    if date_match:
        date_raw = date_match.group(1)
    return ReviewImage(
        image_url=image_url,
        review_id=f"rotita-{comment_id}",
        review_body=normalize_whitespace(" ".join(text_parts)),
        reviewer_name=strip_tags(str(soup.select_one(".user-name") or "")),
        date_raw=date_raw,
        size_raw="",
        extra={"product_url": context.url, "product_title": context.title, "product_description": context.description},
    )


def scrape_product(product_url: str) -> Tuple[List[Dict[str, str]], Dict[str, object], Optional[str]]:
    try:
        html_text = fetch(product_url).text
        context = extract_product_context(product_url, html_text)
        if not context.product_id or OUT_OF_SCOPE_RE.search(context.title):
            return [], {"url": product_url, "status": "out-of-scope", "rows": 0}, None
        if not classify_clothing_type(context):
            return [], {"url": product_url, "status": "out-of-scope", "title": context.title, "rows": 0}, None

        data = batch_review_payload(context.product_id, product_url)
        images = comment_images(data)
        if not images:
            return [], {"url": product_url, "status": "ok", "title": context.title, "review_images": 0, "rows": 0}, None

        comments = structured_comments(data)
        wanted_ids = {image["comment_id"] for image in images if image["comment_id"]}
        max_pages = min(page_count(data), 80)
        for page in range(2, max_pages + 1):
            if wanted_ids.issubset(comments.keys()):
                break
            page_data = comments_page_payload(context.product_id, page, product_url)
            insert_comments = page_data.get("insert_comments") if isinstance(page_data, dict) else None
            content = insert_comments.get("content", "") if isinstance(insert_comments, dict) else ""
            for comment_id in wanted_ids - set(comments):
                if comment_id and comment_id in str(content):
                    # The structured batch is richer than the page HTML; use the photo fallback for the few not on page 1.
                    comments[comment_id] = {}
            time.sleep(0.03)

        reviews: List[ReviewImage] = []
        for image in images:
            comment_id = image["comment_id"]
            image_url = image["image_url"]
            item = comments.get(comment_id)
            if item:
                image_item = dict(item)
                if not image_urls_from_piclist(image_item.get("piclist")):
                    image_item["piclist"] = {"pic_path": image_url}
                reviews.append(review_from_structured(image_item, image_url, context))
            else:
                detail = photo_comment_payload(image["goods_id"] or context.product_id, comment_id, image["field"], product_url)
                reviews.append(parse_photo_comment(detail, image_url, comment_id, context))
                time.sleep(0.03)

        fetched_at = utc_now()
        rows = [build_intake_row(context, review, fetched_at) for review in reviews]
        return rows, {
            "url": product_url,
            "status": "ok",
            "title": context.title,
            "product_id": context.product_id,
            "review_images": len(images),
            "rows": len(rows),
        }, None
    except Exception as exc:
        return [], {"url": product_url, "status": "error", "rows": 0}, f"{product_url}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape Rotita product-page dynamic review images.")
    parser.add_argument("--limit-products", type=int, default=None)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    started_at = utc_now()
    output_csv, summary_json = output_paths(RETAILER)
    urls = discover_urls(args.limit_products)
    print(f"[{RETAILER}] discovered {len(urls)} candidate product URLs", flush=True)

    rows: List[Dict[str, str]] = []
    summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(scrape_product, url): url for url in urls}
        for index, future in enumerate(as_completed(futures), start=1):
            product_rows, summary, error = future.result()
            rows.extend(product_rows)
            summaries.append(summary)
            if error:
                errors.append(error)
            if index % 50 == 0 or index == len(urls):
                print(f"[{RETAILER}] scanned {index}/{len(urls)} products; rows={len(rows)} errors={len(errors)}", flush=True)

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
        products_scanned=len(urls),
        adapter=ADAPTER,
        product_summaries=summaries,
        errors=errors,
    )
    print(f"[{RETAILER}] wrote {len(rows)} rows to {output_csv}", flush=True)
    print(f"[{RETAILER}] summary {summary_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
