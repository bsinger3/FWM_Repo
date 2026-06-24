#!/usr/bin/env python3
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
import html
import json
import os
import re
import sys
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
PIPELINE_SCRIPTS_DIR = REPO_ROOT / "data-pipelines" / "scripts"
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import raw_scraped_data_root  # noqa: E402

STEP1_OUTPUT_ROOT = raw_scraped_data_root()

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
    "bust_in_display",
    "bra_band_in_display",
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
    "weeks_pregnant",
    "pregnancy_evidence",
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
    r"(?::\s*|\s*)"
    r"(DDD/?F|DDD/?E|DD/?E|DDD|DD|AAA|AA|A|B|C|D|F|G|H|I|J|K)(?:\s*[-/]\s*(?:DDD|DD|AAA|AA|A|B|C|D|F|G|H|I|J|K))?\b",
    re.I,
)
CUP_SIZE_RE = re.compile(
    r"\b(DDD/?F|DDD/?E|DD/?E|DDD|DD|AAA|AA|A|B|C|D|F|G|H|I|J|K)\s*(?:cup|cups?)\b|"
    r"\b(?:cup\s*(?:size)?|cups?)\s*(?:is|are|:|：)?\s*(DDD/?F|DDD/?E|DD/?E|DDD|DD|AAA|AA|A|B|C|D|F|G|H|I|J|K)\b",
    re.I,
)
HEIGHT_RE = re.compile(
    r"(?:(?:i\s*(?:am|'m)|im|i’m|i am|height)\s*:?\s*)?"
    # `(?<!\d)` keeps a trailing-apostrophe inch measurement from being read as
    # feet, e.g. the 4' in a "24\" waist" written "24'" or the 7' in "27's".
    # `\.?` after the foot word handles "5 ft. 9 in"; `(?!\d)` on the optional
    # inches stops it grabbing the leading digits of an adjacent number, so
    # "5' 195lbs"/"6ft 160" read as 60"/72" (feet only) instead of 79"/88".
    r"(?<!\d)([3-7])\s*(?:ft|feet|foot|['’])\.?\s*(\d{1,2}(?:\.\d+)?)?(?!\d)\s*(?:in|inches|[\"”])?",
    re.I,
)
# Common review typo where the feet/inches mark is a double quote: 5"4 / 5”11
# means 5'4" / 5'11". Gated to a 3–7 leading digit not preceded by another digit
# so an inch measurement like waist 34" can't be read as 4 feet. Tried AFTER
# HEIGHT_RE so a real inch mark ("5' 4"") isn't read as feet.
HEIGHT_DQ_RE = re.compile(r"(?<!\d)([3-7])\s*[\"”]\s*(\d{1,2})(?!\d)")
# Fully swapped marks: "5"4'" / "5”4’" means 5'4" (quote and apostrophe swapped,
# a very common typo). The TRAILING apostrophe distinguishes it from a genuine
# inch mark like "5' 4"", so this is safe to try before HEIGHT_RE — which would
# otherwise read the bare "4'" as 4 feet.
HEIGHT_REVERSED_RE = re.compile(r"(?<!\d)([3-7])\s*[\"”]\s*(\d{1,2})\s*['’]")
# Fractional inches written tight: "5'6 1/2\"" / "5'61/2”" = 5'6.5".
HEIGHT_FRACTION_RE = re.compile(r"(?<!\d)([3-7])\s*['’]\s*(\d)\s*1\s*/\s*2\s*[\"”]?")
# Decimal feet used casually as feet+inches: "5.4ft" / "5.4'" / "5.2 feet" mean
# 5'4" / 5'2", not 4 or 2 feet. The trailing ft/'/feet keeps it from matching
# ratings like "5.5 stars". Tried before HEIGHT_RE so "4ft"/"2ft" isn't grabbed.
HEIGHT_DECIMAL_FEET_RE = re.compile(r"(?<!\d)([3-7])\.(\d{1,2})\s*(?:ft|feet|foot|['’])", re.I)
# Space between feet and a single inch digit before the mark: "5 3'" = 5'3".
HEIGHT_SPACE_RE = re.compile(r"(?<!\d)([3-7])\s+(\d)\s*['’](?!\d)")
WEIGHT_RE = re.compile(
    r"\b(\d{2,3}(?:\.\d+)?)\s*(?:ish)?\s*(?:lbs?|pounds?|#)\b|"
    r"\b(?:weigh(?:t|s|ed|ing)?|weight)\s*(?:is|:|：)?\s*(?:about|around|approx(?:imately)?\.?)?\s*(\d{2,3}(?:\.\d+)?)\s*(?:ish)?\b",
    re.I,
)
WEIGHT_RANGE_RE = re.compile(
    r"\b(\d{2,3}(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d{2,3}(?:\.\d+)?)\s*(lbs?|pounds?|#)?(?!\d)",
    re.I,
)
WEIGHT_KG_RE = re.compile(
    r"\b(\d{2,3}(?:\.\d+)?)\s*(?:kg|kilograms?)\b|"
    r"\b(?:weigh(?:t|s|ed|ing)?|weight)\s*(?:is|:|：)?\s*(?:about|around|approx(?:imately)?\.?)?\s*(\d{2,3}(?:\.\d+)?)\s*(?:kg|kilograms?)\b",
    re.I,
)
# A weight number is a CHANGE, not a body weight, when a lose/gain verb sits
# just before it — even with hedge words/parens in between: "lost over 50 lbs",
# "gained so much weight (60lbs)". The filler class excludes digits so it stops
# at the next number. Applied to the lowercased text preceding the match.
WEIGHT_CHANGE_PREFIX_RE = re.compile(
    r"\b(?:gain(?:ed|ing)?|lost|los(?:e|ing)|shed|dropped)\b[\sa-z().,&'’\"”-]{0,32}$",
    re.I,
)
# Non-body lifting context: "thighs that can leg press 400lbs" is not a weight.
WEIGHT_NONBODY_PREFIX_RE = re.compile(
    r"\b(?:leg\s*press|squat(?:ted|ting|s)?|dead\s*lift\w*|bench(?:\s*press)?)\b[\sa-z().,&'’\"”-]{0,18}$",
    re.I,
)
# Shared connector/adverb/number fragments for the body-measurement labels.
# `_MSEP` covers the linking word between a label and its number, including
# en/em dashes ("Bust – 93 cm"), verbs ("waist measures 27\""), and relative
# clauses ("waist which is 33\""). `_MADV` absorbs hedges ("currently",
# "about"). The number-before-label alternative ("29\" waist") requires an inch
# mark or "-ish" so stray numbers next to a label word aren't captured.
_MSEP = r"(?:is|are|was|were|=|:|：|[-–—]|measures?|measuring|measured|of|which\s+is|that\s+is)?"
_MADV = r"(?:currently\s+|now\s+|about\s+|approx(?:imately)?\.?\s+|around\s+|roughly\s+|a\s+|an\s+)?"
_MNUM = r"(\d{2,3}(?:\.\d+)?(?:\s+1/2)?)"
_MINCH = r'(?:\s*(?:["”]|in(?:ch(?:es)?)?))?'

# `(?!\s*cm)` keeps the inch matcher from eating a centimetre value ("65cm")
# so the *_CM_RE path can convert it. `(?![\s:=]*\d)` on the number-before-label
# arm stops a neighbouring measurement's number from being captured
# ("4'11\" Bust: 34" must not read bust=11; "41\" Inseam 30\"" must not read 41).
_LABEL_NOT_OWN_NUM = r"(?![\s:=]*\d)"
WAIST_RE = re.compile(
    r"\bwaist(?:line)?\s*" + _MSEP + r"\s*" + _MADV + r"\(?\s*" + _MNUM + r"(?!\s*cm)" + _MINCH
    + r'|(\d{2,3}(?:\.\d+)?)\s*(?:["”]|in(?:ch(?:es)?)?|-?ish)\s*\)?\s*waist(?:line)?\b' + _LABEL_NOT_OWN_NUM,
    re.I,
)
HIPS_RE = re.compile(
    r"\b(?:hips?(?:\s*/\s*butt)?|hip\s*/\s*butt)\s*" + _MSEP + r"\s*" + _MADV + r"\(?\s*" + _MNUM + r"(?!\s*cm)" + _MINCH
    + r'|(\d{2,3}(?:\.\d+)?)\s*(?:["”]|in(?:ch(?:es)?)?|-?ish)\s*\)?\s*hips?(?:\s*/\s*butt)?\b' + _LABEL_NOT_OWN_NUM,
    re.I,
)
# `(?![A-K](?![A-Za-z]))` rejects a bra size read as a bust circumference:
# "Bust: 34B" is band 34 / cup B, not a 34-inch bust — but "bust 36 inches"
# (a space, or "in"/"inches" where the letter continues into a word) is kept.
BUST_RE = re.compile(
    r"(?<!under\s)\b(?:bust|chest)\s*" + _MSEP + r"\s*" + _MADV + r"\(?\s*" + _MNUM + r"(?![A-K](?![A-Za-z]))(?!\s*cm)" + _MINCH
    + r'|(\d{2,3}(?:\.\d+)?)\s*(?:["”]|in(?:ch(?:es)?)?)\s*\)?\s*(?:bust|chest)\b' + _LABEL_NOT_OWN_NUM,
    re.I,
)
UNDERBUST_RE = re.compile(
    r"\b(?:under\s*bust|underbust|under\s*band|band\s*(?:size)?|rib\s*cage|ribcage)\s*"
    + _MSEP + r"\s*" + _MADV + _MNUM + r"(?!\s*cm)" + _MINCH,
    re.I,
)
BUST_CM_RE = re.compile(r"\b(?:bust|chest)\s*" + _MSEP + r"\s*" + _MADV + r"(\d{2,3}(?:\.\d+)?)\s*cm\b", re.I)
HEIGHT_CM_RE = re.compile(
    r"\bheight\s*(?:is|=|:|：|-)?\s*(\d{3}(?:\.\d+)?)\s*cm\b|"
    r"\b(\d{3}(?:\.\d+)?)\s*cm\s*(?:tall|height)\b|"
    r"\b(?:i\s*(?:am|'m)|im|i’m)\s*(?:about|around|approx(?:imately)?\.?)?\s*(\d{3}(?:\.\d+)?)\s*cm\b",
    re.I,
)
WAIST_CM_RE = re.compile(r"\bwaist\s*" + _MSEP + r"\s*" + _MADV + r"(\d{2,3}(?:\.\d+)?)\s*cm\b", re.I)
HIPS_CM_RE = re.compile(r"\b(?:hips?(?:\s*/\s*butt)?|hip\s*/\s*butt)\s*" + _MSEP + r"\s*" + _MADV + r"(\d{2,3}(?:\.\d+)?)\s*cm\b", re.I)
INSEAM_CM_RE = re.compile(r"\binseam\s*" + _MSEP + r"\s*" + _MADV + r"(\d{2,3}(?:\.\d+)?)\s*cm\b", re.I)
# Age: "age 55", "age of 60", "42 yr old", "30 year old", "58 years old", "y/o".
AGE_RE = re.compile(
    r"\bage\s*(?:of|is|:|=)?\s*(\d{1,2})\b|"
    r"\b(\d{1,2})\s*(?:years?|yrs?)\s*old\b|"
    r"\b(\d{1,2})\s*y\s*/?\s*o\b",
    re.I,
)
INSEAM_RE = re.compile(
    r"\binseam\s*" + _MSEP + r"\s*" + _MADV + r"(\d{2,3}(?:\.\d+)?)(?!\s*cm)\b"
    + r'|(\d{2,3}(?:\.\d+)?)\s*(?:["”]|in(?:ch(?:es)?)?)\s*inseam\b' + _LABEL_NOT_OWN_NUM,
    re.I,
)
# Bust-waist-hips triple: also accepts comma separators ("32,29,45") and inch
# marks between numbers ("40\"-30\"-40\""). Still gated by a nearby
# "measurements"/"bust-waist-hips" context in plausible_bust_waist_hips().
MEASUREMENT_TRIPLE_RE = re.compile(
    r"\b(\d{2,3}(?:\.\d+)?)\s*[\"”]?\s*[-/x,]\s*(\d{2,3}(?:\.\d+)?)\s*[\"”]?\s*[-/x,]\s*(\d{2,3}(?:\.\d+)?)\s*[\"”]?",
    re.I,
)
PREGNANCY_NOT_CURRENT_RE = re.compile(
    r"\b(?:postpartum|after\s+baby|pre[-\s]?pregnancy)\b",
    re.I,
)
PREGNANCY_WEEKS_RE = re.compile(
    r"\b(\d{1,2})\s*(?:weeks?|wks?)\s+(?:pregnant|along)\b",
    re.I,
)
PREGNANCY_MONTHS_RE = re.compile(
    r"\b(\d{1,2})\s*months?\s+pregnant\b",
    re.I,
)
# Soft pregnancy-weeks fallback: a bare "N weeks" only counts when it sits next
# to current-pregnancy language, so reviews that mention "due in 3 weeks" or
# "20 weeks postpartum" don't get mis-tagged. Used only after the explicit
# "N weeks pregnant/along" pattern misses.
PREGNANCY_CONTEXT_RE = re.compile(
    r"\b(?:pregnan\w*|maternity|trimester|expecting|baby\s*bump|\bbump\b)\b",
    re.I,
)
PREGNANCY_WEEKS_SOFT_RE = re.compile(r"\b(\d{1,2})\s*(?:weeks?|wks?)\b", re.I)
MEASUREMENT_TRIPLE_CONTEXT_RE = re.compile(
    r"\b(?:measurements?|stats?|my\s+stats|body\s+measurements?|dimensions?|"
    r"bust\s*[-/]\s*waist\s*[-/]\s*hips?|bwh)\b",
    re.I,
)

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
    "bust_in_display",
    "bra_band_in_display",
    "bust_in_number_display",
    "cupsize_display",
    "weight_lbs_display",
    "weeks_pregnant",
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


def _bra_match_ok(match: re.Match[str]) -> bool:
    """Reject false bra sizes where the cup is really the article "a" or the
    pronoun "I" (e.g. "Dirty 30 I recently..." → not a 30I bra). A lone, space-
    separated A/I cup only counts when followed by "cup"/"bra"."""
    cup = (match.group(2) or "").upper()
    whole = (match.group(0) or "").upper()
    if cup in ("A", "I") and re.search(r"\d\s+[AI]$", whole):
        tail = (match.string[match.end():match.end() + 6] or "").lower()
        return bool(re.match(r"\s*(?:cup|bra)\b", tail))
    return True


def bra_size_search(text: str) -> Optional[re.Match[str]]:
    """First BRA_SIZE_RE match that passes the article/pronoun guard."""
    for match in BRA_SIZE_RE.finditer(text or ""):
        if _bra_match_ok(match):
            return match
    return None


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


ORDERED_SIZE_VALUE_RE = r"(?:US\s*)?\d{1,2}W?|xxs|xs|s|m|l|xl|xxl|xxxl|[2-6]x|[2-6]xl"


def normalize_ordered_size(value: str) -> str:
    clean = normalize_whitespace(value)
    clean = re.sub(r"^us\s*", "US", clean, flags=re.I)
    if re.fullmatch(r"(?:US)?\d{1,2}W?", clean, re.I):
        return clean.upper()
    return normalize_generic_size(clean)


def extract_ordered_size(text: str) -> str:
    for pattern in [
        rf"\b(?:ordered|ordereda|bought|purchased|got|wearing|picked|chose|choose)\s+(?:the\s+)?(?:a\s+)?(?:us\s*)?size\s+({ORDERED_SIZE_VALUE_RE})\b",
        rf"\b(?:ordered|ordereda|bought|purchased|got|picked|chose)\s+(?:the|a|an)\s+({ORDERED_SIZE_VALUE_RE})\b",
        rf"\b(?:i\s*(?:am|'m)|im|i’m|she\s*(?:is|'s)|she’s|he\s*(?:is|'s)|he’s)\s+wearing\s+(?:a\s+)?(?:us\s*)?size\s+({ORDERED_SIZE_VALUE_RE})\b",
        rf"\bwearing\s+(?:a\s+)?(?:us\s*)?size\s+({ORDERED_SIZE_VALUE_RE})\b",
    ]:
        match = re.search(pattern, text, re.I)
        if match:
            value = normalize_whitespace(next((group for group in match.groups() if group), ""))
            if not value:
                continue
            return normalize_ordered_size(value)
    return ""


def extract_size(text: str) -> str:
    ordered_size = extract_ordered_size(text)
    if ordered_size:
        return ordered_size
    for pattern in [
        r"\b(?:ordered|bought|purchased|got|wearing|wear|picked|chose|choose)\s+(?:the\s+)?(?:a\s+)?size\s+([a-z0-9\-/ .]+?)(?:[.,;]|$)",
        r"\bsize\s+([a-z0-9\-/ .]+?)(?:\s+(?:fits?|was|is)|[.,;]|$)",
    ]:
        match = re.search(pattern, text, re.I)
        if match:
            value = normalize_whitespace(match.group(1))
            if re.search(r"\b(?:guide|chart|recommendation|recommendations|true\s+to\s+size|size\s+up|size\s+down)\b", value, re.I):
                continue
            value = re.sub(r"^us\s*", "US", value, flags=re.I)
            if re.fullmatch(r"(?:US)?\d{1,2}W?|xxs|xs|s|m|l|xl|xxl|xxxl|[2-6]x|[2-6]xl", value, re.I):
                return normalize_ordered_size(value)
            bra = bra_size_search(value)
            if bra:
                return normalize_bra_size(bra.group(0))
            generic = GENERIC_SIZE_RE.search(value)
            if generic:
                return normalize_generic_size(generic.group(1))
            continue
    bra = bra_size_search(text)
    if bra:
        return normalize_bra_size(bra.group(0))
    return ""


def numeric_text(value: Optional[float]) -> str:
    if value is None:
        return ""
    return str(int(value)) if value == int(value) else f"{value:.2f}".rstrip("0").rstrip(".")


def parse_number_text(value_text: str) -> float:
    value = normalize_whitespace(value_text)
    half_match = re.fullmatch(r"(\d{1,3}(?:\.\d+)?)\s+1/2", value)
    if half_match:
        return float(half_match.group(1)) + 0.5
    return float(value)


def parse_height(text: str) -> Tuple[str, str]:
    # Swapped-mark / decimal / fraction / space forms are tried BEFORE HEIGHT_RE
    # because HEIGHT_RE would otherwise read the bare "4'"/"4ft" they contain as
    # 4 feet. The plain double-quote form ("5"11") is tried AFTER HEIGHT_RE so a
    # genuine inch mark ("5' 4"") still parses as 5'4".
    match = HEIGHT_REVERSED_RE.search(text)
    if match:
        feet = int(match.group(1))
        inches = parse_number_text(match.group(2) or "0")
        if inches <= 11:
            return normalize_whitespace(match.group(0)), numeric_text(feet * 12 + inches)
    match = HEIGHT_FRACTION_RE.search(text)
    if match:
        feet = int(match.group(1))
        inches = parse_number_text(match.group(2) or "0") + 0.5
        return normalize_whitespace(match.group(0)), numeric_text(feet * 12 + inches)
    match = HEIGHT_DECIMAL_FEET_RE.search(text)
    if match:
        feet = int(match.group(1))
        inches = parse_number_text(match.group(2) or "0")
        if inches <= 11:
            return normalize_whitespace(match.group(0)), numeric_text(feet * 12 + inches)
    match = HEIGHT_SPACE_RE.search(text)
    if match:
        feet = int(match.group(1))
        inches = parse_number_text(match.group(2) or "0")
        if inches <= 11:
            return normalize_whitespace(match.group(0)), numeric_text(feet * 12 + inches)
    match = HEIGHT_RE.search(text)
    if match:
        feet = int(match.group(1))
        inches = parse_number_text(match.group(2) or "0")
        # Inches >= 12 means the digits weren't really inches (e.g. an adjacent
        # number or a "5'35"" typo) — keep the feet, drop the bogus inches.
        if inches >= 12:
            inches = 0
        following = text[match.end() : match.end() + 24]
        if re.match(r"\s*(?:-|to|–|—)\s*\d\s*(?:ft|feet|foot|['’])", following, re.I):
            return normalize_whitespace(match.group(0)), ""
        return normalize_whitespace(match.group(0)), numeric_text(feet * 12 + inches)
    match = HEIGHT_DQ_RE.search(text)
    if match:
        feet = int(match.group(1))
        inches = parse_number_text(match.group(2) or "0")
        if inches <= 11:
            return normalize_whitespace(match.group(0)), numeric_text(feet * 12 + inches)
    match = HEIGHT_CM_RE.search(text)
    if match:
        value_text = next((group for group in match.groups() if group), "")
        return normalize_whitespace(match.group(0)), numeric_text(float(value_text) / 2.54)
    return "", ""


def parse_numeric(pattern: re.Pattern[str], text: str, max_value: Optional[float] = None) -> Tuple[str, str]:
    match = pattern.search(text)
    if not match:
        return "", ""
    value_text = next((group for group in match.groups() if group), "")
    try:
        value = parse_number_text(value_text)
    except ValueError:
        return normalize_whitespace(match.group(0)), value_text
    if max_value is not None and value > max_value:
        return normalize_whitespace(match.group(0)), ""
    return normalize_whitespace(match.group(0)), numeric_text(value)


def parse_weight(text: str) -> Tuple[str, str]:
    range_match = WEIGHT_RANGE_RE.search(text)
    if range_match:
        try:
            low = parse_number_text(range_match.group(1))
            high = parse_number_text(range_match.group(2))
        except ValueError:
            low = high = 0
        unit = normalize_whitespace(range_match.group(3))
        context = text[max(0, range_match.start() - 32) : range_match.start()].lower()
        if (unit or re.search(r"\b(?:weight|weighs?|pounds?|lbs?)\b", context)) and 50 <= low < high <= 700 and high - low <= 150:
            return f"{numeric_text(low)}-{numeric_text(high)} lb", ""
    for pattern, multiplier in ((WEIGHT_RE, 1.0), (WEIGHT_KG_RE, 2.2046226218)):
        # Iterate every match (not just the first) so a real body weight after a
        # change phrase is still found, e.g. "gained 50lbs ... around 110lbs".
        for match in pattern.finditer(text):
            value_text = next((group for group in match.groups() if group), "")
            try:
                value = parse_number_text(value_text)
            except ValueError:
                return normalize_whitespace(match.group(0)), value_text
            prefix = text[max(0, match.start() - 36) : match.start()].lower()
            if re.search(r"\b(?:gain(?:ed|ing)?|gained|lost|los(?:t|ing)|down|up)\s*$", prefix):
                continue
            if WEIGHT_CHANGE_PREFIX_RE.search(prefix):
                continue
            if WEIGHT_NONBODY_PREFIX_RE.search(prefix):
                continue
            pounds = value * multiplier
            if not (50 <= pounds <= 700):
                continue
            return normalize_whitespace(match.group(0)), numeric_text(pounds)
    return "", ""


def is_weight_change_value(text: str, value: str) -> bool:
    try:
        numeric_value = float(str(value).strip())
    except ValueError:
        return False
    if numeric_value >= 50:
        return False
    pattern = re.compile(
        rf"\b(?:gain(?:ed|ing)?|gained|lost|los(?:t|ing)|down|up)\s+"
        rf"{re.escape(numeric_text(numeric_value))}(?:\.0+)?\s*(?:lbs?|pounds?|#)\b",
        re.I,
    )
    return bool(pattern.search(text))


def parse_metric_numeric(pattern: re.Pattern[str], text: str, max_inches: Optional[float] = None) -> Tuple[str, str]:
    match = pattern.search(text)
    if not match:
        return "", ""
    value_text = next((group for group in match.groups() if group), "")
    try:
        inches = float(value_text) / 2.54
    except ValueError:
        return normalize_whitespace(match.group(0)), value_text
    if max_inches is not None and inches > max_inches:
        return normalize_whitespace(match.group(0)), ""
    return normalize_whitespace(match.group(0)), numeric_text(inches)


def plausible_bust_waist_hips(values: Sequence[str], text: str, match: re.Match[str]) -> bool:
    try:
        bust, waist, hips = [float(value) for value in values]
    except ValueError:
        return False
    if not (25 <= bust <= 80 and 20 <= waist <= 80 and 25 <= hips <= 90):
        return False
    context = f"{text[max(0, match.start() - 60):match.start()]} {text[match.end():match.end() + 60]}"
    return bool(MEASUREMENT_TRIPLE_CONTEXT_RE.search(context))


def parse_pregnancy(text: str) -> Tuple[str, str]:
    """Return (pregnancy_evidence, weeks_pregnant_str) or ("", "") if not pregnant."""
    # Explicit "N weeks/months pregnant" wins even when the review also mentions
    # a pre-pregnancy weight — those are two different facts in one review.
    match = PREGNANCY_WEEKS_RE.search(text)
    if match:
        return normalize_whitespace(match.group(0)), match.group(1)
    match = PREGNANCY_MONTHS_RE.search(text)
    if match:
        weeks = str(round(float(match.group(1)) * 4.345))
        return normalize_whitespace(match.group(0)), weeks
    # Soft fallback: a bare "N weeks" only when current-pregnancy language is
    # nearby and the number isn't a "postpartum"/"due in" timer.
    if PREGNANCY_CONTEXT_RE.search(text):
        for soft in PREGNANCY_WEEKS_SOFT_RE.finditer(text):
            window = text[max(0, soft.start() - 18): soft.end() + 18].lower()
            if "postpartum" in window or "post partum" in window:
                continue
            if re.search(r"\b(?:due|in|shoot|appointment|delivery|deliver)\b\s*\w*\s*$", text[max(0, soft.start() - 14): soft.start()].lower()):
                continue
            if re.search(r"\b(?:along|pregnant|bump|measuring|measure|trimester)\b", window):
                return normalize_whitespace(soft.group(0)), soft.group(1)
    return "", ""


def extract_measurements(text: str, size_hint: str = "") -> Dict[str, str]:
    height_raw, height_in = parse_height(text)
    weight_raw, weight_lbs = parse_weight(text)
    waist_raw, waist_in = parse_numeric(WAIST_RE, text, max_value=80)
    hips_raw, hips_in = parse_numeric(HIPS_RE, text, max_value=90)
    age_raw, age_years = parse_numeric(AGE_RE, text, max_value=99)
    _, inseam_in = parse_numeric(INSEAM_RE, text, max_value=50)
    bust_raw, bust_in = parse_numeric(BUST_RE, text, max_value=80)
    _underbust_raw, underbust_in = parse_numeric(UNDERBUST_RE, text, max_value=60)
    if not waist_in:
        waist_raw, waist_in = parse_metric_numeric(WAIST_CM_RE, text, max_inches=80)
    if not hips_in:
        hips_raw, hips_in = parse_metric_numeric(HIPS_CM_RE, text, max_inches=90)
    if not inseam_in:
        _, inseam_in = parse_metric_numeric(INSEAM_CM_RE, text, max_inches=50)
    if not bust_in:
        bust_raw, bust_in = parse_metric_numeric(BUST_CM_RE, text, max_inches=80)
    triple = MEASUREMENT_TRIPLE_RE.search(text)
    if triple and plausible_bust_waist_hips(triple.groups(), text, triple):
        if not bust_in:
            bust_raw = triple.group(1)
            bust_in = numeric_text(float(triple.group(1)))
        if not waist_in:
            waist_raw = triple.group(2)
            waist_in = numeric_text(float(triple.group(2)))
        if not hips_in:
            hips_raw = triple.group(3)
            hips_in = numeric_text(float(triple.group(3)))
    pregnancy_evidence, weeks_pregnant = parse_pregnancy(text)
    cup_size = ""
    bra_band_in = underbust_in
    for source in (size_hint, text):
        match = bra_size_search(source or "")
        if match:
            bra_band_in = bra_band_in or match.group(1)
            cup_size = normalize_bra_size(match.group(2))
            break
    if not cup_size:
        match = CUP_SIZE_RE.search(text)
        if match:
            cup_size = normalize_bra_size(next(group for group in match.groups() if group))
    legacy_bust_in = bust_in or (bra_band_in if cup_size else "")
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
        "bust_in_display": bust_in,
        "bra_band_in_display": bra_band_in,
        "bust_in_number_display": legacy_bust_in,
        "cupsize_display": cup_size,
        "weeks_pregnant": weeks_pregnant,
        "pregnancy_evidence": pregnancy_evidence,
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
    raw_size = normalize_whitespace(review.size_raw)
    if raw_size.lower() in {"unknown", "n/a", "na", "none", "null"}:
        raw_size = ""
    size_display = raw_size or extract_size(comment)
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
    numeric_fields = [
        "height_in_display",
        "waist_in",
        "hips_in_display",
        "inseam_inches_display",
        "bust_in_display",
        "bra_band_in_display",
        "bust_in_number_display",
    ]
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
            if ((row.get("bra_band_in_display") or row.get("bust_in_number_display")) and row.get("cupsize_display"))
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
        "rows_with_pregnancy": sum(1 for row in rows if row.get("weeks_pregnant")),
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
