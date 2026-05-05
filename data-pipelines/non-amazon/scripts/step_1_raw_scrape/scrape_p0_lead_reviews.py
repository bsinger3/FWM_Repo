#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from step1_intake_utils import (
    ProductContext,
    ReviewImage,
    build_intake_row,
    classify_clothing_type,
    dedupe_rows,
    discover_shopify_product_urls,
    extract_product_context,
    fetch_json,
    fetch_text,
    hydrate_shopify_context,
    normalize_whitespace,
    output_paths,
    post_json,
    retailer_slug,
    strip_tags,
    utc_now,
    write_intake_csv,
    write_summary,
)

"""
Public review-image scraper for non-Amazon Step 1 intake rows.

Access policy: use only public product pages and public review/provider feeds;
skip pages that are restricted or unavailable; only collect public review data.
"""


DEFAULT_TRIAGE_CSV = (
    Path("/Users/briannasinger/Projects/FWM_Data")
    / "WebLeads"
    / "_lead_runs"
    / "20260424T203030Z"
    / "lead_review_fast_probe_report.csv"
)

SAFE_FIRST_DOMAINS = [
    "shecurve.com",
    "mbmswim.com",
    "livesozy.com",
    "forlest.com",
    "evelynbobbie.com",
    "leonisa.com",
    "under510.com",
    "jackielondon.com",
    "popilush.com",
    "truekind.com",
    "studiosuits.com",
]

OUT_OF_SCOPE_DOMAINS = {
    "studiosuits.com",
    "under510.com",
    "www.studiosuits.com",
    "www.under510.com",
}

def build_url(url: str, params: Dict[str, object]) -> str:
    return f"{url}?{urlencode(params)}"


def extract_attr(fragment: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}=['\"]([^'\"]*)['\"]", fragment, re.I)
    return normalize_whitespace(html.unescape(match.group(1))) if match else ""


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


def retro_stage_product_url_from_title(site_root: str, title: str) -> str:
    slug = normalize_whitespace(title).lower().replace("&", "and")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return f"{site_root.rstrip('/')}/products/{slug}" if slug else ""


def is_in_scope_product(context: ProductContext) -> bool:
    if urlparse(context.url).netloc.lower() in OUT_OF_SCOPE_DOMAINS:
        return False
    return bool(classify_clothing_type(context))


def split_review_blocks(html_text: str, markers: Sequence[str]) -> List[str]:
    blocks: List[str] = []
    for marker in markers:
        starts = [match.start() for match in re.finditer(marker, html_text, re.I)]
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else min(len(html_text), start + 30000)
            blocks.append(html_text[start:end])
    return blocks


class ProviderAdapter:
    name = "base"

    def scrape_product(self, context: ProductContext) -> List[ReviewImage]:
        raise NotImplementedError


class JudgeMeAdapter(ProviderAdapter):
    name = "judgeme"
    widget_url = "https://api.judge.me/reviews/reviews_for_widget"
    all_reviews_url = "https://api.judge.me/reviews/all_reviews_js_based"
    aggregate_consumed: Set[str] = set()

    def scrape_product(self, context: ProductContext) -> List[ReviewImage]:
        reviews = self._widget_reviews(context)
        if reviews:
            return reviews
        return self._all_reviews(context)

    def _widget_reviews(self, context: ProductContext) -> List[ReviewImage]:
        if not context.product_id:
            return []
        params = {
            "url": urlparse(context.url).netloc,
            "shop_domain": context.shop_domain,
            "platform": "shopify",
            "per_page": 20,
            "page": 1,
            "product_id": context.product_id,
            "sort_by": "with_pictures",
        }
        reviews: List[ReviewImage] = []
        seen = set()
        for page in range(1, 10000):
            params["page"] = page
            try:
                payload = fetch_json(build_url(self.widget_url, params), referer=context.url, retries=2)
            except Exception:
                break
            batch = self._parse_json_reviews(payload, context)
            if not batch:
                widget_html = html.unescape(str(payload.get("html") or ""))
                batch = self._parse_blocks(widget_html, context)
            batch = [review for review in batch if review.image_url and review.review_id not in seen]
            for review in batch:
                seen.add(review.review_id)
            reviews.extend(batch)
            pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
            total_pages = int(pagination.get("total_pages") or 0)
            if not batch or (total_pages and page >= total_pages):
                break
        return reviews

    def _all_reviews(self, context: ProductContext) -> List[ReviewImage]:
        aggregate_key = context.shop_domain or urlparse(context.url).netloc
        if aggregate_key in self.aggregate_consumed:
            return []
        self.aggregate_consumed.add(aggregate_key)
        params = {
            "shop_domain": context.shop_domain,
            "platform": "shopify",
            "sort_by": "with_media",
            "per_page": 100,
            "page": 1,
        }
        reviews: List[ReviewImage] = []
        seen = set()
        for page in range(1, 10000):
            params["page"] = page
            try:
                payload = fetch_json(build_url(self.all_reviews_url, params), referer=context.url, retries=2)
            except Exception:
                break
            html_text = html.unescape(str(payload.get("html") or ""))
            parsed = self._parse_blocks(html_text, context)
            for review in parsed:
                if review.extra.get("feed_scope") != "aggregate":
                    review.extra["product_url"] = ""
                    review.extra["product_title"] = ""
                review.extra["feed_scope"] = "aggregate"
            batch = [
                review
                for review in parsed
                if review.image_url and (not review.review_id or review.review_id not in seen)
            ]
            for review in batch:
                if review.review_id:
                    seen.add(review.review_id)
            reviews.extend(batch)
            if not batch:
                break
        return reviews

    def _parse_json_reviews(self, payload: Dict[str, object], context: ProductContext) -> List[ReviewImage]:
        items = payload.get("reviews") or []
        if not isinstance(items, list):
            return []
        reviews: List[ReviewImage] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            images = []
            for picture in item.get("pictures_urls") or []:
                if isinstance(picture, dict):
                    images.append(normalize_whitespace(picture.get("original") or picture.get("huge") or picture.get("compact")))
                elif isinstance(picture, str):
                    images.append(normalize_whitespace(picture))
            images = unique(images)
            if not images:
                continue
            product_url = normalize_whitespace(item.get("product_url_with_utm") or item.get("product_url"))
            if product_url and product_url.startswith("/"):
                product_url = urljoin(context.url, product_url)
            product_title = normalize_whitespace(item.get("product_title")) or context.title
            size = ""
            for answer in item.get("cf_answers") or []:
                if not isinstance(answer, dict):
                    continue
                label = normalize_whitespace(answer.get("question") or answer.get("label") or answer.get("name"))
                value = normalize_whitespace(answer.get("answer") or answer.get("value"))
                if "size" in label.lower() and value:
                    size = value
                    break
            for image_url in images:
                reviews.append(
                    ReviewImage(
                        image_url=image_url,
                        review_id=normalize_whitespace(item.get("uuid") or item.get("id")),
                        review_title=normalize_whitespace(item.get("title")),
                        review_body=strip_tags(item.get("body_html") or item.get("body")),
                        reviewer_name=normalize_whitespace(item.get("reviewer_name")),
                        date_raw=normalize_whitespace(item.get("created_at")),
                        size_raw=size,
                        rating=normalize_whitespace(item.get("rating")),
                        extra={"product_url": product_url or context.url, "product_title": product_title},
                    )
                )
        return reviews

    def _parse_blocks(self, html_text: str, context: Optional[ProductContext] = None) -> List[ReviewImage]:
        reviews: List[ReviewImage] = []
        for block in split_review_blocks(html_text, [r"<div[^>]+class=['\"][^'\"]*jdgm-rev\b"]):
            review_id = extract_attr(block, "data-review-id")
            title = strip_tags(re.search(r"<b[^>]+class=['\"][^'\"]*jdgm-rev__title[^'\"]*['\"][^>]*>(.*?)</b>", block, re.I | re.S).group(1)) if re.search(r"<b[^>]+class=['\"][^'\"]*jdgm-rev__title", block, re.I) else ""
            body = strip_tags(re.search(r"<div[^>]+class=['\"][^'\"]*jdgm-rev__body[^'\"]*['\"][^>]*>(.*?)</div>", block, re.I | re.S).group(1)) if re.search(r"<div[^>]+class=['\"][^'\"]*jdgm-rev__body", block, re.I) else ""
            author = strip_tags(re.search(r"<span[^>]+class=['\"][^'\"]*jdgm-rev__author[^'\"]*['\"][^>]*>(.*?)</span>", block, re.I | re.S).group(1)) if re.search(r"<span[^>]+class=['\"][^'\"]*jdgm-rev__author", block, re.I) else ""
            date_raw = extract_attr(block, "data-content") or extract_attr(block, "data-created-at")
            size = ""
            for label, value in re.findall(
                r"jdgm-rev__cf-ans__title[^>]*>(.*?)</b>\s*<span[^>]+class=['\"][^'\"]*jdgm-rev__cf-ans__value[^'\"]*['\"][^>]*>(.*?)</span>",
                block,
                re.I | re.S,
            ):
                if "size" in strip_tags(label).lower():
                    size = strip_tags(value)
                    break
            product_url = ""
            product_title = ""
            product_match = re.search(
                r"<a\b(?=[^>]*class=['\"][^'\"]*jdgm-rev__prod-link[^'\"]*['\"])(?=[^>]*href=['\"]([^'\"]+)['\"])[^>]*>(.*?)</a>",
                block,
                re.I | re.S,
            )
            if product_match:
                product_url = normalize_whitespace(html.unescape(product_match.group(1)))
                product_title = strip_tags(product_match.group(2))
                if context and product_url.startswith("/"):
                    product_url = urljoin(context.url, product_url)
            images = unique(
                html.unescape(match)
                for match in re.findall(
                    r"(?:data-mfp-src|data-src|href|src)=['\"]([^'\"]+\.(?:jpg|jpeg|png|webp)(?:\?[^'\"]*)?)['\"]",
                    block,
                    re.I,
                )
            )
            for image_url in images:
                if "product-picture" in image_url:
                    continue
                reviews.append(
                    ReviewImage(
                        image_url=image_url,
                        review_id=review_id,
                        review_title=title,
                        review_body=body,
                        reviewer_name=author,
                        date_raw=date_raw,
                        size_raw=size,
                        extra={
                            "product_url": product_url or (context.url if context else ""),
                            "product_title": product_title or (context.title if context else ""),
                            "feed_scope": "aggregate" if product_url else "",
                        },
                    )
                )
        return reviews


class LooxAdapter(ProviderAdapter):
    name = "loox"

    def scrape_product(self, context: ProductContext) -> List[ReviewImage]:
        app_ids = self._app_ids(context)
        if not app_ids or not context.product_id:
            return self._parse_embedded(context.raw_html)
        reviews: List[ReviewImage] = []
        seen = set()
        for app_id in app_ids:
            for page in range(1, 10000):
                url = build_url(
                    f"https://loox.io/widget/{app_id}/reviews",
                    {"productId": context.product_id, "page": page, "limit": 20, "sort_by": "photo"},
                )
                try:
                    payload = fetch_text(url, referer=context.url, retries=2)
                except Exception:
                    break
                batch = self._parse_embedded(payload)
                batch = [review for review in batch if (review.review_id, review.image_url) not in seen]
                for review in batch:
                    seen.add((review.review_id, review.image_url))
                reviews.extend(batch)
                if not batch:
                    break
            if reviews:
                break
        return reviews

    def _app_ids(self, context: ProductContext) -> List[str]:
        html_text = context.raw_html.replace("\\/", "/")
        values = re.findall(r"loox\.io/widget/([^/'\"\s]+)/", html_text, re.I)
        values += re.findall(r"Loox\.shop\s*=\s*['\"]([^'\"]+)['\"]", html_text, re.I)
        values += [context.shop_domain, urlparse(context.url).netloc]
        return unique(values)

    def _parse_embedded(self, html_text: str) -> List[ReviewImage]:
        reviews: List[ReviewImage] = []
        for block in split_review_blocks(
            html_text,
            [
                r"<div[^>]+class=['\"][^'\"]*grid-item-wrap\b",
                r"<div[^>]+class=['\"][^'\"]*loox-review\b",
                r"<li[^>]+class=['\"][^'\"]*loox-review",
            ],
        ):
            review_id = extract_attr(block, "data-review-id") or extract_attr(block, "id")
            if not review_id:
                id_match = re.search(r"review-([A-Za-z0-9_-]+)-(?:media|title|date|stars|text)", block)
                review_id = normalize_whitespace(id_match.group(1)) if id_match else ""
            if not review_id:
                review_id = extract_attr(block, "data-id")
            body = strip_tags(
                first_or_blank(
                    [
                        r"data-testid=['\"]review-[^'\"]+-text['\"][^>]*>(.*?)</div>",
                        r"<div[^>]+class=['\"][^'\"]*content[^'\"]*['\"][^>]*>(.*?)</div>",
                        r"<p[^>]+class=['\"][^'\"]*review[^'\"]*['\"][^>]*>(.*?)</p>",
                    ],
                    block,
                )
            )
            author = strip_tags(
                first_or_blank(
                    [
                        r"data-testid=['\"]review-[^'\"]+-title['\"][^>]*class=['\"][^'\"]*block title[^'\"]*['\"][^>]*>(.*?)(?:<span|</div>)",
                        r"class=['\"][^'\"]*author[^'\"]*['\"][^>]*>(.*?)<",
                    ],
                    block,
                )
            )
            date_raw = strip_tags(first_or_blank([r"class=['\"][^'\"]*date[^'\"]*['\"][^>]*>(.*?)<"], block))
            data_time = first_or_blank(
                [
                    r"data-testid=['\"]review-[^'\"]+-date['\"][^>]+data-time=['\"]([^'\"]+)['\"]",
                    r"data-time=['\"]([^'\"]+)['\"][^>]+data-testid=['\"]review-[^'\"]+-date['\"]",
                ],
                block,
            )
            if data_time and len(data_time) >= 10:
                date_raw = data_time
            product_title = strip_tags(
                first_or_blank(
                    [
                        r"class=['\"][^'\"]*product-thumbnail-product-name[^'\"]*['\"][^>]*>(.*?)</",
                        r"class=['\"][^'\"]*name(?:\s+name-with-img)?[^'\"]*['\"][^>]*>(.*?)</div>",
                    ],
                    block,
                )
            )
            images = unique(
                html.unescape(match)
                for match in re.findall(
                    r"(?:data-img|data-src|src|href)=['\"]([^'\"]+\.(?:jpg|jpeg|png|webp)(?:\?[^'\"]*)?)['\"]",
                    block,
                    re.I,
                )
            )
            images = [f"https:{url}" if url.startswith("//") else url for url in images]
            images = [url for url in images if "images.loox.io" in url or "loox.io/uploads" in url]
            for image_url in images:
                extra = {"product_title": product_title} if product_title else {}
                if "grid-item-wrap" in block:
                    extra["product_url"] = ""
                reviews.append(
                    ReviewImage(
                        image_url=image_url,
                        review_id=review_id,
                        review_body=body,
                        reviewer_name=author,
                        date_raw=date_raw,
                        extra=extra,
                    )
                )
        return reviews


class StampedAdapter(ProviderAdapter):
    name = "stamped"
    reviews_url = "https://stamped.io/api/widget/reviews"
    photo_base = "https://cdn.stamped.io/uploads/photos/"

    def scrape_product(self, context: ProductContext) -> List[ReviewImage]:
        config = self._config(context)
        if not config.get("apiKey") or not context.product_id:
            return self._parse_embedded_reviews_summary(context)
        reviews: List[ReviewImage] = []
        seen = set()
        for page in range(1, 10000):
            params = {
                "apiKey": config.get("apiKey", ""),
                "sId": config.get("sId", ""),
                "storeUrl": config.get("storeUrl") or context.shop_domain,
                "productId": context.product_id,
                "page": page,
                "skip": 100,
                "minRating": 1,
                "isWithPhotos": "true",
                "type": "widget-carousel-photos",
            }
            try:
                payload = fetch_json(build_url(self.reviews_url, params), referer=context.url, retries=2)
            except Exception:
                break
            data = payload.get("data")
            if not isinstance(data, list) or not data:
                break
            page_count = 0
            for item in data:
                if not isinstance(item, dict):
                    continue
                review_id = normalize_whitespace(item.get("id"))
                if review_id in seen:
                    continue
                seen.add(review_id)
                images = self._photo_urls(normalize_whitespace(item.get("reviewUserPhotos")))
                if not images:
                    continue
                page_count += 1
                for image_url in images:
                    reviews.append(
                        ReviewImage(
                            image_url=image_url,
                            review_id=review_id,
                            review_title=normalize_whitespace(item.get("reviewTitle")),
                            review_body=normalize_whitespace(item.get("reviewMessage")),
                            reviewer_name=normalize_whitespace(item.get("author")),
                            date_raw=normalize_whitespace(item.get("dateCreated") or item.get("reviewDate")),
                            size_raw=self._size_from_options(item),
                            rating=normalize_whitespace(item.get("reviewRating")),
                            extra={
                                "product_url": context.url,
                                "product_title": normalize_whitespace(item.get("productName")) or context.title,
                            },
                        )
                    )
            if page_count == 0:
                break
        return reviews or self._parse_embedded_reviews_summary(context)

    def _parse_embedded_reviews_summary(self, context: ProductContext) -> List[ReviewImage]:
        marker = '"reviews_summary"'
        marker_index = context.raw_html.find(marker)
        if marker_index < 0:
            return []
        value_start = context.raw_html.find("{", marker_index)
        if value_start < 0:
            return []
        try:
            summary, _ = json.JSONDecoder().raw_decode(context.raw_html[value_start:])
        except json.JSONDecodeError:
            return []
        if not isinstance(summary, dict):
            return []
        reviews_by_id = summary.get("reviews")
        if not isinstance(reviews_by_id, dict):
            return []
        media_items = summary.get("media")
        if not isinstance(media_items, list):
            media_items = []
        media_by_review: Dict[str, List[str]] = {}
        for media in media_items:
            if not isinstance(media, dict):
                continue
            review_id = normalize_whitespace(media.get("review_id"))
            image_url = normalize_whitespace(media.get("media_url"))
            if review_id and image_url:
                media_by_review.setdefault(review_id, []).append(image_url)

        parsed_reviews: List[ReviewImage] = []
        seen = set()
        for review_id, item in reviews_by_id.items():
            if not isinstance(item, dict):
                continue
            clean_review_id = normalize_whitespace(item.get("id") or review_id)
            images = unique(list(item.get("images_url") or []) + media_by_review.get(clean_review_id, []))
            if not images:
                continue
            variant = normalize_whitespace(item.get("vendor_variant_name"))
            size = ""
            if "/" in variant:
                size = normalize_whitespace(variant.rsplit("/", 1)[-1])
            product_title = normalize_whitespace(item.get("vendor_product_title")) or context.title
            for image_url in images:
                key = (clean_review_id, image_url)
                if key in seen:
                    continue
                seen.add(key)
                parsed_reviews.append(
                    ReviewImage(
                        image_url=image_url,
                        review_id=clean_review_id,
                        review_title=normalize_whitespace(item.get("title")),
                        review_body=normalize_whitespace(item.get("body")),
                        reviewer_name=normalize_whitespace(item.get("author")),
                        date_raw=normalize_whitespace(item.get("date_created") or item.get("date_added")),
                        size_raw=size,
                        rating=normalize_whitespace(item.get("rating")),
                        extra={"product_url": context.url, "product_title": product_title},
                    )
                )
        return parsed_reviews

    def _config(self, context: ProductContext) -> Dict[str, str]:
        html_text = context.raw_html
        return {
            "apiKey": first_or_blank(
                [
                    r"apiKey['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
                    r"data-api-key=['\"]([^'\"]+)['\"]",
                    r'"STAMPED_API_KEY"\s*:\s*"([^"]+)"',
                ],
                html_text,
            ),
            "sId": first_or_blank([r"sId['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", r"data-store-id=['\"]([^'\"]+)['\"]"], html_text),
            "storeUrl": first_or_blank([r"storeUrl['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]"], html_text) or context.shop_domain,
        }

    def _photo_urls(self, raw: str) -> List[str]:
        urls = []
        for part in raw.split(","):
            part = normalize_whitespace(part)
            if not part:
                continue
            urls.append(part if part.startswith("http") else f"{self.photo_base}{part}")
        return urls

    def _size_from_options(self, item: Dict[str, object]) -> str:
        options = item.get("reviewOptionsList")
        if not isinstance(options, list):
            return ""
        for option in options:
            if not isinstance(option, dict):
                continue
            label = normalize_whitespace(option.get("question") or option.get("label") or option.get("name"))
            value = normalize_whitespace(option.get("answer") or option.get("value"))
            if "size" in label.lower() and value:
                return value
        return ""


class OkendoAdapter(ProviderAdapter):
    name = "okendo"

    def scrape_product(self, context: ProductContext) -> List[ReviewImage]:
        subscriber_id = first_or_blank(
            [
                r'"subscriberId"\s*:\s*"([^"]+)"',
                r"subscriberId['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
                r"OkendoApi\.init\(['\"]([^'\"]+)['\"]",
                r"api\.okendo\.io/v1/stores/([^/'\"]+)",
            ],
            context.raw_html,
        )
        if not subscriber_id or not context.product_id:
            return self._parse_embedded(context.raw_html)
        reviews: List[ReviewImage] = []
        seen = set()
        url = build_url(
            f"https://api.okendo.io/v1/stores/{subscriber_id}/products/shopify-{context.product_id}/reviews",
            {"limit": 100, "orderBy": "has_media desc"},
        )
        seen_pages = set()
        while url and url not in seen_pages:
            seen_pages.add(url)
            try:
                payload = fetch_json(url, referer=context.url, retries=2)
            except Exception:
                break
            items = payload.get("reviews") or payload.get("data") or []
            if not isinstance(items, list) or not items:
                break
            page_count = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                review_id = normalize_whitespace(item.get("reviewId") or item.get("id"))
                body = normalize_whitespace(item.get("body") or item.get("reviewBody"))
                media = item.get("media") or item.get("images") or []
                image_urls = extract_media_urls(media)
                if not image_urls:
                    continue
                page_count += 1
                for image_url in image_urls:
                    key = (review_id, image_url)
                    if key in seen:
                        continue
                    seen.add(key)
                    reviewer = item.get("reviewer") if isinstance(item.get("reviewer"), dict) else {}
                    reviews.append(
                        ReviewImage(
                            image_url=image_url,
                            review_id=review_id,
                            review_title=normalize_whitespace(item.get("title")),
                            review_body=body,
                            reviewer_name=normalize_whitespace(reviewer.get("displayName") or item.get("reviewerDisplayName") or item.get("name")),
                            date_raw=normalize_whitespace(item.get("dateCreated") or item.get("createdAt")),
                        )
                    )
            if page_count == 0:
                break
            next_url = normalize_whitespace(payload.get("nextUrl"))
            url = f"https://api.okendo.io/v1{next_url}" if next_url.startswith("/") else next_url
        return reviews or self._parse_embedded(context.raw_html)

    def _parse_embedded(self, html_text: str) -> List[ReviewImage]:
        reviews: List[ReviewImage] = []
        blocks = split_review_blocks(html_text, [r"<li[^>]+class=['\"][^'\"]*oke-w-reviews-list-item\b"])
        if not blocks:
            blocks = split_review_blocks(html_text, [r"<div[^>]+class=['\"][^'\"]*oke-mediaStrip-item\b"])
        for index, block in enumerate(blocks, start=1):
            image_urls = extract_media_urls(block)
            image_urls = [url for url in image_urls if "okendo.io/images/" in url]
            if not image_urls:
                continue
            title = strip_tags(first_or_blank([r"oke-reviewContent-title[^>]*>(.*?)<"], block))
            body = strip_tags(
                first_or_blank(
                    [
                        r"oke-reviewContent-body[^>]*>(.*?)</div>",
                        r"oke-reviewContent-bodyText[^>]*>(.*?)</div>",
                    ],
                    block,
                )
            )
            author = strip_tags(first_or_blank([r"oke-w-reviewer-name[^>]*>(.*?)<", r"oke-reviewer-name[^>]*>(.*?)<"], block))
            date_raw = strip_tags(first_or_blank([r"oke-reviewContent-date[^>]*>(.*?)<", r"oke-w-review-date[^>]*>(.*?)<"], block))
            review_id = first_or_blank([r"data-oke-review-id=['\"]([^'\"]+)['\"]", r"reviewId['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]"], block)
            for image_url in image_urls:
                reviews.append(
                    ReviewImage(
                        image_url=image_url,
                        review_id=review_id or f"embedded-okendo-{index}",
                        review_title=title,
                        review_body=body,
                        reviewer_name=author,
                        date_raw=date_raw,
                    )
                )
        return reviews


def yotpo_app_keys(html_text: str) -> List[str]:
    preferred_keys: List[str] = []
    other_keys: List[str] = []
    for match in re.finditer(r"cdn-widgetsrepository\.yotpo\.com/v1/loader/([^?/'\"]+)", html_text, re.I):
        key = normalize_whitespace(match.group(1))
        nearby = html_text[max(0, match.start() - 500) : match.start()]
        if re.search(r"yotpo-product-reviews|data-yotpo-instance-id|yotpo-widget-instance", nearby, re.I):
            preferred_keys.append(key)
        else:
            other_keys.append(key)
    for pattern in [
        r"staticw2\.yotpo\.com/([^/'\"]+)/",
        r"yotpo\.init\(\s*['\"]([^'\"]+)['\"]",
        r"appKey['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
    ]:
        other_keys.extend(normalize_whitespace(match) for match in re.findall(pattern, html_text, re.I | re.S))
    return unique([key for key in preferred_keys + other_keys if key])


class YotpoAdapter(ProviderAdapter):
    name = "yotpo"

    def scrape_product(self, context: ProductContext) -> List[ReviewImage]:
        if not context.product_id:
            return []
        app_keys = yotpo_app_keys(context.raw_html)
        if not app_keys:
            return []
        reviews: List[ReviewImage] = []
        seen = set()
        for app_key in app_keys:
            app_reviews: List[ReviewImage] = []
            for page in range(1, 10000):
                url = build_url(
                    f"https://api.yotpo.com/v1/widget/{app_key}/products/{context.product_id}/reviews.json",
                    {"page": page, "per_page": 100, "sort": "images"},
                )
                try:
                    payload = fetch_json(url, referer=context.url, retries=2)
                except Exception:
                    break
                response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
                items = response.get("reviews") if isinstance(response, dict) else []
                if not isinstance(items, list) or not items:
                    break
                page_count = 0
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    review_id = normalize_whitespace(item.get("id"))
                    image_urls = extract_media_urls(item.get("images_data") or item.get("images") or [])
                    if not image_urls:
                        continue
                    page_count += 1
                    for image_url in image_urls:
                        key = (review_id, image_url)
                        if key in seen:
                            continue
                        seen.add(key)
                        app_reviews.append(
                            ReviewImage(
                                image_url=image_url,
                                review_id=review_id,
                                review_title=normalize_whitespace(item.get("title")),
                                review_body=normalize_whitespace(item.get("content")),
                                reviewer_name=normalize_whitespace(item.get("user", {}).get("display_name") if isinstance(item.get("user"), dict) else ""),
                                date_raw=normalize_whitespace(item.get("created_at")),
                                size_raw=yotpo_custom_size(item),
                                rating=normalize_whitespace(item.get("score")),
                            )
                        )
                if page_count == 0:
                    break
            if app_reviews:
                reviews.extend(app_reviews)
                break
        return reviews


class RyviuAdapter(ProviderAdapter):
    name = "ryviu"
    reviews_url = "https://app.ryviu.io/frontend/client/get-more-reviews"

    def scrape_product(self, context: ProductContext) -> List[ReviewImage]:
        if "ryviu" not in context.raw_html.lower() or not context.handle:
            return []
        domain = context.shop_domain if context.shop_domain.endswith(".myshopify.com") else urlparse(context.url).netloc
        reviews: List[ReviewImage] = []
        seen = set()
        for page in range(1, 10000):
            payload = {
                "handle": context.handle,
                "product_id": context.product_id,
                "domain": domain,
                "page": page,
                "type": "load-more",
                "order": "late",
                "filter": "all",
                "filter_review": {"stars": [], "image": True, "replies": False},
                "feature": True,
                "feature_extend": True,
                "first_load": page == 1,
                "platform": "shopify",
                "type_review": "all",
                "limit_number": 50,
            }
            try:
                data = post_json(build_url(self.reviews_url, {"domain": domain}), payload, referer=context.url, retries=2)
            except Exception:
                break
            items = data.get("more_reviews") or data.get("reviews") or []
            if not isinstance(items, list) or not items:
                break
            page_count = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                image_urls = [
                    normalize_whitespace(url)
                    for url in extract_media_urls(item.get("body_urls") or [])
                    if normalize_whitespace(url)
                ]
                if not image_urls:
                    continue
                page_count += len(image_urls)
                product_info = item.get("product_info") if isinstance(item.get("product_info"), dict) else {}
                product_url = normalize_whitespace(product_info.get("url")) or urljoin(
                    f"{urlparse(context.url).scheme}://{urlparse(context.url).netloc}",
                    f"/products/{normalize_whitespace(item.get('product_handle')) or context.handle}",
                )
                product_title = normalize_whitespace(product_info.get("title") or item.get("title_product")) or context.title
                for image_index, image_url in enumerate(image_urls, start=1):
                    key = (item.get("key") or item.get("key_id"), image_url)
                    if key in seen:
                        continue
                    seen.add(key)
                    reviews.append(
                        ReviewImage(
                            image_url=image_url,
                            review_id=f"ryviu-{item.get('key') or item.get('key_id') or page}-{image_index}",
                            review_title=normalize_whitespace(html.unescape(str(item.get("title") or ""))),
                            review_body=normalize_whitespace(html.unescape(str(item.get("body_text") or ""))),
                            reviewer_name=normalize_whitespace(html.unescape(str(item.get("author") or ""))),
                            date_raw=normalize_whitespace(item.get("created_at") or item.get("created_at_format")),
                            extra={"product_url": product_url, "product_title": product_title},
                        )
                    )
            if page_count == 0:
                break
        return reviews


def first_or_blank(patterns: Sequence[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return normalize_whitespace(html.unescape(match.group(1)))
    return ""


def extract_media_urls(media: object) -> List[str]:
    urls: List[str] = []
    if isinstance(media, str):
        urls.extend(re.findall(r"(?:https?:)?//[^'\"\s,<>]+\.(?:jpg|jpeg|png|webp)(?:\?[^'\"\s,<>]*)?", media, re.I))
    elif isinstance(media, list):
        for item in media:
            urls.extend(extract_media_urls(item))
    elif isinstance(media, dict):
        for key in [
            "url",
            "original_url",
            "image_url",
            "thumbnail_url",
            "src",
            "fullSizeUrl",
            "largeUrl",
            "largePortraitThumbnailUrl",
            "thumbnailUrl",
        ]:
            if media.get(key):
                urls.append(str(media[key]))
        for value in media.values():
            if isinstance(value, (dict, list)):
                urls.extend(extract_media_urls(value))
    normalized = [f"https:{url}" if url.startswith("//") else url for url in urls]
    return unique(normalized)


def adapter_order(provider_hints: str) -> List[ProviderAdapter]:
    adapters: List[ProviderAdapter] = []
    mapping = [
        ("Judge.me", JudgeMeAdapter()),
        ("Loox", LooxAdapter()),
        ("Stamped", StampedAdapter()),
        ("Okendo", OkendoAdapter()),
        ("Yotpo", YotpoAdapter()),
        ("Ryviu", RyviuAdapter()),
    ]
    for name, adapter in mapping:
        if name.lower() in provider_hints.lower():
            adapters.append(adapter)
    for _, adapter in mapping:
        if all(existing.name != adapter.name for existing in adapters):
            adapters.append(adapter)
    return adapters


def read_leads(triage_csv: Path, domains: Sequence[str]) -> Dict[str, List[str]]:
    wanted = set(domains)
    leads: Dict[str, List[str]] = {domain: [] for domain in domains}
    with triage_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            domain = row.get("merchant_domain", "")
            if domain not in wanted:
                continue
            action = row.get("triage_bucket") or row.get("recommended_next_action")
            if action != "scrape now":
                continue
            leads.setdefault(domain, []).append(row.get("original_url", ""))
    return {domain: unique(urls) for domain, urls in leads.items() if urls}


def discover_yotpo_shopify_contexts(site_root: str, seed_urls: Sequence[str]) -> List[ProductContext]:
    if not seed_urls:
        return []
    seed_context = hydrate_shopify_context(extract_product_context(seed_urls[0]))
    if not yotpo_app_keys(seed_context.raw_html):
        return []
    root = site_root.rstrip("/")
    seed_html = seed_context.raw_html
    contexts: List[ProductContext] = []
    seen = set()
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
            product_id = normalize_whitespace(product.get("id"))
            if not handle or not product_id or handle in seen:
                continue
            seen.add(handle)
            variants = product.get("variants")
            variant = ""
            if isinstance(variants, list) and variants and isinstance(variants[0], dict):
                variant = normalize_whitespace(variants[0].get("title"))
            contexts.append(
                ProductContext(
                    url=f"{root}/products/{handle}",
                    title=normalize_whitespace(product.get("title")),
                    description=strip_tags(product.get("body_html")),
                    category=normalize_whitespace(product.get("product_type")),
                    brand=normalize_whitespace(product.get("vendor")),
                    product_id=product_id,
                    handle=handle,
                    shop_domain=urlparse(root).netloc,
                    provider_hints="Yotpo",
                    raw_html=seed_html,
                    variant=variant,
                )
            )
        if len(products) < 250:
            break
    return contexts


def yotpo_custom_size(item: Dict[str, object]) -> str:
    custom_fields = item.get("custom_fields") if isinstance(item.get("custom_fields"), dict) else {}
    for value in custom_fields.values():
        if not isinstance(value, dict):
            continue
        if normalize_whitespace(value.get("title")).lower() == "size":
            return normalize_whitespace(value.get("value"))
    return ""


def scrape_yotpo_aggregate_reviews(
    site_root: str, contexts: Sequence[ProductContext], fetched_at: str
) -> Tuple[List[Dict[str, str]], List[Dict[str, object]], List[str]]:
    if not contexts:
        return [], [], []
    app_keys = yotpo_app_keys(contexts[0].raw_html)
    if not app_keys:
        return [], [], []
    app_key = app_keys[0]
    context_by_shopify_id = {context.product_id: context for context in contexts if context.product_id}
    context_by_yotpo_id: Dict[str, ProductContext] = {}
    product_counts: Dict[str, int] = {}
    rows: List[Dict[str, str]] = []
    errors: List[str] = []
    seen = set()
    for page in range(1, 10000):
        url = build_url(
            f"https://api.yotpo.com/v1/widget/{app_key}/reviews.json",
            {"page": page, "per_page": 100, "sort": "images"},
        )
        try:
            payload = fetch_json(url, referer=site_root, retries=2)
        except Exception as exc:
            errors.append(f"Yotpo aggregate page {page} failed: {exc}")
            break
        response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
        products = response.get("products") if isinstance(response, dict) else []
        if isinstance(products, list):
            for product in products:
                if not isinstance(product, dict):
                    continue
                yotpo_id = normalize_whitespace(product.get("id"))
                shopify_id = normalize_whitespace(product.get("domain_key"))
                context = context_by_shopify_id.get(shopify_id)
                if context:
                    context_by_yotpo_id[yotpo_id] = context
        items = response.get("reviews") if isinstance(response, dict) else []
        if not isinstance(items, list) or not items:
            break
        page_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            image_urls = extract_media_urls(item.get("images_data") or item.get("images") or [])
            if not image_urls:
                continue
            context = context_by_yotpo_id.get(normalize_whitespace(item.get("product_id")))
            if not context or not is_in_scope_product(context):
                continue
            page_count += len(image_urls)
            review_id = normalize_whitespace(item.get("id"))
            reviewer = item.get("user") if isinstance(item.get("user"), dict) else {}
            for image_url in image_urls:
                key = (review_id, image_url)
                if key in seen:
                    continue
                seen.add(key)
                review = ReviewImage(
                    image_url=image_url,
                    review_id=review_id,
                    review_title=normalize_whitespace(item.get("title")),
                    review_body=normalize_whitespace(item.get("content")),
                    reviewer_name=normalize_whitespace(reviewer.get("display_name")),
                    date_raw=normalize_whitespace(item.get("created_at")),
                    size_raw=yotpo_custom_size(item),
                    rating=normalize_whitespace(item.get("score")),
                )
                rows.append(build_intake_row(context, review, fetched_at))
                product_counts[context.url] = product_counts.get(context.url, 0) + 1
        print(f"[{urlparse(site_root).netloc} yotpo aggregate page {page}] -> {page_count} image rows", flush=True)
        if page_count == 0:
            break
    product_summaries = [
        {
            "product_url": context.url,
            "product_title": context.title,
            "provider_hints": context.provider_hints,
            "adapter_used": "yotpo-aggregate",
            "matching_review_images": product_counts.get(context.url, 0),
            "product_index": index,
        }
        for index, context in enumerate(contexts, start=1)
        if product_counts.get(context.url, 0)
    ]
    return rows, product_summaries, errors


def scrape_yotpo_product_reviews(
    domain: str, contexts: Sequence[ProductContext], fetched_at: str
) -> Tuple[List[Dict[str, str]], List[Dict[str, object]], List[str]]:
    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    adapter = YotpoAdapter()
    product_count = len(contexts)
    for index, context in enumerate(contexts, start=1):
        if not is_in_scope_product(context):
            product_summaries.append(
                {
                    "product_url": context.url,
                    "product_title": context.title,
                    "provider_hints": context.provider_hints,
                    "adapter_used": "yotpo-product-skipped-out-of-scope",
                    "matching_review_images": 0,
                    "product_index": index,
                }
            )
            continue
        try:
            product_reviews = adapter.scrape_product(context)
        except Exception as exc:
            errors.append(f"{context.url}: yotpo product pass failed: {exc}")
            product_reviews = []
        product_rows = [build_intake_row(context, review, fetched_at) for review in product_reviews if review.image_url]
        rows.extend(product_rows)
        product_summaries.append(
            {
                "product_url": context.url,
                "product_title": context.title,
                "provider_hints": context.provider_hints,
                "adapter_used": "yotpo-product",
                "matching_review_images": len(product_rows),
                "product_index": index,
            }
        )
        print(f"[{domain} yotpo product {index}/{product_count}] {context.title or context.url} -> {len(product_rows)} rows", flush=True)
    return rows, product_summaries, errors


def scrape_domain(
    domain: str,
    seed_urls: Sequence[str],
    *,
    only_seed_products: bool = False,
    include_yotpo_product_pass: bool = True,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    started_at = utc_now()
    site_root = f"https://{domain}"
    product_contexts: List[ProductContext] = []
    seed_urls = unique(seed_urls)
    seed_url_count = len(seed_urls)
    discovery_method = "seed_urls_only" if only_seed_products else "shopify_products_json"
    catalog_discovery_attempted = not only_seed_products
    aggregate_feed_used = False

    def scope_status(products_scanned: int) -> str:
        if only_seed_products:
            return "seed_scrape_only"
        if products_scanned > seed_url_count:
            return "full_catalog_attempted"
        return "catalog_discovery_failed_or_seed_only"

    def enrich_summary(summary_json: Path, products_scanned: int, *, aggregate_used: bool) -> None:
        try:
            payload = json.loads(summary_json.read_text(encoding="utf-8"))
        except Exception:
            return
        status = scope_status(products_scanned)
        payload.update(
            {
                "seed_url_count": seed_url_count,
                "seed_urls": list(seed_urls),
                "discovery_method": discovery_method,
                "catalog_discovery_attempted": catalog_discovery_attempted,
                "products_discovered": products_scanned,
                "product_pages_scanned": products_scanned,
                "scrape_scope_status": status,
                "full_catalog_scrape_complete": status == "full_catalog_attempted",
                "seed_scrape_only": status == "seed_scrape_only",
                "aggregate_feed_used": aggregate_used,
            }
        )
        if status != "full_catalog_attempted":
            payload.setdefault("warnings", [])
            if isinstance(payload["warnings"], list):
                payload["warnings"].append(
                    "This output is not a full catalog scrape; do not mark the retailer fully scraped."
                )
        summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if not only_seed_products:
        product_contexts = discover_yotpo_shopify_contexts(site_root, seed_urls)
        if product_contexts:
            discovery_method = "shopify_products_json_yotpo_contexts"
    product_urls = list(seed_urls) if only_seed_products or product_contexts else discover_shopify_product_urls(site_root, seed_urls)
    if not product_urls and not product_contexts:
        product_urls = list(seed_urls)
    product_count = len(product_contexts) or len(product_urls)

    rows: List[Dict[str, str]] = []
    product_summaries: List[Dict[str, object]] = []
    errors: List[str] = []
    adapter_names = set()
    fetched_at = utc_now()

    if domain in {"retro-stage.com", "www.retro-stage.com"} and product_urls:
        try:
            seed_context = hydrate_shopify_context(extract_product_context(seed_urls[0] if seed_urls else product_urls[0]))
            app_ids = LooxAdapter()._app_ids(seed_context)
        except Exception as exc:
            app_ids = []
            errors.append(f"{domain}: Retro Stage Loox app discovery failed: {exc}")
        if app_ids:
            adapter = LooxAdapter()
            site_with_www = "https://www.retro-stage.com"
            seen = set()
            for page in range(1, 10000):
                url = build_url(
                    f"https://loox.io/widget/{app_ids[0]}/reviews",
                    {"productId": seed_context.product_id, "page": page, "limit": 20, "sort_by": "photo"},
                )
                try:
                    payload = fetch_text(url, referer=seed_context.url, retries=2)
                except Exception as exc:
                    errors.append(f"{domain}: Retro Stage Loox page {page} failed: {exc}")
                    break
                batch = adapter._parse_embedded(payload)
                if not batch:
                    break
                for review in batch:
                    product_title = normalize_whitespace(review.extra.get("product_title"))
                    product_url = retro_stage_product_url_from_title(site_with_www, product_title)
                    if not product_title or not product_url:
                        continue
                    review.extra["product_title"] = product_title
                    review.extra["product_url"] = product_url
                    key = (review.review_id, review.image_url, product_url)
                    if key in seen:
                        continue
                    seen.add(key)
                    context = ProductContext(
                        url=product_url,
                        title=product_title,
                        brand="Retro Stage",
                        provider_hints="Loox product-box-attributed media",
                    )
                    rows.append(build_intake_row(context, review, fetched_at))
            rows = dedupe_rows(rows)
            output_csv, summary_json = output_paths(domain)
            write_intake_csv(rows, output_csv)
            product_summaries.append(
                {
                    "product_url": seed_context.url,
                    "product_title": seed_context.title,
                    "provider_hints": seed_context.provider_hints,
                    "adapter_used": "loox-product-box-title-to-product-page-url",
                    "matching_review_images": len(rows),
                    "product_index": 1,
                    "note": (
                        "Rows retained only when the Loox media card includes a product-box title; "
                        "product_page_url is reconstructed from that Retro Stage product title."
                    ),
                }
            )
            write_summary(
                summary_json,
                site=site_root,
                retailer=domain,
                rows=rows,
                output_csv=output_csv,
                started_at=started_at,
                finished_at=utc_now(),
                products_scanned=product_count,
                adapter="loox-product-box-title-to-product-page-url",
                product_summaries=product_summaries,
                errors=errors,
            )
            enrich_summary(summary_json, product_count, aggregate_used=False)
            return rows, {"output_csv": str(output_csv), "summary_json": str(summary_json), "rows": len(rows), "errors": errors}

    if product_contexts:
        aggregate_feed_used = True
        rows, product_summaries, errors = scrape_yotpo_aggregate_reviews(site_root, product_contexts, fetched_at)
        adapter = "yotpo-aggregate"
        if include_yotpo_product_pass:
            product_rows, product_pass_summaries, product_errors = scrape_yotpo_product_reviews(
                domain, product_contexts, fetched_at
            )
            rows.extend(product_rows)
            product_summaries.extend(product_pass_summaries)
            errors.extend(product_errors)
            adapter = "yotpo-aggregate; yotpo-product"
        rows = dedupe_rows(rows)
        output_csv, summary_json = output_paths(domain)
        write_intake_csv(rows, output_csv)
        write_summary(
            summary_json,
            site=site_root,
            retailer=domain,
            rows=rows,
            output_csv=output_csv,
            started_at=started_at,
            finished_at=utc_now(),
            products_scanned=product_count,
            adapter=adapter,
            product_summaries=product_summaries,
            errors=errors,
        )
        enrich_summary(summary_json, product_count, aggregate_used=aggregate_feed_used)
        if rows or not errors:
            return rows, {"output_csv": str(output_csv), "summary_json": str(summary_json), "rows": len(rows), "errors": errors}
        print(f"[{domain}] Yotpo discovery yielded 0 rows; falling back to full product-page provider scan", flush=True)
        product_urls = [context.url for context in product_contexts]
        product_count = len(product_urls)
        rows = []
        product_summaries = []
        product_contexts = []

    for index, product_ref in enumerate(product_contexts or product_urls, start=1):
        try:
            if isinstance(product_ref, ProductContext):
                product_url = product_ref.url
                context = product_ref
            else:
                product_url = product_ref
                context = hydrate_shopify_context(extract_product_context(product_url))
        except Exception as exc:
            errors.append(f"{product_url}: product context failed: {exc}")
            continue
        if not is_in_scope_product(context):
            product_summaries.append(
                {
                    "product_url": product_url,
                    "product_title": context.title,
                    "provider_hints": context.provider_hints,
                    "adapter_used": "skipped-out-of-scope",
                    "matching_review_images": 0,
                    "product_index": index,
                }
            )
            print(f"[{domain} {index}/{product_count}] {context.title or product_url} -> skipped out of scope", flush=True)
            continue
        is_loox_aggregate = bool(re.search(r"data-loox-aggregate", context.raw_html, re.I))
        product_reviews: List[ReviewImage] = []
        adapter_used = ""
        for adapter in adapter_order(context.provider_hints):
            try:
                product_reviews = adapter.scrape_product(context)
            except Exception as exc:
                errors.append(f"{product_url}: {adapter.name} failed: {exc}")
                product_reviews = []
            if product_reviews:
                adapter_used = adapter.name
                adapter_names.add(adapter.name)
                break
        product_rows = [build_intake_row(context, review, fetched_at) for review in product_reviews if review.image_url]
        rows.extend(product_rows)
        if adapter_used == "loox" and product_reviews and all("product_url" in review.extra and not review.extra.get("product_url") for review in product_reviews):
            is_loox_aggregate = True
        if is_loox_aggregate and adapter_used == "loox":
            adapter_used = "loox-aggregate-or-product"
        if adapter_used == "judgeme" and product_reviews and all(review.extra.get("feed_scope") == "aggregate" for review in product_reviews):
            adapter_used = "judgeme-aggregate-or-product"
        product_summaries.append(
            {
                "product_url": product_url,
                "product_title": context.title,
                "provider_hints": context.provider_hints,
                "adapter_used": adapter_used,
                "matching_review_images": len(product_rows),
                "product_index": index,
            }
        )
        print(f"[{domain} {index}/{product_count}] {context.title or product_url} -> {len(product_rows)} rows", flush=True)

    rows = dedupe_rows(rows)
    output_csv, summary_json = output_paths(domain)
    write_intake_csv(rows, output_csv)
    write_summary(
        summary_json,
        site=site_root,
        retailer=domain,
        rows=rows,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=utc_now(),
        products_scanned=product_count,
        adapter="; ".join(sorted(adapter_names)) or "none",
        product_summaries=product_summaries,
        errors=errors,
    )
    enrich_summary(summary_json, product_count, aggregate_used=aggregate_feed_used)
    return rows, {"output_csv": str(output_csv), "summary_json": str(summary_json), "rows": len(rows), "errors": errors}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape public P0 non-Amazon lead review-image rows into the Step 1 intake format. "
            "Uses only public product and review pages; restricted or unavailable pages are skipped."
        )
    )
    parser.add_argument("--triage-csv", type=Path, default=DEFAULT_TRIAGE_CSV)
    parser.add_argument("--domain", action="append", dest="domains", help="Domain to scrape. May be repeated.")
    parser.add_argument("--safe-first", action="store_true", help="Scrape the safe first P0 batch from the implementation plan.")
    parser.add_argument(
        "--only-seed-products",
        action="store_true",
        help="Smoke-test mode: only scrape product URLs from the triage CSV. Outputs are marked seed_scrape_only.",
    )
    parser.add_argument(
        "--allow-incomplete-seed-scrape",
        action="store_true",
        help="Required with --only-seed-products to acknowledge the output is not a full catalog scrape.",
    )
    parser.add_argument(
        "--skip-yotpo-product-pass",
        action="store_true",
        help="Skip the default public product-specific Yotpo endpoint pass after aggregate scraping.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.only_seed_products and not args.allow_incomplete_seed_scrape:
        raise SystemExit(
            "--only-seed-products is smoke-test mode and does not scan the full catalog. "
            "Use full discovery for production scrapes, or add --allow-incomplete-seed-scrape deliberately."
        )
    domains = args.domains or (SAFE_FIRST_DOMAINS if args.safe_first else [])
    if not domains:
        raise SystemExit("Provide --domain at least once or use --safe-first.")
    leads = read_leads(args.triage_csv, domains)
    if not leads:
        raise SystemExit(f"No scrape-now lead URLs found in {args.triage_csv}")

    overall: Dict[str, object] = {}
    exit_code = 0
    for domain in domains:
        seed_urls = leads.get(domain, [])
        if not seed_urls:
            print(f"Skipping {domain}: no seed URLs", flush=True)
            continue
        try:
            _, summary = scrape_domain(
                domain,
                seed_urls,
                only_seed_products=args.only_seed_products,
                include_yotpo_product_pass=not args.skip_yotpo_product_pass,
            )
            overall[domain] = summary
        except Exception as exc:
            print(f"ERROR {domain}: {exc}", file=sys.stderr, flush=True)
            overall[domain] = {"error": str(exc)}
            exit_code = 1
    print(json.dumps(overall, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
