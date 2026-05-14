#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Dict, Iterable, List, Sequence, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
NON_AMAZON_UTILS = REPO_ROOT / "data-pipelines" / "non-amazon" / "scripts" / "step_1_raw_scrape"
if str(NON_AMAZON_UTILS) not in sys.path:
    sys.path.insert(0, str(NON_AMAZON_UTILS))

from step1_intake_utils import BUST_RE, extract_measurements, is_weight_change_value  # noqa: E402


DISPLAY_MEASUREMENT_FIELDS: Sequence[str] = (
    "height_in_display",
    "weight_lbs_display",
    "bust_in_display",
    "bra_band_in_display",
    "cupsize_display",
    "waist_in",
    "hips_in_display",
    "age_years_display",
    "inseam_inches_display",
)

MEASUREMENT_UPDATE_PAIRS: Sequence[Tuple[str, str]] = (
    ("height_in_display", "height_raw"),
    ("weight_lbs_display", "weight_raw"),
    ("waist_in", "waist_raw_display"),
    ("hips_in_display", "hips_raw"),
    ("age_years_display", "age_raw"),
    ("inseam_inches_display", ""),
    ("bust_in_display", ""),
    ("bra_band_in_display", ""),
    ("bust_in_number_display", ""),
    ("cupsize_display", ""),
)

NEW_MEASUREMENT_COLUMNS: Sequence[str] = (
    "bust_in_display",
    "bra_band_in_display",
)

REQUIRED_COLUMNS = {"user_comment", "height_in_display", "weight_lbs_display"}
RAW_GENERATED_REQUIRED_COLUMNS = {"View1", "HEIGHT_INCHES(generated)", "weightPounds(generated)"}

RAW_GENERATED_UPDATE_PAIRS: Sequence[Tuple[str, str, str]] = (
    ("height_in_display", "HEIGHT_INCHES(generated)", "heightSnippet(generated)"),
    ("weight_lbs_display", "weightPounds(generated)", ""),
    ("waist_in", "waistHardcoded", "waistSnippet(generated)"),
    ("hips_in_display", "hipsHardcoded", "hipSnippetsGenerated"),
    ("age_years_display", "AgeHardcoded", "yearsSnippetsGenerated"),
    ("inseam_inches_display", "inseamHardcoded", ""),
)


def iter_csv_paths(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.csv")):
        parts = set(path.parts)
        if "archive" in parts or "backup" in parts or "openai_experiments" in parts or "reports" in parts:
            continue
        yield path


def measurement_count(row: Dict[str, str]) -> int:
    count = sum(1 for field in DISPLAY_MEASUREMENT_FIELDS if row.get(field))
    legacy_bust = row.get("bust_in_number_display", "")
    if legacy_bust:
        if row.get("cupsize_display") and not row.get("bra_band_in_display"):
            count += 1
        elif not row.get("cupsize_display") and not row.get("bust_in_display"):
            count += 1
    return count


def should_repair_existing(row: Dict[str, str], extracted: Dict[str, str], display_field: str, raw_field: str) -> bool:
    current = row.get(display_field, "")
    replacement = extracted.get(display_field, "")
    if not current or not replacement or current == replacement:
        return False
    if display_field == "bust_in_number_display":
        return bool(BUST_RE.search(row.get("user_comment", "")))
    if not raw_field:
        return False
    current_raw = row.get(raw_field, "")
    replacement_raw = extracted.get(raw_field, "")
    return bool(replacement_raw and current_raw != replacement_raw)


def add_missing_measurement_columns(fieldnames: Sequence[str]) -> List[str]:
    updated = list(fieldnames)
    insert_at = updated.index("bust_in_number_display") if "bust_in_number_display" in updated else len(updated)
    for column in NEW_MEASUREMENT_COLUMNS:
        if column not in updated:
            updated.insert(insert_at, column)
            insert_at += 1
    return updated


def apply_bust_band_legacy_split(row: Dict[str, str], extracted: Dict[str, str]) -> int:
    updates = 0
    legacy_bust = row.get("bust_in_number_display", "")
    cup_size = row.get("cupsize_display") or extracted.get("cupsize_display", "")
    actual_bust = extracted.get("bust_in_display", "")
    bra_band = extracted.get("bra_band_in_display", "")

    if actual_bust and not row.get("bust_in_display"):
        row["bust_in_display"] = actual_bust
        updates += 1
    elif legacy_bust and not cup_size and not row.get("bust_in_display"):
        row["bust_in_display"] = legacy_bust
        updates += 1

    if bra_band and not row.get("bra_band_in_display"):
        row["bra_band_in_display"] = bra_band
        updates += 1
    elif legacy_bust and cup_size and not row.get("bra_band_in_display"):
        row["bra_band_in_display"] = legacy_bust
        updates += 1

    return updates


def update_row(row: Dict[str, str], *, repair_existing: bool) -> int:
    comment = row.get("user_comment", "")
    if not comment:
        return 0
    extracted = extract_measurements(comment, row.get("size_display", ""))
    updates = 0
    updates += apply_bust_band_legacy_split(row, extracted)
    for display_field, raw_field in MEASUREMENT_UPDATE_PAIRS:
        value = extracted.get(display_field, "")
        if not value:
            continue
        if row.get(display_field):
            if not repair_existing or not should_repair_existing(row, extracted, display_field, raw_field):
                continue
        row[display_field] = value
        updates += 1
        if raw_field and raw_field in row and extracted.get(raw_field):
            row[raw_field] = extracted[raw_field]

    if "weight_display_display" in row and row.get("weight_lbs_display") and not row.get("weight_display_display"):
        row["weight_display_display"] = row["weight_lbs_display"]
    if repair_existing and is_weight_change_value(comment, row.get("weight_lbs_display", "")):
        for field in ("weight_lbs_display", "weight_raw", "weight_display_display"):
            if field in row and row.get(field):
                row[field] = ""
                updates += 1

    for count_field in ("measurement_count_REVIEWONLY", "measurement_count"):
        if count_field not in row:
            continue
        new_count = str(measurement_count(row))
        if row.get(count_field) != new_count:
            row[count_field] = new_count
            updates += 1
    return updates


def update_raw_generated_row(row: Dict[str, str]) -> int:
    comment = row.get("View1", "")
    if not comment:
        return 0
    extracted = extract_measurements(comment, row.get("SizeOrdered(generated)", "") or row.get("asizemini", ""))
    updates = 0
    for source_field, target_field, snippet_field in RAW_GENERATED_UPDATE_PAIRS:
        if target_field not in row:
            continue
        value = extracted.get(source_field, "")
        if not value or row.get(target_field):
            continue
        row[target_field] = value
        updates += 1
        raw_value = extracted.get(
            {
                "height_in_display": "height_raw",
                "waist_in": "waist_raw_display",
                "hips_in_display": "hips_raw",
                "age_years_display": "age_raw",
            }.get(source_field, ""),
            "",
        )
        if snippet_field and snippet_field in row and raw_value and not row.get(snippet_field):
            row[snippet_field] = raw_value
            updates += 1
    if is_weight_change_value(comment, row.get("weightPounds(generated)", "")):
        row["weightPounds(generated)"] = ""
        updates += 1
    return updates


def rewrite_csv(csv_path: Path, *, dry_run: bool, repair_existing: bool) -> Dict[str, int]:
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return {"rows": 0, "rows_updated": 0, "fields_updated": 0, "skipped": 1}
        fieldnames = list(reader.fieldnames)
        is_standardized = REQUIRED_COLUMNS.issubset(fieldnames)
        is_raw_generated = RAW_GENERATED_REQUIRED_COLUMNS.issubset(fieldnames)
        if not is_standardized and not is_raw_generated:
            return {"rows": 0, "rows_updated": 0, "fields_updated": 0, "skipped": 1}
        if is_standardized:
            fieldnames = add_missing_measurement_columns(fieldnames)
        rows = [dict(row) for row in reader]

    rows_updated = 0
    fields_updated = 0
    for row in rows:
        if is_standardized:
            updates = update_row(row, repair_existing=repair_existing)
        else:
            updates = update_raw_generated_row(row)
        if updates:
            rows_updated += 1
            fields_updated += updates

    if fields_updated and not dry_run:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fieldnames})

    return {"rows": len(rows), "rows_updated": rows_updated, "fields_updated": fields_updated, "skipped": 0}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill Amazon structured review measurement columns from deterministic user_comment parsing."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/Users/briannasinger/Projects/FWM_Data/amazon/data"),
        help="Amazon data root to scan for active structured CSVs.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report changes without rewriting CSVs.")
    parser.add_argument(
        "--repair-existing",
        action="store_true",
        help="Also replace existing waist/hip/bust values when deterministic labels in the comment are clearer.",
    )
    args = parser.parse_args()

    totals = {"files": 0, "skipped_files": 0, "rows": 0, "rows_updated": 0, "fields_updated": 0}
    changed_files: List[Tuple[Path, Dict[str, int]]] = []
    for csv_path in iter_csv_paths(args.root):
        stats = rewrite_csv(csv_path, dry_run=args.dry_run, repair_existing=args.repair_existing)
        totals["files"] += 1
        totals["skipped_files"] += stats["skipped"]
        totals["rows"] += stats["rows"]
        totals["rows_updated"] += stats["rows_updated"]
        totals["fields_updated"] += stats["fields_updated"]
        if stats["fields_updated"]:
            changed_files.append((csv_path, stats))

    print(json.dumps(totals, indent=2))
    for csv_path, stats in changed_files:
        print(f"{csv_path}: {stats['rows_updated']} rows, {stats['fields_updated']} fields")


if __name__ == "__main__":
    main()
