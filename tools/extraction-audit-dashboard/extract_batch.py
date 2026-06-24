#!/usr/bin/env python3
"""Batch measurement extractor for the audit dashboard builder.

Reads NDJSON {"id":..., "comment":...} on stdin, runs the CURRENT
extract_measurements() on each comment, and writes NDJSON
{"id":..., "m":{<dashboard fields>}} on stdout. This is how the Node dataset
builder shows extractions from the live regexes instead of stale workbook values.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "data-pipelines" / "scripts" / "00_raw_scrape" / "non_amazon"))
from step1_intake_utils import extract_measurements  # noqa: E402


def to_dashboard(m):
    return {
        "heightIn": m["height_in_display"],
        "weightLbs": m["weight_lbs_display"] or m["weight_display_display"],
        "waistIn": m["waist_in"],
        "hipsIn": m["hips_in_display"],
        "bustIn": m["bust_in_display"],
        "braBandIn": m["bra_band_in_display"],
        "cupSize": m["cupsize_display"],
        "inseamIn": m["inseam_inches_display"],
        "ageYears": m["age_years_display"],
        "weeksPregnant": m["weeks_pregnant"],
    }


def main():
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        m = extract_measurements(rec.get("comment", "") or "")
        out.write(json.dumps({"id": rec["id"], "m": to_dashboard(m)}) + "\n")


if __name__ == "__main__":
    main()
