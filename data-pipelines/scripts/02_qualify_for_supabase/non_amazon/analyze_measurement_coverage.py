#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PIPELINE_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import (  # noqa: E402
    cv_annotated_pending_human_review_root,
    fwm_data_dir,
    human_reviewed_ready_to_publish_root,
    repo_root,
    reports_root,
    supabase_qualified_data_root,
)

REPO_ROOT = repo_root()
DEFAULT_OUTPUTS_ROOT = fwm_data_dir()
DEFAULT_REPORT_ROOT = reports_root() / "measurement_coverage"
pd = None


def require_pandas():
    global pd
    if pd is None:
        try:
            import pandas as pandas_module
        except ImportError as exc:
            raise SystemExit(
                "pandas is required to run measurement coverage analysis. "
                "Install project dependencies or run in the bundled workspace environment."
            ) from exc
        pd = pandas_module
    return pd


@dataclass(frozen=True)
class SourceSpec:
    label: str
    tier: str
    pattern: str
    file_type: str
    priority: int


SOURCE_SPECS = (
    SourceSpec(
        "cv_gate_checkpoint_parts",
        "cv_gated_all",
        str(
            cv_annotated_pending_human_review_root()
            .relative_to(DEFAULT_OUTPUTS_ROOT)
            / "partial_170000_rows_cv_gated/cv_gate_checkpoint_parts/full_cv_gate_part_*.csv"
        ),
        "csv",
        50,
    ),
    SourceSpec(
        "human_labeled_returns",
        "human_labeled",
        str(
            human_reviewed_ready_to_publish_root()
            .relative_to(DEFAULT_OUTPUTS_ROOT)
            / "human_labeled_returns/human_labeled_*.xlsx"
        ),
        "xlsx",
        10,
    ),
    SourceSpec(
        "ready_human_approved",
        "ready_human_approved",
        str(
            human_reviewed_ready_to_publish_root()
            .relative_to(DEFAULT_OUTPUTS_ROOT)
            / "legacy_approved_batches/**/approved_rows/*.csv"
        ),
        "csv",
        20,
    ),
    SourceSpec(
        "ready_labeled_source",
        "ready_labeled_source",
        str(
            human_reviewed_ready_to_publish_root()
            .relative_to(DEFAULT_OUTPUTS_ROOT)
            / "legacy_approved_batches/**/labeled_source/*.csv"
        ),
        "csv",
        30,
    ),
    SourceSpec(
        "unprocessed_not_cv_or_human",
        "unprocessed",
        str(
            supabase_qualified_data_root()
            .relative_to(DEFAULT_OUTPUTS_ROOT)
            / "legacy_outputs_2026-06-15/03_supabase_unprocessed_not_cv_or_human/unprocessed_rows_part_*.csv"
        ),
        "csv",
        60,
    ),
)


NUMERIC_COLUMNS = (
    "height_in_display",
    "weight_lbs_display",
    "waist_in",
    "hips_in_display",
    "bust_in_display",
    "bra_band_in_display",
    "bust_in_number_display",
    "inseam_inches_display",
    "body_coverage_score_yolo_pose",
    "main_person_height_pct_yolo_detect",
)

MEASUREMENT_COLUMNS = (
    "height_in_display",
    "weight_lbs_display",
    "waist_in",
    "hips_in_display",
    "bust_in_display",
    "bra_band_in_display",
    "bust_in_number_display",
    "cupsize_display",
    "inseam_inches_display",
    "size_display",
)

BIN_SPECS = {
    "height_in_display": list(range(48, 85, 2)),
    "weight_lbs_display": list(range(80, 331, 20)),
    "waist_in": list(range(20, 61, 4)),
    "hips_in_display": list(range(28, 71, 4)),
    "bust_in_display": list(range(28, 61, 4)),
    "bra_band_in_display": list(range(26, 51, 2)),
    "bust_in_number_display": list(range(28, 61, 4)),
    "inseam_inches_display": list(range(24, 39, 2)),
}

CUP_ORDER = [
    "AA",
    "A",
    "B",
    "C",
    "D",
    "DD",
    "DDD",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
    "O",
]

SIZE_ORDER = [
    "XXS",
    "XS",
    "S",
    "M",
    "L",
    "XL",
    "XXL",
    "XXXL",
    "0X",
    "1X",
    "2X",
    "3X",
    "4X",
    "5X",
    "6X",
]


def nonempty(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().ne("")


def as_number(value: object) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def normalize_cup(value: object) -> str:
    text = str(value or "").upper().strip()
    text = re.sub(r"[^A-Z]+", "", text)
    if text == "DDDD":
        return "G"
    return text


def normalize_size(value: object) -> str:
    text = str(value or "").upper().strip()
    if not text:
        return ""
    text = re.sub(r"\bUS\b|\bWOMEN'?S\b|\bWOMENS\b|\bSIZE\b", "", text)
    text = re.sub(r"[^A-Z0-9+/.-]+", " ", text).strip()
    tokens = text.split()
    for token in tokens:
        token = token.strip()
        if token in SIZE_ORDER:
            return token
        if re.fullmatch(r"[0-9]X", token):
            return token
    for token in tokens:
        if re.fullmatch(r"\d{1,2}", token):
            return token
    return tokens[0] if tokens else ""


def bin_label(value: float | None, edges: list[int]) -> str:
    if value is None:
        return "missing"
    if value < edges[0]:
        return f"<{edges[0]}"
    if value >= edges[-1]:
        return f"{edges[-1]}+"
    for start, end in zip(edges, edges[1:]):
        if start <= value < end:
            return f"{start}-{end - 1}"
    return "missing"


def read_source(path: Path, file_type: str) -> pd.DataFrame:
    pandas = require_pandas()
    if file_type == "csv":
        return pandas.read_csv(path, dtype=str, keep_default_na=False)
    return pandas.read_excel(path, dtype=str, keep_default_na=False)


def iter_source_frames(outputs_root: Path, include_tiers: set[str] | None = None) -> Iterable[pd.DataFrame]:
    for spec in SOURCE_SPECS:
        if include_tiers and spec.tier not in include_tiers:
            continue
        for path in sorted(outputs_root.glob(spec.pattern)):
            try:
                frame = read_source(path, spec.file_type)
            except Exception as exc:
                print(f"warning: failed to read {path}: {exc}")
                continue
            frame["coverage_source_label"] = spec.label
            frame["coverage_source_tier"] = spec.tier
            frame["coverage_source_file"] = str(path.relative_to(outputs_root))
            frame["coverage_source_priority"] = spec.priority
            yield frame


def load_rows(outputs_root: Path, include_tiers: set[str] | None = None, production_decision: str | None = None) -> pd.DataFrame:
    frames = list(iter_source_frames(outputs_root, include_tiers=include_tiers))
    if not frames:
        raise SystemExit(f"No source files found under {outputs_root}")
    all_columns = sorted(set().union(*(set(frame.columns) for frame in frames)))
    normalized = [frame.reindex(columns=all_columns, fill_value="") for frame in frames]
    rows = pd.concat(normalized, ignore_index=True)
    if production_decision:
        if "production_decision" not in rows.columns:
            raise SystemExit("Cannot filter by production_decision because that column is not present.")
        rows = rows[rows["production_decision"].fillna("").astype(str).str.upper().eq(production_decision.upper())].copy()
        if rows.empty:
            raise SystemExit(f"No rows matched production_decision={production_decision!r}.")
    input_source_summary = (
        rows.groupby(["coverage_source_tier", "coverage_source_label"], dropna=False)
        .size()
        .reset_index(name="input_rows_before_dedupe")
        .sort_values("input_rows_before_dedupe", ascending=False)
    )

    for column in NUMERIC_COLUMNS:
        if column in rows.columns:
            rows[f"{column}__num"] = rows[column].map(as_number)
    if "cupsize_display" in rows.columns:
        rows["cupsize_display__norm"] = rows["cupsize_display"].map(normalize_cup)
    if "size_display" in rows.columns:
        rows["size_display__norm"] = rows["size_display"].map(normalize_size)

    key_parts = []
    for column in ("review_row_key", "image_url_to_use", "raw_scraped_image_url", "product_page_url_display", "source_file", "source_row_number"):
        if column in rows.columns:
            key_parts.append(rows[column].fillna("").astype(str).str.strip())
    if key_parts:
        rows["coverage_dedupe_key"] = key_parts[0]
        for part in key_parts[1:]:
            rows["coverage_dedupe_key"] = rows["coverage_dedupe_key"].where(rows["coverage_dedupe_key"].ne(""), part)
    else:
        rows["coverage_dedupe_key"] = rows.index.astype(str)
    rows["coverage_dedupe_key"] = rows["coverage_dedupe_key"].where(rows["coverage_dedupe_key"].ne(""), rows.index.astype(str))
    rows["coverage_source_priority"] = pd.to_numeric(rows["coverage_source_priority"], errors="coerce").fillna(999)
    rows = rows.sort_values(["coverage_source_priority", "coverage_source_tier"]).drop_duplicates("coverage_dedupe_key", keep="first").reset_index(drop=True)
    rows.attrs["input_source_summary"] = input_source_summary

    rows["has_height"] = rows.get("height_in_display", pd.Series("", index=rows.index)).pipe(nonempty)
    rows["has_weight"] = rows.get("weight_lbs_display", pd.Series("", index=rows.index)).pipe(nonempty)
    rows["has_height_weight"] = rows["has_height"] & rows["has_weight"]
    body_fields = [field for field in ("waist_in", "hips_in_display", "bust_in_display", "bra_band_in_display", "cupsize_display", "inseam_inches_display") if field in rows.columns]
    rows["has_any_body_measurement"] = False
    for field in body_fields:
        rows["has_any_body_measurement"] = rows["has_any_body_measurement"] | nonempty(rows[field])
    rows["usable_for_body_size_prospecting"] = rows["has_height_weight"] | rows["has_any_body_measurement"]
    return rows


def count_table(series: pd.Series, name: str) -> pd.DataFrame:
    counts = series.value_counts(dropna=False).rename_axis(name).reset_index(name="row_count")
    total = int(counts["row_count"].sum())
    counts["pct_of_rows"] = counts["row_count"].map(lambda n: round((n / total) * 100, 2) if total else 0)
    return counts


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def output_stem(field: str) -> str:
    replacements = {
        "height_in_display": "height",
        "weight_lbs_display": "weight_lbs",
        "waist_in": "waist",
        "hips_in_display": "hips",
        "bust_in_display": "bust",
        "bra_band_in_display": "bra_band",
        "bust_in_number_display": "bust_number",
        "inseam_inches_display": "inseam_inches",
    }
    return replacements.get(field, field)


def simple_bar_svg(path: Path, frame: pd.DataFrame, label_col: str, value_col: str, title: str, limit: int = 40) -> None:
    data = frame[[label_col, value_col]].head(limit).copy()
    data[value_col] = pd.to_numeric(data[value_col], errors="coerce").fillna(0)
    max_value = float(data[value_col].max() or 1)
    row_h = 24
    label_w = 118
    bar_w = 560
    width = label_w + bar_w + 95
    height = 54 + row_h * len(data)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        f'<text x="16" y="28" font-family="Arial, sans-serif" font-size="18" font-weight="700">{html.escape(title)}</text>',
    ]
    for idx, row in data.iterrows():
        y = 48 + idx * row_h
        label = html.escape(str(row[label_col]))
        value = int(row[value_col])
        bar_len = 0 if max_value == 0 else int((value / max_value) * bar_w)
        parts.append(f'<text x="16" y="{y + 15}" font-family="Arial, sans-serif" font-size="12" fill="#333">{label}</text>')
        parts.append(f'<rect x="{label_w}" y="{y}" width="{bar_len}" height="16" fill="#28666e"/>')
        parts.append(f'<text x="{label_w + bar_len + 8}" y="{y + 13}" font-family="Arial, sans-serif" font-size="12" fill="#333">{value:,}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def summarize_undercoverage(rows: pd.DataFrame) -> pd.DataFrame:
    usable = rows[rows["usable_for_body_size_prospecting"]].copy()
    segments: list[dict[str, object]] = []

    def add_segment(name: str, mask: pd.Series, why: str, target: str) -> None:
        count = int(mask.sum())
        pct = round(count / len(usable) * 100, 2) if len(usable) else 0
        segments.append(
            {
                "segment": name,
                "current_rows": count,
                "pct_of_usable_rows": pct,
                "coverage_read": why,
                "prospecting_target": target,
            }
        )

    height = usable.get("height_in_display__num")
    weight = usable.get("weight_lbs_display__num")
    waist = usable.get("waist_in__num")
    hips = usable.get("hips_in_display__num")
    bust = usable.get("bust_in_display__num")
    band = usable.get("bra_band_in_display__num")
    cup = usable.get("cupsize_display__norm")

    if height is not None:
        add_segment("very petite height (<5'0)", height.lt(60), "Sparse relative to 5'2-5'8 center mass.", "Petite-specialty retailers, short inseam denim, petite formalwear.")
        add_segment("tall height (5'10+)", height.ge(70), "Tails thin out above 5'10.", "Tall-size shops, tall denim, long torso swim/activewear.")
        add_segment("very tall height (6'0+)", height.ge(72), "Very small upper-tail sample.", "Tall-focused brands and communities with reviewer measurements.")
    if weight is not None:
        add_segment("low weight (<110 lb)", weight.lt(110), "Thin lower-weight tail.", "Petite/XXS brands with explicit reviewer stats.")
        add_segment("higher weight (200+ lb)", weight.ge(200), "Higher weights are materially under-covered.", "Plus-size, curve, shapewear, extended-size brands with photo reviews.")
        add_segment("very high weight (260+ lb)", weight.ge(260), "Very sparse far upper tail.", "Dedicated extended plus and inclusive sizing retailers.")
    if waist is not None:
        add_segment("waist 40+ in", waist.ge(40), "Plus waist measurements are thin.", "Curve denim, shapewear, plus workwear, plus formalwear.")
    if hips is not None:
        add_segment("hips 48+ in", hips.ge(48), "High-hip rows are thin.", "Curve denim/swim/activewear where reviewers state hip measurements.")
    if bust is not None:
        add_segment("bust 44+ in", bust.ge(44), "Large bust measurements are thin.", "Full-bust swim, dresses, bras, and bust-friendly apparel.")
    if band is not None:
        add_segment("bra band 40+", band.ge(40), "Large-band bra rows are thin.", "Full-bust and plus lingerie sites.")
    if cup is not None:
        add_segment("cup DD+", cup.isin(["DD", "DDD", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O"]), "Full-bust cup data exists but is not broad enough.", "Full-bust bra/swim retailers with structured review fields.")

    return pd.DataFrame(segments).sort_values(["pct_of_usable_rows", "current_rows"], ascending=[True, True])


def write_markdown_report(report_dir: Path, rows: pd.DataFrame, summary: pd.DataFrame, undercovered: pd.DataFrame) -> None:
    usable_count = int(rows["usable_for_body_size_prospecting"].sum())
    hw_count = int(rows["has_height_weight"].sum())
    body_count = int(rows["has_any_body_measurement"].sum())
    source_counts = rows["coverage_source_tier"].value_counts().to_dict()
    input_source_summary = rows.attrs.get("input_source_summary", pd.DataFrame())
    lines = [
        "# Measurement Coverage Snapshot",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Scope",
        "",
        f"- Unique rows scanned: {len(rows):,}",
        f"- Rows usable for body-size prospecting: {usable_count:,}",
        f"- Rows with both height and weight: {hw_count:,}",
        f"- Rows with any body-specific measurement beyond height/weight: {body_count:,}",
        "",
        "## Source Mix",
        "",
    ]
    for tier, count in source_counts.items():
        lines.append(f"- {tier}: {count:,}")
    if not input_source_summary.empty:
        lines.extend(["", "Input rows before dedupe:", ""])
        for _, row in input_source_summary.iterrows():
            lines.append(f"- {row['coverage_source_tier']} / {row['coverage_source_label']}: {int(row['input_rows_before_dedupe']):,}")
    lines.extend(
        [
            "",
            "## Coverage By Field",
            "",
            "| field | rows_with_value | pct_of_unique_rows |",
            "| --- | ---: | ---: |",
        ]
    )
    for _, row in summary.iterrows():
        lines.append(f"| {row['field']} | {int(row['rows_with_value']):,} | {row['pct_of_unique_rows']} |")
    lines.extend(["", "## Early Prospecting Gaps", ""])
    for _, row in undercovered.head(12).iterrows():
        lines.append(
            f"- {row['segment']}: {int(row['current_rows']):,} rows ({row['pct_of_usable_rows']}% of usable rows). "
            f"Target: {row['prospecting_target']}"
        )
    lines.extend(
        [
            "",
            "## Files",
            "",
            "- `field_presence_summary.csv`",
            "- `undercovered_segments.csv`",
            "- `height_bins.csv`, `weight_bins.csv`, and body-measurement bin CSVs",
            "- `height_x_weight_bins.csv`",
            "- `charts/*.svg`",
        ]
    )
    (report_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze(outputs_root: Path, report_dir: Path, include_tiers: set[str] | None = None, production_decision: str | None = None) -> None:
    rows = load_rows(outputs_root, include_tiers=include_tiers, production_decision=production_decision)
    report_dir.mkdir(parents=True, exist_ok=True)
    charts_dir = report_dir / "charts"
    charts_dir.mkdir(exist_ok=True)

    inventory_cols = [
        col
        for col in (
            "coverage_source_tier",
            "coverage_source_label",
            "coverage_source_file",
            "review_row_key",
            "source_site_display",
            "brand",
            "clothing_type_id",
            "size_display",
            "height_in_display",
            "weight_lbs_display",
            "waist_in",
            "hips_in_display",
            "bust_in_display",
            "bra_band_in_display",
            "bust_in_number_display",
            "cupsize_display",
            "inseam_inches_display",
            "body_coverage_score_yolo_pose",
            "main_person_height_pct_yolo_detect",
        )
        if col in rows.columns
    ]
    write_csv(report_dir / "measurement_row_inventory.csv", rows[inventory_cols])

    summary_rows = []
    for field in MEASUREMENT_COLUMNS:
        if field not in rows.columns:
            continue
        count = int(nonempty(rows[field]).sum())
        summary_rows.append(
            {
                "field": field,
                "rows_with_value": count,
                "pct_of_unique_rows": round(count / len(rows) * 100, 2) if len(rows) else 0,
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values("rows_with_value", ascending=False)
    write_csv(report_dir / "field_presence_summary.csv", summary)

    for field, edges in BIN_SPECS.items():
        num_col = f"{field}__num"
        if num_col not in rows.columns:
            continue
        binned = rows[num_col].map(lambda value: bin_label(value, edges))
        table = count_table(binned, f"{field}_bin")
        table = table[table[f"{field}_bin"].ne("missing")]
        table = table.sort_values(f"{field}_bin", key=lambda s: s.map(lambda x: edges.index(int(x.split("-")[0])) if "-" in x and int(x.split("-")[0]) in edges else 999))
        write_csv(report_dir / f"{output_stem(field)}_bins.csv", table)
        simple_bar_svg(charts_dir / f"{field}.svg", table, f"{field}_bin", "row_count", field)

    if "cupsize_display__norm" in rows.columns:
        cups = count_table(rows["cupsize_display__norm"].where(rows["cupsize_display__norm"].ne(""), "missing"), "cupsize")
        cups = cups[cups["cupsize"].ne("missing")]
        cups = cups.sort_values("cupsize", key=lambda s: s.map(lambda x: CUP_ORDER.index(x) if x in CUP_ORDER else 999))
        write_csv(report_dir / "cupsize_bins.csv", cups)
        simple_bar_svg(charts_dir / "cupsize_display.svg", cups, "cupsize", "row_count", "cupsize_display")

    if "size_display__norm" in rows.columns:
        sizes = count_table(rows["size_display__norm"].where(rows["size_display__norm"].ne(""), "missing"), "size")
        sizes = sizes[sizes["size"].ne("missing")]
        sizes = sizes.sort_values("row_count", ascending=False)
        write_csv(report_dir / "size_bins.csv", sizes)
        simple_bar_svg(charts_dir / "size_display.svg", sizes, "size", "row_count", "size_display")

    if "height_in_display__num" in rows.columns and "weight_lbs_display__num" in rows.columns:
        cross = pd.DataFrame(
            {
                "height_bin": rows["height_in_display__num"].map(lambda value: bin_label(value, BIN_SPECS["height_in_display"])),
                "weight_bin": rows["weight_lbs_display__num"].map(lambda value: bin_label(value, BIN_SPECS["weight_lbs_display"])),
            }
        )
        cross = cross[cross["height_bin"].ne("missing") & cross["weight_bin"].ne("missing")]
        cross = cross.value_counts(["height_bin", "weight_bin"]).reset_index(name="row_count")
        write_csv(report_dir / "height_x_weight_bins.csv", cross)

    tier_summary = []
    for tier, group in rows.groupby("coverage_source_tier"):
        tier_summary.append(
            {
                "tier": tier,
                "unique_rows": len(group),
                "height_weight_rows": int(group["has_height_weight"].sum()),
                "any_body_measurement_rows": int(group["has_any_body_measurement"].sum()),
                "usable_for_body_size_prospecting_rows": int(group["usable_for_body_size_prospecting"].sum()),
            }
        )
    write_csv(report_dir / "source_tier_summary.csv", pd.DataFrame(tier_summary).sort_values("unique_rows", ascending=False))
    input_source_summary = rows.attrs.get("input_source_summary", pd.DataFrame())
    if not input_source_summary.empty:
        write_csv(report_dir / "input_source_summary_before_dedupe.csv", input_source_summary)

    undercovered = summarize_undercoverage(rows)
    write_csv(report_dir / "undercovered_segments.csv", undercovered)
    write_markdown_report(report_dir, rows, summary, undercovered)

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "outputs_root": str(outputs_root),
        "report_dir": str(report_dir),
        "unique_rows": int(len(rows)),
        "usable_for_body_size_prospecting_rows": int(rows["usable_for_body_size_prospecting"].sum()),
        "include_tiers": sorted(include_tiers) if include_tiers else None,
        "production_decision": production_decision,
    }
    (report_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze body measurement coverage across FWM output files.")
    parser.add_argument("--outputs-root", type=Path, default=DEFAULT_OUTPUTS_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument(
        "--include-tier",
        action="append",
        choices=sorted({spec.tier for spec in SOURCE_SPECS}),
        help="Limit analysis to one or more source tiers. Can be passed more than once.",
    )
    parser.add_argument("--production-decision", help="Limit analysis to a production_decision value, e.g. APPROVE.")
    args = parser.parse_args()
    require_pandas()
    analyze(args.outputs_root, args.report_dir, include_tiers=set(args.include_tier or []) or None, production_decision=args.production_decision)
    print(args.report_dir)


if __name__ == "__main__":
    main()
