# Plan: Face + Smile detection pass (for prettiness `face_visible` + `smile_score`)

**Status:** SCOPED — awaiting Bri's approval. No long run started.
**Author:** Claude Code session 2026-06-24.
**Why:** The prettiness scorer (`scripts/score-dev-image-prettiness.mjs`, model
`prettiness_domainfit_technical_v4`) has two components wired but permanently
`null`/pending because the data does not exist:

- `face_visible_score` — "is the subject's face visible"
- `smile_score` — "is the subject smiling"

Both need a face/expression detection pass over the images. This document scopes
that pass: what to run, on which images, how to integrate it back into the score,
and how to validate it. It does **not** run anything yet.

---

## 1. Key findings from the existing pipeline

### Face: the detector exists and is already validated — it was just never persisted
- YuNet face detection was evaluated against a 3,000-row hand-labelled ground
  truth (`has_face_GroundTruth`) in
  `data-pipelines/docs/amazon_legacy/step_4_face_detectors_vs_ground_truth_part_001_report.md`.
  **YuNet won**: accuracy 0.972, precision 0.851, recall **0.987**, F1 **0.914** —
  beating SCRFD (F1 0.874) and OpenCV-DNN-SSD (F1 0.774).
- The detector is already coded in
  `data-pipelines/amazon/scripts/step_4_human_review_and_visibility_decisions/cv_rules_workflow_lib.py`
  via `cv2.FaceDetectorYN.create(...)` with model `face_detection_yunet_2023mar.onnx`.
- **But** the `has_face_yunet` column is **empty in 100% of the 326,058 rows** of
  the exported CV-gate checkpoints (`.../cv_gate_checkpoint_parts/full_cv_gate_part_*.csv`).
  Whatever path produced those checkpoints did not populate it. So the prettiness
  CV index (`scripts/lib/workbook-cv-index.mjs`, keyed by `review_row_key`) has no
  face signal to join. **The face work is mostly "actually run the proven detector
  over the full set and persist it" — low model risk.**

### Smile: no prior art anywhere
- Exhaustive grep for `smile|emotion|expression|FER|affect|happiness` found
  **nothing**. There is no expression model, column, or experiment in the repo.
  This part is greenfield.

### Current CV venv is minimal and on bleeding-edge Python
- `../FWM_Data/_venv_cv` → Python **3.14**. Installed: `cv2 4.13.0`
  (`cv2.FaceDetectorYN` present ✓), `ultralytics 8.4.75`, `numpy`, `PIL`, `requests`.
- **NOT installed:** `mediapipe`, `insightface`, `onnxruntime`, `fer`, `hsemotion`,
  `deepface`. The old experiments' insightface/mediapipe deps are gone.
- **Python 3.14 wheel risk:** mediapipe / onnxruntime / torch frequently lag new
  Python releases; a `pip install mediapipe` on 3.14 may fail outright. This pushes
  the design toward **what `cv2` alone can do**, because `cv2.dnn.readNetFromONNX`
  can run ONNX models with **no `onnxruntime` and no new wheels**.

---

## 2. Proposed approach

A single new pass that, per image, detects faces and scores smile intensity, using
**only the already-installed `cv2`** plus small downloadable model files.

### Face presence → `has_face`, `face_conf`, `face_box`
- **Model:** YuNet (`face_detection_yunet_2023mar.onnx`, ~340 KB, OpenCV Zoo) via
  `cv2.FaceDetectorYN`. Proven winner above; zero new pip deps.
- Run on each image (optionally limited to the person bbox / autocrop window from
  `crop_bboxes_full.ndjson` to cut false positives from background faces on prints,
  posters, etc.). Emit the highest-confidence face's score and box.
- Maps directly onto the scorer's existing `faceVisibleScore(cv)` (visible face →
  higher, scaled by confidence; no face → 0).

### Smile intensity → `smile_score` (0..1)
Recommended primary, with a fallback, in dependency-risk order:

1. **PRIMARY — smile/expression ONNX via `cv2.dnn` (no new deps).**
   Load a small FER/smile classifier ONNX with `cv2.dnn.readNetFromONNX`, run it on
   the YuNet face crop, take the "happy"/"smiling" probability as `smile_score`.
   Candidate models (small, permissive, ONNX-exportable): a CelebA "Smiling"
   attribute CNN, or an FER mini-Xception / HSEmotion `enet_b0` exported to ONNX.
   **This keeps the whole pass inside the current cv2-only venv** and dodges the
   3.14 wheel problem. The one-time cost is sourcing/exporting a clean ONNX.
2. **FALLBACK — MediaPipe Face Landmarker v2 blendshapes** (`mouthSmileLeft/Right`
   → continuous 0..1 smile). Geometric and very interpretable, but needs
   `pip install mediapipe` + a `.task` model, and **may have no Python 3.14 wheel**.
   If we accept a second venv (py3.11/3.12) for this pass, this becomes attractive.
3. Not recommended: `cv2` Haar `haarcascade_smile` — ships with cv2 (zero deps) but
   is unreliable (high false rate), only a last resort if model sourcing stalls.

**Decision needed from Bri:** accept option 1 (source a smile ONNX, stay cv2-only)
vs option 2 (add a mediapipe venv). Recommendation: **option 1**.

---

## 3. Implementation — `scripts/detect_faces_smiles.py`

Mirror the proven skeleton of `scripts/detect_person_boxes.py` (concurrent download,
batched CPU inference, `--resume` by id, ndjson in/out):

- **Input:** `../FWM_Data/_cache/crop_bboxes_full.ndjson` (the detection output —
  rows already carry `id`, `url`, `review_row_key`, `clothing_type_id`, person
  `bbox_xyxy`). Running only over person-positive rows shrinks the set vs all 47k
  images and gives a face-search region for free.
- **CLI:** `--input --output --face-model --smile-model --limit --min-face-conf
  --timeout --workers --batch --resume` (same shape as detection).
- **Output ndjson** per row:
  ```json
  {"id": "...", "review_row_key": "...", "url": "...",
   "has_face": true, "face_conf": 0.93, "face_box_xyxy": [x1,y1,x2,y2],
   "face_count": 1, "smile_score": 0.78, "smile_model": "<name>"}
  ```
- **Resume / detached run:** identical to the detection job —
  `caffeinate -is nohup ../FWM_Data/_venv_cv/bin/python scripts/detect_faces_smiles.py
  --input ... --output ../FWM_Data/_cache/face_smile_full.ndjson --resume
  > ../FWM_Data/_cache/face_smile_run.log 2>&1 &`. Run in Bri's own Terminal (the
  agent harness reaps long background tasks — same constraint as detection).

### Scale & runtime
- Person-positive rows in `crop_bboxes_full.ndjson` (≤ 45k). YuNet is ~10–30 ms/img
  on CPU; smile ONNX on a face crop is a few ms. As with detection, **download is
  the bottleneck**, so expect a job in the same multi-hour ballpark as the YOLO run,
  detached. Re-running on already-passed images only would cut it further.

---

## 4. Integrating back into the prettiness score

The scorer joins CV by `review_row_key` through `loadWorkbookCvIndex`. Two options:

- **RECOMMENDED — overlay file (low-risk, no checkpoint regen).** Write a compact
  `face_smile_index.json` (review_row_key → {has_face, face_conf, smile_score}) and
  merge it in `loadWorkbookCvIndex` exactly like crop_spec overlays already work.
  The scorer's `faceVisibleScore` lights up immediately; add a `smileScore()` reading
  `cv.smile_score`. No 326k-row checkpoint rebuild needed.
- Alternative — backfill `has_face`/`smile` columns into the dev `images` table via
  the gated dev-write flow (like `backfill-dev-image-crops.mjs`). Heavier; only if we
  want these queryable in dev SQL.

### Where `smile_score` lands in the blend (current weights kept per Bri)
- `face_visible_score` already sits in `DOMAIN_FIT_WEIGHTS` (0.15) and activates the
  moment the overlay exists — no code change needed beyond the loader.
- `smile_score` is a soft "nice photo" signal. Proposal: a small dedicated slot
  (e.g. fold into domain-fit at ~0.1, or a new tiny "expression" contribution),
  weighted modestly so a non-smiling but otherwise great shot isn't tanked. Exact
  weight to be tuned with a before/after dashboard run, not guessed here.

---

## 5. Validation

- **Face:** reuse `analyze_face_detectors_against_ground_truth.py` against the
  existing `has_face_GroundTruth` labels to confirm the fresh YuNet run reproduces
  the F1 ≈ 0.91 from the report. This is a cheap, already-built check.
- **Smile:** no ground truth exists. Build a review dashboard (reuse the prettiness
  dashboard pattern) with a **smile-intensity slider** — slide it up and confirm the
  surviving images are visibly smilier. Hand-label a ~200-image sample to get a rough
  precision/recall and to set the `smile_score` threshold/weight.

---

## 6. Risks & open questions

1. **Smile model sourcing** (the only real unknown): need a clean, permissively
   licensed smile/FER ONNX that loads via `cv2.dnn`. If none is readily exportable,
   fall back to a mediapipe venv (option 2). **← main thing that could slow this.**
2. **Python 3.14 wheels:** avoided by the cv2-only path; becomes real if we choose
   mediapipe/onnxruntime.
3. **YuNet model file:** `face_detection_yunet_2023mar.onnx` is referenced in
   `cv_rules_workflow_lib.py` but not found on disk — locate or re-download (tiny).
4. **Face-on-prints false positives:** faces on graphic tees / posters / packaging.
   Mitigated by restricting face search to the person bbox / autocrop window.
5. **Multi-person frames:** use the main-person box (already in the detection
   output) to pick which face/smile counts.
6. **Re-download vs reuse:** detection already downloaded these images once; if a
   local cache survived we can skip re-downloading and the pass is much faster.

---

## 7. Phased effort estimate

| Phase | Work | Rough size |
|---|---|---|
| A | Source + smoke-test YuNet onnx and a smile ONNX via `cv2.dnn` on ~50 images | ~half day (model sourcing is the variable) |
| B | Write `scripts/detect_faces_smiles.py` (skeleton from detection) + dry-run | small |
| C | Detached full run over person-positive rows (Bri's Terminal) | hours, unattended |
| D | Overlay loader + `smileScore()` in scorer; re-score dashboard; tune smile weight | small |
| E | Validate face vs ground truth; smile review dashboard + sample labels | small |

## 8. Decisions for Bri before Phase A
1. Smile approach: **cv2-only ONNX (recommended)** vs add a mediapipe venv?
2. Run scope: **person-positive rows only (recommended)** vs all ~47k images?
3. Integration: **overlay file (recommended)** vs dev-DB column backfill?
4. Smile weight: tune empirically after a dashboard run (no blind weight now).
