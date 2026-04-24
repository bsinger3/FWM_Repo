import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Iterable

from apify_client import ApifyClient


DEFAULT_BATCH_SIZE = 50
MAX_BATCH_SIZE = 100
DEFAULT_MAX_PAGES = 3
DEFAULT_DOMAIN_CODE = "com"
DEFAULT_SORT_BY = "recent"
DEFAULT_REVIEWER_TYPE = "all_reviews"
DEFAULT_MEDIA_TYPE = "media_reviews_only"
DEFAULT_FORMAT_TYPE = "current_format"
DEFAULT_OUTPUT_PREFIX = "batch_"
DEFAULT_DEDUPE_KEY = "review_variation"
TERMINAL_RUN_STATUSES = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}
ASIN_COLUMN_CANDIDATES = ("asin", "ASIN", "asin_value", "ASIN_Value", "asin_values", "ASIN_Values")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def data_root() -> Path:
    return repo_root().parent / "FWM_Data"


def output_dir() -> Path:
    return data_root() / "raw" / "apify"


def metadata_dir(destination: Path) -> Path:
    return destination / "_runs"


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        if key and key not in os.environ:
            os.environ[key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Amazon image reviews from a CSV of ASINs using Apify."
    )
    parser.add_argument(
        "csv_path",
        type=Path,
        help="Path to the input CSV containing an 'asin' column.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Number of ASINs per Apify run (default: {DEFAULT_BATCH_SIZE}, max: {MAX_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--actor-id",
        default=os.getenv("APIFY_ACTOR_ID"),
        help="Apify actor ID. Defaults to APIFY_ACTOR_ID from the environment.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Maximum review pages per ASIN (default: {DEFAULT_MAX_PAGES}).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=output_dir(),
        help="Directory for raw batch JSON output.",
    )
    parser.add_argument(
        "--start-batch-number",
        type=int,
        default=None,
        help="Optional override for the first batch file number.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Optional pause between completed batches.",
    )
    parser.add_argument(
        "--dedupe-key",
        choices=("review", "review_variation"),
        default=DEFAULT_DEDUPE_KEY,
        help=(
            "How to deduplicate saved review rows. "
            "'review' keeps one row per reviewId, 'review_variation' keeps one row per reviewId + variationId."
        ),
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not os.getenv("APIFY_TOKEN"):
        raise ValueError("Missing APIFY_TOKEN environment variable.")
    if not args.actor_id:
        raise ValueError("Missing actor ID. Set APIFY_ACTOR_ID or pass --actor-id.")
    if args.batch_size < 1:
        raise ValueError("--batch-size must be at least 1.")
    if args.batch_size > MAX_BATCH_SIZE:
        raise ValueError(f"--batch-size cannot exceed {MAX_BATCH_SIZE}.")
    if args.max_pages < 1:
        raise ValueError("--max-pages must be at least 1.")


def resolve_csv_path(csv_path: Path) -> Path:
    if csv_path.is_absolute():
        resolved = csv_path
    else:
        resolved = (repo_root() / csv_path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"CSV file not found: {resolved}")
    return resolved


def load_asins(csv_path: Path) -> list[str]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Input CSV must contain a header row.")

        asin_column = next(
            (column for column in ASIN_COLUMN_CANDIDATES if column in reader.fieldnames),
            None,
        )
        if not asin_column:
            raise ValueError(
                "Input CSV must contain an ASIN column. "
                f"Accepted names: {', '.join(ASIN_COLUMN_CANDIDATES)}"
            )

        seen = set()
        asins: list[str] = []
        for row_number, row in enumerate(reader, start=2):
            raw_asin = (row.get(asin_column) or "").strip()
            if not raw_asin:
                print(f"Skipping blank ASIN at CSV row {row_number}.")
                continue
            asin = raw_asin.upper()
            if asin in seen:
                continue
            seen.add(asin)
            asins.append(asin)

    if not asins:
        raise ValueError("No ASINs found in the input CSV.")
    return asins


def chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def build_actor_input(batch_asins: list[str], max_pages: int) -> dict:
    return {
        "input": [
            {
                "asin": asin,
                "domainCode": DEFAULT_DOMAIN_CODE,
                "sortBy": DEFAULT_SORT_BY,
                "maxPages": max_pages,
                "reviewerType": DEFAULT_REVIEWER_TYPE,
                "mediaType": DEFAULT_MEDIA_TYPE,
                "formatType": DEFAULT_FORMAT_TYPE,
            }
            for asin in batch_asins
        ]
    }


def next_batch_number(destination: Path) -> int:
    existing_numbers: list[int] = []
    for path in destination.glob(f"{DEFAULT_OUTPUT_PREFIX}*.json"):
        suffix = path.stem.replace(DEFAULT_OUTPUT_PREFIX, "", 1)
        if suffix.isdigit():
            existing_numbers.append(int(suffix))
    if not existing_numbers:
        return 1
    return max(existing_numbers) + 1


def batch_file_path(destination: Path, batch_number: int) -> Path:
    return destination / f"{DEFAULT_OUTPUT_PREFIX}{batch_number:03d}.json"


def batch_metadata_path(destination: Path, batch_number: int) -> Path:
    return metadata_dir(destination) / f"{DEFAULT_OUTPUT_PREFIX}{batch_number:03d}.run.json"


def load_batch_metadata(destination: Path, batch_number: int) -> dict | None:
    path = batch_metadata_path(destination, batch_number)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_batch_metadata(destination: Path, batch_number: int, payload: dict) -> Path:
    meta_directory = metadata_dir(destination)
    meta_directory.mkdir(parents=True, exist_ok=True)
    path = batch_metadata_path(destination, batch_number)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_batch_output(destination: Path, batch_number: int, items: list[dict]) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    output_path = batch_file_path(destination, batch_number)
    output_path.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return output_path


def fetch_run_items(client: ApifyClient, dataset_id: str) -> list[dict]:
    return list(client.dataset(dataset_id).iterate_items())


def start_batch_run(
    client: ApifyClient,
    actor_id: str,
    batch_asins: list[str],
    max_pages: int,
) -> tuple[str, dict]:
    actor_input = build_actor_input(batch_asins, max_pages)
    started_run = client.actor(actor_id).start(run_input=actor_input)
    run_id = started_run.get("id")
    if not run_id:
        raise RuntimeError("Apify actor start did not return a run ID.")
    return run_id, actor_input


def wait_for_run_finish(client: ApifyClient, run_id: str, poll_seconds: int = 10) -> dict:
    run_client = client.run(run_id)

    while True:
        run = run_client.get()
        status = (run or {}).get("status")
        if status in TERMINAL_RUN_STATUSES:
            return run
        time.sleep(poll_seconds)


def dedupe_value(item: dict, dedupe_key: str) -> tuple[str, ...] | None:
    review_id = (item.get("reviewId") or "").strip()
    if not review_id:
        return None
    if dedupe_key == "review":
        return (review_id,)
    variation_id = (item.get("variationId") or "").strip()
    return (review_id, variation_id)


def filter_and_dedupe_items(items: list[dict], dedupe_key: str) -> list[dict]:
    seen: set[tuple[str, ...]] = set()
    filtered: list[dict] = []

    for item in items:
        image_url_list = item.get("imageUrlList") or []
        if not image_url_list:
            continue

        key = dedupe_value(item, dedupe_key)
        if key is None:
            filtered.append(item)
            continue
        if key in seen:
            continue
        seen.add(key)
        filtered.append(item)

    return filtered


def build_metadata_payload(
    *,
    batch_asins: list[str],
    actor_id: str,
    actor_input: dict,
    batch_number: int,
    run_id: str,
    dataset_id: str | None = None,
    status: str = "RUNNING",
) -> dict:
    return {
        "batchNumber": batch_number,
        "actorId": actor_id,
        "runId": run_id,
        "datasetId": dataset_id,
        "status": status,
        "batchAsins": batch_asins,
        "actorInput": actor_input,
    }


def recover_batch_from_metadata(
    *,
    client: ApifyClient,
    destination: Path,
    batch_number: int,
    dedupe_key: str,
) -> tuple[list[dict], str, str]:
    metadata = load_batch_metadata(destination, batch_number)
    if not metadata:
        raise RuntimeError(f"Missing batch metadata for batch {batch_number:03d}.")

    run_id = metadata["runId"]
    run = wait_for_run_finish(client, run_id)
    status = run.get("status")
    if status != "SUCCEEDED":
        raise RuntimeError(f"Apify run {run_id} finished with non-success status: {status}")

    dataset_id = run.get("defaultDatasetId") or metadata.get("datasetId")
    if not dataset_id:
        raise RuntimeError(f"Apify run {run_id} completed without a default dataset ID.")

    raw_items = fetch_run_items(client, dataset_id)
    items = filter_and_dedupe_items(raw_items, dedupe_key=dedupe_key)

    write_batch_metadata(
        destination,
        batch_number,
        {
            **metadata,
            "datasetId": dataset_id,
            "status": status,
            "savedItemCount": len(items),
            "rawItemCount": len(raw_items),
        },
    )
    return items, dataset_id, run_id


def main() -> int:
    try:
        load_dotenv(repo_root() / ".env")
        args = parse_args()
        validate_args(args)
        csv_path = resolve_csv_path(args.csv_path)
        asins = load_asins(csv_path)
    except (FileNotFoundError, ValueError) as exc:
        print(exc)
        return 1

    client = ApifyClient(os.getenv("APIFY_TOKEN"))
    destination = args.output_dir if args.output_dir.is_absolute() else (repo_root() / args.output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    total_asins = len(asins)
    batches = list(chunked(asins, args.batch_size))
    batch_number = args.start_batch_number or next_batch_number(destination)
    processed_asins = 0

    print(f"Loaded {total_asins} ASINs from {csv_path}")
    print(f"Writing raw output to {destination}")
    print(f"Starting at batch number {batch_number:03d}")

    for batch_index, batch_asins in enumerate(batches, start=1):
        current_batch_number = batch_number + batch_index - 1
        print(
            f"[Batch {batch_index}/{len(batches)} | file {current_batch_number:03d}] "
            f"Running {len(batch_asins)} ASINs..."
        )

        try:
            existing_output_path = batch_file_path(destination, current_batch_number)
            if existing_output_path.exists():
                print(
                    f"[Batch {batch_index}/{len(batches)} | file {current_batch_number:03d}] "
                    "Output file already exists. Skipping."
                )
                processed_asins += len(batch_asins)
                continue

            metadata = load_batch_metadata(destination, current_batch_number)
            if metadata:
                print(
                    f"[Batch {batch_index}/{len(batches)} | file {current_batch_number:03d}] "
                    f"Recovering existing Apify run {metadata['runId']}..."
                )
                items, dataset_id, run_id = recover_batch_from_metadata(
                    client=client,
                    destination=destination,
                    batch_number=current_batch_number,
                    dedupe_key=args.dedupe_key,
                )
            else:
                run_id, actor_input = start_batch_run(
                    client=client,
                    actor_id=args.actor_id,
                    batch_asins=batch_asins,
                    max_pages=args.max_pages,
                )
                write_batch_metadata(
                    destination,
                    current_batch_number,
                    build_metadata_payload(
                        batch_asins=batch_asins,
                        actor_id=args.actor_id,
                        actor_input=actor_input,
                        batch_number=current_batch_number,
                        run_id=run_id,
                    ),
                )
                print(
                    f"[Batch {batch_index}/{len(batches)} | file {current_batch_number:03d}] "
                    f"Started Apify run {run_id}"
                )
                items, dataset_id, run_id = recover_batch_from_metadata(
                    client=client,
                    destination=destination,
                    batch_number=current_batch_number,
                    dedupe_key=args.dedupe_key,
                )

            output_path = write_batch_output(destination, current_batch_number, items)
            processed_asins += len(batch_asins)
            print(
                f"[Batch {batch_index}/{len(batches)} | file {current_batch_number:03d}] "
                f"Saved {len(items)} filtered review records from dataset {dataset_id} "
                f"(run {run_id}) to {output_path}"
            )
        except KeyboardInterrupt:
            metadata = load_batch_metadata(destination, current_batch_number)
            run_id = metadata.get("runId") if metadata else "unknown"
            print(
                f"[Batch {batch_index}/{len(batches)} | file {current_batch_number:03d}] "
                f"Interrupted locally. Apify run {run_id} was checkpointed and can be recovered on restart."
            )
            return 130
        except Exception as exc:
            print(
                f"[Batch {batch_index}/{len(batches)} | file {current_batch_number:03d}] "
                f"Failed for {len(batch_asins)} ASINs: {exc}"
            )
            processed_asins += len(batch_asins)
            continue

        print(f"Progress: processed {processed_asins}/{total_asins} ASINs")

        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    print("Finished batch run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
