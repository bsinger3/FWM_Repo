#!/usr/bin/env python3
import argparse
import concurrent.futures
import os
import subprocess
import sys
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = PIPELINE_ROOT / "data" / "step_3_image_annotation" / "raw_inputs"
DEFAULT_OUTPUT_DIR = PIPELINE_ROOT / "data" / "step_3_image_annotation" / "machine_annotated_outputs"
ENRICH_SCRIPT = PIPELINE_ROOT / "scripts" / "step_3_image_annotation" / "enrich_approval_batch_vision.py"
FALLBACK_PYTHON_BIN = (
    PIPELINE_ROOT.parents[2] / "AmazonBigImages" / ".venv" / "bin" / "python"
)
PYTHON_BIN = FALLBACK_PYTHON_BIN if FALLBACK_PYTHON_BIN.exists() else Path(sys.executable)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run vision enrichment against approval-batch part CSVs one chunk at a time."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="Directory containing images_to_approve_part_*.csv files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where enriched chunk CSVs will be written.",
    )
    parser.add_argument(
        "--start-part",
        type=int,
        default=1,
        help="First part number to process.",
    )
    parser.add_argument(
        "--end-part",
        type=int,
        default=999,
        help="Last part number to process.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip chunk outputs that already exist.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Per-image download timeout passed through to the enrichment script.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of chunk files to process in parallel.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress from both this runner and the per-chunk enrichment script.",
    )
    return parser.parse_args()


def iter_parts(input_dir: Path, start_part: int, end_part: int):
    for path in sorted(input_dir.glob("images_to_approve_part_*.csv")):
        suffix = path.stem.rsplit("_", 1)[-1]
        try:
            part_number = int(suffix)
        except ValueError:
            continue
        if start_part <= part_number <= end_part:
            yield part_number, path


def run_part(
    queue_index: int,
    total: int,
    part_number: int,
    input_path: Path,
    output_dir: Path,
    timeout: float,
    verbose: bool,
) -> tuple[int, bool]:
    output_path = output_dir / input_path.name
    if output_path.exists():
        source_path = output_path
    else:
        source_path = input_path
    temp_output_path = output_path.with_suffix(output_path.suffix + ".tmp")

    print(
        f"[{queue_index}/{total}] Processing part {part_number:03d} from {source_path.name} -> {output_path.name}",
        file=sys.stderr,
        flush=True,
    )
    command = [
        str(PYTHON_BIN),
        str(ENRICH_SCRIPT),
        "--input",
        str(source_path),
        "--output",
        str(temp_output_path),
        "--timeout",
        str(timeout),
    ]
    if verbose:
        command.append("--verbose")
    env = os.environ.copy()
    env["MPLCONFIGDIR"] = f"/tmp/matplotlib-codex-runner-part-{part_number:03d}"
    subprocess.run(command, check=True, cwd=str(PIPELINE_ROOT), env=env)
    temp_output_path.replace(output_path)
    print(f"[done] part {part_number:03d}", file=sys.stderr, flush=True)
    return part_number, True


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not PYTHON_BIN.exists():
        raise SystemExit(f"Python venv not found: {PYTHON_BIN}")
    if not ENRICH_SCRIPT.exists():
        raise SystemExit(f"Enrichment script not found: {ENRICH_SCRIPT}")

    parts = list(iter_parts(input_dir, args.start_part, args.end_part))
    if not parts:
        raise SystemExit("No matching part files found.")
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")

    queued_parts = []
    total = len(parts)
    for index, (part_number, input_path) in enumerate(parts, start=1):
        output_path = output_dir / input_path.name
        if args.skip_existing and output_path.exists():
            print(
                f"[{index}/{total}] Skipping part {part_number:03d}: output already exists",
                file=sys.stderr,
                flush=True,
            )
            continue
        queued_parts.append((index, total, part_number, input_path))

    if not queued_parts:
        print("Chunk run complete.", file=sys.stderr)
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                run_part,
                queue_index,
                queue_total,
                part_number,
                input_path,
                output_dir,
                args.timeout,
                args.verbose,
            )
            for queue_index, queue_total, part_number, input_path in queued_parts
        ]
        for future in concurrent.futures.as_completed(futures):
            future.result()

    print("Chunk run complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
