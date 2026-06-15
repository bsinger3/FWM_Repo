#!/usr/bin/env python3
"""Run the resumable YOLO CV gate over every Supabase-qualified review row."""

from __future__ import annotations
import sys

import argparse
import csv
from collections import Counter
from pathlib import Path

from build_supabase_image_review_package import gather_candidates
from run_supabase_approval_cv_gate import (
    BASE_COLUMNS,
    DEFAULT_OUTPUT_PACKAGE,
    MAX_ROWS_PER_WORKBOOK,
    chunked,
    enrich_rows_with_yolo_gate,
    import_yolo_dependencies,
    route_row,
    write_package,
    write_readme,
)
from cv_rules_workflow_lib import (
    DEFAULT_VENDOR_DIR,
    DEFAULT_YOLO_DETECT_MODEL,
    DEFAULT_YOLO_POSE_MODEL,
    bootstrap_vendor_paths,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
PIPELINE_SCRIPTS_DIR = REPO_ROOT / "data-pipelines" / "scripts"
if str(PIPELINE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SCRIPTS_DIR))

from pipeline_paths import archive_root, cv_annotated_pending_human_review_root  # noqa: E402

LEGACY_OUTPUTS_ARCHIVE = archive_root() / "old_outputs" / "repo_outputs_archive" / "supabase_output_cleanup_2026_05_29"
CV_EXPERIMENTS_DIR = LEGACY_OUTPUTS_ARCHIVE / "cv_experiments"

DEFAULT_FULL_OUTPUT = cv_annotated_pending_human_review_root() / "supabase_production_image_review_2026_05_28_s3_refresh_full_cv_gated"
PART_COLUMNS = BASE_COLUMNS + ["original_review_bucket", "full_cv_route_bucket"]

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-package", type=Path, default=DEFAULT_FULL_OUTPUT)
    parser.add_argument("--chunk-size", type=int, default=5000)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-chunks", type=int, default=0, help="Optional cap for this invocation; useful for smoke tests.")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--yolo-batch-size", type=int, default=16)
    parser.add_argument("--download-workers", type=int, default=16)
    parser.add_argument("--vendor-dir", type=Path, default=DEFAULT_VENDOR_DIR)
    parser.add_argument("--yolo-detect-model", type=Path, default=DEFAULT_YOLO_DETECT_MODEL)
    parser.add_argument("--yolo-pose-model", type=Path, default=DEFAULT_YOLO_POSE_MODEL)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--finalize-only", action="store_true", help="Only combine completed checkpoint parts into workbooks.")
    return parser.parse_args()


def load_all_rows(limit: int = 0) -> list[dict[str, object]]:
    buckets = gather_candidates()
    rows: list[dict[str, object]] = []
    for bucket_name in ["approve_candidates", "needs_human_review", "disapprove_candidates"]:
        for row in buckets.get(bucket_name, []):
            updated = dict(row)
            updated["original_review_bucket"] = bucket_name
            updated["original_url_display"] = updated.get("image_url_to_use") or updated.get("raw_scraped_image_url") or ""
            rows.append(updated)
            if limit and len(rows) >= limit:
                return rows
    return rows


def full_route_row(row: dict[str, object]) -> str:
    cv_route = route_row(row)
    row["full_cv_route_bucket"] = cv_route
    return cv_route


def write_part(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PART_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in PART_COLUMNS})


def read_part(path: Path) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def run_chunks(args: argparse.Namespace) -> None:
    rows = load_all_rows(args.limit)
    part_dir = args.output_package / "cv_gate_checkpoint_parts"
    chunks = chunked(rows, args.chunk_size)

    bootstrap_vendor_paths(args.vendor_dir.resolve())
    np, requests, Image, YOLO = import_yolo_dependencies()
    detect_model = YOLO(str(args.yolo_detect_model.resolve()))
    pose_model = YOLO(str(args.yolo_pose_model.resolve()))
    session = requests.Session()

    processed_this_run = 0
    for index, chunk in enumerate(chunks, start=1):
        part_path = part_dir / f"full_cv_gate_part_{index:04d}.csv"
        if part_path.exists():
            print(f"skipping completed part {index}/{len(chunks)}: {part_path.name}", flush=True)
            continue
        if args.max_chunks and processed_this_run >= args.max_chunks:
            break

        print(f"processing part {index}/{len(chunks)} rows={len(chunk)}", flush=True)
        enriched = enrich_rows_with_yolo_gate(
            rows=chunk,
            detect_model=detect_model,
            pose_model=pose_model,
            np=np,
            session=session,
            Image=Image,
            timeout=args.timeout,
            min_person_confidence=0.35,
            min_pose_keypoint_confidence=0.35,
            yolo_batch_size=args.yolo_batch_size,
            download_workers=args.download_workers,
            verbose=args.verbose,
        )
        for row in enriched:
            row["full_cv_route_bucket"] = full_route_row(row)
        write_part(part_path, enriched)
        processed_this_run += 1
        print(f"wrote {part_path}", flush=True)


def finalize(args: argparse.Namespace) -> None:
    part_dir = args.output_package / "cv_gate_checkpoint_parts"
    part_paths = sorted(part_dir.glob("full_cv_gate_part_*.csv"))
    if not part_paths:
        raise SystemExit(f"No checkpoint parts found in {part_dir}")

    buckets: dict[str, list[dict[str, object]]] = {
        "approve_candidates": [],
        "disapprove_candidates": [],
        "needs_human_review": [],
    }
    for path in part_paths:
        for row in read_part(path):
            bucket = full_route_row(row)
            if bucket not in buckets:
                bucket = "needs_human_review"
            buckets[str(bucket)].append(row)

    files = write_package(args.output_package, buckets)
    write_readme(args.output_package, buckets, files)

    cv_counts = Counter(row.get("cv_reason_code") or "" for bucket_rows in buckets.values() for row in bucket_rows)
    route_counts = {bucket: len(rows) for bucket, rows in buckets.items()}
    lines = [
        "# Full Supabase CV Gate Summary",
        "",
        f"- checkpoint parts: `{len(part_paths)}`",
        f"- total rows: `{sum(route_counts.values())}`",
        "",
        "## Route Counts",
        "",
    ]
    for bucket, count in route_counts.items():
        lines.append(f"- `{bucket}`: {count}")
    lines.extend(["", "## CV Reasons", ""])
    for reason, count in cv_counts.most_common():
        lines.append(f"- `{reason or '<blank>'}`: {count}")
    lines.append("")
    (args.output_package / "FULL_CV_GATE_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")

    print(args.output_package)
    for bucket, count in route_counts.items():
        print(f"{bucket}: {count}")
    print(f"workbooks: {len(files)}")


def main() -> None:
    args = parse_args()
    args.output_package.mkdir(parents=True, exist_ok=True)
    if not args.finalize_only:
        run_chunks(args)
    finalize(args)


if __name__ == "__main__":
    main()
