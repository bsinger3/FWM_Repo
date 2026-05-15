#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from step1_intake_utils import MEASUREMENT_FIELDS, extract_ordered_size


PROJECTS_ROOT = Path("/Users/briannasinger/Projects")
FWM_DATA_ROOT = PROJECTS_ROOT / "FWM_Data"
NON_AMAZON_STEP1_ROOT = FWM_DATA_ROOT / "non-amazon" / "data" / "step_1_raw_scraping_data"
AMAZON_STEP1_ROOT = FWM_DATA_ROOT / "amazon" / "data" / "step_1_raw_scraping_data"

SKIP_DIR_NAMES = {
    "_claims",
    "_lead_runs",
    "_reports",
    "archive",
    "archives",
    "checkpoints",
    "debug",
    "logs",
}

BLANK_SIZE_VALUES = {"", "unknown", "n/a", "na", "none", "null", "nan"}

COMMENT_COLUMNS = [
    "user_comment",
    "body",
    "review_body",
    "review_text",
    "review_comment",
    "comment",
    "View1",
]

SIZE_COLUMNS = [
    "size_ordered",
    "SizeOrdered(generated)",
    "SizeOrdered(comment_deterministic)",
    "size_display",
    "customer_ordered_size",
    "ordered_size",
]

AMAZON_COMMENT_SIZE_COLUMN = "SizeOrdered(comment_deterministic)"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_blank_size(value: object) -> bool:
    return str(value or "").strip().lower() in BLANK_SIZE_VALUES


def choose_column(fieldnames: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    by_lower = {field.lower(): field for field in fieldnames}
    for candidate in candidates:
        found = by_lower.get(candidate.lower())
        if found:
            return found
    return None


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def iter_review_csvs(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.csv")):
        if should_skip(path):
            continue
        yield path


def read_rows(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def write_rows(path: Path, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def qualified_count(rows: List[Dict[str, str]], size_column: str) -> int:
    return sum(
        1
        for row in rows
        if row.get("original_url_display")
        and row.get("product_page_url_display")
        and not is_blank_size(row.get(size_column))
        and any(row.get(field) for field in MEASUREMENT_FIELDS)
    )


def update_adjacent_summary(csv_path: Path, rows: List[Dict[str, str]], size_column: str, updated: int) -> bool:
    stem = csv_path.stem
    suffix = "_summary.json"
    candidates = [csv_path.with_name(f"{stem}_summary.json")]
    for name in (
        stem.replace("_reviews_matching_amazon_schema", "_reviews_matching_intake_schema"),
        stem.replace("_reviews_matching_intake_schema", "_reviews_matching_amazon_schema"),
    ):
        candidates.append(csv_path.with_name(f"{name}{suffix}"))

    summary_path = next((path for path in candidates if path.exists()), None)
    if not summary_path:
        return False

    try:
        with summary_path.open("r", encoding="utf-8") as handle:
            summary = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return False

    summary["rows_with_size"] = sum(1 for row in rows if not is_blank_size(row.get(size_column)))
    summary["rows_with_customer_ordered_size"] = summary["rows_with_size"]
    if "original_url_display" in rows[0] if rows else False:
        summary["supabase_qualified_rows"] = qualified_count(rows, size_column)
        summary["rows_with_image_product_size_and_measurement"] = summary["supabase_qualified_rows"]
    summary["deterministic_comment_size_backfill_applied"] = True
    summary["deterministic_comment_size_backfill_function"] = "step1_intake_utils.extract_ordered_size"
    summary["deterministic_comment_size_backfill_rows_updated"] = updated
    summary["deterministic_comment_size_backfill_updated_at"] = utc_stamp()

    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return True


def process_csv(path: Path, root: Path, dry_run: bool) -> Dict[str, object]:
    fieldnames, rows = read_rows(path)
    comment_column = choose_column(fieldnames, COMMENT_COLUMNS)
    existing_size_column = choose_column(fieldnames, SIZE_COLUMNS)

    if not comment_column:
        return {
            "path": str(path),
            "status": "skipped_no_comment_column",
            "rows": len(rows),
            "updated_rows": 0,
        }

    size_column = existing_size_column
    added_size_column = False
    if not size_column and root == AMAZON_STEP1_ROOT:
        size_column = AMAZON_COMMENT_SIZE_COLUMN
        fieldnames.append(size_column)
        added_size_column = True

    if not size_column:
        return {
            "path": str(path),
            "status": "skipped_no_size_column",
            "rows": len(rows),
            "comment_column": comment_column,
            "updated_rows": 0,
        }

    rows_missing_size = 0
    rows_with_comment = 0
    updated_rows = 0
    examples: List[Dict[str, str]] = []

    for row in rows:
        if added_size_column:
            row.setdefault(size_column, "")
        if not is_blank_size(row.get(size_column)):
            continue
        rows_missing_size += 1
        comment = row.get(comment_column, "")
        if not str(comment or "").strip():
            continue
        rows_with_comment += 1
        extracted = extract_ordered_size(comment)
        if not extracted:
            continue
        row[size_column] = extracted
        updated_rows += 1
        if len(examples) < 5:
            examples.append(
                {
                    "row_id": row.get("id") or row.get("Title_URL") or row.get("product_url") or "",
                    "size": extracted,
                    "comment": str(comment).replace("\n", " ")[:220],
                }
            )

    if updated_rows and not dry_run:
        write_rows(path, fieldnames, rows)

    summary_updated = False
    if updated_rows and not dry_run and existing_size_column == "size_display":
        summary_updated = update_adjacent_summary(path, rows, size_column, updated_rows)

    return {
        "path": str(path),
        "status": "updated" if updated_rows else "no_matches",
        "rows": len(rows),
        "comment_column": comment_column,
        "size_column": size_column,
        "added_size_column": added_size_column,
        "rows_missing_size": rows_missing_size,
        "rows_missing_size_with_comment": rows_with_comment,
        "updated_rows": updated_rows,
        "summary_updated": summary_updated,
        "examples": examples,
    }


def write_audit(results: List[Dict[str, object]], dry_run: bool) -> Tuple[Path, Path]:
    reports_dir = FWM_DATA_ROOT / "_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mode = "dry_run" if dry_run else "applied"
    json_path = reports_dir / f"ordered_size_comment_backfill_{mode}_{stamp}.json"
    csv_path = reports_dir / f"ordered_size_comment_backfill_{mode}_{stamp}.csv"

    payload = {
        "created_at": utc_stamp(),
        "dry_run": dry_run,
        "function": "step1_intake_utils.extract_ordered_size",
        "roots": [str(NON_AMAZON_STEP1_ROOT), str(AMAZON_STEP1_ROOT)],
        "files_scanned": len(results),
        "files_updated": sum(1 for result in results if result.get("updated_rows")),
        "rows_updated": sum(int(result.get("updated_rows") or 0) for result in results),
        "results": results,
    }
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")

    fieldnames = [
        "path",
        "status",
        "rows",
        "comment_column",
        "size_column",
        "added_size_column",
        "rows_missing_size",
        "rows_missing_size_with_comment",
        "updated_rows",
        "summary_updated",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    return json_path, csv_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill structured ordered-size fields from review comments.")
    parser.add_argument("--dry-run", action="store_true", help="Audit possible changes without writing CSVs.")
    args = parser.parse_args()

    results = []
    for root in (NON_AMAZON_STEP1_ROOT, AMAZON_STEP1_ROOT):
        for path in iter_review_csvs(root):
            results.append(process_csv(path, root, args.dry_run))

    json_path, csv_path = write_audit(results, args.dry_run)
    print(
        json.dumps(
            {
                "dry_run": args.dry_run,
                "files_scanned": len(results),
                "files_updated": sum(1 for result in results if result.get("updated_rows")),
                "rows_updated": sum(int(result.get("updated_rows") or 0) for result in results),
                "audit_json": str(json_path),
                "audit_csv": str(csv_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
