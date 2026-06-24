#!/usr/bin/env bash
# Auto-restarting wrapper around detect_person_boxes.py.
#
# Re-runs the detector with --resume until every worklist row has an output row,
# so a kill (OOM, sleep, crash) just resumes instead of ending the job. If a run
# makes no progress, it backs off to the lightest batch; after a few dead runs in
# a row it stops rather than spinning forever.
#
# Launch and walk away:
#   caffeinate -is nohup bash scripts/run-detection-until-complete.sh \
#     >> ../FWM_Data/_cache/detect_run.log 2>&1 &
#
# Watch:  wc -l < ../FWM_Data/_cache/crop_bboxes_full.ndjson   # out of 45269

set -u
cd "$(dirname "$0")/.." || exit 1

PY=${PY:-../FWM_Data/_venv_cv/bin/python}
SCRIPT=${SCRIPT:-scripts/detect_person_boxes.py}
WL=${WL:-../FWM_Data/_cache/crop_worklist.ndjson}
OUT=${OUT:-../FWM_Data/_cache/crop_bboxes_full.ndjson}
DETECT_MODEL=${DETECT_MODEL:-../FWM_Data/_models/yolov8n.pt}
POSE_MODEL=${POSE_MODEL:-../FWM_Data/_models/yolov8n-pose.pt}
BATCH=${BATCH:-4}
WORKERS=${WORKERS:-6}
MAX_STALE=${MAX_STALE:-3}

count() { wc -l < "$1" 2>/dev/null | tr -d ' '; }

TOTAL=$(count "$WL")
if [ -z "$TOTAL" ] || [ "$TOTAL" -eq 0 ]; then
  echo "[wrapper] worklist missing or empty: $WL" >&2
  exit 1
fi

stale=0
attempt=0
while :; do
  done_count=$(count "$OUT"); done_count=${done_count:-0}
  if [ "$done_count" -ge "$TOTAL" ]; then
    echo "[wrapper] $(date) COMPLETE: $done_count/$TOTAL detection rows."
    break
  fi

  attempt=$((attempt + 1))
  echo "[wrapper] $(date) attempt $attempt: $done_count/$TOTAL done; starting detector (batch=$BATCH workers=$WORKERS)"
  "$PY" "$SCRIPT" \
    --input "$WL" --output "$OUT" \
    --detect-model "$DETECT_MODEL" --pose-model "$POSE_MODEL" \
    --resume --batch "$BATCH" --workers "$WORKERS"
  code=$?

  after=$(count "$OUT"); after=${after:-0}
  echo "[wrapper] $(date) detector exited code=$code; now $after/$TOTAL"

  if [ "$after" -le "$done_count" ]; then
    stale=$((stale + 1))
    echo "[wrapper] no progress (stale=$stale/$MAX_STALE); backing off to batch=1 workers=4"
    BATCH=1
    WORKERS=4
    if [ "$stale" -ge "$MAX_STALE" ]; then
      echo "[wrapper] $(date) GIVING UP after $MAX_STALE no-progress runs at $after/$TOTAL."
      echo "[wrapper] Investigate the next unprocessed rows; the rest is still resumable later."
      exit 2
    fi
    sleep 10
  else
    stale=0
    sleep 3
  fi
done
