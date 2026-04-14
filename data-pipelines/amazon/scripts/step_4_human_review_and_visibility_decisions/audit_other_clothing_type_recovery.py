#!/usr/bin/env python3
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


PIPELINE_ROOT = Path(__file__).resolve().parents[2]
STEP4_INPUT_DIR = PIPELINE_ROOT / "data" / "step_4_human_review_and_visibility_decisions"
DOCS_DIR = PIPELINE_ROOT / "docs"
REPORT_PATH = DOCS_DIR / "step_4_clothing_type_other_audit.md"
PREVIEW_PATH = DOCS_DIR / "step_4_clothing_type_other_inference_preview.csv"

OTHER_VALUE = "other"
PRODUCT_MAJORITY_MIN_ROWS = 3
PRODUCT_MAJORITY_MIN_SHARE = 0.70
PRODUCT_OVERRIDE_SHARE = 0.85

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
}


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def normalize_type(value: str) -> str:
    return normalize_whitespace(value).lower()


def iter_step4_rows():
    for path in sorted(STEP4_INPUT_DIR.glob("images_to_approve_part_*.csv")):
        with path.open("r", encoding="utf-8", newline="") as infile:
            reader = csv.DictReader(infile)
            for row_number, row in enumerate(reader, start=2):
                yield path.name, row_number, row


def build_product_type_counts(rows: List[Tuple[str, int, Dict[str, str]]]) -> Dict[str, Counter]:
    counts = defaultdict(Counter)
    for _, _, row in rows:
        product_url = (row.get("product_page_url_display") or "").strip()
        clothing_type = normalize_type(row.get("clothing_type_id") or "")
        if product_url and clothing_type and clothing_type != OTHER_VALUE:
            counts[product_url][clothing_type] += 1
    return counts


def infer_by_product_majority(
    product_url: str, product_type_counts: Dict[str, Counter]
) -> Tuple[Optional[str], Optional[float], Optional[int]]:
    counts = product_type_counts.get(product_url)
    if not counts:
        return None, None, None

    total = sum(counts.values())
    top_type, top_count = counts.most_common(1)[0]
    share = top_count / total if total else 0.0

    if total >= PRODUCT_MAJORITY_MIN_ROWS and share >= PRODUCT_MAJORITY_MIN_SHARE:
        return top_type, share, total
    return None, share, total


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


def infer_replacement(
    row: Dict[str, str], product_type_counts: Dict[str, Counter]
) -> Dict[str, object]:
    product_url = (row.get("product_page_url_display") or "").strip()
    product_type, product_share, product_total = infer_by_product_majority(product_url, product_type_counts)
    keyword_type, keyword_status = infer_by_keywords(row)

    inferred_type = None
    source = "unresolved"
    note = ""

    if product_type and keyword_type:
        if product_type == keyword_type:
            inferred_type = product_type
            source = "product+keyword_agree"
        elif product_share is not None and product_share >= PRODUCT_OVERRIDE_SHARE:
            inferred_type = product_type
            source = "product_majority_override"
            note = "product-majority and keyword disagree; strong product-majority wins"
        else:
            note = "product-majority and keyword disagree"
    elif product_type:
        inferred_type = product_type
        source = "product_majority_only"
    elif keyword_type:
        inferred_type = keyword_type
        source = "keyword_only"
    else:
        note = keyword_status

    return {
        "inferred_type": inferred_type or "",
        "source": source,
        "product_majority_type": product_type or "",
        "product_majority_share": f"{product_share:.2%}" if product_share is not None else "",
        "product_majority_known_rows": product_total if product_total is not None else "",
        "keyword_type": keyword_type or "",
        "keyword_status": keyword_status,
        "note": note,
    }


def write_preview(preview_rows: List[Dict[str, str]]) -> None:
    fieldnames = [
        "file_name",
        "row_number",
        "original_url_display",
        "product_page_url_display",
        "clothing_type_id",
        "clothing_type_inferred_REVIEWONLY",
        "clothing_type_inference_source_REVIEWONLY",
        "clothing_type_product_majority_REVIEWONLY",
        "clothing_type_product_majority_share_REVIEWONLY",
        "clothing_type_product_majority_known_rows_REVIEWONLY",
        "clothing_type_keyword_match_REVIEWONLY",
        "clothing_type_keyword_status_REVIEWONLY",
        "clothing_type_inference_note_REVIEWONLY",
        "user_comment",
    ]
    with PREVIEW_PATH.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(preview_rows)


def write_report(lines: List[str]) -> None:
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rows = list(iter_step4_rows())
    product_type_counts = build_product_type_counts(rows)

    total_rows = len(rows)
    overall_type_counts = Counter(normalize_type(row.get("clothing_type_id") or "") for _, _, row in rows)
    other_rows = [(file_name, row_number, row) for file_name, row_number, row in rows if normalize_type(row.get("clothing_type_id") or "") == OTHER_VALUE]

    source_counter = Counter()
    inferred_type_counter = Counter()
    keyword_counter = Counter()
    preview_rows = []
    examples = defaultdict(list)

    for file_name, row_number, row in other_rows:
        result = infer_replacement(row, product_type_counts)
        source_counter[result["source"]] += 1
        if result["inferred_type"]:
            inferred_type_counter[result["inferred_type"]] += 1
        keyword_counter[result["keyword_type"] or result["keyword_status"]] += 1

        preview_rows.append(
            {
                "file_name": file_name,
                "row_number": str(row_number),
                "original_url_display": row.get("original_url_display", ""),
                "product_page_url_display": row.get("product_page_url_display", ""),
                "clothing_type_id": row.get("clothing_type_id", ""),
                "clothing_type_inferred_REVIEWONLY": result["inferred_type"],
                "clothing_type_inference_source_REVIEWONLY": result["source"],
                "clothing_type_product_majority_REVIEWONLY": result["product_majority_type"],
                "clothing_type_product_majority_share_REVIEWONLY": result["product_majority_share"],
                "clothing_type_product_majority_known_rows_REVIEWONLY": str(result["product_majority_known_rows"]),
                "clothing_type_keyword_match_REVIEWONLY": result["keyword_type"],
                "clothing_type_keyword_status_REVIEWONLY": result["keyword_status"],
                "clothing_type_inference_note_REVIEWONLY": result["note"],
                "user_comment": row.get("user_comment", ""),
            }
        )

        bucket = result["source"]
        if len(examples[bucket]) < 5:
            examples[bucket].append(
                {
                    "file_name": file_name,
                    "row_number": row_number,
                    "product_url": row.get("product_page_url_display", ""),
                    "existing_type": row.get("clothing_type_id", ""),
                    "inferred_type": result["inferred_type"],
                    "product_majority_type": result["product_majority_type"],
                    "product_majority_share": result["product_majority_share"],
                    "keyword_type": result["keyword_type"] or result["keyword_status"],
                    "note": result["note"],
                    "comment_excerpt": (row.get("user_comment", "") or "")[:180],
                }
            )

    resolved_count = sum(inferred_type_counter.values())
    unresolved_count = len(other_rows) - resolved_count

    lines = [
        "# Step 4 Clothing Type `other` Audit",
        "",
        "This report audits how many Step 4 rows currently have `clothing_type_id = other`",
        "and estimates how many can be recovered with deterministic Python logic",
        "without mutating the Step 4 chunk files.",
        "",
        "## Current Counts",
        "",
        f"- total Step 4 rows: `{total_rows}`",
        f"- rows with `clothing_type_id = other`: `{len(other_rows)}`",
        f"- percentage of Step 4 rows in `other`: `{(len(other_rows) / total_rows * 100):.2f}%`",
        "",
        "Current overall clothing type counts:",
        "",
    ]

    for clothing_type, count in overall_type_counts.most_common():
        label = clothing_type or "<blank>"
        lines.append(f"- `{label}`: `{count}`")

    lines.extend(
        [
            "",
            "## Proposed Inference Logic",
            "",
            "- keep any non-`other` `clothing_type_id` unchanged",
            f"- use product-majority when a product has at least `{PRODUCT_MAJORITY_MIN_ROWS}` known rows and the dominant type is at least `{PRODUCT_MAJORITY_MIN_SHARE:.0%}`",
            "- otherwise fall back to keyword matching on comments, search text, and product URLs",
            f"- if product-majority and keywords disagree, let product-majority win only when it is at least `{PRODUCT_OVERRIDE_SHARE:.0%}`",
            "- otherwise leave the row unresolved for review",
            "",
            "## First-Pass Results",
            "",
            f"- rows recoverable in the first pass: `{resolved_count}`",
            f"- percentage of `other` recoverable in the first pass: `{(resolved_count / len(other_rows) * 100):.2f}%`",
            f"- rows still unresolved after the first pass: `{unresolved_count}`",
            "",
            "Inference source counts:",
            "",
        ]
    )

    for source, count in source_counter.most_common():
        lines.append(f"- `{source}`: `{count}`")

    lines.extend(["", "Recovered clothing types:", ""])
    for clothing_type, count in inferred_type_counter.most_common():
        lines.append(f"- `{clothing_type}`: `{count}`")

    lines.extend(["", "Keyword signal counts for `other` rows:", ""])
    for label, count in keyword_counter.most_common():
        lines.append(f"- `{label}`: `{count}`")

    lines.extend(
        [
            "",
            "## Preview Output",
            "",
            "- detailed per-row preview CSV:",
            f"  `{PREVIEW_PATH.name}`",
            "- this CSV includes helper columns showing the inferred type, the source of the inference,",
            "  the product-majority evidence, and the keyword evidence",
            "",
        ]
    )

    for bucket in ["product+keyword_agree", "product_majority_override", "product_majority_only", "keyword_only", "unresolved"]:
        if not examples[bucket]:
            continue
        lines.append("## Examples: `{}`".format(bucket))
        lines.append("")
        for example in examples[bucket]:
            lines.append("- file: `{}` row `{}`".format(example["file_name"], example["row_number"]))
            lines.append("  product: `{}`".format(example["product_url"]))
            lines.append("  existing type: `{}`".format(example["existing_type"]))
            lines.append("  inferred type: `{}`".format(example["inferred_type"]))
            lines.append("  product-majority: `{}` at `{}`".format(example["product_majority_type"], example["product_majority_share"]))
            lines.append("  keyword signal: `{}`".format(example["keyword_type"]))
            if example["note"]:
                lines.append("  note: `{}`".format(example["note"]))
            lines.append("  comment excerpt: `{}`".format(example["comment_excerpt"]))
            lines.append("")

    write_preview(preview_rows)
    write_report(lines)
    print(REPORT_PATH)
    print(PREVIEW_PATH)


if __name__ == "__main__":
    main()
