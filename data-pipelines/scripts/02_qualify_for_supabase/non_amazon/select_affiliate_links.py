#!/usr/bin/env python3
"""Select AWIN vs Sovrn monetization candidates for qualified scrape rows."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from generate_awin_affiliate_links import (  # noqa: E402
    DEFAULT_ADVERTISER_CSVS,
    clean,
    collect_candidates,
    discover_input_csvs,
    domain_from_url,
    load_advertisers,
    load_domain_filters,
    normalize_product_url,
)
from pipeline_paths import raw_scraped_data_root, reports_root  # noqa: E402


SOVRN_CANDIDATES = REPO_ROOT / "data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv"
SOVRN_TRACKER = REPO_ROOT / "data-pipelines/docs/sovrn_commerce/sovrn_commerce_apparel_triage_tracker.csv"
DEFAULT_OUTPUT_ROOT = reports_root() / "affiliate_links" / "selection"


@dataclass
class SovrnMerchant:
    domain: str
    merchant_group: str = ""
    pricing: str = ""
    estimated_commission_per_click: str = ""
    priority: str = ""
    payout_priority_rank: str = ""
    source_csv: str = ""


def utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_csv(path: Path) -> Iterable[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def domain_variants(domain: str) -> Iterable[str]:
    current = domain.lower().strip(".")
    while current:
        yield current
        if "." not in current:
            break
        current = current.split(".", 1)[1]


def parse_money(value: str) -> Optional[float]:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_rank(value: str) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return 999_999


def parse_awin_epc(value: str) -> Optional[float]:
    parsed = parse_money(value)
    if parsed is None:
        return None
    # AWIN exports are treated as ranking values until the exact unit is pinned
    # in each source export; this preserves comparability without inventing money.
    return parsed


def load_sovrn_merchants(paths: Sequence[Path]) -> Dict[str, SovrnMerchant]:
    merchants: Dict[str, SovrnMerchant] = {}
    for path in paths:
        for row in read_csv(path):
            domains = clean(row.get("primary_domain") or row.get("primary_domains"))
            for domain_text in re.split(r"[;,|]", domains):
                domain = domain_from_url(domain_text)
                if not domain:
                    continue
                candidate = SovrnMerchant(
                    domain=domain,
                    merchant_group=clean(row.get("merchant_group")),
                    pricing=clean(row.get("pricing")),
                    estimated_commission_per_click=clean(row.get("estimated_commission_per_click")),
                    priority=clean(row.get("priority")),
                    payout_priority_rank=clean(row.get("payout_priority_rank")),
                    source_csv=str(path),
                )
                current = merchants.get(domain)
                if current is None or parse_rank(candidate.payout_priority_rank) < parse_rank(current.payout_priority_rank):
                    merchants[domain] = candidate
    return merchants


def load_awin_epc_by_advertiser_id(paths: Sequence[Path]) -> Dict[str, float]:
    epc_by_id: Dict[str, float] = {}
    for path in paths:
        for row in read_csv(path):
            advertiser_id = clean(row.get("advertiserId"))
            epc = parse_awin_epc(row.get("epc", ""))
            if advertiser_id and epc is not None and advertiser_id not in epc_by_id:
                epc_by_id[advertiser_id] = epc
    return epc_by_id


def match_sovrn(product_domain: str, merchants: Dict[str, SovrnMerchant]) -> tuple[str, Optional[SovrnMerchant]]:
    for candidate in domain_variants(product_domain):
        merchant = merchants.get(candidate)
        if merchant:
            return candidate, merchant
    return "", None


def select_network(
    awin_available: bool,
    awin_epc: Optional[float],
    sovrn: Optional[SovrnMerchant],
    sovrn_epc: Optional[float],
) -> tuple[str, str, str]:
    sovrn_available = sovrn is not None
    if awin_epc is not None and sovrn_epc is not None:
        if awin_epc > sovrn_epc:
            return "awin", "awin_epc_gt_sovrn", f"{awin_epc}>{sovrn_epc}"
        if sovrn_epc > awin_epc:
            return "sovrn", "sovrn_epc_gt_awin", f"{sovrn_epc}>{awin_epc}"
        return "awin", "epc_tie_prefers_live_awin_generation", f"{awin_epc}={sovrn_epc}"
    if awin_available and not sovrn_available:
        return "awin", "awin_only", ""
    if sovrn_available and not awin_available:
        return "sovrn", "sovrn_only", ""
    if awin_available and sovrn_available:
        pricing = (sovrn.pricing or "").upper() if sovrn else ""
        if awin_epc is not None:
            return "awin", "awin_epc_known_sovrn_unknown", str(awin_epc)
        if sovrn_epc is not None:
            return "sovrn", "sovrn_epc_known_awin_unknown", str(sovrn_epc)
        if "CPA+CPC" in pricing or "CPA" in pricing:
            return "awin", "both_unknown_prefers_approved_awin_before_sovrn_pricing", pricing
        return "review", "both_available_unknown_payout", ""
    return "none", "no_affiliate_match", ""


def write_csv(path: Path, headers: Sequence[str], rows: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(headers))
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select AWIN vs Sovrn affiliate candidates for qualified rows.")
    parser.add_argument("--input-root", type=Path, default=raw_scraped_data_root())
    parser.add_argument("--advertisers-csv", action="append", type=Path, default=[])
    parser.add_argument("--sovrn-csv", action="append", type=Path, default=[])
    parser.add_argument("--domains-csv", action="append", type=Path, default=[])
    parser.add_argument("--domains-csv-column", default="normalized_domain")
    parser.add_argument("--domain", action="append", default=[])
    parser.add_argument("--include-unqualified", action="store_true")
    parser.add_argument("--include-existing", action="store_true")
    parser.add_argument("--run-id", default=f"affiliate_selection_{utc_now_compact()}")
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    advertiser_paths = args.advertisers_csv or DEFAULT_ADVERTISER_CSVS
    advertisers = load_advertisers(advertiser_paths)
    awin_epc_by_id = load_awin_epc_by_advertiser_id(advertiser_paths)
    sovrn_merchants = load_sovrn_merchants(args.sovrn_csv or [SOVRN_CANDIDATES, SOVRN_TRACKER])
    domain_filters = {domain_from_url(domain) for domain in args.domain if domain_from_url(domain)}
    domain_filters.update(load_domain_filters(args.domains_csv, args.domains_csv_column))
    input_paths = discover_input_csvs(args.input_root)
    candidate_rows, _targets = collect_candidates(
        input_paths=input_paths,
        advertisers=advertisers,
        include_existing=args.include_existing,
        supabase_qualified_only=not args.include_unqualified,
        domain_filters=domain_filters,
        limit=0,
    )

    row_outputs: list[dict[str, object]] = []
    map_by_url: dict[str, dict[str, object]] = {}
    for row in candidate_rows:
        normalized_url = row.get("normalized_product_url", "")
        if not normalized_url:
            continue
        product_domain = row.get("product_domain", "")
        awin_advertiser = advertisers.get(row.get("matched_domain", ""))
        awin_epc = None
        if awin_advertiser:
            awin_epc = awin_epc_by_id.get(awin_advertiser.advertiser_id)
        sovrn_domain, sovrn = match_sovrn(product_domain, sovrn_merchants)
        sovrn_epc = parse_money(sovrn.estimated_commission_per_click) if sovrn else None
        selected_network, selected_reason, selected_detail = select_network(bool(awin_advertiser), awin_epc, sovrn, sovrn_epc)
        output = {
            **row,
            "awin_available": "yes" if awin_advertiser else "no",
            "awin_epc": "" if awin_epc is None else awin_epc,
            "sovrn_available": "yes" if sovrn else "no",
            "sovrn_matched_domain": sovrn_domain,
            "sovrn_merchant_group": sovrn.merchant_group if sovrn else "",
            "sovrn_pricing": sovrn.pricing if sovrn else "",
            "sovrn_estimated_commission_per_click": "" if sovrn_epc is None else sovrn_epc,
            "selected_network": selected_network,
            "selected_reason": selected_reason,
            "selected_detail": selected_detail,
        }
        row_outputs.append(output)
        current = map_by_url.get(normalized_url)
        if current is None:
            map_by_url[normalized_url] = output

    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / args.run_id)
    row_headers = list(row_outputs[0].keys()) if row_outputs else []
    map_rows = list(map_by_url.values())
    write_csv(output_dir / "affiliate_link_candidates.csv", row_headers, row_outputs)
    write_csv(output_dir / "affiliate_link_map.csv", row_headers, map_rows)
    network_counts: dict[str, int] = {}
    for row in map_rows:
        network = str(row.get("selected_network") or "")
        network_counts[network] = network_counts.get(network, 0) + 1
    summary = {
        "run_id": output_dir.name,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "input_root": str(args.input_root),
        "source_csv_count": len(input_paths),
        "candidate_rows": len(row_outputs),
        "unique_product_urls": len(map_rows),
        "selected_network_counts": network_counts,
        "output_dir": str(output_dir),
    }
    (output_dir / "affiliate_link_run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
