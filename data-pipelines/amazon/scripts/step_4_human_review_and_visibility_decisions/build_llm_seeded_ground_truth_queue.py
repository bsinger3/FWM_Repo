#!/usr/bin/env python3
"""Build the next reason-labeling queue with LLM-vision seeded candidates."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = REPO_ROOT.parent
DATA_ROOT = PROJECT_ROOT / "FWM_Data"
PART002 = DATA_ROOT / "amazon/data/step_4_human_review_and_visibility_decisions/part_002_REVIEWED.csv"
PREVIOUS_LABELS = REPO_ROOT / "outputs/cv_experiments/ground_truth_labeling/labeled_image_rejection_reason_queue.csv"
OUT_DIR = REPO_ROOT / "outputs/cv_experiments/ground_truth_labeling_next"
DEFAULT_ENV_PATH = REPO_ROOT / ".env"

MANUAL_COL = "Manual_approval(1=approved,2=reject, 3=ApprovedANDLabel'Pretty\")"
TARGET_LABELS = [
    "LOW_RESOLUTION",
    "TOO_BRIGHT_OR_WASHED_OUT",
    "BLURRY_OR_MOTION_BLUR",
    "GRAINY_OR_NOISY",
    "GARMENT_CUT_OFF",
    "TARGET_WEARER_AMBIGUOUS",
    "PERSON_TOO_FAR",
]

SYSTEM_PROMPT = """You are helping seed a ground-truth labeling queue for a clothing fit-photo quality system.

Your task is not to make the final label. Your task is to identify whether this image is a promising candidate for any sparse rejection-reason labels that need more human-labeled examples.

Only use the visual image. Do not reject or label based on product category mismatch.

Candidate labels:
- LOW_RESOLUTION: image is visibly tiny, pixelated, or heavily compressed.
- TOO_BRIGHT_OR_WASHED_OUT: image is overexposed or washed out enough to hurt fit evaluation.
- BLURRY_OR_MOTION_BLUR: image is blurred enough to hurt fit evaluation.
- GRAINY_OR_NOISY: image has heavy noise/grain enough to hurt fit evaluation.
- GARMENT_CUT_OFF: the relevant worn clothing/fit view is materially cut off by the image boundary.
- TARGET_WEARER_AMBIGUOUS: there are multiple people and it is unclear whose garment/fit should be evaluated.
- PERSON_TOO_FAR: the person/garment is too small or distant for fit evaluation.

Return JSON only. Be generous about candidates: if the image might be a useful positive example for human labeling, include the label.
If none apply, return an empty labels array.
"""


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def read_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def to_float(value: object) -> float:
    try:
        if value is None or str(value).strip() == "":
            return 0.0
        return float(value)
    except ValueError:
        return 0.0


def known_labeled_keys() -> set[str]:
    if not PREVIOUS_LABELS.exists():
        return set()
    return {row.get("review_row_key", "") for row in read_rows(PREVIOUS_LABELS)}


def heuristic_tags(row: Dict[str, str]) -> List[str]:
    tags: List[str] = []
    height = to_float(row.get("main_person_height_pct_yolo_detect"))
    area = to_float(row.get("main_person_bbox_area_pct_yolo_detect"))
    coverage = to_float(row.get("body_coverage_score_yolo_pose"))
    url = row.get("original_url_display", "")
    cv_reason = row.get("cv_reason_code", "")
    if height and height < 0.70:
        tags.append("PERSON_TOO_FAR")
    if area and area < 0.30:
        tags.append("PERSON_TOO_FAR")
    if coverage and coverage <= 66.7:
        tags.append("GARMENT_CUT_OFF")
    if "BORDERLINE_SUBJECT_SIZE" in cv_reason:
        tags.append("PERSON_TOO_FAR")
    if "BORDERLINE_BODY_COVERAGE" in cv_reason:
        tags.append("GARMENT_CUT_OFF")
    if "._S" in url or "._AC_" in url:
        tags.append("LOW_RESOLUTION")
    return list(dict.fromkeys(tags))


def candidate_score(row: Dict[str, str]) -> float:
    tags = heuristic_tags(row)
    score = 10.0 * len(tags)
    manual = row.get(MANUAL_COL, "")
    if manual == "2" and not row.get("Rejection Reason_Manual", "").strip():
        score += 25
    elif manual == "":
        score += 12
    elif manual == "2":
        score += 8
    height = to_float(row.get("main_person_height_pct_yolo_detect"))
    area = to_float(row.get("main_person_bbox_area_pct_yolo_detect"))
    if height:
        score += max(0.0, (0.85 - height) * 20)
    if area:
        score += max(0.0, (0.45 - area) * 15)
    return round(score, 3)


def select_candidates(limit: int) -> List[Dict[str, str]]:
    labeled = known_labeled_keys()
    rows = [row for row in read_rows(PART002) if row.get("review_row_key") not in labeled and row.get("original_url_display", "").strip()]
    rows = [row for row in rows if row.get(MANUAL_COL, "") in {"", "2"}]
    for row in rows:
        row["candidate_heuristic_tags"] = ";".join(heuristic_tags(row))
        row["candidate_score"] = str(candidate_score(row))
    tagged = [row for row in rows if row["candidate_heuristic_tags"]]
    untagged_rejects = [row for row in rows if not row["candidate_heuristic_tags"] and row.get(MANUAL_COL) == "2"]
    selected = sorted(tagged, key=lambda row: float(row["candidate_score"]), reverse=True)[: int(limit * 0.75)]
    remaining = max(0, limit - len(selected))
    selected.extend(sorted(untagged_rejects, key=lambda row: float(row["candidate_score"]), reverse=True)[:remaining])
    return selected[:limit]


def build_payload(model: str, row: Dict[str, str]) -> Dict[str, object]:
    user_text = {
        "review_row_key": row.get("review_row_key", ""),
        "candidate_heuristic_tags": row.get("candidate_heuristic_tags", ""),
        "cv_reason_code": row.get("cv_reason_code", ""),
        "manual_approval": row.get(MANUAL_COL, ""),
        "manual_reason": row.get("Rejection Reason_Manual", ""),
        "user_comment": row.get("user_comment", "")[:1200],
    }
    return {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": json.dumps(user_text, ensure_ascii=False)},
                    {"type": "input_image", "image_url": row.get("original_url_display", ""), "detail": "low"},
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "candidate_labels",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "labels": {
                            "type": "array",
                            "items": {"type": "string", "enum": TARGET_LABELS},
                        },
                        "summary": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["labels", "summary", "confidence"],
                },
                "strict": True,
            }
        },
        "max_output_tokens": 250,
    }


def extract_response_text(response_json: Dict[str, object]) -> str:
    output_text = response_json.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    outputs = response_json.get("output")
    if isinstance(outputs, list):
        parts: List[str] = []
        for output in outputs:
            if not isinstance(output, dict):
                continue
            for content in output.get("content", []) or []:
                if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                    text = content.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        if parts:
            return "\n".join(parts).strip()
    raise ValueError("Could not extract response text")


def classify_candidate(api_key: str, model: str, row: Dict[str, str], timeout_seconds: int) -> Dict[str, object]:
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(build_payload(model, row)).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        response_json = json.loads(response.read().decode("utf-8"))
    parsed = json.loads(extract_response_text(response_json))
    usage = response_json.get("usage") if isinstance(response_json.get("usage"), dict) else {}
    return {
        "llm_candidate_labels": ";".join(parsed.get("labels") or []),
        "llm_candidate_summary": parsed.get("summary", ""),
        "llm_candidate_confidence": parsed.get("confidence", ""),
        "llm_request_status": "OK",
        "llm_input_tokens": usage.get("input_tokens", 0),
        "llm_output_tokens": usage.get("output_tokens", 0),
        "llm_error_message": "",
    }


def output_rows(candidates: Sequence[Dict[str, str]], llm_results: Dict[str, Dict[str, object]]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for row in candidates:
        key = row.get("review_row_key", "")
        labels = str(llm_results.get(key, {}).get("llm_candidate_labels", "") or "")
        likely_labels = labels or row.get("candidate_heuristic_tags", "")
        out: Dict[str, object] = {
            "queue_priority": "LLM_SEEDED_CANDIDATE",
            "review_row_key": key,
            "original_url_display": row.get("original_url_display", ""),
            "image_preview": f'=IMAGE("{row.get("original_url_display", "")}")',
            "existing_manual_label": row.get(MANUAL_COL, ""),
            "existing_manual_reason": row.get("Rejection Reason_Manual", ""),
            "cv_reason_code": row.get("cv_reason_code", ""),
            "candidate_heuristic_tags": row.get("candidate_heuristic_tags", ""),
            "candidate_score": row.get("candidate_score", ""),
            "llm_suggested_labels": labels,
            "llm_summary": llm_results.get(key, {}).get("llm_candidate_summary", ""),
            "llm_confidence": llm_results.get(key, {}).get("llm_candidate_confidence", ""),
            "likely_label_to_check": likely_labels,
            "final_human_decision": "",
            "primary_reason_code": "",
            "secondary_reason_code": "",
            "labeler_notes": "",
        }
        for label in TARGET_LABELS:
            out[label] = ""
        rows.append(out)
    return rows


def write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, rows: Sequence[Dict[str, object]], started_at: str, elapsed: float) -> None:
    llm_labels = Counter()
    heuristic_labels = Counter()
    for row in rows:
        for label in str(row.get("llm_suggested_labels", "") or "").split(";"):
            if label:
                llm_labels[label] += 1
        for label in str(row.get("candidate_heuristic_tags", "") or "").split(";"):
            if label:
                heuristic_labels[label] += 1
    lines = [
        "# LLM-Seeded Ground Truth Queue",
        "",
        f"- started at: `{started_at}`",
        f"- elapsed seconds: `{elapsed:.1f}`",
        f"- rows in queue: `{len(rows)}`",
        "",
        "## LLM Suggested Label Counts",
        "",
        "| label | count |",
        "| --- | ---: |",
    ]
    for label in TARGET_LABELS:
        count = llm_labels.get(label, 0)
        lines.append(f"| `{label}` | {count} |")
    lines.extend(["", "## Heuristic Seed Counts", "", "| label | count |", "| --- | ---: |"])
    for label in TARGET_LABELS:
        count = heuristic_labels.get(label, 0)
        lines.append(f"| `{label}` | {count} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    load_env_file(DEFAULT_ENV_PATH)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        raise SystemExit("OPENAI_API_KEY is not set")

    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    start = time.perf_counter()
    candidates = select_candidates(args.limit)
    llm_results: Dict[str, Dict[str, object]] = {}
    if args.dry_run:
        llm_results = {
            row["review_row_key"]: {
                "llm_candidate_labels": "",
                "llm_candidate_summary": "",
                "llm_candidate_confidence": "",
                "llm_request_status": "DRY_RUN",
            }
            for row in candidates
        }
    else:
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            future_to_row = {
                executor.submit(classify_candidate, api_key, args.model, row, args.timeout_seconds): row for row in candidates
            }
            completed = 0
            for future in as_completed(future_to_row):
                row = future_to_row[future]
                key = row["review_row_key"]
                try:
                    llm_results[key] = future.result()
                except Exception as exc:  # noqa: BLE001
                    llm_results[key] = {
                        "llm_candidate_labels": "",
                        "llm_candidate_summary": "",
                        "llm_candidate_confidence": "",
                        "llm_request_status": "ERROR",
                        "llm_error_message": repr(exc),
                    }
                completed += 1
                if completed % 20 == 0:
                    print(f"classified {completed}/{len(candidates)}", flush=True)

    rows = output_rows(candidates, llm_results)
    write_csv(OUT_DIR / "llm_seeded_ground_truth_queue.csv", rows)
    write_report(OUT_DIR / "llm_seeded_ground_truth_queue_report.md", rows, started_at, time.perf_counter() - start)
    print(f"Wrote {OUT_DIR}")


if __name__ == "__main__":
    main()
