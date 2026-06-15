#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from scrape_p0_lead_reviews import scrape_domain
from step1_intake_utils import (
    discover_shopify_product_urls,
    fetch_json,
    normalize_whitespace,
    output_paths,
    retailer_slug,
    utc_now,
)


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
DEFAULT_QUEUE_CSV = (
    REPO_ROOT
    / "outputs"
    / "measurement_coverage"
    / "20260609_human_labeled_approved_only"
    / "affiliate_network_leads"
    / "awin_scrape_work_queue.csv"
)
DEFAULT_RUN_DIR = DEFAULT_QUEUE_CSV.parent
CLAIMS_DIR = REPO_ROOT / "_claims"
ACTIVE_CLAIMS_DIR = REPO_ROOT / "_active_scrape_claims"

PROVIDER_PRIORITY = {
    "Okendo": 10,
    "Loox": 20,
    "Judge.me": 30,
    "Stamped": 40,
    "Yotpo": 50,
    "Bazaarvoice": 60,
}


def read_queue(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return sorted(
        rows,
        key=lambda row: (
            PROVIDER_PRIORITY.get(row.get("review_providers", ""), 999),
            int(row.get("apply_order") or 9999),
        ),
    )


def write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "started_at",
        "finished_at",
        "domain",
        "programme_name",
        "provider",
        "status",
        "rows",
        "errors_count",
        "output_csv",
        "summary_json",
        "claim_file",
        "error",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})


def bounded_shopify_seed_urls(domain: str, limit: int) -> List[str]:
    if limit <= 0:
        return []
    root = f"https://{domain}".rstrip("/")
    urls: List[str] = []
    seen = set()
    for page in range(1, 10000):
        if len(urls) >= limit:
            break
        api_url = f"{root}/products.json?limit=250&page={page}"
        try:
            payload = fetch_json(api_url, referer=root, retries=1)
        except Exception:
            break
        products = payload.get("products")
        if not isinstance(products, list) or not products:
            break
        for product in products:
            if not isinstance(product, dict):
                continue
            handle = normalize_whitespace(product.get("handle"))
            if not handle or handle in seen:
                continue
            seen.add(handle)
            urls.append(f"{root}/products/{handle}")
            if len(urls) >= limit:
                break
        if len(products) < 250:
            break
    if urls:
        return urls
    return discover_shopify_product_urls(root, [])[:limit]


def claim_text(
    *,
    row: Dict[str, str],
    started_at: str,
    finished_at: str,
    status: str,
    output_csv: str = "",
    summary_json: str = "",
    rows_written: object = "",
    error: str = "",
) -> str:
    domain = row.get("normalized_domain", "")
    slug = retailer_slug(domain)
    lines = [
        f"retailer: {slug}",
        f"site: {domain}",
        f"claimed_at: {started_at}",
        f"completed_at: {finished_at}",
        f"status: {status}",
        "source: Awin advertiser queue",
        f"programme: {row.get('programmeName', '')}",
        f"provider_hint: {row.get('review_providers', '')}",
        f"why_request: {row.get('why_request', '')}",
        "scope: public product pages and public review/provider feeds only",
        "stop_conditions: 429/captcha/WAF/auth challenge",
        f"rows_written: {rows_written}",
        f"output_csv: {output_csv}",
        f"summary_json: {summary_json}",
    ]
    if error:
        lines.append(f"error: {error}")
    return "\n".join(lines) + "\n"


def existing_summary(domain: str) -> Optional[Path]:
    _, summary_json = output_paths(domain)
    return summary_json if summary_json.exists() else None


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape public review-image rows for merchants in the Awin affiliate queue."
    )
    parser.add_argument("--queue-csv", type=Path, default=DEFAULT_QUEUE_CSV)
    parser.add_argument("--run-label", default="awin_affiliate_scrape_2026-06-10")
    parser.add_argument("--provider", action="append", dest="providers", help="Provider name to include. May repeat.")
    parser.add_argument("--domain", action="append", dest="domains", help="Specific domain to scrape. May repeat.")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--seed-products",
        type=int,
        default=0,
        help="Use a bounded products.json seed-only scrape with this many product URLs per merchant.",
    )
    parser.add_argument("--include-existing", action="store_true", help="Re-run domains with existing summary output.")
    parser.add_argument("--skip-yotpo-product-pass", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    providers = set(args.providers or [])
    domains = set(args.domains or [])
    rows = read_queue(args.queue_csv)
    if providers:
        rows = [row for row in rows if row.get("review_providers") in providers]
    if domains:
        rows = [row for row in rows if row.get("normalized_domain") in domains]
    if args.limit > 0:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("No matching Awin queue rows to scrape.")

    ACTIVE_CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
    CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
    run_rows: List[Dict[str, object]] = []
    exit_code = 0

    for row in rows:
        domain = row.get("normalized_domain", "").strip()
        started_at = utc_now()
        slug = retailer_slug(domain)
        active_claim = ACTIVE_CLAIMS_DIR / f"{slug}.claim"
        completed_claim = CLAIMS_DIR / f"{slug}_2026-06-10_awin.claim"
        output_csv, summary_json = output_paths(domain)

        if not args.include_existing and existing_summary(domain):
            finished_at = utc_now()
            run_rows.append(
                {
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "domain": domain,
                    "programme_name": row.get("programmeName", ""),
                    "provider": row.get("review_providers", ""),
                    "status": "skipped_existing_output",
                    "rows": "",
                    "errors_count": "",
                    "output_csv": str(output_csv),
                    "summary_json": str(summary_json),
                    "claim_file": "",
                    "error": "",
                }
            )
            continue

        active_claim.write_text(
            claim_text(
                row=row,
                started_at=started_at,
                finished_at="",
                status="active",
            ),
            encoding="utf-8",
        )
        print(f"[awin] scraping {domain} ({row.get('review_providers', '')})", flush=True)
        status = "completed"
        error = ""
        summary: Dict[str, object] = {}
        try:
            seed_urls = bounded_shopify_seed_urls(domain, args.seed_products)
            if args.seed_products and not seed_urls:
                status = "no_public_product_seed"
                error = "No product seed URLs discovered; likely products.json/sitemap unavailable or rate-limited."
                summary = {
                    "error": error,
                    "output_csv": str(output_csv),
                    "summary_json": str(summary_json),
                    "rows": 0,
                    "errors": [error],
                }
            else:
                _, summary = scrape_domain(
                    domain,
                    seed_urls,
                    only_seed_products=bool(args.seed_products),
                    include_yotpo_product_pass=not args.skip_yotpo_product_pass,
                )
        except Exception as exc:
            status = "failed"
            error = str(exc)
            summary = {"error": error, "output_csv": str(output_csv), "summary_json": str(summary_json), "rows": 0}
            exit_code = 1
        finally:
            finished_at = utc_now()
            errors = summary.get("errors") if isinstance(summary.get("errors"), list) else []
            completed_claim.write_text(
                claim_text(
                    row=row,
                    started_at=started_at,
                    finished_at=finished_at,
                    status=status,
                    output_csv=str(summary.get("output_csv") or output_csv),
                    summary_json=str(summary.get("summary_json") or summary_json),
                    rows_written=summary.get("rows", ""),
                    error=error,
                ),
                encoding="utf-8",
            )
            try:
                active_claim.unlink()
            except FileNotFoundError:
                pass
            run_rows.append(
                {
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "domain": domain,
                    "programme_name": row.get("programmeName", ""),
                    "provider": row.get("review_providers", ""),
                    "status": status,
                    "rows": summary.get("rows", 0),
                    "errors_count": len(errors) if not error else 1,
                    "output_csv": str(summary.get("output_csv") or output_csv),
                    "summary_json": str(summary.get("summary_json") or summary_json),
                    "claim_file": str(completed_claim),
                    "error": error,
                }
            )
            write_csv(DEFAULT_RUN_DIR / f"{args.run_label}_run_log.csv", run_rows)

    run_json = DEFAULT_RUN_DIR / f"{args.run_label}_run_log.json"
    run_json.write_text(json.dumps(run_rows, indent=2), encoding="utf-8")
    print(json.dumps(run_rows, indent=2), flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
