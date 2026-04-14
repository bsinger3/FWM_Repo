#!/usr/bin/env python3
import csv
import hashlib
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = PIPELINE_ROOT / "data" / "step_3_image_annotation" / "machine_annotated_outputs"
OUTPUT_PATH = PIPELINE_ROOT / "docs" / "reviewer_cap_impact_report.md"

ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})(?:[/?#]|$)", re.I)
ACCOUNT_RE = re.compile(r"(amzn1\.account\.[A-Z0-9]+)", re.I)
PROFILE_RE = re.compile(r"/gp/profile/([^/?#]+)", re.I)
WS_RE = re.compile(r"\s+")


def extract_asin(url: str) -> str:
    value = (url or "").strip()
    match = ASIN_RE.search(value)
    return match.group(1).upper() if match else value


def extract_profile_id(url: str) -> str:
    value = (url or "").strip()
    match = ACCOUNT_RE.search(value)
    if match:
        return match.group(1)
    match = PROFILE_RE.search(value)
    return match.group(1) if match else ""


def normalize_text(value: str) -> str:
    return WS_RE.sub(" ", (value or "").strip().lower())


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12] if value else ""


def reviewer_key(row: dict[str, str]) -> tuple[str, str]:
    profile_id = extract_profile_id(row.get("reviewer_profile_url") or "")
    if profile_id:
        return ("profile", profile_id)

    reviewer_name = normalize_text(row.get("reviewer_name_raw") or "")
    review_date = (row.get("review_date") or "").strip()
    user_comment = normalize_text(row.get("user_comment") or "")

    if reviewer_name and review_date and user_comment:
        return ("name_date_comment", f"{reviewer_name}|{review_date}|{short_hash(user_comment)}")
    if review_date and user_comment:
        return ("date_comment", f"{review_date}|{short_hash(user_comment)}")
    if user_comment:
        return ("comment", short_hash(user_comment))
    if reviewer_name and review_date:
        return ("name_date", f"{reviewer_name}|{review_date}")
    if reviewer_name:
        return ("name", reviewer_name)
    return ("missing", "")


def load_rows():
    files = sorted(INPUT_DIR.glob("images_to_approve_part_*.csv"))
    for path in files:
        with path.open("r", newline="", encoding="utf-8-sig") as infile:
            reader = csv.DictReader(infile)
            for row in reader:
                yield row


def main() -> None:
    usable_rows = []
    fallback_counter = Counter()
    profile_present = 0

    for row in load_rows():
        if (row.get("has_person_REVIEWONLY") or "").strip().lower() != "true":
            continue
        product_id = extract_asin(row.get("product_page_url_display") or "")
        reviewer_kind, reviewer_id = reviewer_key(row)
        if reviewer_kind == "profile":
            profile_present += 1
        else:
            fallback_counter[reviewer_kind] += 1
        usable_rows.append(
            {
                "product_id": product_id,
                "reviewer_kind": reviewer_kind,
                "reviewer_id": reviewer_id,
                "product_url": (row.get("product_page_url_display") or "").strip(),
                "reviewer_url": (row.get("reviewer_profile_url") or "").strip(),
            }
        )

    combo_counts = Counter((row["product_id"], row["reviewer_kind"], row["reviewer_id"]) for row in usable_rows)
    combo_sizes = list(combo_counts.values())

    cap_results = {}
    cap_examples = {}
    for cap in (2, 3, 4):
        running = defaultdict(int)
        kept = 0
        removed = 0
        for row in usable_rows:
            key = (row["product_id"], row["reviewer_kind"], row["reviewer_id"])
            running[key] += 1
            if running[key] <= cap:
                kept += 1
            else:
                removed += 1
        cap_results[cap] = {"kept": kept, "removed": removed}
        cap_examples[cap] = sum(1 for size in combo_sizes if size > cap)

    top_combos = []
    for (product_id, reviewer_kind, reviewer_id), count in combo_counts.most_common(25):
        top_combos.append(
            {
                "product_id": product_id or "(missing)",
                "reviewer_kind": reviewer_kind,
                "reviewer_id": reviewer_id or "(missing)",
                "images": count,
            }
        )

    lines = []
    lines.append("# Reviewer Cap Impact Report")
    lines.append("")
    lines.append(
        "Source: usable rows from finished chunk files in "
        "`data/step_3_image_annotation/machine_annotated_outputs/images_to_approve_part_*.csv`, "
        "where usable means `has_person_REVIEWONLY = true`."
    )
    lines.append("")
    lines.append("## Reviewer Identity Rule")
    lines.append("")
    lines.append("- Use reviewer profile ID when `reviewer_profile_url` is present.")
    lines.append("- Otherwise fall back in this order:")
    lines.append("  1. `reviewer_name_raw + review_date + hash(user_comment)`")
    lines.append("  2. `review_date + hash(user_comment)`")
    lines.append("  3. `hash(user_comment)`")
    lines.append("  4. `reviewer_name_raw + review_date`")
    lines.append("  5. `reviewer_name_raw`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total usable images (`has_person_REVIEWONLY = true`): {len(usable_rows):,}")
    lines.append(f"- Usable rows with profile-based reviewer ID: {profile_present:,}")
    lines.append(f"- Usable rows using fallback reviewer identity: {sum(fallback_counter.values()):,}")
    lines.append(f"- Unique product-reviewer combinations under smart fallback: {len(combo_counts):,}")
    lines.append(f"- Median usable images per smart reviewer-product combination: {statistics.median(combo_sizes):.0f}")
    lines.append(f"- Max usable images for one smart reviewer-product combination: {max(combo_sizes):,}")
    lines.append("")
    lines.append("## Fallback Coverage")
    lines.append("")
    lines.append("| Fallback type | Rows | Share of usable rows |")
    lines.append("|---|---:|---:|")
    total_usable = len(usable_rows)
    lines.append(f"| profile | {profile_present:,} | {profile_present/total_usable:.1%} |")
    for kind in ("name_date_comment", "date_comment", "comment", "name_date", "name", "missing"):
        count = fallback_counter.get(kind, 0)
        lines.append(f"| {kind} | {count:,} | {count/total_usable:.1%} |")
    lines.append("")
    lines.append("## Cap Impact")
    lines.append("")
    lines.append("| Cap per reviewer-product pair | Kept usable images | Removed usable images | Share removed | Combos affected |")
    lines.append("|---|---:|---:|---:|---:|")
    for cap in (2, 3, 4):
        kept = cap_results[cap]["kept"]
        removed = cap_results[cap]["removed"]
        affected = cap_examples[cap]
        lines.append(
            f"| {cap} | {kept:,} | {removed:,} | {removed/total_usable:.1%} | {affected:,} |"
        )
    lines.append("")
    lines.append("## Comparison To Profile-Only Cap")
    lines.append("")
    lines.append("- Earlier profile-only estimate for cap 2 kept `33,430` usable images.")
    lines.append(f"- Smart fallback keeps `{cap_results[2]['kept']:,}` usable images at cap 2.")
    lines.append(
        f"- That preserves `{cap_results[2]['kept'] - 33430:,}` more usable images than the profile-only method."
    )
    lines.append("")
    lines.append("## Top 25 Most Repeated Smart Reviewer-Product Combinations")
    lines.append("")
    lines.append("| Rank | Images | Product ID | Reviewer key type | Reviewer key |")
    lines.append("|---|---:|---|---|---|")
    for index, item in enumerate(top_combos, start=1):
        lines.append(
            f"| {index} | {item['images']} | {item['product_id']} | {item['reviewer_kind']} | {item['reviewer_id']} |"
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append("")
    lines.append("- If you want to reduce concentration without throwing away a huge number of usable rows, the smart fallback is much better than relying on profile URL alone.")
    lines.append("- A cap of 2 is still pretty aggressive.")
    lines.append("- A cap of 3 or 4 may be a better starting point if you want to preserve more reviewer/product coverage while still cutting down repeated images.")

    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
