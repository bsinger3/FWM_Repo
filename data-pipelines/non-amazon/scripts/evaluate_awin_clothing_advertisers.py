#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXPORT = Path("/Users/briannasinger/Desktop/AWIN Advertisers to Triage/AWIN_AllClothingAdvertisers.csv")
OUT_DIR = (
    REPO_ROOT
    / "outputs"
    / "measurement_coverage"
    / "20260609_human_labeled_approved_only"
    / "affiliate_network_leads"
)
EXISTING_RECOMMENDATIONS = OUT_DIR / "awin_program_review_scrape_join_recommendations.csv"
OUTPUT_RECOMMENDATIONS = OUT_DIR / "awin_program_review_scrape_join_recommendations.csv"
OUTPUT_EXPANDED = OUT_DIR / "awin_all_clothing_advertisers_triaged_2026-06-10.csv"
OUTPUT_TOP = OUT_DIR / "awin_all_clothing_advertisers_top_scrape_prospects_2026-06-10.csv"
OUTPUT_MD = OUT_DIR / "awin_all_clothing_advertisers_triage_update_2026-06-10.md"

DATA_ROOT = REPO_ROOT / "data-pipelines" / "non-amazon" / "data" / "step_1_raw_scraping_data"
DOCS_ROOT = REPO_ROOT / "data-pipelines" / "non-amazon" / "docs"
SCRIPTS_ROOT = REPO_ROOT / "data-pipelines" / "non-amazon" / "scripts"
CLAIMS_ROOT = REPO_ROOT / "_claims"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

RECOMMENDATION_FIELDS = [
    "recommended_action",
    "final_score",
    "programmeName",
    "normalized_domain",
    "review_providers",
    "photo_signal",
    "measurement_signal",
    "gap_tags",
    "primarySector",
    "subSectors",
    "approvalRate",
    "epc",
    "awinIndex",
    "feedEnabled",
    "productReporting",
    "primaryRegion",
    "displayUrl",
    "sample_product_urls",
    "already_in_lead_or_sovrn",
    "existing_data_dir_found",
    "existing_scrape_doc_found",
    "existing_claim_found",
    "probe_status",
    "notes",
    "advertiserId",
    "base_gap_score",
]

EXPANDED_FIELDS = RECOMMENDATION_FIELDS + [
    "source_export",
    "conversionRate",
    "launchDate",
    "paymentStatus",
    "paymentRiskLevel",
    "commissionMin",
    "commissionMax",
    "cookieLength",
    "parentSectors",
    "averagePaymentTime",
    "descriptionShort",
]

PROVIDER_PATTERNS = [
    ("Okendo", re.compile(r"okendo|api\.okendo\.io", re.I)),
    ("Loox", re.compile(r"loox|loox\.io", re.I)),
    ("Judge.me", re.compile(r"judge\.me|judgeme|jdgm", re.I)),
    ("Stamped", re.compile(r"stamped\.io|stamped-main-widget|stamped-reviews", re.I)),
    ("Yotpo", re.compile(r"yotpo|staticw2\.yotpo\.com", re.I)),
    ("Bazaarvoice", re.compile(r"bazaarvoice|bvseo|bv-product", re.I)),
    ("Reviews.io", re.compile(r"reviews\.io", re.I)),
    ("Shopify Product Reviews", re.compile(r"shopify-product-reviews|spr-badge", re.I)),
]

HIGH_VALUE_RULES = [
    ("full_bust_lingerie", 110, re.compile(r"\b(bra|bralette|lingerie|intimates?|underwear|panty|panties|bust|dd\+|full bust|cup size)\b", re.I)),
    ("swim_shapewear", 85, re.compile(r"\b(swim|swimsuit|bikini|tankini|one[- ]?piece|shapewear|shape wear|bodysuit)\b", re.I)),
    ("maternity_postpartum", 80, re.compile(r"\b(maternity|postpartum|pregnan|nursing)\b", re.I)),
    ("bottoms_denim_active", 65, re.compile(r"\b(jeans?|denim|pants?|trousers?|leggings?|activewear|sportswear|yoga|workout|athletic)\b", re.I)),
    ("plus_curve", 60, re.compile(r"\b(plus|curve|curvy|extended size|inclusive siz|size inclusive)\b", re.I)),
    ("petite_tall", 45, re.compile(r"\b(petite|tall|short inseam|long inseam)\b", re.I)),
    ("dresses_formal", 35, re.compile(r"\b(dress|gown|bridal|bridesmaid|formal|prom)\b", re.I)),
    ("general_womenswear", 20, re.compile(r"\b(women|womenswear|ladies|female)\b", re.I)),
]

LOW_VALUE_RE = re.compile(
    r"\b("
    r"hair|wig|extensions?|cosplay|costume|jewelry|jewellery|watch|sunglasses|eyewear|"
    r"bag|handbag|wallet|shoe|sneaker|boots?|sandals?|kids?|baby|men'?s only|"
    r"printing|transfer|uniform|merch|gaming gear|fan gear|costume|grills?|skincare|skin care|"
    r"esthetician|spa|beauty|wellness|marketplace|everything sustainable|collectibles"
    r")\b",
    re.I,
)

APPAREL_DESC_RE = re.compile(
    r"\b("
    r"women|womenswear|ladies|bra|bralette|lingerie|intimates?|underwear|panty|panties|"
    r"shapewear|swim|swimsuit|bikini|activewear|sports bra|leggings?|jeans?|denim|"
    r"dress|gown|maternity|postpartum|petite|plus|curve|clothing|apparel"
    r")\b",
    re.I,
)


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or "").replace("\xa0", " "))).strip()


def score_float(value: object) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except ValueError:
        return 0.0


def retailer_slug(value: str) -> str:
    slug = re.sub(r"^www\.", "", value.strip().lower())
    slug = slug.split("/")[0].split(":")[0]
    return re.sub(r"[^a-z0-9]+", "_", slug).strip("_")


def normalize_domain(url_or_domain: str) -> str:
    raw = norm(url_or_domain)
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    host = host.removeprefix("www.")
    if host.startswith("m.") and host.count(".") >= 2:
        host = host[2:]
    return host


def fetch_text(url: str, *, timeout: float = 8.0) -> Tuple[str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            text = response.read(900_000).decode("utf-8", "replace")
        return text, f"http_{status}"
    except HTTPError as exc:
        return "", f"http_{exc.code}"
    except (URLError, TimeoutError, OSError) as exc:
        return "", f"fetch_error:{type(exc).__name__}"


def provider_hints(text: str) -> List[str]:
    found = [name for name, pattern in PROVIDER_PATTERNS if pattern.search(text)]
    return list(dict.fromkeys(found))


def sample_products(domain: str, limit: int) -> Tuple[List[str], str]:
    if limit <= 0:
        return [], "not_probed"
    root = f"https://{domain}"
    text, status = fetch_text(f"{root}/products.json?limit={limit}&page=1", timeout=6.0)
    if not text:
        return [], status
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [], "products_json_invalid"
    products = payload.get("products")
    if not isinstance(products, list):
        return [], "products_json_no_products_key"
    urls: List[str] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        handle = norm(product.get("handle"))
        if handle:
            urls.append(f"{root}/products/{handle}")
    return urls[:limit], f"products_json_{len(urls)}"


def existing_flags(domain: str) -> Dict[str, str]:
    slug = retailer_slug(domain)
    return {
        "existing_data_dir_found": "yes" if (DATA_ROOT / slug).exists() else "no",
        "existing_scrape_doc_found": "yes" if any(DOCS_ROOT.glob(f"*{slug}*")) else "no",
        "existing_scraper_script_found": "yes" if any(SCRIPTS_ROOT.glob(f"**/*{slug}*")) else "no",
        "existing_claim_found": "yes" if any(CLAIMS_ROOT.glob(f"{slug}*")) else "no",
    }


def load_existing(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    out: Dict[str, Dict[str, str]] = {}
    for row in rows:
        key = row.get("advertiserId") or row.get("normalized_domain")
        if key:
            out[key] = row
    return out


def gap_score(row: Dict[str, str]) -> Tuple[float, List[str], bool]:
    sub_sectors = [part.strip() for part in norm(row.get("subSectors")).split("|") if part.strip()]
    broad_sector_list = len(sub_sectors) > 10
    descriptive_text = " ".join(
        [
            norm(row.get("programmeName")),
            norm(row.get("primarySector")),
            norm(row.get("descriptionShort")),
            norm(row.get("displayUrl")),
        ]
    )
    sector_text = "" if broad_sector_list else norm(row.get("subSectors"))
    text = " ".join([descriptive_text, sector_text])
    score = 0.0
    tags: List[str] = []
    for tag, points, pattern in HIGH_VALUE_RULES:
        if pattern.search(text):
            tags.append(tag)
            score += points
    low_value = bool(LOW_VALUE_RE.search(text))
    if low_value:
        score -= 80
    primary = norm(row.get("primarySector")).lower()
    sectors = sector_text.lower()
    if "womenswear" in primary or "womenswear" in sectors:
        score += 35
    if "lingerie" in primary or "lingerie" in sectors:
        score += 65
        if "full_bust_lingerie" not in tags:
            tags.append("full_bust_lingerie")
    if "sportswear" in primary or "sportswear" in sectors:
        score += 25
        if "bottoms_denim_active" not in tags:
            tags.append("bottoms_denim_active")
    if "shoes" in primary or "jewellery" in primary or "clothing accessories" in primary:
        score -= 55
    if primary in {"health & beauty", "home & garden", "green (eco friendly)", "sports equipment"} and not APPAREL_DESC_RE.search(descriptive_text):
        score -= 160
        low_value = True
    menswear_only = bool(re.search(r"\b(menswear|men's underwear|men'?s swim|men'?s apparel)\b", descriptive_text, re.I))
    if (primary == "menswear" or menswear_only) and not re.search(r"\b(women|womenswear|unisex|bra|lingerie|maternity|plus|curve)\b", descriptive_text, re.I):
        score -= 120
        low_value = True
    if broad_sector_list and not APPAREL_DESC_RE.search(descriptive_text):
        score -= 130
        low_value = True
    return score, list(dict.fromkeys(tags)), low_value


def rank_action(row: Dict[str, str], score: float, providers: List[str], flags: Dict[str, str], probe_status: str) -> str:
    if flags["existing_data_dir_found"] == "yes" or flags["existing_claim_found"] == "yes":
        return "skip_existing_or_refresh_only"
    if score < 45:
        return "do_not_prioritize_now"
    has_known_provider = bool(providers)
    if score >= 170 and has_known_provider:
        return "request_to_join_p1_scrape_likely"
    if score >= 130 and has_known_provider:
        return "request_to_join_p2_scrape_probe"
    if score >= 110:
        return "maybe_join_manual_review_probe"
    if probe_status.startswith("http_429"):
        return "maybe_join_manual_review_probe"
    return "do_not_prioritize_now"


def evaluate_row(
    row: Dict[str, str],
    *,
    existing_by_key: Dict[str, Dict[str, str]],
    probe: bool,
    product_limit: int,
) -> Dict[str, str]:
    domain = normalize_domain(row.get("displayUrl", ""))
    base_score, tags, low_value = gap_score(row)
    flags = existing_flags(domain)
    key = row.get("advertiserId") or domain
    prior = existing_by_key.get(key) or existing_by_key.get(domain) or {}

    providers: List[str] = []
    sample_urls: List[str] = []
    probe_status = "not_probed"
    notes: List[str] = []
    if prior.get("review_providers"):
        providers.extend(
            [
                part.strip()
                for part in prior["review_providers"].split(";")
                if part.strip() and part.strip().lower() != "unknown"
            ]
        )
    if prior.get("sample_product_urls"):
        sample_urls.extend([part.strip() for part in prior["sample_product_urls"].split("|") if part.strip()])
    if probe and domain and not providers:
        home_html, home_status = fetch_text(f"https://{domain}", timeout=7.0)
        providers.extend(provider_hints(home_html))
        sample_urls, product_status = sample_products(domain, product_limit)
        product_html = ""
        for product_url in sample_urls[: min(3, len(sample_urls))]:
            fetched, status = fetch_text(product_url, timeout=7.0)
            if fetched:
                product_html += "\n" + fetched
            elif status.startswith("http_429"):
                notes.append(f"product_probe_{status}")
                break
        providers.extend(provider_hints(product_html))
        probe_status = ";".join([home_status, product_status])
    elif prior:
        probe_status = prior.get("probe_status") or "prior_triage"

    providers = list(dict.fromkeys(providers))
    provider_score = 75 if providers else 0
    product_feed_score = 15 if norm(row.get("feedEnabled")).lower() == "yes" else 0
    reporting_score = 10 if norm(row.get("productReporting")).lower() == "yes" else 0
    approval_score = min(score_float(row.get("approvalRate")), 100.0) / 5.0
    epc_score = min(score_float(row.get("epc")) * 20.0, 25.0)
    final_score = base_score + provider_score + product_feed_score + reporting_score + approval_score + epc_score
    if low_value and not tags:
        final_score -= 40

    action = rank_action(row, final_score, providers, flags, probe_status)
    photo_signal = "yes" if providers else ("unknown" if action != "do_not_prioritize_now" else "no")
    measurement_signal = "yes" if tags else "no"
    already = "yes" if any(flags[k] == "yes" for k in ["existing_data_dir_found", "existing_scrape_doc_found", "existing_claim_found"]) else "no"
    return {
        "recommended_action": action,
        "final_score": f"{final_score:.1f}",
        "programmeName": norm(row.get("programmeName")),
        "normalized_domain": domain,
        "review_providers": ";".join(providers) or "unknown",
        "photo_signal": photo_signal,
        "measurement_signal": measurement_signal,
        "gap_tags": ";".join(tags),
        "primarySector": norm(row.get("primarySector")),
        "subSectors": norm(row.get("subSectors")),
        "approvalRate": norm(row.get("approvalRate")),
        "epc": norm(row.get("epc")),
        "awinIndex": norm(row.get("awinIndex")),
        "feedEnabled": norm(row.get("feedEnabled")),
        "productReporting": norm(row.get("productReporting")),
        "primaryRegion": norm(row.get("primaryRegion")),
        "displayUrl": norm(row.get("displayUrl")),
        "sample_product_urls": " | ".join(sample_urls[:5]),
        "already_in_lead_or_sovrn": already,
        "existing_data_dir_found": flags["existing_data_dir_found"],
        "existing_scrape_doc_found": flags["existing_scrape_doc_found"],
        "existing_claim_found": flags["existing_claim_found"],
        "probe_status": probe_status,
        "notes": "; ".join(notes),
        "advertiserId": norm(row.get("advertiserId")),
        "base_gap_score": f"{base_score:.1f}",
        "source_export": "AWIN_AllClothingAdvertisers.csv",
        "conversionRate": norm(row.get("conversionRate")),
        "launchDate": norm(row.get("launchDate")),
        "paymentStatus": norm(row.get("paymentStatus")),
        "paymentRiskLevel": norm(row.get("paymentRiskLevel")),
        "commissionMin": norm(row.get("commissionMin")),
        "commissionMax": norm(row.get("commissionMax")),
        "cookieLength": norm(row.get("cookieLength")),
        "parentSectors": norm(row.get("parentSectors")),
        "averagePaymentTime": norm(row.get("averagePaymentTime")),
        "descriptionShort": norm(row.get("descriptionShort")),
    }


def write_rows(path: Path, rows: Sequence[Dict[str, str]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_markdown(path: Path, rows: Sequence[Dict[str, str]], export_path: Path, probe_limit: int) -> None:
    from collections import Counter

    action_counts = Counter(row["recommended_action"] for row in rows)
    provider_counts = Counter(
        provider
        for row in rows
        for provider in row["review_providers"].split(";")
        if provider and provider != "unknown"
    )
    top = [
        row
        for row in rows
        if row["recommended_action"] in {"request_to_join_p1_scrape_likely", "request_to_join_p2_scrape_probe"}
    ][:30]
    lines = [
        "# Awin clothing advertiser triage update",
        "",
        f"Source export: `{export_path}`",
        f"Rows evaluated: {len(rows)}",
        f"Light provider probe limit: {probe_limit}",
        "",
        "## Action counts",
        "",
    ]
    for action, count in action_counts.most_common():
        lines.append(f"- {action}: {count}")
    lines.extend(["", "## Provider signals", ""])
    for provider, count in provider_counts.most_common():
        lines.append(f"- {provider}: {count}")
    lines.extend(["", "## Top new/refresh scrape prospects", ""])
    lines.append("| Rank | Action | Score | Advertiser | Domain | Providers | Gap tags | Notes |")
    lines.append("|---:|---|---:|---|---|---|---|---|")
    for index, row in enumerate(top, 1):
        notes = row["probe_status"]
        if row["already_in_lead_or_sovrn"] == "yes":
            notes += "; existing/refresh"
        lines.append(
            "| {rank} | {action} | {score} | {name} | {domain} | {providers} | {tags} | {notes} |".format(
                rank=index,
                action=row["recommended_action"],
                score=row["final_score"],
                name=row["programmeName"].replace("|", "/"),
                domain=row["normalized_domain"],
                providers=row["review_providers"].replace("|", "/"),
                tags=row["gap_tags"].replace("|", "/"),
                notes=notes.replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Files updated",
            "",
            f"- `{OUTPUT_RECOMMENDATIONS}`",
            f"- `{OUTPUT_EXPANDED}`",
            f"- `{OUTPUT_TOP}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the full Awin clothing advertiser export for FWM scrape prospects.")
    parser.add_argument("--export-csv", type=Path, default=DEFAULT_EXPORT)
    parser.add_argument("--probe-limit", type=int, default=160)
    parser.add_argument("--product-limit", type=int, default=8)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    existing_by_key = load_existing(EXISTING_RECOMMENDATIONS)
    with args.export_csv.open(newline="", encoding="utf-8-sig") as handle:
        export_rows = list(csv.DictReader(handle))

    prelim: List[Tuple[float, Dict[str, str]]] = []
    for row in export_rows:
        score, _, _ = gap_score(row)
        score += min(score_float(row.get("approvalRate")), 100.0) / 5.0
        prelim.append((score, row))
    prelim.sort(key=lambda item: item[0], reverse=True)
    probe_ids = {row.get("advertiserId") for _, row in prelim[: args.probe_limit]}

    evaluated: List[Dict[str, str]] = []
    for index, (_, row) in enumerate(prelim, start=1):
        evaluated.append(
            evaluate_row(
                row,
                existing_by_key=existing_by_key,
                probe=row.get("advertiserId") in probe_ids,
                product_limit=args.product_limit,
            )
        )
        if index % 25 == 0 and index <= args.probe_limit:
            time.sleep(1.0)

    evaluated.sort(key=lambda row: float(row["final_score"]), reverse=True)
    write_rows(OUTPUT_EXPANDED, evaluated, EXPANDED_FIELDS)
    write_rows(OUTPUT_RECOMMENDATIONS, evaluated, RECOMMENDATION_FIELDS)
    top = [row for row in evaluated if row["recommended_action"] != "do_not_prioritize_now"]
    write_rows(OUTPUT_TOP, top, RECOMMENDATION_FIELDS)
    write_markdown(OUTPUT_MD, evaluated, args.export_csv, args.probe_limit)
    print(json.dumps({
        "rows_evaluated": len(evaluated),
        "recommendations_csv": str(OUTPUT_RECOMMENDATIONS),
        "expanded_csv": str(OUTPUT_EXPANDED),
        "top_csv": str(OUTPUT_TOP),
        "summary_md": str(OUTPUT_MD),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
