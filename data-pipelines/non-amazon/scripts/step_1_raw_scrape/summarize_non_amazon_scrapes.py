#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from step1_intake_utils import BRA_SIZE_RE, MEASUREMENT_FIELDS, STEP1_OUTPUT_ROOT, normalize_whitespace


REPORT_DIR = STEP1_OUTPUT_ROOT.parent / "reports"
REPORT_CSV = REPORT_DIR / "non_amazon_merchant_scrape_summary.csv"
REPORT_MD = REPORT_DIR / "non_amazon_merchant_scrape_summary.md"

REPORT_HEADERS = [
    "merchant",
    "source_site_domain",
    "output_csv_path",
    "summary_json_path",
    "rows_scraped",
    "rows_with_image_url",
    "rows_with_customer_review_image",
    "rows_with_catalog_model_image",
    "distinct_review_ids",
    "distinct_image_urls",
    "distinct_product_urls",
    "rows_with_user_comment",
    "rows_with_size_display",
    "rows_with_customer_ordered_size",
    "rows_with_any_measurement",
    "rows_for_bra_products",
    "rows_for_bra_products_with_customer_bra_size",
    "rows_with_product_context",
    "rows_missing_image_url",
    "rows_missing_product_url",
    "rows_with_image_and_product_url",
    "rows_with_image_product_and_measurement",
    "rows_with_image_product_size_and_measurement",
    "rows_with_image_product_and_user_comment",
    "products_discovered",
    "product_pages_scanned",
    "seed_url_count",
    "discovery_method",
    "scrape_scope_status",
    "full_catalog_scrape_complete",
    "aggregate_feed_used",
    "latest_fetched_or_finished_at",
    "dataset_kind",
    "notes",
]


def optional_openpyxl():
    try:
        import openpyxl  # type: ignore

        return openpyxl
    except Exception:
        return None


def read_csv_rows(path: Path) -> Tuple[List[Dict[str, str]], List[str], str]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            rows = [{key or "": value or "" for key, value in row.items()} for row in reader]
            return rows, list(reader.fieldnames or []), ""
    except Exception as exc:
        return [], [], f"csv read failed: {exc}"


def read_xlsx_rows(path: Path) -> Tuple[List[Dict[str, str]], List[str], str]:
    openpyxl = optional_openpyxl()
    if openpyxl is None:
        return [], [], "legacy spreadsheet-only; install/use bundled openpyxl runtime to inspect row stats"
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        row_iter = ws.iter_rows(values_only=True)
        headers = [normalize_whitespace(value) for value in next(row_iter)]
        rows: List[Dict[str, str]] = []
        for values in row_iter:
            row = {headers[index]: normalize_whitespace(value) for index, value in enumerate(values or []) if index < len(headers)}
            if any(row.values()):
                rows.append(row)
        return rows, headers, ""
    except Exception as exc:
        return [], [], f"xlsx read failed: {exc}"


def summary_rows_written(data_file: Path) -> Optional[int]:
    exact = data_file.with_name(data_file.stem + "_summary.json")
    if not exact.exists():
        return None
    try:
        payload = json.loads(exact.read_text(encoding="utf-8"))
    except Exception:
        return None
    value = payload.get("rows_written")
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def find_best_data_file(merchant_dir: Path) -> Tuple[Optional[Path], str, List[str]]:
    notes: List[str] = []
    preferred = sorted(merchant_dir.glob("*_reviews_matching_intake_schema.csv"))
    if preferred:
        rows_written = summary_rows_written(preferred[0])
        if rows_written is None or rows_written > 0:
            return preferred[0], "current_intake_csv", notes
        notes.append("current intake csv has 0 rows; reporting best legacy data file instead")
    legacy_csv = sorted(merchant_dir.glob("*_reviews_matching_amazon_schema.csv"))
    if legacy_csv:
        return legacy_csv[0], "legacy_review_csv", notes
    any_csv = sorted(path for path in merchant_dir.glob("*.csv") if path.name.lower() not in {"_drive_download_log.csv"})
    if any_csv:
        non_empty_csv = [path for path in any_csv if path not in preferred]
        if non_empty_csv:
            return non_empty_csv[0], "legacy_csv", notes
    any_xlsx = sorted(merchant_dir.glob("*.xlsx"))
    if any_xlsx:
        return any_xlsx[0], "legacy_spreadsheet", notes
    return None, "no_readable_table", notes


def find_summary_file(merchant_dir: Path, data_file: Optional[Path]) -> Optional[Path]:
    if data_file:
        exact = data_file.with_name(data_file.stem + "_summary.json")
        if exact.exists():
            return exact
    summaries = sorted(merchant_dir.glob("*summary.json"))
    return summaries[0] if summaries else None


def get_value(row: Dict[str, str], candidates: Sequence[str]) -> str:
    lower = {key.lower(): value for key, value in row.items()}
    for candidate in candidates:
        value = row.get(candidate)
        if value:
            return value
        value = lower.get(candidate.lower())
        if value:
            return value
    return ""


def has_any_measurement(row: Dict[str, str]) -> bool:
    return any(get_value(row, [field]) for field in MEASUREMENT_FIELDS)


def has_product_context(row: Dict[str, str]) -> bool:
    return bool(
        get_value(
            row,
            [
                "product_title_raw",
                "product_description_raw",
                "product_detail_raw",
                "product_title",
                "product_name",
                "title",
                "description",
            ],
        )
    )


def is_bra_product_row(row: Dict[str, str]) -> bool:
    clothing_type = get_value(row, ["clothing_type_id", "clothing_type"])
    title = get_value(row, ["product_title_raw", "product_title", "product_name", "title"])
    return clothing_type == "bra" or bool(title and re.search(r"\bbras?|bralettes?\b", title, re.I))


def has_customer_bra_size(row: Dict[str, str]) -> bool:
    band = get_value(row, ["bust_in_number_display", "bra_band", "band_size"])
    cup = get_value(row, ["cupsize_display", "cup_size"])
    size = get_value(row, ["size_display", "size", "reviewed size", "size ordered"])
    return bool((band and cup) or BRA_SIZE_RE.search(size))


def summarize_merchant(merchant_dir: Path) -> Dict[str, str]:
    data_file, dataset_kind, selection_notes = find_best_data_file(merchant_dir)
    summary_file = find_summary_file(merchant_dir, data_file)
    notes: List[str] = list(selection_notes)
    rows: List[Dict[str, str]] = []
    headers: List[str] = []
    if data_file is None:
        notes.append("no csv/xlsx data file found")
    elif data_file.suffix.lower() == ".csv":
        rows, headers, note = read_csv_rows(data_file)
        if note:
            notes.append(note)
    elif data_file.suffix.lower() == ".xlsx":
        rows, headers, note = read_xlsx_rows(data_file)
        if note:
            notes.append(note)

    summary_payload: Dict[str, object] = {}
    if summary_file:
        try:
            summary_payload = json.loads(summary_file.read_text(encoding="utf-8"))
        except Exception as exc:
            notes.append(f"summary json read failed: {exc}")
    else:
        notes.append("missing summary json")

    known_headers = {
        "original_url_display",
        "product_page_url_display",
        "monetized_product_url_display",
        "user_comment",
        "size_display",
        "product_title_raw",
        "product_description_raw",
    }
    if headers and not any(header in known_headers for header in headers):
        notes.append("nonstandard columns")
    if dataset_kind.startswith("legacy"):
        notes.append(dataset_kind)
    scrape_scope_status = normalize_whitespace(summary_payload.get("scrape_scope_status"))
    if scrape_scope_status and scrape_scope_status != "full_catalog_attempted":
        notes.append(scrape_scope_status)
    if summary_payload.get("full_catalog_scrape_complete") is False:
        notes.append("still needs full scrape")
    if summary_payload.get("aggregate_feed_used") is True:
        notes.append("aggregate_feed_used")

    image_values = {
        get_value(row, ["original_url_display", "image_url", "image", "photo_url", "review_image_url"])
        for row in rows
        if get_value(row, ["original_url_display", "image_url", "image", "photo_url", "review_image_url"])
    }
    customer_review_image_rows = [
        row
        for row in rows
        if get_value(row, ["original_url_display", "image_url", "image", "photo_url", "review_image_url"])
        and (get_value(row, ["image_source_type"]) or "customer_review_image") == "customer_review_image"
    ]
    catalog_model_image_rows = [
        row
        for row in rows
        if get_value(row, ["original_url_display", "image_url", "image", "photo_url", "review_image_url"])
        and get_value(row, ["image_source_type"]) == "catalog_model_image"
    ]
    product_values = {
        get_value(row, ["product_page_url_display", "monetized_product_url_display", "product_url", "product link", "link"])
        for row in rows
        if get_value(row, ["product_page_url_display", "monetized_product_url_display", "product_url", "product link", "link"])
    }
    review_ids = {get_value(row, ["id", "review_id", "review id"]) for row in rows if get_value(row, ["id", "review_id", "review id"])}
    rows_with_image = [row for row in rows if get_value(row, ["original_url_display", "image_url", "image", "photo_url", "review_image_url"])]
    rows_with_product = [
        row
        for row in rows
        if get_value(row, ["product_page_url_display", "monetized_product_url_display", "product_url", "product link", "link"])
    ]
    rows_with_image_product = [
        row
        for row in rows
        if get_value(row, ["original_url_display", "image_url", "image", "photo_url", "review_image_url"])
        and get_value(row, ["product_page_url_display", "monetized_product_url_display", "product_url", "product link", "link"])
    ]
    bra_product_rows = [row for row in rows if is_bra_product_row(row)]
    fetched_values = [
        get_value(row, ["fetched_at", "updated_at", "review_date", "date_review_submitted_raw"])
        for row in rows
        if get_value(row, ["fetched_at", "updated_at", "review_date", "date_review_submitted_raw"])
    ]
    latest = normalize_whitespace(summary_payload.get("finished_at")) or (max(fetched_values) if fetched_values else "")
    source_site = normalize_whitespace(summary_payload.get("site")) or next(iter(product_values), "")

    return {
        "merchant": merchant_dir.name,
        "source_site_domain": source_site,
        "output_csv_path": str(data_file) if data_file and data_file.suffix.lower() == ".csv" else "",
        "summary_json_path": str(summary_file) if summary_file else "",
        "rows_scraped": str(len(rows) or summary_payload.get("rows_written") or ""),
        "rows_with_image_url": str(len(rows_with_image) or summary_payload.get("rows_with_image_url") or ""),
        "rows_with_customer_review_image": str(
            len(customer_review_image_rows) or summary_payload.get("rows_with_customer_review_image") or ""
        ),
        "rows_with_catalog_model_image": str(
            len(catalog_model_image_rows) or summary_payload.get("rows_with_catalog_model_image") or ""
        ),
        "distinct_review_ids": str(len(review_ids) or summary_payload.get("distinct_reviews") or ""),
        "distinct_image_urls": str(len(image_values) or summary_payload.get("distinct_images") or ""),
        "distinct_product_urls": str(len(product_values) or summary_payload.get("distinct_products") or ""),
        "rows_with_user_comment": str(sum(1 for row in rows if get_value(row, ["user_comment", "review", "review_text", "body", "comment"]))),
        "rows_with_size_display": str(sum(1 for row in rows if get_value(row, ["size_display", "size", "reviewed size", "size ordered"]))),
        "rows_with_customer_ordered_size": str(
            sum(1 for row in rows if get_value(row, ["size_display", "size", "reviewed size", "size ordered"]))
            if rows
            else summary_payload.get("rows_with_customer_ordered_size") or ""
        ),
        "rows_with_any_measurement": str(sum(1 for row in rows if has_any_measurement(row))),
        "rows_for_bra_products": str(
            len(bra_product_rows) if rows else summary_payload.get("rows_for_bra_products") or ""
        ),
        "rows_for_bra_products_with_customer_bra_size": str(
            sum(1 for row in bra_product_rows if has_customer_bra_size(row))
            if rows
            else summary_payload.get("rows_for_bra_products_with_customer_bra_size") or ""
        ),
        "rows_with_product_context": str(sum(1 for row in rows if has_product_context(row))),
        "rows_missing_image_url": str((len(rows) - len(rows_with_image)) if rows else summary_payload.get("rows_missing_image_url") or ""),
        "rows_missing_product_url": str((len(rows) - len(rows_with_product)) if rows else summary_payload.get("rows_missing_product_url") or ""),
        "rows_with_image_and_product_url": str(
            len(rows_with_image_product) or summary_payload.get("rows_with_image_and_product_url") or ""
        ),
        "rows_with_image_product_and_measurement": str(
            sum(1 for row in rows_with_image_product if has_any_measurement(row))
            or summary_payload.get("rows_with_image_product_and_measurement")
            or ""
        ),
        "rows_with_image_product_size_and_measurement": str(
            sum(
                1
                for row in rows_with_image_product
                if get_value(row, ["size_display", "size", "reviewed size", "size ordered"]) and has_any_measurement(row)
            )
            if rows
            else summary_payload.get("rows_with_image_product_size_and_measurement") or ""
        ),
        "rows_with_image_product_and_user_comment": str(
            sum(1 for row in rows_with_image_product if get_value(row, ["user_comment", "review", "review_text", "body", "comment"]))
            or summary_payload.get("rows_with_image_product_and_user_comment")
            or ""
        ),
        "products_discovered": str(summary_payload.get("products_discovered") or summary_payload.get("products_scanned") or ""),
        "product_pages_scanned": str(summary_payload.get("product_pages_scanned") or summary_payload.get("products_scanned") or ""),
        "seed_url_count": str(summary_payload.get("seed_url_count") or ""),
        "discovery_method": normalize_whitespace(summary_payload.get("discovery_method")),
        "scrape_scope_status": scrape_scope_status,
        "full_catalog_scrape_complete": str(summary_payload.get("full_catalog_scrape_complete") if "full_catalog_scrape_complete" in summary_payload else ""),
        "aggregate_feed_used": str(summary_payload.get("aggregate_feed_used") if "aggregate_feed_used" in summary_payload else ""),
        "latest_fetched_or_finished_at": latest,
        "dataset_kind": dataset_kind,
        "notes": "; ".join(dict.fromkeys(notes)),
    }


def write_csv(rows: Sequence[Dict[str, str]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in REPORT_HEADERS})


def write_markdown(rows: Sequence[Dict[str, str]], output_md: Path) -> None:
    output_md.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Non-Amazon Merchant Scrape Summary",
        "",
        "| Merchant | Rows | Images | Catalog Model Images | Reviews | Products | Scanned | Scope | Comments | Ordered Size | Measurements | Qualified Fit Rows | Bra Rows | Bra Rows w/ Bra Size | Image+Product | Image+Product+Measurement | Missing Product URL | Context | Kind | Notes |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {merchant} | {rows} | {images} | {catalog_model_images} | {reviews} | {products} | {scanned} | {scope} | {comments} | {ordered_size} | {measurements} | {qualified_fit_rows} | {bra_rows} | {bra_size_rows} | {image_product} | {image_product_measurement} | {missing_product} | {context} | {kind} | {notes} |".format(
                merchant=md_cell(row["merchant"]),
                rows=row["rows_scraped"] or "0",
                images=row["distinct_image_urls"] or "0",
                catalog_model_images=row["rows_with_catalog_model_image"] or "0",
                reviews=row["distinct_review_ids"] or "0",
                products=row["distinct_product_urls"] or "0",
                scanned=row["product_pages_scanned"] or row["products_discovered"] or "",
                scope=md_cell(row["scrape_scope_status"]),
                comments=row["rows_with_user_comment"] or "0",
                ordered_size=row["rows_with_customer_ordered_size"] or row["rows_with_size_display"] or "0",
                measurements=row["rows_with_any_measurement"] or "0",
                qualified_fit_rows=row["rows_with_image_product_size_and_measurement"] or "0",
                bra_rows=row["rows_for_bra_products"] or "0",
                bra_size_rows=row["rows_for_bra_products_with_customer_bra_size"] or "0",
                image_product=row["rows_with_image_and_product_url"] or "0",
                image_product_measurement=row["rows_with_image_product_and_measurement"] or "0",
                missing_product=row["rows_missing_product_url"] or "0",
                context=row["rows_with_product_context"] or "0",
                kind=md_cell(row["dataset_kind"]),
                notes=md_cell(row["notes"]),
            )
        )
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def md_cell(value: str) -> str:
    return normalize_whitespace(value).replace("|", "\\|")


def build_report(root: Path) -> List[Dict[str, str]]:
    merchant_dirs = sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith("_"))
    rows = [summarize_merchant(path) for path in merchant_dirs]
    rows.sort(key=lambda row: int(row["rows_scraped"] or 0), reverse=True)
    return rows


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize non-Amazon Step 1 scrape volume by merchant.")
    parser.add_argument("--root", type=Path, default=STEP1_OUTPUT_ROOT)
    parser.add_argument("--csv", type=Path, default=REPORT_CSV)
    parser.add_argument("--md", type=Path, default=REPORT_MD)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    rows = build_report(args.root)
    write_csv(rows, args.csv)
    write_markdown(rows, args.md)
    print(f"Wrote {len(rows)} merchant rows to {args.csv}")
    print(f"Wrote markdown report to {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
