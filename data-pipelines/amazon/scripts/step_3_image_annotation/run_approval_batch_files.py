#!/usr/bin/env python3
import argparse
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
        description="Run vision enrichment against all approval-batch CSV files."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="Directory containing approval-batch CSV files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where enriched CSV files will be written.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Per-image download timeout passed through to the enrichment script.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress from both this runner and the per-file enrichment script.",
    )
    return parser.parse_args()


def iter_input_files(input_dir: Path):
    paths = [path for path in input_dir.glob("*.csv") if not path.name.endswith(".bak")]
    paths.sort(key=lambda path: (path.name == "images_to_approve.csv", path.name))
    for path in paths:
        if path.name.endswith(".bak"):
            continue
        yield path


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not PYTHON_BIN.exists():
        raise SystemExit(f"Python venv not found: {PYTHON_BIN}")
    if not ENRICH_SCRIPT.exists():
        raise SystemExit(f"Enrichment script not found: {ENRICH_SCRIPT}")

    files = list(iter_input_files(input_dir))
    if not files:
        raise SystemExit("No CSV files found.")

    total = len(files)
    for index, input_path in enumerate(files, start=1):
        output_path = output_dir / input_path.name
        temp_output_path = output_path.with_suffix(output_path.suffix + ".tmp")
        print(f"[{index}/{total}] Processing {input_path.name}", file=sys.stderr)
        command = [
            str(PYTHON_BIN),
            str(ENRICH_SCRIPT),
            "--input",
            str(input_path),
            "--output",
            str(temp_output_path),
            "--timeout",
            str(args.timeout),
        ]
        if args.verbose:
            command.append("--verbose")

        env = os.environ.copy()
        env["MPLCONFIGDIR"] = "/tmp/matplotlib-codex-runner"
        subprocess.run(command, check=True, cwd=str(PIPELINE_ROOT), env=env)
        temp_output_path.replace(output_path)

    print("Approval batch refresh complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
