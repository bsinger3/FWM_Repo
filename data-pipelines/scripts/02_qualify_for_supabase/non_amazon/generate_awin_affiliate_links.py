#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


PIPELINE_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import raw_scraped_data_root, reports_root  # noqa: E402


AFFILIATE_LEADS_DIR = (
    reports_root()
    / "measurement_coverage"
    / "20260609_human_labeled_approved_only"
    / "affiliate_network_leads"
)
DEFAULT_ADVERTISER_CSVS = [
    AFFILIATE_LEADS_DIR / "awin_program_review_scrape_join_recommendations.csv",
    AFFILIATE_LEADS_DIR / "awin_all_clothing_advertisers_triaged_2026-06-10.csv",
]
DEFAULT_OUTPUT_ROOT = reports_root() / "affiliate_links" / "awin"
AWIN_API_BASE = "https://api.awin.com"
AWIN_MIN_SECONDS_BETWEEN_CALLS = 3.1

PRODUCT_URL_COLUMNS = ["product_page_url_display", "monetized_product_url_display"]
SIZE_SIGNAL_COLUMNS = [
    "size_display",
    "size_ordered_raw_display",
    "size_ordered_norm",
    "product_variant_raw",
]
MEASUREMENT_SIGNAL_COLUMNS = [
    "height_raw",
    "height_in_display",
    "weight_raw",
    "weight_display_display",
    "weight_lbs_display",
    "weight_lb",
    "waist_raw_display",
    "waist_in",
    "hips_raw",
    "hips_in_display",
    "bust_in_display",
    "bust_in_number_display",
    "bra_band_in_display",
    "inseam_inches_display",
    "age_raw",
    "age_years_display",
]
SOURCE_CONTEXT_COLUMNS = [
    "id",
    "original_url_display",
    "source_site_display",
    "brand",
    "product_title_raw",
    "product_page_url_display",
    "monetized_product_url_display",
]
CANDIDATE_HEADERS = [
    "status",
    "skip_reason",
    "source_csv",
    "source_row_number",
    "row_id",
    "destination_url",
    "normalized_product_url",
    "product_domain",
    "matched_domain",
    "advertiserId",
    "programmeName",
    "existing_monetized_url",
    "source_site_display",
    "brand",
    "product_title_raw",
]
LINK_MAP_HEADERS = [
    "status",
    "error",
    "normalized_product_url",
    "destination_url",
    "product_domain",
    "matched_domain",
    "advertiserId",
    "programmeName",
    "tracking_url",
    "short_url",
    "source_row_count",
    "source_files",
]


@dataclass
class Advertiser:
    advertiser_id: str
    normalized_domain: str
    programme_name: str = ""
    display_url: str = ""
    source_csv: str = ""


@dataclass
class LinkTarget:
    normalized_product_url: str
    destination_url: str
    product_domain: str
    matched_domain: str
    advertiser: Advertiser
    source_files: Set[str] = field(default_factory=set)
    source_row_count: int = 0


def utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def domain_from_url(value: str) -> str:
    raw = clean(value)
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


def normalize_product_url(value: str) -> str:
    raw = clean(value)
    if not raw or not raw.lower().startswith(("http://", "https://")):
        return ""
    parsed = urlparse(raw)
    scheme = "https" if parsed.scheme in {"http", "https"} else parsed.scheme.lower()
    host = parsed.netloc.lower().split("@")[-1]
    if host.endswith(":80") or host.endswith(":443"):
        host = host.rsplit(":", 1)[0]
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_pairs = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower()
        not in {
            "fbclid",
            "gclid",
            "gbraid",
            "wbraid",
            "mc_cid",
            "mc_eid",
            "irclickid",
            "clickid",
            "awc",
        }
    ]
    query = urlencode(sorted(query_pairs), doseq=True)
    return urlunparse((scheme, host, path, "", query, ""))


def is_valid_product_url(value: str) -> bool:
    parsed = urlparse(clean(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_awin_tracking_url(value: str) -> bool:
    host = domain_from_url(value)
    return host in {"awin1.com", "tidd.ly"} or host.endswith(".awin1.com") or host.endswith(".tidd.ly")


def has_any_value(row: Dict[str, str], columns: Sequence[str]) -> bool:
    return any(clean(row.get(column)) for column in columns)


def is_catalog_image_row(row: Dict[str, str]) -> bool:
    image_source = " ".join(
        [
            clean(row.get("image_source_type")).lower(),
            clean(row.get("image_source_detail")).lower(),
        ]
    )
    return "catalog" in image_source


def is_supabase_qualified_image_row(row: Dict[str, str]) -> bool:
    return (
        bool(clean(row.get("original_url_display")))
        and bool(first_product_url(row))
        and not is_catalog_image_row(row)
        and (has_any_value(row, SIZE_SIGNAL_COLUMNS) or has_any_value(row, MEASUREMENT_SIGNAL_COLUMNS))
    )


def scrub_secret(value: str, secret: str) -> str:
    if secret and secret in value:
        return value.replace(secret, "[REDACTED]")
    return value


def domain_variants(domain: str) -> Iterable[str]:
    current = domain.lower().strip(".")
    while current:
        yield current
        if "." not in current:
            break
        current = current.split(".", 1)[1]


def load_advertisers(paths: Sequence[Path]) -> Dict[str, Advertiser]:
    advertisers: Dict[str, Advertiser] = {}
    for path in paths:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                advertiser_id = clean(row.get("advertiserId"))
                domain = domain_from_url(row.get("normalized_domain") or row.get("displayUrl") or "")
                if not advertiser_id or not domain:
                    continue
                advertiser = Advertiser(
                    advertiser_id=advertiser_id,
                    normalized_domain=domain,
                    programme_name=clean(row.get("programmeName")),
                    display_url=clean(row.get("displayUrl")),
                    source_csv=str(path),
                )
                advertisers.setdefault(domain, advertiser)
    return advertisers


def load_domain_filters(paths: Sequence[Path], column: str) -> Set[str]:
    domains: Set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                domain = domain_from_url(row.get(column) or "")
                if domain:
                    domains.add(domain)
    return domains


def match_advertiser(product_domain: str, advertisers: Dict[str, Advertiser]) -> Tuple[str, Optional[Advertiser]]:
    for candidate in domain_variants(product_domain):
        advertiser = advertisers.get(candidate)
        if advertiser:
            return candidate, advertiser
    return "", None


def discover_input_csvs(input_root: Path) -> List[Path]:
    if input_root.is_file():
        return [input_root]
    patterns = [
        "**/*_reviews_matching_intake_schema.csv",
        "**/*_reviews_matching_amazon_schema.csv",
    ]
    paths: List[Path] = []
    for pattern in patterns:
        paths.extend(input_root.glob(pattern))
    return sorted(set(paths))


def first_product_url(row: Dict[str, str]) -> str:
    product_url = clean(row.get("product_page_url_display"))
    monetized_url = clean(row.get("monetized_product_url_display"))
    if product_url:
        return product_url
    if monetized_url and not is_awin_tracking_url(monetized_url):
        return monetized_url
    return ""


def make_clickref(prefix: str, normalized_product_url: str) -> str:
    digest = hashlib.sha1(normalized_product_url.encode("utf-8")).hexdigest()[:16]
    if not prefix:
        return digest
    safe_prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", prefix).strip("_")
    return f"{safe_prefix}_{digest}"[:50]


def candidate_row(
    *,
    status: str,
    skip_reason: str,
    source_csv: Path,
    source_row_number: int,
    row: Dict[str, str],
    destination_url: str,
    normalized_product_url: str,
    product_domain: str,
    matched_domain: str = "",
    advertiser: Optional[Advertiser] = None,
) -> Dict[str, str]:
    return {
        "status": status,
        "skip_reason": skip_reason,
        "source_csv": str(source_csv),
        "source_row_number": str(source_row_number),
        "row_id": clean(row.get("id")),
        "destination_url": destination_url,
        "normalized_product_url": normalized_product_url,
        "product_domain": product_domain,
        "matched_domain": matched_domain,
        "advertiserId": advertiser.advertiser_id if advertiser else "",
        "programmeName": advertiser.programme_name if advertiser else "",
        "existing_monetized_url": clean(row.get("monetized_product_url_display")),
        "source_site_display": clean(row.get("source_site_display")),
        "brand": clean(row.get("brand")),
        "product_title_raw": clean(row.get("product_title_raw")),
    }


def collect_candidates(
    *,
    input_paths: Sequence[Path],
    advertisers: Dict[str, Advertiser],
    include_existing: bool,
    supabase_qualified_only: bool,
    domain_filters: Set[str],
    limit: int,
) -> Tuple[List[Dict[str, str]], Dict[str, LinkTarget]]:
    rows_out: List[Dict[str, str]] = []
    targets: Dict[str, LinkTarget] = {}
    for path in input_paths:
        if domain_filters and not any(domain.replace(".", "_") in path.as_posix() for domain in domain_filters):
            # Domain-scoped smoke runs should stay small and readable. The URL-level
            # filter below remains the source of truth for matching.
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for source_row_number, row in enumerate(reader, start=2):
                if supabase_qualified_only and not is_supabase_qualified_image_row(row):
                    continue
                destination_url = first_product_url(row)
                normalized_product_url = normalize_product_url(destination_url)
                product_domain = domain_from_url(destination_url)
                if domain_filters and product_domain and product_domain not in domain_filters:
                    continue
                if not destination_url or not normalized_product_url or not is_valid_product_url(destination_url):
                    if domain_filters:
                        continue
                    rows_out.append(
                        candidate_row(
                            status="skipped",
                            skip_reason="missing_valid_product_url",
                            source_csv=path,
                            source_row_number=source_row_number,
                            row=row,
                            destination_url=destination_url,
                            normalized_product_url=normalized_product_url,
                            product_domain=product_domain,
                        )
                    )
                    continue
                existing_monetized = clean(row.get("monetized_product_url_display"))
                if existing_monetized and is_awin_tracking_url(existing_monetized) and not include_existing:
                    rows_out.append(
                        candidate_row(
                            status="skipped",
                            skip_reason="existing_awin_tracking_url",
                            source_csv=path,
                            source_row_number=source_row_number,
                            row=row,
                            destination_url=destination_url,
                            normalized_product_url=normalized_product_url,
                            product_domain=product_domain,
                        )
                    )
                    continue
                matched_domain, advertiser = match_advertiser(product_domain, advertisers)
                if not advertiser:
                    rows_out.append(
                        candidate_row(
                            status="skipped",
                            skip_reason="no_awin_advertiser_match",
                            source_csv=path,
                            source_row_number=source_row_number,
                            row=row,
                            destination_url=destination_url,
                            normalized_product_url=normalized_product_url,
                            product_domain=product_domain,
                        )
                    )
                    continue

                rows_out.append(
                    candidate_row(
                        status="eligible",
                        skip_reason="",
                        source_csv=path,
                        source_row_number=source_row_number,
                        row=row,
                        destination_url=destination_url,
                        normalized_product_url=normalized_product_url,
                        product_domain=product_domain,
                        matched_domain=matched_domain,
                        advertiser=advertiser,
                    )
                )
                target = targets.get(normalized_product_url)
                if target is None:
                    if limit > 0 and len(targets) >= limit:
                        continue
                    target = LinkTarget(
                        normalized_product_url=normalized_product_url,
                        destination_url=destination_url,
                        product_domain=product_domain,
                        matched_domain=matched_domain,
                        advertiser=advertiser,
                    )
                    targets[normalized_product_url] = target
                target.source_files.add(str(path))
                target.source_row_count += 1
    return rows_out, targets


def write_csv(path: Path, headers: Sequence[str], rows: Sequence[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(headers))
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})


def request_awin_link(
    *,
    publisher_id: str,
    access_token: str,
    target: LinkTarget,
    campaign: str,
    clickref_prefix: str,
    shorten: bool,
    timeout: float,
) -> Dict[str, str]:
    endpoint = f"{AWIN_API_BASE}/publishers/{publisher_id}/linkbuilder/generate"
    parameters: Dict[str, str] = {}
    if campaign:
        parameters["campaign"] = campaign
    clickref = make_clickref(clickref_prefix, target.normalized_product_url)
    if clickref:
        parameters["clickref"] = clickref
    body = {
        "advertiserId": int(target.advertiser.advertiser_id),
        "destinationUrl": target.destination_url,
    }
    if parameters:
        body["parameters"] = parameters
    if shorten:
        body["shorten"] = True
    request = Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "FWM AWIN affiliate link generator",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", "replace")
            payload = json.loads(response_body or "{}")
        return {
            "status": "generated",
            "tracking_url": clean(payload.get("url")),
            "short_url": clean(payload.get("shortUrl")),
            "error": "",
        }
    except HTTPError as exc:
        error_body = scrub_secret(exc.read().decode("utf-8", "replace")[:1000], access_token)
        return {"status": f"http_{exc.code}", "tracking_url": "", "short_url": "", "error": error_body}
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
        error = scrub_secret(f"{type(exc).__name__}: {exc}", access_token)
        return {"status": "failed", "tracking_url": "", "short_url": "", "error": error}


def single_link_target(advertiser_id: str, destination_url: str) -> LinkTarget:
    product_domain = domain_from_url(destination_url)
    advertiser = Advertiser(
        advertiser_id=advertiser_id,
        normalized_domain=product_domain,
        programme_name=f"advertiser_{advertiser_id}",
        display_url=destination_url,
        source_csv="single_link_verification",
    )
    return LinkTarget(
        normalized_product_url=normalize_product_url(destination_url),
        destination_url=destination_url,
        product_domain=product_domain,
        matched_domain=product_domain,
        advertiser=advertiser,
        source_files={"single_link_verification"},
        source_row_count=1,
    )


def link_map_rows(
    *,
    targets: Dict[str, LinkTarget],
    dry_run: bool,
    publisher_id: str,
    access_token: str,
    campaign: str,
    clickref_prefix: str,
    shorten: bool,
    request_timeout: float,
    sleep_seconds: float,
    max_retries: int,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    last_call = 0.0
    for target in targets.values():
        api_result = {"status": "dry_run", "tracking_url": "", "short_url": "", "error": ""}
        if not dry_run:
            for attempt in range(max_retries + 1):
                elapsed = time.monotonic() - last_call
                if elapsed < sleep_seconds:
                    time.sleep(sleep_seconds - elapsed)
                api_result = request_awin_link(
                    publisher_id=publisher_id,
                    access_token=access_token,
                    target=target,
                    campaign=campaign,
                    clickref_prefix=clickref_prefix,
                    shorten=shorten,
                    timeout=request_timeout,
                )
                last_call = time.monotonic()
                if api_result["status"] not in {"http_429", "http_500", "http_502", "http_503", "http_504"}:
                    break
                if attempt < max_retries:
                    time.sleep(min(60.0, sleep_seconds * (attempt + 2)))
        rows.append(
            {
                "status": api_result["status"],
                "error": api_result["error"],
                "normalized_product_url": target.normalized_product_url,
                "destination_url": target.destination_url,
                "product_domain": target.product_domain,
                "matched_domain": target.matched_domain,
                "advertiserId": target.advertiser.advertiser_id,
                "programmeName": target.advertiser.programme_name,
                "tracking_url": api_result["tracking_url"],
                "short_url": api_result["short_url"],
                "source_row_count": target.source_row_count,
                "source_files": " | ".join(sorted(target.source_files)),
            }
        )
    return rows


def summarize(
    *,
    args: argparse.Namespace,
    advertiser_count: int,
    input_paths: Sequence[Path],
    candidate_rows: Sequence[Dict[str, str]],
    link_rows: Sequence[Dict[str, object]],
    output_dir: Path,
) -> Dict[str, object]:
    candidate_status_counts: Dict[str, int] = {}
    skip_reason_counts: Dict[str, int] = {}
    link_status_counts: Dict[str, int] = {}
    unmatched_domains: Dict[str, int] = {}
    for row in candidate_rows:
        candidate_status_counts[row["status"]] = candidate_status_counts.get(row["status"], 0) + 1
        if row["skip_reason"]:
            skip_reason_counts[row["skip_reason"]] = skip_reason_counts.get(row["skip_reason"], 0) + 1
        if row["skip_reason"] == "no_awin_advertiser_match" and row["product_domain"]:
            unmatched_domains[row["product_domain"]] = unmatched_domains.get(row["product_domain"], 0) + 1
    for row in link_rows:
        status = str(row.get("status") or "")
        link_status_counts[status] = link_status_counts.get(status, 0) + 1
    return {
        "run_id": output_dir.name,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "dry_run": bool(args.dry_run),
        "supabase_qualified_only": bool(args.supabase_qualified_only),
        "input_root": str(args.input_root),
        "input_csv_count": len(input_paths),
        "advertiser_count": advertiser_count,
        "candidate_rows": len(candidate_rows),
        "unique_link_targets": len(link_rows),
        "candidate_status_counts": candidate_status_counts,
        "skip_reason_counts": skip_reason_counts,
        "link_status_counts": link_status_counts,
        "top_unmatched_domains": sorted(unmatched_domains.items(), key=lambda item: item[1], reverse=True)[:50],
        "output_dir": str(output_dir),
        "outputs": {
            "candidates_csv": str(output_dir / "awin_affiliate_link_candidates.csv"),
            "link_map_csv": str(output_dir / "awin_affiliate_link_map.csv"),
            "summary_json": str(output_dir / "awin_affiliate_link_run_summary.json"),
        },
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate AWIN affiliate tracking links for FWM product URLs in image/review CSV data."
    )
    parser.add_argument("--input-root", type=Path, default=raw_scraped_data_root())
    parser.add_argument("--advertisers-csv", action="append", type=Path, default=[])
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--run-id", default=f"awin_affiliate_links_{utc_now_compact()}")
    parser.add_argument("--publisher-id", default=os.environ.get("AWIN_PUBLISHER_ID", ""))
    parser.add_argument("--access-token", default=os.environ.get("AWIN_ACCESS_TOKEN", ""))
    parser.add_argument("--campaign", default="fwm_product_links")
    parser.add_argument("--clickref-prefix", default="fwm")
    parser.add_argument("--shorten", action="store_true")
    parser.add_argument("--include-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--supabase-qualified-only",
        action="store_true",
        help="Only generate links for rows with image URL, product URL, non-catalog image source, and size/measurement signal.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit unique product URLs sent to AWIN.")
    parser.add_argument("--domain", action="append", default=[], help="Only include this normalized product domain. May repeat.")
    parser.add_argument("--domains-csv", action="append", type=Path, default=[], help="CSV containing domains to include.")
    parser.add_argument("--domains-csv-column", default="normalized_domain", help="Column to read from --domains-csv.")
    parser.add_argument("--single-advertiser-id", default="", help="Generate one AWIN link for this advertiserId.")
    parser.add_argument("--single-destination-url", default="", help="Destination URL for --single-advertiser-id.")
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument("--sleep-seconds", type=float, default=AWIN_MIN_SECONDS_BETWEEN_CALLS)
    parser.add_argument("--max-retries", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if bool(args.single_advertiser_id) != bool(args.single_destination_url):
        raise SystemExit("--single-advertiser-id and --single-destination-url must be provided together.")
    if not args.dry_run and (not args.publisher_id or not args.access_token):
        raise SystemExit("Live AWIN generation requires --publisher-id/--access-token or AWIN_PUBLISHER_ID/AWIN_ACCESS_TOKEN.")

    if args.single_advertiser_id and args.single_destination_url:
        if not is_valid_product_url(args.single_destination_url):
            raise SystemExit("--single-destination-url must be an http(s) URL.")
        target = single_link_target(args.single_advertiser_id, args.single_destination_url)
        link_rows = link_map_rows(
            targets={target.normalized_product_url: target},
            dry_run=args.dry_run,
            publisher_id=args.publisher_id,
            access_token=args.access_token,
            campaign=args.campaign,
            clickref_prefix=args.clickref_prefix,
            shorten=args.shorten,
            request_timeout=args.request_timeout,
            sleep_seconds=0.0,
            max_retries=args.max_retries,
        )
        output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / args.run_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        link_map_csv = output_dir / "awin_affiliate_link_map.csv"
        summary_json = output_dir / "awin_affiliate_link_run_summary.json"
        write_csv(link_map_csv, LINK_MAP_HEADERS, link_rows)
        tracking_url = str(link_rows[0].get("tracking_url") or "")
        summary = {
            "run_id": output_dir.name,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "dry_run": bool(args.dry_run),
            "mode": "single_link",
            "supabase_qualified_only": False,
            "publisher_id_present": bool(args.publisher_id),
            "access_token_present": bool(args.access_token),
            "advertiserId": args.single_advertiser_id,
            "destination_url": args.single_destination_url,
            "status": link_rows[0].get("status"),
            "tracking_url": tracking_url,
            "contains_awinaffid_2928915": "awinaffid=2928915" in tracking_url,
            "contains_awinmid_117505": "awinmid=117505" in tracking_url,
            "output_dir": str(output_dir),
            "outputs": {
                "link_map_csv": str(link_map_csv),
                "summary_json": str(summary_json),
            },
        }
        summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)
        return 0

    advertiser_paths = args.advertisers_csv or DEFAULT_ADVERTISER_CSVS
    advertisers = load_advertisers(advertiser_paths)
    if not advertisers:
        raise SystemExit("No AWIN advertiser metadata loaded. Provide --advertisers-csv with advertiserId and domain columns.")

    input_paths = discover_input_csvs(args.input_root)
    if not input_paths:
        raise SystemExit(f"No input CSVs found under {args.input_root}.")

    domain_filters = {domain_from_url(domain) for domain in args.domain if domain_from_url(domain)}
    domain_filters.update(load_domain_filters(args.domains_csv, args.domains_csv_column))
    candidate_rows, targets = collect_candidates(
        input_paths=input_paths,
        advertisers=advertisers,
        include_existing=args.include_existing,
        supabase_qualified_only=args.supabase_qualified_only,
        domain_filters=domain_filters,
        limit=args.limit,
    )
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / args.run_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    link_rows = link_map_rows(
        targets=targets,
        dry_run=args.dry_run,
        publisher_id=args.publisher_id,
        access_token=args.access_token,
        campaign=args.campaign,
        clickref_prefix=args.clickref_prefix,
        shorten=args.shorten,
        request_timeout=args.request_timeout,
        sleep_seconds=args.sleep_seconds,
        max_retries=args.max_retries,
    )

    candidates_csv = output_dir / "awin_affiliate_link_candidates.csv"
    link_map_csv = output_dir / "awin_affiliate_link_map.csv"
    summary_json = output_dir / "awin_affiliate_link_run_summary.json"
    write_csv(candidates_csv, CANDIDATE_HEADERS, candidate_rows)
    write_csv(link_map_csv, LINK_MAP_HEADERS, link_rows)
    summary = summarize(
        args=args,
        advertiser_count=len(advertisers),
        input_paths=input_paths,
        candidate_rows=candidate_rows,
        link_rows=link_rows,
        output_dir=output_dir,
    )
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
