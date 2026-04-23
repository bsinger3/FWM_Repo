#!/usr/bin/env python3
import argparse
from pathlib import Path

from csv_output_validation import validate_csv_file
from cv_rules_workflow_lib import (
    CV_ENRICHED_DIR,
    CV_RULES_DIR,
    REPORTS_DIR,
    REVIEW_QUEUE_DIR,
    CV_METADATA_COLUMNS,
    OPTIONAL_CV_COLUMNS,
    REQUIRED_CV_COLUMNS,
    RULE_OUTPUT_COLUMNS,
    add_row_identity,
    apply_rules,
    bootstrap_vendor_paths,
    build_batch_report,
    build_review_queue,
    create_cv_models,
    enrich_rows_with_cv,
    ensure_columns,
    import_cv_dependencies,
    read_csv_rows,
    review_queue_columns,
    write_csv_rows,
    DEFAULT_VENDOR_DIR,
    DEFAULT_YOLO_DETECT_MODEL,
    DEFAULT_YOLO_POSE_MODEL,
    DEFAULT_YUNET_MODEL,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the rules-based Step 4 CV workflow on one or more Step 4 CSV files. "
            "This performs CV enrichment, applies rules, writes a batch report, and "
            "exports a combined review queue."
        )
    )
    parser.add_argument("--batch-name", required=True, help="Short batch name used for output paths.")
    parser.add_argument("--input-files", nargs="+", type=Path, required=True, help="One or more Step 4 CSV files to process.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-image download timeout in seconds.")
    parser.add_argument("--limit", type=int, default=0, help="Optional image-processing limit for smoke tests. 0 means process every row.")
    parser.add_argument("--min-person-confidence", type=float, default=0.35, help="Minimum YOLO confidence for person detections.")
    parser.add_argument("--min-pose-keypoint-confidence", type=float, default=0.35, help="Minimum YOLO pose keypoint confidence for body coverage.")
    parser.add_argument("--yolo-batch-size", type=int, default=8, help="Batch size for YOLO detect/pose inference.")
    parser.add_argument("--download-workers", type=int, default=8, help="Number of concurrent image downloads.")
    parser.add_argument("--vendor-dir", type=Path, default=DEFAULT_VENDOR_DIR, help="Directory containing vendored runtimes.")
    parser.add_argument("--yolo-detect-model", type=Path, default=DEFAULT_YOLO_DETECT_MODEL, help="YOLO detect model path.")
    parser.add_argument("--yolo-pose-model", type=Path, default=DEFAULT_YOLO_POSE_MODEL, help="YOLO pose model path.")
    parser.add_argument("--yunet-model", type=Path, default=DEFAULT_YUNET_MODEL, help="YuNet model path.")
    parser.add_argument("--verbose", action="store_true", help="Print progress to stderr.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_files = [path.resolve() for path in args.input_files]
    for path in input_files:
        if not path.exists():
            raise SystemExit("Input CSV not found: {}".format(path))
        validate_csv_file(path, "step4_manual_chunk")

    bootstrap_vendor_paths(args.vendor_dir.resolve())
    cv2, np, requests, Image, YOLO = import_cv_dependencies()
    models = create_cv_models(
        cv2=cv2,
        YOLO=YOLO,
        yolo_detect_model=args.yolo_detect_model.resolve(),
        yolo_pose_model=args.yolo_pose_model.resolve(),
        yunet_model=args.yunet_model.resolve(),
    )
    session = requests.Session()

    enriched_batch_dir = CV_ENRICHED_DIR / args.batch_name
    rules_batch_dir = CV_RULES_DIR / args.batch_name
    report_path = REPORTS_DIR / "{}_cv_batch_report.md".format(args.batch_name)
    review_queue_path = REVIEW_QUEUE_DIR / "{}_combined_review_queue.csv".format(args.batch_name)

    all_rule_rows = []
    for input_path in input_files:
        input_fieldnames, input_rows = read_csv_rows(input_path)
        identified_rows = add_row_identity(input_rows, input_path)
        enriched_rows = enrich_rows_with_cv(
            rows=identified_rows,
            models=models,
            cv2=cv2,
            np=np,
            session=session,
            Image=Image,
            timeout=args.timeout,
            min_person_confidence=args.min_person_confidence,
            min_pose_keypoint_confidence=args.min_pose_keypoint_confidence,
            limit=args.limit,
            yolo_batch_size=args.yolo_batch_size,
            download_workers=args.download_workers,
            verbose=args.verbose,
        )
        enriched_fieldnames = ensure_columns(
            input_fieldnames,
            CV_METADATA_COLUMNS + REQUIRED_CV_COLUMNS + OPTIONAL_CV_COLUMNS,
        )
        write_csv_rows(
            enriched_batch_dir / input_path.name,
            enriched_fieldnames,
            enriched_rows,
            validation_profile="step4_cv_enriched",
        )

        rule_rows = apply_rules(enriched_rows)
        rule_fieldnames = ensure_columns(enriched_fieldnames, RULE_OUTPUT_COLUMNS)
        write_csv_rows(
            rules_batch_dir / input_path.name,
            rule_fieldnames,
            rule_rows,
            validation_profile="step4_cv_rules",
        )
        all_rule_rows.extend(rule_rows)

    report_text = build_batch_report(args.batch_name, all_rule_rows, input_files)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")

    review_rows = build_review_queue(all_rule_rows)
    review_headers = review_queue_columns(review_rows)
    write_csv_rows(
        review_queue_path,
        review_headers,
        review_rows,
        validation_profile="step4_review_queue",
    )

    print("Wrote enriched files to {}".format(enriched_batch_dir))
    print("Wrote rules-applied files to {}".format(rules_batch_dir))
    print("Wrote batch report to {}".format(report_path))
    print("Wrote review queue to {}".format(review_queue_path))
    print("Review queue rows: {}".format(len(review_rows)))


if __name__ == "__main__":
    main()
