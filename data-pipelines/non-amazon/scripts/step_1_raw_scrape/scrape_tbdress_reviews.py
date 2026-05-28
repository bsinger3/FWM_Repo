#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from step1_intake_utils import output_paths, write_intake_csv, utc_now, validate_rows


SITE = "https://www.tbdress.com"
RETAILER = "tbdress_com"
TRIAGE_CATEGORY_URL = f"{SITE}/factory/132"
SOVRN_DOMAIN = "cart.tbdress.com"
RELATED_DOMAINS = ["cart.tbdress.com", "m.tbdress.com", "tbdress.com", "www.tbdress.com"]
BLOCKING_STATUS_CODES = {401, 403, 407, 429, 503}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
BLOCK_BODY_RE = re.compile(r"\b(?:captcha|access denied|forbidden|too many requests|datadome|akamai|cloudflare)\b", re.I)
LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
IMG_RE = re.compile(r"<img\b[^>]*>", re.I | re.S)
ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*(["\'])(.*?)\2', re.I | re.S)


@dataclass
class PublicPage:
    url: str
    final_url: str
    content_type: str = ""
    bytes: int = 0
    links: List[str] = field(default_factory=list)
    images: List[Dict[str, str]] = field(default_factory=list)
    product_like_links: int = 0
    review_hints: int = 0
    notes: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TB Dress public surface preflight and zero-row intake output.")
    parser.add_argument("--sleep", type=float, default=0.05, help="Sleep between public requests.")
    return parser.parse_args()


def parse_attrs(tag: str) -> Dict[str, str]:
    return {match.group(1).lower(): match.group(3) for match in ATTR_RE.finditer(tag)}


def curl_fetch_text(url: str, *, referer: str = SITE, retries: int = 2) -> Tuple[str, Dict[str, str], str]:
    last_error = ""
    for attempt in range(retries):
        cmd = [
            "curl.exe",
            "-L",
            "-sS",
            "--fail-with-body",
            "--max-time",
            "45",
            "-w",
            "\n__FINAL_URL__:%{url_effective}",
            "-D",
            "-",
            "-A",
            USER_AGENT,
            "-H",
            "Accept: text/html,application/xml,text/plain,*/*",
            "-H",
            "Accept-Language: en-US,en;q=0.9",
        ]
        if referer:
            cmd.extend(["-e", referer])
        cmd.append(url)
        result = subprocess.run(
            cmd,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode == 0:
            payload, _, final_marker = result.stdout.rpartition("\n__FINAL_URL__:")
            final_url = final_marker.strip() or url
            header_text, _, body = payload.partition("\r\n\r\n")
            if not body:
                header_text, _, body = payload.partition("\n\n")
            if BLOCK_BODY_RE.search(body[:2500]):
                raise RuntimeError(f"blocked_or_challenge_body url={url}")
            headers: Dict[str, str] = {}
            for line in header_text.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            return body, headers, final_url
        last_error = result.stderr or result.stdout
        if any(f" {code}" in last_error or f"error: {code}" in last_error.lower() for code in BLOCKING_STATUS_CODES):
            raise RuntimeError(f"blocked_or_rate_limited_fetch url={url} detail={last_error.strip()}")
        time.sleep(min(2**attempt, 4))
    raise RuntimeError(f"fetch_failed url={url} detail={last_error.strip()}")


def resolve_domains() -> List[Dict[str, object]]:
    results = []
    for domain in RELATED_DOMAINS:
        try:
            addresses = sorted({item[-1][0] for item in socket.getaddrinfo(domain, 443)})
            results.append({"domain": domain, "resolves": True, "addresses": addresses[:5]})
        except socket.gaierror as exc:
            results.append({"domain": domain, "resolves": False, "error": str(exc)})
    return results


def absolute_url(value: str, base: str = SITE) -> str:
    return urljoin(base, value.strip()).rstrip("/")


def inspect_page(url: str, *, referer: str = SITE) -> PublicPage:
    html_text, headers, final_url = curl_fetch_text(url, referer=referer)
    links = sorted({absolute_url(match.group(1), final_url) for match in LINK_RE.finditer(html_text)})
    images = []
    for tag_match in IMG_RE.finditer(html_text):
        attrs = parse_attrs(tag_match.group(0))
        src = attrs.get("src") or attrs.get("data-src") or ""
        if not src:
            continue
        images.append(
            {
                "src": absolute_url(src, final_url),
                "alt": attrs.get("alt", ""),
                "class": attrs.get("class", ""),
            }
        )
    product_like_links = sum(1 for link in links if re.search(r"/(?:product|products|item|dress|review)s?/", link, re.I))
    review_hints = len(re.findall(r"\breviews?\b|rating|customer\s+photo", html_text, re.I))
    notes = "factory-directory page"
    if "/factory/" in urlparse(final_url).path:
        notes = "factory detail page; public image is a factory/company logo, not apparel product/model media"
    elif urlparse(final_url).path in {"", "/"}:
        notes = "homepage factory directory; public images are factory/company logos"
    return PublicPage(
        url=url,
        final_url=final_url,
        content_type=headers.get("content-type", ""),
        bytes=len(html_text.encode("utf-8", errors="replace")),
        links=links,
        images=images,
        product_like_links=product_like_links,
        review_hints=review_hints,
        notes=notes,
    )


def discover_public_pages(args: argparse.Namespace) -> Tuple[List[PublicPage], List[str]]:
    pages: List[PublicPage] = []
    errors: List[str] = []
    seed_urls = [SITE, TRIAGE_CATEGORY_URL]
    seen = set()
    for url in seed_urls:
        if url in seen:
            continue
        seen.add(url)
        page = inspect_page(url)
        pages.append(page)
        if args.sleep:
            time.sleep(args.sleep)
    factory_links = []
    for page in pages:
        factory_links.extend(link for link in page.links if urlparse(link).netloc == "www.tbdress.com" and "/factory/" in urlparse(link).path)
    for link in sorted(set(factory_links)):
        if link in seen:
            continue
        seen.add(link)
        try:
            pages.append(inspect_page(link))
        except RuntimeError as exc:
            errors.append(str(exc))
        if args.sleep:
            time.sleep(args.sleep)
    return pages, errors


def write_summary(
    summary_json,
    *,
    output_csv,
    started_at: str,
    finished_at: str,
    pages: Sequence[PublicPage],
    domain_resolution: Sequence[Dict[str, object]],
    errors: Sequence[str],
) -> None:
    rows: List[Dict[str, str]] = []
    page_summaries = [
        {
            "url": page.url,
            "final_url": page.final_url,
            "content_type": page.content_type,
            "bytes": page.bytes,
            "links": len(page.links),
            "images": len(page.images),
            "product_like_links": page.product_like_links,
            "review_hints": page.review_hints,
            "notes": page.notes,
            "sample_images": page.images[:5],
        }
        for page in pages
    ]
    summary = {
        "site": SITE,
        "retailer": RETAILER,
        "adapter": "public_domain_preflight_no_product_review_surface",
        "provider_identified": (
            "No public apparel PDP/review implementation found. Sovrn domain cart.tbdress.com did not resolve; "
            "tbdress.com redirected to www.tbdress.com, currently a WordPress factory directory. "
            "Public images are factory/company logos, not customer review or catalog model images."
        ),
        "output_csv": str(output_csv),
        "started_at": started_at,
        "finished_at": finished_at,
        "product_sources": {
            "triage_category_url": TRIAGE_CATEGORY_URL,
            "sovrn_domain": SOVRN_DOMAIN,
            "domain_resolution": list(domain_resolution),
            "public_pages_scanned": page_summaries,
        },
        "products_discovered": 0,
        "products_scanned": 0,
        "review_pages_scanned": 0,
        "factory_pages_scanned": sum(1 for page in pages if "/factory/" in urlparse(page.final_url).path),
        "usable_media_source": "",
        "stop_reason": "no_public_product_or_review_surface",
        "errors": list(errors),
        "access_policy": "public TB Dress domain/category/factory pages only; unauthorized WordPress REST endpoints were not used; stop on 429/captcha/WAF/auth behavior.",
        "sovrn_triage_source": {
            "source_file": "data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv",
            "status": "first-pass candidate",
            "payout_model": "CPC",
            "provider": "unknown",
            "reviews_present": "yes",
            "photo_reviews": "yes",
            "shipping": "US",
            "payout_note": "CPC amount not populated",
            "merchant_domain": SOVRN_DOMAIN,
            "category_evidence_url": TRIAGE_CATEGORY_URL,
        },
    }
    summary.update(validate_rows(rows))
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    started_at = utc_now()
    output_csv, summary_json = output_paths(RETAILER)
    rows: List[Dict[str, str]] = []
    errors: List[str] = []
    domain_resolution = resolve_domains()
    pages: List[PublicPage] = []
    try:
        pages, page_errors = discover_public_pages(args)
        errors.extend(page_errors)
    except RuntimeError as exc:
        errors.append(str(exc))
    write_intake_csv(rows, output_csv)
    write_summary(
        summary_json,
        output_csv=output_csv,
        started_at=started_at,
        finished_at=utc_now(),
        pages=pages,
        domain_resolution=domain_resolution,
        errors=errors,
    )
    print(str(output_csv))
    print(str(summary_json))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
