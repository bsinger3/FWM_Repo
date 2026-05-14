#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Dict, Iterable, List, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from step1_intake_utils import BUST_RE, MEASUREMENT_FIELDS, extract_measurements, is_weight_change_value, validate_rows  # noqa: E402


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


def iter_csv_paths(root: Path) -> Iterable[Path]:
    patterns = ("*reviews_matching_intake_schema.csv", "*reviews_matching_amazon_schema.csv")
    seen = set()
    for pattern in patterns:
        for path in root.rglob(pattern):
            if path in seen:
                continue
            seen.add(path)
            yield path


def summary_path_for(csv_path: Path) -> Path:
    name = csv_path.name
    if name.endswith(".csv"):
        return csv_path.with_name(f"{name[:-4]}_summary.json")
    return csv_path.with_suffix(".json")


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


def backfill_row(row: Dict[str, str], *, repair_existing: bool = False) -> Tuple[Dict[str, str], int]:
    comment = row.get("user_comment", "")
    if not comment:
        return row, 0
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
    if "weight_display_display" in row and not row.get("weight_display_display") and row.get("weight_lbs_display"):
        row["weight_display_display"] = row["weight_lbs_display"]
    if repair_existing and is_weight_change_value(comment, row.get("weight_lbs_display", "")):
        for field in ("weight_lbs_display", "weight_raw", "weight_display_display"):
            if field in row and row.get(field):
                row[field] = ""
                updates += 1
    return row, updates


def rewrite_csv(csv_path: Path, *, dry_run: bool = False, repair_existing: bool = False) -> Dict[str, int]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return {"rows": 0, "rows_updated": 0, "fields_added": 0}
        fieldnames = add_missing_measurement_columns(reader.fieldnames)
        rows = [dict(row) for row in reader]

    rows_updated = 0
    fields_added = 0
    for row in rows:
        _, updates = backfill_row(row, repair_existing=repair_existing)
        if updates:
            rows_updated += 1
            fields_added += updates

    if not dry_run and fields_added:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fieldnames})
        update_summary(csv_path, rows)

    return {"rows": len(rows), "rows_updated": rows_updated, "fields_added": fields_added}


def update_summary(csv_path: Path, rows: List[Dict[str, str]]) -> None:
    summary_path = summary_path_for(csv_path)
    if not summary_path.exists():
        return
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    validation = validate_rows(rows)
    payload.update(validation)
    summary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill structured body measurements in existing review CSVs from deterministic comment parsing."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data"),
        help="Root containing retailer review CSV outputs.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report additions without rewriting CSVs.")
    parser.add_argument(
        "--repair-existing",
        action="store_true",
        help=(
            "Also replace existing waist/hip/bust fields when the current comment has a clearer deterministic "
            "label match than the stored value."
        ),
    )
    args = parser.parse_args()

    totals = {"files": 0, "rows": 0, "rows_updated": 0, "fields_added": 0}
    changed_files = []
    for csv_path in sorted(iter_csv_paths(args.root)):
        stats = rewrite_csv(csv_path, dry_run=args.dry_run, repair_existing=args.repair_existing)
        totals["files"] += 1
        totals["rows"] += stats["rows"]
        totals["rows_updated"] += stats["rows_updated"]
        totals["fields_added"] += stats["fields_added"]
        if stats["fields_added"]:
            changed_files.append((csv_path, stats))

    print(json.dumps(totals, indent=2))
    for csv_path, stats in changed_files:
        print(f"{csv_path}: {stats['rows_updated']} rows, {stats['fields_added']} fields")


if __name__ == "__main__":
    main()
