#!/usr/bin/env python3
"""Audit LOW_RESOLUTION yes-label rows for recoverable larger image URLs."""

from __future__ import annotations
import sys

import csv
import re
from io import BytesIO
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[4]
PIPELINE_SCRIPTS_DIR = REPO_ROOT / "data-pipelines" / "scripts"
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, cv_annotated_pending_human_review_root  # noqa: E402

LEGACY_OUTPUTS_ARCHIVE = archive_root() / "old_outputs" / "repo_outputs_archive" / "supabase_output_cleanup_2026_05_29"
CV_EXPERIMENTS_DIR = LEGACY_OUTPUTS_ARCHIVE / "cv_experiments"

OUT_DIR = CV_EXPERIMENTS_DIR / "combined_reason_ground_truth_2026_05_25"
LABELED_DIR = OUT_DIR / "labeled_2026_05_27"
LABELED_CSV = LABELED_DIR / "combined_rejection_reason_yes_no_review_queue_labeled.csv"
AUDIT_CSV = LABELED_DIR / "low_resolution_url_upgrade_audit.csv"


def normalize_answer(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"Y", "YES", "TRUE", "1"}:
        return "YES"
    if text in {"N", "NO", "FALSE", "0"}:
        return "NO"
    if text in {"UNSURE", "UNKNOWN", "MAYBE", "?"}:
        return "UNSURE"
    return ""


def unique(items: Iterable[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def replace_query_params(url: str, replacements: dict[str, str | None]) -> str:
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key in replacements:
            replacement = replacements[key]
            if replacement is None:
                continue
            query.append((key, replacement))
        else:
            query.append((key, value))
    existing_keys = {key for key, _ in query}
    for key, value in replacements.items():
        if value is not None and key not in existing_keys:
            query.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def larger_image_url_candidates(url: str) -> list[str]:
    candidates = [url]
    try:
        parts = urlsplit(url)
    except Exception:
        return candidates

    host = parts.netloc.lower()
    filename = parts.path.rsplit("/", 1)[-1]

    if ("media-amazon.com" in host or "images-amazon.com" in host) and "._" in filename:
        stem, _transform = filename.split("._", 1)
        extension = ""
        for candidate_extension in (".jpg", ".jpeg", ".png", ".webp"):
            if filename.lower().endswith(candidate_extension):
                extension = filename[-len(candidate_extension) :]
                break
        if extension:
            canonical_path = parts.path.rsplit("/", 1)[0] + "/" + stem + extension
            candidates.insert(0, urlunsplit((parts.scheme, parts.netloc, canonical_path, parts.query, parts.fragment)))

    if "imgix.net" in host:
        candidates.insert(0, replace_query_params(url, {"w": "1200", "h": None, "fit": None, "crop": None}))
        candidates.insert(0, replace_query_params(url, {"w": None, "h": None, "fit": None, "crop": None}))

    if "media-dynamic.okendo.io" in host:
        candidates.insert(0, replace_query_params(url, {"d": "1200x1200", "crop": None}))
        candidates.insert(0, replace_query_params(url, {"d": None, "crop": None}))

    if "judgeme" in host and "w=" in parts.query:
        candidates.insert(0, replace_query_params(url, {"w": "1200"}))
        candidates.insert(0, replace_query_params(url, {"w": None}))

    return unique(candidates)


def fetch_dimensions(url: str, timeout: float = 8.0) -> tuple[bool, int, int, int, str]:
    try:
        request = Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123 Safari/537.36"},
        )
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
        image = Image.open(BytesIO(data))
        return True, image.size[0], image.size[1], len(data), ""
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return False, 0, 0, 0, repr(exc)


def read_rows() -> list[dict[str, str]]:
    with LABELED_CSV.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    source_rows = [
        row
        for row in read_rows()
        if row.get("rejection_reason") == "LOW_RESOLUTION"
        and normalize_answer(row.get("answer_yes_no")) == "YES"
        and row.get("original_url_display")
    ]
    audit_rows = []
    for row in source_rows:
        original_url = row["original_url_display"]
        best = {"url": original_url, "ok": False, "width": 0, "height": 0, "bytes": 0, "error": ""}
        attempts = []
        for candidate in larger_image_url_candidates(original_url):
            ok, width, height, byte_count, error = fetch_dimensions(candidate)
            attempts.append(f"{candidate}=>{width}x{height}" if ok else f"{candidate}=>ERROR")
            if ok and width * height > int(best["width"]) * int(best["height"]):
                best = {"url": candidate, "ok": ok, "width": width, "height": height, "bytes": byte_count, "error": error}
        original_ok, original_width, original_height, original_bytes, original_error = fetch_dimensions(original_url)
        upgraded = best["ok"] and best["url"] != original_url and int(best["width"]) * int(best["height"]) > original_width * original_height
        audit_rows.append(
            {
                "review_row_key": row.get("review_row_key", ""),
                "source_site_display": row.get("source_site_display", ""),
                "original_url_display": original_url,
                "recommended_image_url": best["url"] if upgraded else original_url,
                "url_upgrade_found": upgraded,
                "original_load_ok": original_ok,
                "original_width": original_width,
                "original_height": original_height,
                "best_width": best["width"],
                "best_height": best["height"],
                "best_bytes": best["bytes"],
                "attempts": " | ".join(attempts),
                "product_page_url_display": row.get("product_page_url_display", ""),
            }
        )

    with AUDIT_CSV.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(audit_rows[0].keys()) if audit_rows else [
            "review_row_key",
            "source_site_display",
            "original_url_display",
            "recommended_image_url",
            "url_upgrade_found",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(audit_rows)
    print(AUDIT_CSV)
    print(f"rows: {len(audit_rows)}")
    print(f"upgrades: {sum(1 for row in audit_rows if row['url_upgrade_found'])}")


if __name__ == "__main__":
    main()
