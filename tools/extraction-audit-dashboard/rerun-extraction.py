#!/usr/bin/env python3
"""Re-run the improved extract_measurements() over every approved review comment
and diff it against what was originally stored.

Input : FWM_Data/_reports/extraction_audit/dataset.json  (all approved + commented
        comments, deduped, with the originally-extracted measurements)
Output: FWM_Data/_reports/extraction_audit/reextraction.json  (per-comment old vs
        new + a summary of what changed) and a printed summary.

Run: python3 tools/extraction-audit-dashboard/rerun-extraction.py
"""
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO.parent / "FWM_Data" / "_reports" / "extraction_audit"
sys.path.insert(0, str(REPO / "data-pipelines" / "scripts" / "00_raw_scrape" / "non_amazon"))
from step1_intake_utils import extract_measurements, extract_size  # noqa: E402

# new dashboard-shaped field <- parser output. weight prefers the numeric lb,
# falling back to the range string ("175-180 lb").
FIELDS = [
    ("heightIn", lambda m: m["height_in_display"]),
    ("weightLbs", lambda m: m["weight_lbs_display"] or m["weight_display_display"]),
    ("waistIn", lambda m: m["waist_in"]),
    ("hipsIn", lambda m: m["hips_in_display"]),
    ("bustIn", lambda m: m["bust_in_display"]),
    ("braBandIn", lambda m: m["bra_band_in_display"]),
    ("cupSize", lambda m: m["cupsize_display"]),
    ("inseamIn", lambda m: m["inseam_inches_display"]),
    # New columns the review workbooks never had:
    ("ageYears", lambda m: m["age_years_display"]),
    ("weeksPregnant", lambda m: m["weeks_pregnant"]),
]


import re

NUMERIC_FIELDS = {"heightIn", "weightLbs", "waistIn", "hipsIn", "bustIn", "braBandIn", "inseamIn"}
_CUP_RE = re.compile(r"(?:AAA|AA|DDD|DD|[A-K])(?:/[A-K])?$", re.I)


def norm(v):
    return str(v or "").strip()


def old_is_valid(field, v):
    """Is a pre-existing workbook value a real measurement (vs column-shift
    garbage like a whole comment, or a stray letter in a numeric column)?
    Valid old values are preserved when the comment yields nothing."""
    if not v:
        return False
    if field == "cupSize":
        return len(v) <= 5 and bool(_CUP_RE.match(v))
    if field in NUMERIC_FIELDS:
        return len(v) <= 14 and bool(re.search(r"\d", v))
    return True


def main() -> int:
    dataset = json.loads((DATA / "dataset.json").read_text())
    rows = dataset["rows"]
    out_rows = []
    filled = Counter()       # comment filled a field that was empty/garbage
    corrected = Counter()    # comment changed a valid old value
    dropped = Counter()      # garbage old value removed (comment empty)
    preserved = Counter()    # valid old value kept (comment empty)
    comments_improved = 0

    for r in rows:
        m = extract_measurements(r["comment"])
        old = r.get("extracted", {})
        new, final, diffs = {}, {}, {}
        improved = False
        for name, getter in FIELDS:
            nv = norm(getter(m))
            ov = norm(old.get(name, ""))
            valid_old = old_is_valid(name, ov)
            new[name] = nv
            # Merge: comment value wins; else keep a valid old value; else clear.
            fv = nv if nv else (ov if valid_old else "")
            final[name] = fv
            if nv and nv != ov:
                if valid_old:
                    corrected[name] += 1
                    diffs[name] = {"old": ov, "new": nv, "kind": "corrected"}
                else:
                    filled[name] += 1
                    diffs[name] = {"old": ov, "new": nv, "kind": "filled"}
                improved = True
            elif not nv and ov:
                if valid_old:
                    preserved[name] += 1
                else:
                    dropped[name] += 1
                    diffs[name] = {"old": ov, "new": "", "kind": "dropped_garbage"}
                    improved = True
        if improved:
            comments_improved += 1
        out_rows.append({
            "id": r.get("id"),
            "rowKey": r.get("rowKey"),
            "sourceSite": r.get("sourceSite"),
            "comment": r["comment"],
            "old": {k: norm(old.get(k, "")) for k, _ in FIELDS},
            "new": new,
            "final": final,
            "diffs": diffs,
        })

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "rerun_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "extractor": "step1_intake_utils.extract_measurements (audit-fix rev)",
        "merge_policy": "comment value wins; valid old value preserved; garbage dropped",
        "total_comments": len(rows),
        "comments_improved": comments_improved,
        "filled_from_comment": dict(filled),
        "corrected_value": dict(corrected),
        "dropped_garbage": dict(dropped),
        "preserved_old_structured": dict(preserved),
        "rows": out_rows,
    }
    out = DATA / "reextraction.json"
    out.write_text(json.dumps(payload))
    (DATA / f"reextraction_{stamp}.json").write_text(json.dumps(payload))

    print(f"Re-ran extractor on {len(rows):,} approved/commented comments.")
    print(f"  {comments_improved:,} comments improved ({comments_improved/len(rows)*100:.1f}%).\n")
    def show(title, ctr, sign=""):
        print(f"  {title}:")
        for k, v in sorted(ctr.items(), key=lambda x: -x[1]):
            print(f"    {k:14} {sign}{v:,}")
        print()
    show("Filled from comment (was empty/garbage)", filled, "+")
    show("Corrected a valid value", corrected)
    show("Dropped column-shift garbage", dropped, "-")
    show("Preserved valid old value (comment silent — NOT a regression)", preserved)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
