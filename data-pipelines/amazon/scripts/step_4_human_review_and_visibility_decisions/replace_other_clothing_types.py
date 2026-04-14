#!/usr/bin/env python3
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


PIPELINE_ROOT = Path(__file__).resolve().parents[2]
STEP4_DIR = PIPELINE_ROOT / "data" / "step_4_human_review_and_visibility_decisions"
DOCS_DIR = PIPELINE_ROOT / "docs"
REPORT_PATH = DOCS_DIR / "step_4_clothing_type_replacement_report.md"

OTHER_VALUE = "other"
PRODUCT_MAJORITY_MIN_ROWS = 3
PRODUCT_MAJORITY_MIN_SHARE = 0.70
PRODUCT_OVERRIDE_SHARE = 0.85
PRODUCT_SMALL_SAMPLE_MIN_ROWS = 1
PRODUCT_SMALL_SAMPLE_REQUIRED_SHARE = 1.00

KEYWORD_PATTERNS = {
    "dress": [r"\bdresses?\b", r"\bgown\b"],
    "skirt": [r"\bskirts?\b", r"\bmini skirt\b", r"\bmidi skirt\b", r"\bmaxi skirt\b"],
    "jumpsuit": [r"\bjumpsuits?\b"],
    "romper": [r"\brompers?\b"],
    "overalls": [r"\boveralls?\b"],
    "jeans": [r"\bjeans?\b", r"\bdenim\b"],
    "pants": [r"\bpants?\b", r"\btrousers?\b", r"\bslacks?\b"],
    "leggings": [r"\bleggings?\b"],
    "top": [r"\btop\b", r"\bblouse\b", r"\btunic\b", r"\bvest\b", r"\bcami\b", r"\bbustier\b", r"\bbralette\b"],
    "shirt": [r"\bshirt\b", r"\bbutton[- ]?down\b"],
    "tank": [r"\btank\b", r"\btank top\b"],
    "t-shirt": [r"\bt[- ]?shirt\b", r"\btee\b"],
    "sweater": [r"\bsweater\b", r"\bcardigan\b"],
    "shorts": [r"\bshorts\b", r"\bbermuda shorts?\b"],
    "swimsuit": [r"\bswimsuit\b", r"\bswim suit\b", r"\bbathing suit\b", r"\bone piece\b", r"\bmonokini\b"],
    "bikini": [r"\bbikini\b", r"\bbikini top\b", r"\bbikini bottom\b"],
    "coverup": [r"\bcover[- ]?up\b", r"\bbeach cover\b"],
    "bra": [r"\bbra\b"],
    "jacket": [r"\bjacket\b", r"\bblazer\b", r"\bcoat\b"],
    "bodysuit": [r"\bbodysuit\b"],
    "capris": [r"\bcapris?\b"],
}


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def normalize_type(value: str) -> str:
    return normalize_whitespace(value).lower()


def iter_step4_files() -> List[Path]:
    return sorted(STEP4_DIR.glob("images_to_approve_part_*.csv"))


def load_rows_by_file(files: List[Path]) -> Tuple[List[str], Dict[Path, List[Dict[str, str]]]]:
    header = None
    rows_by_file: Dict[Path, List[Dict[str, str]]] = {}
    for path in files:
        with path.open("r", encoding="utf-8", newline="") as infile:
            reader = csv.DictReader(infile)
            if not reader.fieldnames:
                raise SystemExit(f"No CSV header found in {path}")
            if header is None:
                header = list(reader.fieldnames)
            rows_by_file[path] = list(reader)
    if header is None:
        raise SystemExit("No Step 4 chunk files found.")
    return header, rows_by_file


def build_product_type_counts(rows_by_file: Dict[Path, List[Dict[str, str]]]) -> Dict[str, Counter]:
    counts: Dict[str, Counter] = defaultdict(Counter)
    for rows in rows_by_file.values():
        for row in rows:
            product_url = (row.get("product_page_url_display") or "").strip()
            clothing_type = normalize_type(row.get("clothing_type_id") or "")
            if product_url and clothing_type and clothing_type != OTHER_VALUE:
                counts[product_url][clothing_type] += 1
    return counts


def infer_by_product_majority(
    product_url: str, product_type_counts: Dict[str, Counter]
) -> Tuple[Optional[str], Optional[float], Optional[int], str]:
    counts = product_type_counts.get(product_url)
    if not counts:
        return None, None, None, "no_product_signal"
    total = sum(counts.values())
    top_type, top_count = counts.most_common(1)[0]
    share = top_count / total if total else 0.0
    if total >= PRODUCT_MAJORITY_MIN_ROWS and share >= PRODUCT_MAJORITY_MIN_SHARE:
        return top_type, share, total, "product_majority"
    if total >= PRODUCT_SMALL_SAMPLE_MIN_ROWS and share >= PRODUCT_SMALL_SAMPLE_REQUIRED_SHARE:
        return top_type, share, total, "product_small_sample"
    return None, share, total, "product_insufficient_confidence"


def infer_by_keywords(row: Dict[str, str]) -> Tuple[Optional[str], str]:
    text = " ".join(
        filter(
            None,
            [
                row.get("user_comment", ""),
                row.get("search_fts", ""),
                row.get("product_page_url_display", ""),
                row.get("monetized_product_url_display", ""),
            ],
        )
    ).lower()
    matches = []
    for label, patterns in KEYWORD_PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            matches.append(label)
    unique_matches = sorted(set(matches))
    if len(unique_matches) == 1:
        return unique_matches[0], "keyword"
    if len(unique_matches) > 1:
        return None, "ambiguous"
    return None, "no_match"


def infer_replacement(row: Dict[str, str], product_type_counts: Dict[str, Counter]) -> Tuple[str, str]:
    product_url = (row.get("product_page_url_display") or "").strip()
    product_type, product_share, _, product_source = infer_by_product_majority(product_url, product_type_counts)
    keyword_type, _ = infer_by_keywords(row)

    if product_type and keyword_type:
        if product_type == keyword_type:
            if product_source == "product_small_sample":
                return product_type, "product_small_sample+keyword_agree"
            return product_type, "product+keyword_agree"
        if product_share is not None and product_share >= PRODUCT_OVERRIDE_SHARE:
            if product_source == "product_small_sample":
                return product_type, "product_small_sample_override"
            return product_type, "product_majority_override"
        return "", "unresolved"
    if product_type:
        if product_source == "product_small_sample":
            return product_type, "product_small_sample_only"
        return product_type, "product_majority_only"
    if keyword_type:
        return keyword_type, "keyword_only"
    return "", "unresolved"


def write_rows(path: Path, header: List[str], rows: List[Dict[str, str]]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=header)
        writer.writeheader()
        writer.writerows({name: row.get(name, "") for name in header} for row in rows)
    temp_path.replace(path)


def write_report(lines: List[str]) -> None:
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    files = iter_step4_files()
    header, rows_by_file = load_rows_by_file(files)
    product_type_counts = build_product_type_counts(rows_by_file)

    total_other = 0
    total_replaced = 0
    source_counter = Counter()
    inferred_type_counter = Counter()
    unresolved_examples = []

    for path, rows in rows_by_file.items():
        for index, row in enumerate(rows, start=2):
            if normalize_type(row.get("clothing_type_id") or "") != OTHER_VALUE:
                continue
            total_other += 1
            inferred_type, source = infer_replacement(row, product_type_counts)
            source_counter[source] += 1
            if inferred_type:
                row["clothing_type_id"] = inferred_type
                total_replaced += 1
                inferred_type_counter[inferred_type] += 1
            elif len(unresolved_examples) < 10:
                unresolved_examples.append(
                    {
                        "file": path.name,
                        "row": index,
                        "product_url": row.get("product_page_url_display", ""),
                        "comment": (row.get("user_comment", "") or "")[:160],
                    }
                )

    for path, rows in rows_by_file.items():
        write_rows(path, header, rows)

    lines = [
        "# Step 4 Clothing Type Replacement Report",
        "",
        "This report records the direct replacement of `clothing_type_id = other`",
        "inside the Step 4 chunk files.",
        "",
        f"- total `other` rows before replacement: `{total_other}`",
        f"- rows replaced with inferred clothing types: `{total_replaced}`",
        f"- rows still left as `other`: `{total_other - total_replaced}`",
        f"- replacement rate: `{(total_replaced / total_other * 100):.2f}%`" if total_other else "- replacement rate: `0.00%`",
        "",
        "Replacement sources:",
        "",
    ]

    for source, count in source_counter.most_common():
        lines.append(f"- `{source}`: `{count}`")

    lines.extend(["", "Inferred clothing types written into `clothing_type_id`:", ""])
    for clothing_type, count in inferred_type_counter.most_common():
        lines.append(f"- `{clothing_type}`: `{count}`")

    if unresolved_examples:
        lines.extend(["", "Sample unresolved rows left as `other`:", ""])
        for item in unresolved_examples:
            lines.append(f"- `{item['file']}` row `{item['row']}`")
            lines.append(f"  product: `{item['product_url']}`")
            lines.append(f"  comment excerpt: `{item['comment']}`")

    write_report(lines)
    print(f"Updated Step 4 files in {STEP4_DIR}")
    print(f"Wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
