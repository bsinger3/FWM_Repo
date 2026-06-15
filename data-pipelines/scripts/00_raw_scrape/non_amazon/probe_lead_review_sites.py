#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
import json
import re
import socket
import ssl
import sys
from pathlib import Path

PIPELINE_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, legacy_raw_run_dir, raw_scraped_data_root, reports_root  # noqa: E402
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECTS_ROOT = REPO_ROOT.parent
DATA_ROOT = PROJECTS_ROOT / "FWM_Data"
DEFAULT_LEADS_CSV = archive_root() / "deprecated_scrape_runs" / "legacy_top_level_2026-06-15" / "WebLeads" / "leads.csv"
DEFAULT_OUTPUT_ROOT = reports_root() / "lead_runs"
LOCAL_DATA_ROOT = raw_scraped_data_root()
DEFAULT_MERCHANT_SUMMARY_CSV = reports_root() / "non_amazon_merchant_scrape_summary.csv"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
MAX_HTML_BYTES = 2_500_000
FETCH_TIMEOUT_SECONDS = 20


REPORT_COLUMNS = [
    "lead_row_number",
    "merchant_domain",
    "normalized_url",
    "original_url",
    "column_3_note",
    "has_existing_local_data",
    "existing_local_data_paths",
    "existing_scrape_rows",
    "existing_distinct_image_urls",
    "existing_dataset_kind",
    "existing_data_coverage",
    "probe_status",
    "http_status",
    "final_url",
    "page_title",
    "estimated_total_reviews_visible",
    "image_reviews_found_in_fast_probe",
    "size_data_status",
    "measurement_data_status",
    "review_platform_provider",
    "scrape_at_scale_difficulty",
    "scale_notes",
    "recommended_next_action",
    "out_of_scope_reason",
]


PROVIDER_PATTERNS = [
    ("Judge.me", [r"judge\.me", r"jdgm-", r"judgeme_product_reviews"]),
    ("Loox", [r"loox", r"looxReviews", r"loox-rating"]),
    ("Stamped", [r"stamped\.io", r"stamped-main-widget", r"data-widget-style"]),
    ("TurnTo", [r"turnto\.com", r"tt-teaser", r"TurnToCmd"]),
    ("Bazaarvoice", [r"bazaarvoice", r"bvseo", r"bv_reviews", r"api\.bazaarvoice\.com"]),
    ("PowerReviews", [r"powerreviews", r"pr-review", r"ui.powerreviews.com"]),
    ("Yotpo", [r"yotpo", r"staticw2\.yotpo\.com"]),
    ("Okendo", [r"okendo", r"okeReviews", r"oke-widget"]),
    ("Reviews.io", [r"reviews\.io", r"widget.reviews.co.uk", r"ruk_rating_snippet"]),
    ("Shopify Product Reviews", [r"shopify-product-reviews", r"spr-container", r"Product Reviews Addon"]),
    ("Custom/embedded reviews", [r"review-list", r"customerReviews", r"reviewSubmissionTime", r"review-thumbnail"]),
]


STRUCTURED_SIZE_PATTERNS = [
    r'"(?:size|variantSize|selectedSize|fitSize|productSize)"\s*:\s*"[^"]+"',
    r"(?:data-size|data-review-size|data-selected-size)=['\"][^'\"]+",
    r"\b(?:Size Ordered|Purchased size|Size purchased|Usual size|Fit:)\b",
]

COMMENT_SIZE_PATTERNS = [
    r"\b(?:ordered|wear|wearing|bought|purchased|got|size)\s+(?:a\s+)?(?:size\s+)?(?:xxs|xs|small|medium|large|xl|xxl|[1-6]x|\d{1,2}[A-Z]?)\b",
    r"\b(?:I'm|I am|im|i’m).{0,60}\b(?:xxs|xs|small|medium|large|xl|xxl|[1-6]x)\b",
    r"\b(?:28|30|32|34|36|38|40|42|44|46|48|50|52|54)\s*(?:A|B|C|D|DD|DDD|E|F|G|H|I|J|K)\b",
]

STRUCTURED_MEASUREMENT_PATTERNS = [
    r'"(?:bodyMetrics|body_metrics|fitProfile|reviewerMeasurements|customerMeasurements|measurements)"\s*:',
    r'"(?:reviewerHeight|reviewerWeight|reviewerWaist|reviewerHips|reviewerBust)"\s*:',
    r"(?:data-height|data-weight|data-waist|data-hips|data-bust)=['\"][^'\"]+",
    r"\b(?:Customer|Reviewer|Body)\s+(?:Height|Weight|Waist|Hips|Bust)\s*:\s*(?:\d|[45]'|[45] ft)",
]

COMMENT_MEASUREMENT_PATTERNS = [
    r"\b[45]\s*(?:ft|feet|foot|['’])\s*\d{0,2}\s*(?:in|inches|[\"”])?\b",
    r"\b\d{2,3}\s*(?:lbs?|pounds?)\b",
    r"\b\d{2,3}\s*(?:\"|in(?:ches)?)?\s*(?:waist|hips?|bust)\b",
    r"\b\d{2,3}\s*/\s*\d{2,3}\s*/\s*\d{2,3}\b",
]

REVIEW_COUNT_PATTERNS = [
    r'"reviewCount"\s*:\s*"?([0-9][0-9,]*)"?',
    r'"ratingCount"\s*:\s*"?([0-9][0-9,]*)"?',
    r'"totalReviewCount"\s*:\s*([0-9][0-9,]*)',
    r'"review_count"\s*:\s*([0-9][0-9,]*)',
    r'"reviews_count"\s*:\s*([0-9][0-9,]*)',
    r'"total_reviews"\s*:\s*([0-9][0-9,]*)',
    r"data-number-of-product-reviews=['\"]([0-9][0-9,]*)['\"]",
    r"data-review-count=['\"]([0-9][0-9,]*)['\"]",
    r"([0-9][0-9,]*)\s+(?:customer\s+)?reviews?\b",
]

IMAGE_REVIEW_PATTERNS = [
    r"review[^\"'<>]{0,80}(?:image|photo|media)",
    r"(?:image|photo|media)[^\"'<>]{0,80}review",
    r"review-thumbnail",
    r"jdgm-rev__pic",
    r"loox-photo",
    r"stamped-review-image",
    r"bv-content-media",
    r"pr-media",
    r"yotpo-review-media",
    r"oke-reviewContent-media",
]

OUT_OF_SCOPE_DOMAIN_TERMS = {
    "danielwellington": "watches/jewelry",
    "isabellegracejewelry": "jewelry",
    "barse": "jewelry",
    "glasseslit": "eyewear",
    "halloweencostumes": "costumes",
}

OUT_OF_SCOPE_PAGE_TERMS = [
    ("watch", "watches/jewelry"),
    ("jewelry", "jewelry"),
    ("necklace", "jewelry"),
    ("earring", "jewelry"),
    ("bracelet", "jewelry"),
    ("ring", "jewelry"),
    ("sunglasses", "eyewear"),
    ("eyeglasses", "eyewear"),
    ("shoes", "shoes/accessories"),
    ("sneaker", "shoes/accessories"),
    ("boots", "shoes/accessories"),
    ("costume", "costumes"),
]

CLOTHING_SCOPE_TERMS = [
    "bra",
    "bralette",
    "bikini",
    "bodysuit",
    "bottom",
    "camisole",
    "dress",
    "jean",
    "jumpsuit",
    "legging",
    "lingerie",
    "pant",
    "shirt",
    "shapewear",
    "short",
    "skirt",
    "swimsuit",
    "swimwear",
    "top",
    "trouser",
    "underwear",
    "women",
    "womens",
    "women's",
]

EXISTING_DATA_ALIASES = {
    "victoriassecret.com": ["vs"],
    "urbanoutfitters.com": ["urban_outfitters"],
    "universalstandard.com": ["universal_standard"],
    "missme.com": ["miss_me_jeans"],
    "babyboofashion.com": ["babyboo"],
    "thehalara.com": ["halara"],
    "oglmove.com": ["oglmove"],
    "prana.com": [],
    "rei.com": ["rei"],
    "ta3swim.com": ["ta3swim"],
}


@dataclass(frozen=True)
class Lead:
    row_number: int
    original_url: str
    normalized_url: str
    merchant_domain: str
    note: str


@dataclass
class FetchResult:
    status: str
    http_status: str = ""
    final_url: str = ""
    html: str = ""
    error: str = ""


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"^www\.", "", value)
    value = re.sub(r"\.(com|co|net|org|us|uk|au|ca)$", "", value)
    value = value.replace("-", "_")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_")


def normalize_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if not re.match(r"https?://", value, re.I):
        value = f"https://{value}"
    return value


def merchant_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower().split("@")[-1].split(":")[0].removeprefix("www.")


def read_leads(path: Path) -> List[Lead]:
    leads: List[Lead] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        next(reader, None)
        for row_number, row in enumerate(reader, start=2):
            if not row or not (row[0] or "").strip():
                continue
            original = row[0].strip()
            normalized = normalize_url(original)
            leads.append(
                Lead(
                    row_number=row_number,
                    original_url=original,
                    normalized_url=normalized,
                    merchant_domain=merchant_domain(normalized),
                    note=(row[2].strip() if len(row) > 2 else ""),
                )
            )
    return leads


def existing_data_index(data_root: Path) -> Dict[str, List[Path]]:
    index: Dict[str, List[Path]] = {}
    if not data_root.exists():
        return index
    for child in data_root.iterdir():
        if not child.is_dir() or child.name.startswith("_"):
            continue
        index.setdefault(slugify(child.name), []).append(child)
    return index


def existing_paths_for_domain(domain: str, index: Dict[str, List[Path]]) -> List[Path]:
    candidates = {slugify(domain)}
    parts = domain.split(".")
    if parts:
        candidates.add(slugify(parts[0]))
    for alias in EXISTING_DATA_ALIASES.get(domain, []):
        candidates.add(slugify(alias))
    paths: List[Path] = []
    for candidate in candidates:
        paths.extend(index.get(candidate, []))
    return sorted(set(paths))


def merchant_report_keys(domain: str) -> List[str]:
    keys = {slugify(domain), slugify(domain.split(".")[0])}
    for alias in EXISTING_DATA_ALIASES.get(domain, []):
        keys.add(slugify(alias))
    return sorted(keys)


def read_existing_scrape_stats(path: Path) -> Dict[str, Dict[str, str]]:
    stats: Dict[str, Dict[str, str]] = {}
    if not path.exists():
        return stats
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            merchant = slugify(row.get("merchant", ""))
            if merchant:
                stats[merchant] = row
    return stats


def existing_stats_for_domain(domain: str, stats_index: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    for key in merchant_report_keys(domain):
        if key in stats_index:
            return stats_index[key]
    return {}


def int_value(value: object) -> int:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return 0


def existing_data_coverage(
    stats: Dict[str, str],
    existing_paths: Sequence[Path],
    min_rows_to_defer: int,
    min_images_to_defer: int,
) -> str:
    if not existing_paths and not stats:
        return "none"
    rows = int_value(stats.get("rows_scraped"))
    images = int_value(stats.get("distinct_image_urls"))
    if rows >= min_rows_to_defer and images >= min_images_to_defer:
        return "sufficient"
    if rows > 0 or images > 0:
        return "thin"
    return "unknown"


def fetch_url(url: str) -> FetchResult:
    urls = [url]
    if url.startswith("https://"):
        urls.append("http://" + url[len("https://") :])
    last_error = ""
    for candidate in urls:
        req = Request(
            candidate,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        try:
            with urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
                content_type = resp.headers.get("content-type", "")
                raw = resp.read(MAX_HTML_BYTES)
                encoding = "utf-8"
                match = re.search(r"charset=([^;\s]+)", content_type, re.I)
                if match:
                    encoding = match.group(1)
                return FetchResult(
                    status="fetched",
                    http_status=str(resp.status),
                    final_url=resp.geturl(),
                    html=raw.decode(encoding, errors="replace"),
                )
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code in {401, 403, 407, 429, 451, 503}:
                return FetchResult(status="blocked", http_status=str(exc.code), error=last_error)
        except (URLError, socket.timeout, ssl.SSLError, TimeoutError) as exc:
            last_error = str(exc.reason if isinstance(exc, URLError) else exc)
    return FetchResult(status="fetch_failed", error=last_error)


def text_matches_any(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, re.I | re.S) for pattern in patterns)


def page_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not match:
        return ""
    return normalize_space(strip_tags(match.group(1)))[:250]


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", unescape(value or ""))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def detect_provider(html: str) -> str:
    found = []
    for name, patterns in PROVIDER_PATTERNS:
        if text_matches_any(html, patterns):
            found.append(name)
    return "; ".join(found) if found else "unknown"


def estimate_review_count(html: str) -> str:
    counts = []
    for pattern in REVIEW_COUNT_PATTERNS:
        for match in re.finditer(pattern, html, re.I):
            try:
                value = int(match.group(1).replace(",", ""))
            except ValueError:
                continue
            if 0 < value < 10_000_000:
                counts.append(value)
    return str(max(counts)) if counts else ""


def count_image_review_hints(html: str) -> str:
    total = 0
    for pattern in IMAGE_REVIEW_PATTERNS:
        total += len(re.findall(pattern, html, re.I))
    # This is a fast-probe hint count, not a deduped production row count.
    return str(total)


def data_status(html: str, structured_patterns: Sequence[str], comment_patterns: Sequence[str]) -> str:
    if text_matches_any(html, structured_patterns):
        return "structured"
    if text_matches_any(strip_tags(html), comment_patterns):
        return "comment-only"
    return "absent_or_unclear"


def out_of_scope_reason(lead: Lead, title: str, html: str) -> str:
    domain_key = lead.merchant_domain.split(".")[0].lower()
    for term, reason in OUT_OF_SCOPE_DOMAIN_TERMS.items():
        if term in domain_key:
            return reason
    parsed = urlparse(lead.normalized_url)
    path_text = unescape(parsed.path or "").replace("-", " ").replace("_", " ")
    page_text = f"{lead.original_url} {title}".lower()
    if any(re.search(rf"\b{re.escape(term)}\b", page_text) for term in CLOTHING_SCOPE_TERMS):
        return ""
    # Bare domains often mention many departments in navigation. Only mark them
    # out of scope from page terms when the URL/title itself is specific enough.
    if not path_text.strip("/") and not title:
        return ""
    haystack = f"{path_text} {title}".lower()
    for term, reason in OUT_OF_SCOPE_PAGE_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", haystack):
            return reason
    return ""


def has_cupshe_model_exception(lead: Lead) -> bool:
    return lead.merchant_domain == "cupshe.com" and "model" in lead.note.lower()


def difficulty_and_notes(
    lead: Lead,
    fetch: FetchResult,
    provider: str,
    review_count: str,
    image_hints: str,
    existing_paths: Sequence[Path],
    existing_stats: Dict[str, str],
    coverage: str,
    html: str,
) -> Tuple[str, str, str]:
    notes: List[str] = []
    recommended = "manual inspect"

    if coverage == "sufficient":
        notes.append(
            "Existing scraped data appears sufficient "
            f"({existing_stats.get('rows_scraped', '0')} rows, "
            f"{existing_stats.get('distinct_image_urls', '0')} distinct image URLs); defer refresh until after thinner merchants."
        )
        recommended = "defer existing data"
    elif coverage == "thin":
        notes.append(
            "Existing local data is thin "
            f"({existing_stats.get('rows_scraped', '0')} rows, "
            f"{existing_stats.get('distinct_image_urls') or '0'} distinct image URLs); keep eligible for scraping."
        )
    elif coverage == "unknown" and existing_paths:
        notes.append("Local folder exists, but confirmed scrape volume is unknown/empty; do not auto-defer.")

    if fetch.status == "blocked":
        notes.append(f"Fetch blocked or rate-limited ({fetch.error or fetch.http_status}).")
        return "blocked", "; ".join(notes), recommended if coverage == "sufficient" else "blocked"
    if fetch.status != "fetched":
        notes.append(f"Fetch failed: {fetch.error or 'unknown error'}.")
        return "high", "; ".join(notes), recommended if coverage == "sufficient" else "manual inspect"

    lower = html.lower()
    challenge_title = re.search(r"<title[^>]*>[^<]*(?:captcha|challenge|access denied|forbidden)[^<]*</title>", html, re.I)
    hard_security = any(token in lower for token in ("access denied", "perimeterx", "datadome", "akamai bot"))
    cloudflare_block = "cloudflare" in lower and any(token in lower for token in ("attention required", "checking your browser"))
    captcha_block = "captcha" in lower and any(token in lower for token in ("verify you are human", "are you a human"))
    if challenge_title or hard_security or cloudflare_block or captcha_block:
        notes.append("Bot/security challenge indicators found in fetched HTML.")
        return "blocked", "; ".join(notes), "blocked"
    if "enable javascript" in lower or "javascript is disabled" in lower:
        notes.append("HTML suggests JavaScript rendering may be required.")

    if provider != "unknown":
        notes.append(f"Detected review provider: {provider}.")
    else:
        notes.append("No known review provider detected in initial HTML.")

    if review_count:
        notes.append(f"Visible review-count hint: {review_count}.")
    else:
        notes.append("No reliable review-count hint found.")

    try:
        image_count = int(image_hints or "0")
    except ValueError:
        image_count = 0
    if image_count:
        notes.append(f"Review-image/media hints in probe HTML: {image_count}.")
    else:
        notes.append("No review-image/media hints found in initial HTML.")

    if has_cupshe_model_exception(lead):
        notes.append("Cupshe exception: prioritize model images and model measurements from product pages.")
        if recommended != "defer existing data":
            recommended = "build adapter"
        return "medium", "; ".join(notes), recommended

    if provider in {"unknown", "Custom/embedded reviews"}:
        difficulty = "medium" if review_count or image_count else "high"
        if recommended != "defer existing data":
            recommended = "manual inspect" if difficulty == "high" else "build adapter"
    elif "Bazaarvoice" in provider or "PowerReviews" in provider:
        difficulty = "medium"
        if recommended != "defer existing data":
            recommended = "build adapter"
        notes.append("Provider usually supports public endpoints, but product/client IDs need discovery.")
    elif "Judge.me" in provider or "Stamped" in provider or "TurnTo" in provider or "Loox" in provider:
        difficulty = "low" if image_count or review_count else "medium"
        if recommended != "defer existing data":
            recommended = "scrape now" if difficulty == "low" else "build adapter"
    else:
        difficulty = "medium"
        if recommended != "defer existing data":
            recommended = "build adapter"

    if "shopify" in lower:
        notes.append("Shopify signals found; product JSON, sitemaps, or app widgets may help scale.")
    if re.search(r"(next_data|__next_data__|window\.__|hydration|__NUXT__)", html, re.I):
        notes.append("Hydrated page JSON likely available for endpoint discovery.")

    return difficulty, "; ".join(notes), recommended


def probe_lead(
    lead: Lead,
    existing_index: Dict[str, List[Path]],
    existing_stats_index: Dict[str, Dict[str, str]],
    min_existing_rows_to_defer: int,
    min_existing_images_to_defer: int,
) -> Dict[str, str]:
    existing_paths = existing_paths_for_domain(lead.merchant_domain, existing_index)
    existing_stats = existing_stats_for_domain(lead.merchant_domain, existing_stats_index)
    coverage = existing_data_coverage(
        existing_stats,
        existing_paths,
        min_existing_rows_to_defer,
        min_existing_images_to_defer,
    )
    fetch = fetch_url(lead.normalized_url)
    html = fetch.html
    title = page_title(html)
    provider = detect_provider(html) if html else "unknown"
    review_count = estimate_review_count(html) if html else ""
    image_hints = count_image_review_hints(html) if html else "0"
    size_status = data_status(html, STRUCTURED_SIZE_PATTERNS, COMMENT_SIZE_PATTERNS) if html else "unclear"
    measurement_status = (
        data_status(html, STRUCTURED_MEASUREMENT_PATTERNS, COMMENT_MEASUREMENT_PATTERNS) if html else "unclear"
    )
    scope_reason = out_of_scope_reason(lead, title, html)
    difficulty, notes, recommended = difficulty_and_notes(
        lead, fetch, provider, review_count, image_hints, existing_paths, existing_stats, coverage, html
    )
    probe_status = fetch.status

    if scope_reason and not has_cupshe_model_exception(lead):
        recommended = "out of scope"
        if fetch.status == "fetched":
            probe_status = "out_of_scope"
        notes = f"Out of scope: {scope_reason}. {notes}".strip()

    if has_cupshe_model_exception(lead):
        provider = f"{provider}; product-page model-image exception" if provider != "unknown" else "product-page model-image exception"

    return {
        "lead_row_number": str(lead.row_number),
        "merchant_domain": lead.merchant_domain,
        "normalized_url": lead.normalized_url,
        "original_url": lead.original_url,
        "column_3_note": lead.note,
        "has_existing_local_data": "yes" if existing_paths else "no",
        "existing_local_data_paths": " | ".join(str(path) for path in existing_paths),
        "existing_scrape_rows": existing_stats.get("rows_scraped", ""),
        "existing_distinct_image_urls": existing_stats.get("distinct_image_urls", ""),
        "existing_dataset_kind": existing_stats.get("dataset_kind", ""),
        "existing_data_coverage": coverage,
        "probe_status": probe_status,
        "http_status": fetch.http_status,
        "final_url": fetch.final_url,
        "page_title": title,
        "estimated_total_reviews_visible": review_count,
        "image_reviews_found_in_fast_probe": image_hints,
        "size_data_status": size_status,
        "measurement_data_status": measurement_status,
        "review_platform_provider": provider,
        "scrape_at_scale_difficulty": difficulty,
        "scale_notes": notes,
        "recommended_next_action": recommended,
        "out_of_scope_reason": scope_reason,
    }


def write_csv(path: Path, rows: Sequence[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_markdown(path: Path, payload: Dict[str, object], rows: Sequence[Dict[str, str]]) -> None:
    counts = payload["counts"]
    lines = [
        "# Lead Review Site Fast Probe Report",
        "",
        f"- Started: `{payload['started_at']}`",
        f"- Finished: `{payload['finished_at']}`",
        f"- Lead rows: `{payload['lead_rows']}`",
        f"- Unique merchant domains: `{payload['unique_merchant_domains']}`",
        f"- Rows with existing local data: `{counts.get('existing_local_data_rows', 0)}`",
        f"- Rows with sufficient existing scrape data: `{counts.get('sufficient_existing_data_rows', 0)}`",
        f"- Rows with thin or unknown existing scrape data: `{counts.get('thin_or_unknown_existing_data_rows', 0)}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in sorted(counts.get("probe_status", {}).items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Recommended Actions", ""])
    for key, value in sorted(counts.get("recommended_next_action", {}).items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Difficulty", ""])
    for key, value in sorted(counts.get("scrape_at_scale_difficulty", {}).items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Highest-Signal Rows", ""])
    preview = sorted(
        rows,
        key=lambda row: (
            row["recommended_next_action"] not in {"scrape now", "build adapter"},
            row["scrape_at_scale_difficulty"],
            row["existing_data_coverage"] == "sufficient",
            row["merchant_domain"],
        ),
    )[:40]
    lines.append(
        "| Domain | Action | Difficulty | Existing data | Reviews | Image hints | Size | Measurements | Provider | Notes |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---|---|---|---|")
    for row in preview:
        lines.append(
            "| {domain} | {action} | {difficulty} | {existing} | {reviews} | {images} | {size} | {measurements} | {provider} | {notes} |".format(
                domain=md_cell(row["merchant_domain"]),
                action=md_cell(row["recommended_next_action"]),
                difficulty=md_cell(row["scrape_at_scale_difficulty"]),
                existing=md_cell(
                    "{coverage} ({rows} rows/{images} images)".format(
                        coverage=row.get("existing_data_coverage", ""),
                        rows=row.get("existing_scrape_rows", "") or "0",
                        images=row.get("existing_distinct_image_urls", "") or "0",
                    )
                ),
                reviews=md_cell(row["estimated_total_reviews_visible"]),
                images=md_cell(row["image_reviews_found_in_fast_probe"]),
                size=md_cell(row["size_data_status"]),
                measurements=md_cell(row["measurement_data_status"]),
                provider=md_cell(row["review_platform_provider"]),
                notes=md_cell(row["scale_notes"][:260]),
            )
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def md_cell(value: str) -> str:
    value = normalize_space(value)
    return value.replace("|", "\\|") or " "


def count_by(rows: Sequence[Dict[str, str]], field: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        key = row.get(field) or "blank"
        counts[key] = counts.get(key, 0) + 1
    return counts


def build_summary(
    rows: Sequence[Dict[str, str]],
    leads: Sequence[Lead],
    started_at: str,
    finished_at: str,
    csv_path: Path,
    json_path: Path,
    md_path: Path,
) -> Dict[str, object]:
    return {
        "site": "lead review fast probe",
        "scope": "women's clothing review-image scrape triage",
        "started_at": started_at,
        "finished_at": finished_at,
        "lead_rows": len(leads),
        "unique_merchant_domains": len({lead.merchant_domain for lead in leads}),
        "output_csv": str(csv_path),
        "output_json": str(json_path),
        "output_markdown": str(md_path),
        "counts": {
            "probe_status": count_by(rows, "probe_status"),
            "recommended_next_action": count_by(rows, "recommended_next_action"),
            "scrape_at_scale_difficulty": count_by(rows, "scrape_at_scale_difficulty"),
            "review_platform_provider": count_by(rows, "review_platform_provider"),
            "size_data_status": count_by(rows, "size_data_status"),
            "measurement_data_status": count_by(rows, "measurement_data_status"),
            "existing_local_data_rows": sum(1 for row in rows if row["has_existing_local_data"] == "yes"),
            "existing_data_coverage": count_by(rows, "existing_data_coverage"),
            "sufficient_existing_data_rows": sum(1 for row in rows if row["existing_data_coverage"] == "sufficient"),
            "thin_or_unknown_existing_data_rows": sum(
                1 for row in rows if row["existing_data_coverage"] in {"thin", "unknown"}
            ),
        },
    }


def run(args: argparse.Namespace) -> int:
    leads = read_leads(args.leads_csv)
    if args.limit:
        leads = leads[: args.limit]

    output_dir = args.output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "lead_review_fast_probe_report.csv"
    json_path = output_dir / "lead_review_fast_probe_summary.json"
    md_path = output_dir / "lead_review_fast_probe_report.md"

    existing_index = existing_data_index(args.local_data_root)
    existing_stats_index = read_existing_scrape_stats(args.merchant_summary_csv)
    started_at = utc_stamp()
    rows: List[Dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                probe_lead,
                lead,
                existing_index,
                existing_stats_index,
                args.min_existing_rows_to_defer,
                args.min_existing_images_to_defer,
            ): lead
            for lead in leads
        }
        completed = 0
        for future in as_completed(futures):
            lead = futures[future]
            completed += 1
            try:
                rows.append(future.result())
            except Exception as exc:
                rows.append(
                    {
                        "lead_row_number": str(lead.row_number),
                        "merchant_domain": lead.merchant_domain,
                        "normalized_url": lead.normalized_url,
                        "original_url": lead.original_url,
                        "column_3_note": lead.note,
                        "has_existing_local_data": "no",
                        "existing_local_data_paths": "",
                        "existing_scrape_rows": "",
                        "existing_distinct_image_urls": "",
                        "existing_dataset_kind": "",
                        "existing_data_coverage": "none",
                        "probe_status": "probe_error",
                        "http_status": "",
                        "final_url": "",
                        "page_title": "",
                        "estimated_total_reviews_visible": "",
                        "image_reviews_found_in_fast_probe": "0",
                        "size_data_status": "unclear",
                        "measurement_data_status": "unclear",
                        "review_platform_provider": "unknown",
                        "scrape_at_scale_difficulty": "high",
                        "scale_notes": f"Probe exception: {exc}",
                        "recommended_next_action": "manual inspect",
                        "out_of_scope_reason": "",
                    }
                )
            if args.verbose and (completed == 1 or completed % 10 == 0 or completed == len(leads)):
                print(f"[{completed}/{len(leads)}] probed", file=sys.stderr)

    rows.sort(key=lambda row: int(row["lead_row_number"]))
    finished_at = utc_stamp()
    summary = build_summary(rows, leads, started_at, finished_at, csv_path, json_path, md_path)
    write_csv(csv_path, rows)
    write_json(json_path, summary)
    write_markdown(md_path, summary, rows)

    print(f"Wrote CSV: {csv_path}")
    print(f"Wrote JSON: {json_path}")
    print(f"Wrote Markdown: {md_path}")
    print(f"Rows: {len(rows)}")
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fast-probe lead URLs for review image scrape feasibility.")
    parser.add_argument("--leads-csv", type=Path, default=DEFAULT_LEADS_CSV)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--local-data-root", type=Path, default=LOCAL_DATA_ROOT)
    parser.add_argument("--merchant-summary-csv", type=Path, default=DEFAULT_MERCHANT_SUMMARY_CSV)
    parser.add_argument("--min-existing-rows-to-defer", type=int, default=100)
    parser.add_argument("--min-existing-images-to-defer", type=int, default=25)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
