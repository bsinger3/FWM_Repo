#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


PIPELINE_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import raw_scraped_data_root, repo_root, reports_root  # noqa: E402

REPO_ROOT = repo_root()
DEFAULT_CANDIDATES = REPO_ROOT / "data-pipelines" / "non-amazon" / "docs" / "sovrn_commerce_scrape_triage_candidates.csv"
DEFAULT_TRACKER = REPO_ROOT / "data-pipelines" / "non-amazon" / "docs" / "sovrn_commerce_apparel_triage_tracker.csv"
DEFAULT_REPORT_DIR = reports_root() / "measurement_coverage" / "20260609_human_labeled_approved_only"
DEFAULT_OUTPUT = DEFAULT_REPORT_DIR / "lead_gap_reprioritization.csv"
DOCS_DIR = REPO_ROOT / "data-pipelines" / "non-amazon" / "docs"
SCRAPERS_DIR = REPO_ROOT / "data-pipelines" / "scripts" / "00_raw_scrape" / "non_amazon"
DATA_ROOT = raw_scraped_data_root()


@dataclass(frozen=True)
class GapRule:
    tag: str
    approved_gap: str
    score: int
    keywords: tuple[str, ...]
    target: str


GAP_RULES = (
    GapRule(
        "plus_full_bust_lingerie",
        "bra band 40+ / cup DD+ / bust 44+",
        140,
        ("bra", "bralette", "lingerie", "underwear", "intimates", "bust", "cup", "full bust", "lascana", "foxylingerie", "wildsecrets", "thirdlove", "pepper"),
        "Highest priority: approved images are extremely thin for large bands and full-bust cups.",
    ),
    GapRule(
        "curve_denim_bottoms",
        "hips 48+ / waist 40+",
        120,
        ("jean", "denim", "pants", "trouser", "bottom", "leggings", "curve", "wide leg", "spanx", "seven7", "rollas", "abrand", "nojeans"),
        "High priority: approved rows have very little high-hip/high-waist coverage.",
    ),
    GapRule(
        "curve_swim_shapewear",
        "hips 48+ / waist 40+ / weight 260+",
        115,
        ("swim", "bikini", "swimsuit", "swimwear", "shapewear", "spanx", "lascana", "prettylittlething"),
        "High priority: swim and shapewear often expose plus/curve fit context.",
    ),
    GapRule(
        "extended_plus",
        "weight 260+ / waist 40+ / hips 48+",
        105,
        ("plus", "curve", "extended", "xxl", "3x", "4x", "5x", "6x", "tbdress", "prettylittlething", "lascana"),
        "High priority when reviews also expose photos and measurements.",
    ),
    GapRule(
        "tall_long_inseam",
        "height 5'10+ / 6'0+",
        80,
        ("tall", "inseam", "jeans", "pants", "trousers", "denim", "jumpsuit"),
        "Medium-high priority: tall rows are thin, especially 6 ft plus.",
    ),
    GapRule(
        "petite",
        "height under 5'0",
        45,
        ("petite", "cropped", "mini"),
        "Lower than plus/full-bust, but useful if measurement/photo yield is strong.",
    ),
)

KNOWN_PROVIDER_BONUS = {
    "bazaarvoice": 35,
    "yotpo": 30,
    "okendo": 30,
    "judge.me": 25,
    "loox": 20,
    "reviews.io": 20,
    "stamped": 15,
}


def norm(value: str | None) -> str:
    return (value or "").strip()


def slug(value: str) -> str:
    value = value.lower()
    value = re.sub(r"^www\.", "", value)
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def host_from_url(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"https://{text}"
    host = urlparse(text).netloc.lower()
    return re.sub(r"^www\.", "", host)


def host_slugs(value: str) -> set[str]:
    host = host_from_url(value) or value.strip().lower()
    host = re.sub(r"^www\.", "", host)
    if not host:
        return set()
    parts = [part for part in host.split(".") if part]
    slugs = {slug(host)}
    second_level_tlds = {"co", "com", "net", "org"}
    if len(parts) >= 3 and parts[-2] in second_level_tlds and len(parts[-1]) == 2:
        slugs.add(slug(".".join(parts[-3:])))
        slugs.add(parts[-3])
    elif len(parts) >= 2:
        slugs.add(slug(".".join(parts[-2:])))
        slugs.add(parts[-2])
    if len(parts) >= 3 and not (parts[-2] in second_level_tlds and len(parts[-1]) == 2):
        slugs.add(slug(".".join(parts[-3:])))
    return {item for item in slugs if item}


def artifact_aliases(row: dict[str, str]) -> set[str]:
    aliases: set[str] = set()
    fields = ("primary_domain", "category_evidence_url", "sample_pdp_urls")
    for field in fields:
        raw = norm(row.get(field))
        if not raw:
            continue
        for piece in re.split(r"\s+\|\s+|\s+", raw):
            aliases.update(host_slugs(piece))
    return aliases


def money_to_float(value: str) -> float:
    text = norm(value).replace("$", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return 0.0


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def tracker_by_domain(tracker_rows: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for row in tracker_rows:
        domains = [part.strip() for part in norm(row.get("primary_domains")).split(";") if part.strip()]
        for domain in domains:
            lookup.setdefault(domain, row)
            lookup.setdefault(domain.replace("www.", ""), row)
    return lookup


def text_blob(row: dict[str, str], tracker_row: dict[str, str] | None) -> str:
    parts = []
    for source in (row, tracker_row or {}):
        for field in (
            "merchant_group",
            "primary_domain",
            "category_evidence_url",
            "sample_pdp_urls",
            "integration_note",
            "human_findings",
            "final_queue_notes",
            "reason",
            "size_basis",
            "review_photo_evidence",
            "next_action",
        ):
            parts.append(norm(source.get(field)))
    return " ".join(parts).lower()


def gap_target_blob(row: dict[str, str], tracker_row: dict[str, str] | None) -> str:
    parts = []
    for source in (row, tracker_row or {}):
        for field in (
            "merchant_group",
            "primary_domain",
            "category_evidence_url",
            "sample_pdp_urls",
            "human_findings",
            "final_queue_notes",
            "review_photo_evidence",
        ):
            parts.append(norm(source.get(field)))
    return " ".join(parts).lower()


def gap_matches(blob: str) -> list[GapRule]:
    matches = []
    for rule in GAP_RULES:
        if any(keyword_matches(blob, keyword) for keyword in rule.keywords):
            matches.append(rule)
    return matches


def keyword_matches(blob: str, keyword: str) -> bool:
    keyword = keyword.lower()
    if " " in keyword or "'" in keyword:
        return keyword in blob
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", blob))


def provider_score(provider: str) -> int:
    text = provider.lower()
    return sum(score for key, score in KNOWN_PROVIDER_BONUS.items() if key in text)


def existing_artifacts(row: dict[str, str]) -> dict[str, str]:
    aliases = artifact_aliases(row)
    alias_compacts = {compact(alias) for alias in aliases}

    def matches_alias(path: Path) -> bool:
        path_compact = compact(path.stem)
        return any(alias and alias in path_compact for alias in alias_compacts)

    docs = sorted(path for path in DOCS_DIR.glob("*_scrape_*.md") if matches_alias(path))
    scripts = sorted(path for path in SCRAPERS_DIR.glob("scrape_*_reviews.py") if matches_alias(path))
    data_dirs = sorted(path for path in DATA_ROOT.iterdir() if path.is_dir() and not path.name.startswith("_") and matches_alias(path)) if DATA_ROOT.exists() else []
    claims_dir = DATA_ROOT / "_claims"
    claims = sorted(path for path in claims_dir.glob("*.claim") if matches_alias(path)) if claims_dir.exists() else []

    status = "not_seen"
    claim_text = " ".join(path.name.lower() for path in claims)
    if "completed" in claim_text:
        status = "completed"
    elif any(term in claim_text for term in ("blocked", "stopped", "deferred", "no_public")):
        status = "blocked_or_no_public"
    elif docs or data_dirs:
        status = "data_present"
    elif scripts:
        status = "script_exists"

    evidence = [*(str(path.relative_to(REPO_ROOT)) for path in docs[-2:])]
    evidence.extend(str(path.relative_to(REPO_ROOT)) for path in scripts[-1:])
    evidence.extend(str(path.relative_to(DATA_ROOT)) for path in data_dirs[-2:])
    evidence.extend(str(path.relative_to(DATA_ROOT)) for path in claims[-3:])
    return {
        "existing_artifact_status": status,
        "existing_scrape_doc_found": "yes" if docs else "no",
        "existing_scraper_script_found": "yes" if scripts else "no",
        "existing_data_dir_found": "yes" if data_dirs else "no",
        "existing_claim_found": "yes" if claims else "no",
        "existing_artifact_aliases": ";".join(sorted(aliases)),
        "existing_scrape_artifacts": "; ".join(evidence),
    }


def score_candidate(row: dict[str, str], tracker_row: dict[str, str] | None) -> dict[str, str]:
    blob = gap_target_blob(row, tracker_row)
    matches = gap_matches(blob)
    gap_score = sum(rule.score for rule in matches)
    tags = [rule.tag for rule in matches]
    approved_gaps = sorted({rule.approved_gap for rule in matches})
    targets = [rule.target for rule in matches]

    photo_reviews = norm(row.get("photo_reviews") or (tracker_row or {}).get("photo_reviews")).lower()
    reviews_present = norm(row.get("reviews_present") or (tracker_row or {}).get("reviews_present")).lower()
    review_provider = norm(row.get("review_provider") or (tracker_row or {}).get("review_provider"))
    priority = norm(row.get("priority") or (tracker_row or {}).get("priority"))
    queue_status = norm(row.get("queue_status"))
    final_decision = norm(row.get("final_queue_decision"))
    artifacts = existing_artifacts(row)
    is_active_candidate = final_decision in {
        "ready_first_pass_candidate",
        "refresh_existing_scraper",
        "approved_category_specific_scrape",
    } or queue_status in {
        "sovrn_first_pass_scrape_candidate",
        "approved_refresh_existing_scraper",
        "approved_category_specific_scrape",
    }

    evidence_score = 0
    if photo_reviews == "yes":
        evidence_score += 60
    elif photo_reviews == "unknown_sample_too_small":
        evidence_score += 25
    if reviews_present == "yes":
        evidence_score += 30
    evidence_score += provider_score(review_provider)
    if priority == "P1":
        evidence_score += 25
    elif priority == "P2":
        evidence_score += 15
    elif priority == "P3":
        evidence_score += 5
    if "approved" in queue_status:
        evidence_score += 25
    if "refresh" in queue_status:
        evidence_score += 10
    if "candidate" in final_decision:
        evidence_score += 15
    payout_score = min(int(money_to_float(row.get("estimated_commission_per_click")) * 100), 40)

    existing_penalty = 0
    if artifacts["existing_artifact_status"] == "completed" and "refresh" not in queue_status:
        existing_penalty = 350
    elif artifacts["existing_artifact_status"] in {"blocked_or_no_public", "data_present"} and "refresh" not in queue_status:
        existing_penalty = 220
    elif artifacts["existing_artifact_status"] == "script_exists" and "refresh" not in queue_status:
        existing_penalty = 80
    inactive_penalty = 0 if is_active_candidate else 500

    total = gap_score + evidence_score + payout_score - existing_penalty - inactive_penalty
    if not matches:
        total -= 40

    if not is_active_candidate:
        next_action = "do_not_queue_existing_triage_rejected"
    elif artifacts["existing_artifact_status"] == "completed" and "refresh" not in queue_status:
        next_action = "skip_already_completed"
    elif artifacts["existing_artifact_status"] == "blocked_or_no_public" and "refresh" not in queue_status:
        next_action = "skip_or_revisit_only_if_gap_is_critical"
    elif artifacts["existing_artifact_status"] == "data_present" and "refresh" not in queue_status:
        next_action = "inspect_existing_output_before_new_scrape"
    elif "refresh" in queue_status or artifacts["existing_scraper_script_found"] == "yes":
        next_action = "probe_refresh_for_gap_yield"
    elif photo_reviews == "yes" and matches:
        next_action = "probe_then_scrape_if_measurement_yield_is_good"
    elif photo_reviews == "unknown_sample_too_small" and matches:
        next_action = "quick_photo_measurement_probe_before_scrape"
    elif matches:
        next_action = "category_level_gap_probe"
    else:
        next_action = "hold_low_gap_fit"

    return {
        "gap_priority_score": str(total),
        "gap_match_tags": ";".join(tags),
        "approved_coverage_gaps_targeted": "; ".join(approved_gaps),
        "gap_target_reason": " | ".join(targets),
        "gap_evidence_score": str(evidence_score),
        "gap_category_score": str(gap_score),
        "payout_score": str(payout_score),
        **artifacts,
        "active_candidate_status": "yes" if is_active_candidate else "no",
        "recommended_gap_next_action": next_action,
    }


def write_ranked(candidates_path: Path, tracker_path: Path, output_path: Path) -> None:
    candidates = read_csv(candidates_path)
    tracker_lookup = tracker_by_domain(read_csv(tracker_path))
    ranked = []
    for row in candidates:
        domain = norm(row.get("primary_domain"))
        tracker_row = tracker_lookup.get(domain) or tracker_lookup.get(domain.replace("www.", ""))
        scored = dict(row)
        scored.update(score_candidate(row, tracker_row))
        ranked.append(scored)

    ranked.sort(key=lambda row: int(row["gap_priority_score"]), reverse=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "gap_priority_score",
        "gap_match_tags",
        "approved_coverage_gaps_targeted",
        "recommended_gap_next_action",
        "merchant_group",
        "primary_domain",
        "priority",
        "queue_status",
        "review_provider",
        "photo_reviews",
        "reviews_present",
        "estimated_commission_per_click",
        "category_evidence_url",
        "sample_pdp_urls",
        "gap_target_reason",
        "gap_evidence_score",
        "gap_category_score",
        "payout_score",
        "existing_scrape_doc_found",
        "existing_scraper_script_found",
        "existing_data_dir_found",
        "existing_claim_found",
        "existing_artifact_status",
        "active_candidate_status",
        "existing_artifact_aliases",
        "existing_scrape_artifacts",
        "final_queue_decision",
        "final_queue_notes",
        "human_findings",
    ]
    extras = [field for field in ranked[0].keys() if field not in fieldnames]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames + extras)
        writer.writeheader()
        writer.writerows(ranked)


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-rank triaged Sovrn leads against approved-image measurement coverage gaps.")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--tracker", type=Path, default=DEFAULT_TRACKER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    write_ranked(args.candidates, args.tracker, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
