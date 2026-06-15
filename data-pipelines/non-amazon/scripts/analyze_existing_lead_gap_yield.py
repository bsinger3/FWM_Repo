#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from prioritize_leads_for_measurement_gaps import DATA_ROOT, DEFAULT_REPORT_DIR, artifact_aliases, compact, read_csv  # noqa: E402


DEFAULT_LEAD_RANKING = DEFAULT_REPORT_DIR / "lead_gap_reprioritization.csv"
DEFAULT_OUTPUT = DEFAULT_REPORT_DIR / "existing_scrape_gap_yield.csv"
DEFAULT_TOP_EXAMPLES = DEFAULT_REPORT_DIR / "existing_scrape_gap_examples.csv"

CUP_DD_PLUS = {"DD", "DDD", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O"}
CSV_PATTERNS = ("*reviews_matching_intake_schema.csv", "*reviews_matching_amazon_schema.csv")


def norm(value: object) -> str:
    return str(value or "").strip()


def as_number(value: object) -> float | None:
    text = norm(value)
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def numbers(value: object) -> list[float]:
    text = norm(value).replace(",", "")
    out = []
    for match in re.finditer(r"-?\d+(?:\.\d+)?", text):
        try:
            out.append(float(match.group(0)))
        except ValueError:
            pass
    return out


def max_number(*values: object) -> float | None:
    found: list[float] = []
    for value in values:
        found.extend(numbers(value))
    return max(found) if found else None


def height_inches_from_text(value: object) -> float | None:
    text = norm(value).lower()
    if not text:
        return None
    values = []
    for match in re.finditer(r"(\d)\s*(?:ft|feet|foot|['’])\s*(\d{1,2})?", text):
        feet = float(match.group(1))
        inches = float(match.group(2) or 0)
        values.append(feet * 12 + inches)
    if values:
        return max(values)
    return as_number(text)


def normalize_cup(value: object) -> str:
    text = re.sub(r"[^A-Za-z]+", "", norm(value)).upper()
    return "G" if text == "DDDD" else text


def nonempty(row: dict[str, str], *fields: str) -> bool:
    return any(norm(row.get(field)) for field in fields)


def has_image(row: dict[str, str]) -> bool:
    return nonempty(row, "image_url_to_use", "raw_scraped_image_url", "image_url", "image_preview", "original_url_display")


def has_product(row: dict[str, str]) -> bool:
    return nonempty(row, "product_page_url_display", "product_url", "monetized_product_url_display")


def has_size(row: dict[str, str]) -> bool:
    return nonempty(row, "size_display", "customer_ordered_size", "ordered_size")


def has_measurement(row: dict[str, str]) -> bool:
    return nonempty(
        row,
        "height_in_display",
        "weight_lbs_display",
        "waist_in",
        "hips_in_display",
        "bust_in_display",
        "bra_band_in_display",
        "bust_in_number_display",
        "cupsize_display",
        "inseam_inches_display",
    )


def row_key(row: dict[str, str], fallback: str) -> str:
    for field in ("review_row_key", "image_url_to_use", "raw_scraped_image_url", "product_page_url_display"):
        value = norm(row.get(field))
        if value:
            return value
    return fallback


def gap_tags(row: dict[str, str]) -> set[str]:
    tags: set[str] = set()
    height = as_number(row.get("height_in_display"))
    if height is None:
        height = height_inches_from_text(row.get("height_raw"))
    weight = max_number(row.get("weight_lbs_display"), row.get("weight_display_display"), row.get("weight_raw"))
    waist = as_number(row.get("waist_in"))
    hips = as_number(row.get("hips_in_display"))
    bust = as_number(row.get("bust_in_display")) or as_number(row.get("bust_in_number_display"))
    band = as_number(row.get("bra_band_in_display"))
    cup = normalize_cup(row.get("cupsize_display"))

    if height is not None and height < 60:
        tags.add("petite_height_under_5ft")
    if height is not None and height >= 70:
        tags.add("tall_height_5ft10_plus")
    if height is not None and height >= 72:
        tags.add("very_tall_height_6ft_plus")
    if weight is not None and weight >= 200:
        tags.add("higher_weight_200_plus")
    if weight is not None and weight >= 260:
        tags.add("very_high_weight_260_plus")
    if waist is not None and waist >= 40:
        tags.add("waist_40_plus")
    if hips is not None and hips >= 48:
        tags.add("hips_48_plus")
    if bust is not None and bust >= 44:
        tags.add("bust_44_plus")
    if band is not None and band >= 40:
        tags.add("bra_band_40_plus")
    if cup in CUP_DD_PLUS:
        tags.add("cup_dd_plus")
    return tags


def matching_data_dirs(lead: dict[str, str]) -> list[Path]:
    aliases = artifact_aliases(lead)
    alias_compacts = {compact(alias) for alias in aliases}
    dirs = []
    if not DATA_ROOT.exists():
        return dirs
    for path in DATA_ROOT.iterdir():
        if not path.is_dir() or path.name.startswith("_"):
            continue
        path_compact = compact(path.name)
        if any(alias and alias in path_compact for alias in alias_compacts):
            dirs.append(path)
    return sorted(dirs)


def iter_csv_paths(dirs: Iterable[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for data_dir in dirs:
        for pattern in CSV_PATTERNS:
            for path in sorted(data_dir.glob(pattern)):
                if path not in seen:
                    seen.add(path)
                    yield path


def summary_payloads(dirs: Iterable[Path]) -> list[dict[str, object]]:
    payloads = []
    for data_dir in dirs:
        for path in sorted(data_dir.glob("*summary.json")):
            try:
                payloads.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
    return payloads


def aggregate_summary(payloads: list[dict[str, object]]) -> dict[str, int]:
    keys = (
        "rows_written",
        "distinct_reviews",
        "distinct_images",
        "rows_with_customer_review_image",
        "rows_with_catalog_model_image",
        "rows_with_any_measurement",
        "rows_with_image_product_and_measurement",
        "supabase_qualified_rows",
        "rows_supabase_qualified",
        "rows_for_bra_products",
        "rows_for_bra_products_with_customer_bra_size",
    )
    totals: dict[str, int] = {}
    for key in keys:
        values = [payload.get(key) for payload in payloads if isinstance(payload.get(key), int)]
        if values:
            totals[key] = max(values)
    return totals


def analyze_lead(lead: dict[str, str]) -> tuple[dict[str, str], list[dict[str, str]]]:
    dirs = matching_data_dirs(lead)
    csv_paths = list(iter_csv_paths(dirs))
    summary = aggregate_summary(summary_payloads(dirs))
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    examples: list[dict[str, str]] = []

    for csv_path in csv_paths:
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for idx, row in enumerate(reader, 2):
                key = row_key(row, f"{csv_path}:{idx}")
                if key in seen:
                    continue
                seen.add(key)
                tags = gap_tags(row)
                counts["rows"] += 1
                if has_image(row):
                    counts["image_rows"] += 1
                if has_product(row):
                    counts["product_rows"] += 1
                if has_size(row):
                    counts["size_rows"] += 1
                if has_measurement(row):
                    counts["measurement_rows"] += 1
                if has_image(row) and has_product(row) and has_size(row) and has_measurement(row):
                    counts["supabase_shape_rows"] += 1
                if tags:
                    counts["any_gap_rows"] += 1
                    for tag in tags:
                        counts[tag] += 1
                    if len(examples) < 5:
                        examples.append(
                            {
                                "primary_domain": lead.get("primary_domain", ""),
                                "merchant_group": lead.get("merchant_group", ""),
                                "gap_tags": ";".join(sorted(tags)),
                                "source_csv": str(csv_path),
                                "review_row_key": norm(row.get("review_row_key")),
                                "product_page_url_display": norm(row.get("product_page_url_display")),
                                "size_display": norm(row.get("size_display")),
                                "height_in_display": norm(row.get("height_in_display")),
                                "weight_lbs_display": norm(row.get("weight_lbs_display")),
                                "waist_in": norm(row.get("waist_in")),
                                "hips_in_display": norm(row.get("hips_in_display")),
                                "bust_in_display": norm(row.get("bust_in_display") or row.get("bust_in_number_display")),
                                "bra_band_in_display": norm(row.get("bra_band_in_display")),
                                "cupsize_display": norm(row.get("cupsize_display")),
                            }
                        )

    result = {
        "primary_domain": lead.get("primary_domain", ""),
        "merchant_group": lead.get("merchant_group", ""),
        "recommended_gap_next_action": lead.get("recommended_gap_next_action", ""),
        "existing_artifact_status": lead.get("existing_artifact_status", ""),
        "gap_match_tags": lead.get("gap_match_tags", ""),
        "data_dirs": ";".join(str(path.relative_to(DATA_ROOT)) for path in dirs),
        "csv_files_scanned": str(len(csv_paths)),
        "unique_rows_scanned": str(counts["rows"]),
        "image_rows": str(counts["image_rows"]),
        "measurement_rows": str(counts["measurement_rows"]),
        "supabase_shape_rows": str(counts["supabase_shape_rows"]),
        "any_gap_rows": str(counts["any_gap_rows"]),
        "bra_band_40_plus": str(counts["bra_band_40_plus"]),
        "cup_dd_plus": str(counts["cup_dd_plus"]),
        "bust_44_plus": str(counts["bust_44_plus"]),
        "waist_40_plus": str(counts["waist_40_plus"]),
        "hips_48_plus": str(counts["hips_48_plus"]),
        "higher_weight_200_plus": str(counts["higher_weight_200_plus"]),
        "very_high_weight_260_plus": str(counts["very_high_weight_260_plus"]),
        "tall_height_5ft10_plus": str(counts["tall_height_5ft10_plus"]),
        "very_tall_height_6ft_plus": str(counts["very_tall_height_6ft_plus"]),
        "petite_height_under_5ft": str(counts["petite_height_under_5ft"]),
        "summary_rows_written": str(summary.get("rows_written", "")),
        "summary_supabase_qualified_rows": str(summary.get("supabase_qualified_rows") or summary.get("rows_supabase_qualified") or ""),
        "summary_rows_with_any_measurement": str(summary.get("rows_with_any_measurement", "")),
        "summary_rows_for_bra_products": str(summary.get("rows_for_bra_products", "")),
        "summary_rows_for_bra_products_with_customer_bra_size": str(summary.get("rows_for_bra_products_with_customer_bra_size", "")),
    }
    return result, examples


def write_outputs(lead_ranking: Path, output: Path, examples_output: Path) -> None:
    leads = [row for row in read_csv(lead_ranking) if row.get("active_candidate_status") == "yes"]
    results = []
    examples = []
    for lead in leads:
        result, lead_examples = analyze_lead(lead)
        results.append(result)
        examples.extend(lead_examples)
    results.sort(key=lambda row: (int(row["any_gap_rows"]), int(row["supabase_shape_rows"]), int(row["measurement_rows"])), reverse=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    with examples_output.open("w", newline="", encoding="utf-8") as handle:
        if examples:
            writer = csv.DictWriter(handle, fieldnames=list(examples[0].keys()))
            writer.writeheader()
            writer.writerows(examples)


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure gap yield in existing scrape outputs for active lead-table candidates.")
    parser.add_argument("--lead-ranking", type=Path, default=DEFAULT_LEAD_RANKING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--examples-output", type=Path, default=DEFAULT_TOP_EXAMPLES)
    args = parser.parse_args()
    write_outputs(args.lead_ranking, args.output, args.examples_output)
    print(args.output)
    print(args.examples_output)


if __name__ == "__main__":
    main()
