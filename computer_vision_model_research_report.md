# Computer Vision Model Research For Image Sorting

Date: 2026-05-20

## Summary

Yes, this workspace has human-labeled reference data that can be used as ground truth for image-sorting experiments. The strongest local source is:

- `/Users/briannasinger/Projects/FWM/FWM_Data/amazon/data/step_4_human_review_and_visibility_decisions/manual_chunks/backup/images_to_approve_part_001_SORTED_FacialDetectionGT_RejectionReasons1.csv`
- `/Users/briannasinger/Projects/FWM/FWM_Data/amazon/data/step_4_human_review_and_visibility_decisions/part_002_REVIEWED.csv`

These files include manual approval/rejection labels, manually labeled face presence, free-text rejection reasons for some rows, and prior CV outputs from YOLO/YuNet-style detectors.

The practical recommendation is not to look for one single model that fully approves/rejects images. The useful setup is a small model stack:

1. A person detector: YOLO11/YOLOv8 detection.
2. A pose detector: YOLO11-pose, YOLOv8-pose, or MediaPipe Pose.
3. A face detector: OpenCV YuNet.
4. A fashion-aware text/image model: Marqo FashionCLIP or OpenAI CLIP/OpenCLIP for category and catalog/product-photo checks.
5. Optional open-vocabulary detector: Grounding DINO, OWLv2, or YOLO-World for prompts like `pants`, `dress`, `jeans`, `full body`, `person`.

The currently available local CV outputs show that YOLO + YuNet are useful for triage and automation guardrails, but they do not understand the full editorial rule: "is this shopper image useful for judging fit of the reviewed garment?"

## Ground Truth Available Locally

### Part 001 Face And Approval Ground Truth

File:

`/Users/briannasinger/Projects/FWM/FWM_Data/amazon/data/step_4_human_review_and_visibility_decisions/manual_chunks/backup/images_to_approve_part_001_SORTED_FacialDetectionGT_RejectionReasons1.csv`

Rows: 3,000.

Manual labels:

| Label | Meaning | Count |
| --- | --- | ---: |
| `1` | Approved | 1,908 |
| `2` | Not approved | 1,092 |

Manual face labels:

| Label | Meaning | Count |
| --- | --- | ---: |
| `1` | Face present | 451 |
| `2` | No face | 2,549 |

### Part 002 Manual Approval Ground Truth

File:

`/Users/briannasinger/Projects/FWM/FWM_Data/amazon/data/step_4_human_review_and_visibility_decisions/part_002_REVIEWED.csv`

Labeled rows: 707.

Manual labels:

| Label | Meaning | Count |
| --- | --- | ---: |
| `1` | Approved | 260 |
| `2` | Reject | 419 |
| `3` | Approved and label "Pretty" | 28 |

The Part 002 file also includes prior CV columns:

- `cv_decision`
- `cv_reason_code`
- `has_face_yunet`
- `person_count_yolo_detect`
- `main_person_height_pct_yolo_detect`
- `main_person_bbox_area_pct_yolo_detect`
- `body_coverage_score_yolo_pose`

## Models Researched

### 1. Ultralytics YOLO11 / YOLOv8 Detection

Download/source:

- https://docs.ultralytics.com/models/yolo11/
- https://huggingface.co/Ultralytics/YOLO11

License:

- AGPL-3.0 for Ultralytics YOLO11/YOLOv8 unless using an enterprise license.

Why useful:

- Detects people.
- Counts people.
- Gives bounding boxes to estimate whether the subject is large enough in frame.
- Local repo already contains YOLOv8 weights:
  - `/Users/briannasinger/Projects/FWM/FWM_Data/models/yolov8n.pt`

Best use here:

- Auto-reject no-person images.
- Auto-reject obvious multiple-person images when the target shopper is ambiguous.
- Estimate subject height and area in frame.
- Feed deterministic review rules rather than making a final editorial decision alone.

Limitations:

- COCO-trained YOLO detects `person`, not "is this the reviewed garment?"
- It cannot reliably tell whether the pants hem is cut off, whether a jeans waist is covered, or whether the visible garment matches the product category.
- Ultralytics licensing needs attention for any commercial deployment.

### 2. YOLO11-Pose / YOLOv8-Pose

Download/source:

- https://docs.ultralytics.com/models/yolo11/
- https://huggingface.co/Ultralytics/YOLO11

License:

- AGPL-3.0 for Ultralytics distributions unless using an enterprise license.

Why useful:

- Estimates body keypoints.
- Can score how much of the body is visible.
- Local repo already contains:
  - `/Users/briannasinger/Projects/FWM/FWM_Data/models/yolov8n-pose.pt`

Best use here:

- Detect severe crops.
- Flag "too little body visible."
- Separate full-body/mostly-body review photos from detail shots.

Limitations:

- Pose coverage is not the same as garment coverage.
- In the Part 002 reviewed set, body coverage medians were close for approved and rejected rows, so this is a triage signal, not a complete approval model.

### 3. OpenCV YuNet Face Detector

Download/source:

- https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/README.md

License:

- MIT for files in the OpenCV Zoo YuNet directory.

Why useful:

- Very small, fast face detector.
- Helps identify person-centered images.
- The repo already has historical `has_face_yunet` outputs.

Local test result on Part 001 face ground truth:

| Metric | Value |
| --- | ---: |
| True positives | 445 |
| False positives | 78 |
| True negatives | 2,471 |
| False negatives | 6 |
| Precision | 0.851 |
| Recall | 0.987 |
| Specificity | 0.969 |
| Accuracy | 0.972 |

Best use here:

- A supporting signal.
- Detect whether a photo is likely person-centered.
- Identify disagreement cases for manual review.

Important warning:

- Face presence should not be required for approval. In Part 001, 1,483 approved images were manually labeled as no-face. Many useful fit photos show torso/lower body only.

### 4. MediaPipe Pose

Download/source:

- https://aihub.qualcomm.com/models/mediapipe_pose

License:

- Apache-2.0 for the model listing on Qualcomm AI Hub.

Why useful:

- Lightweight body pose pipeline.
- Predicts pose skeletons for face, hands, and torso.
- More permissive license than Ultralytics AGPL options.

Best use here:

- Alternative to YOLO-pose if license simplicity matters.
- Mobile/edge-friendly pose visibility checks.

Limitations:

- It still does not know garment category.
- Needs local benchmarking against the same Part 001/Part 002 labels before replacing YOLO-pose.

### 5. Marqo FashionCLIP

Download/source:

- https://huggingface.co/Marqo/marqo-fashionCLIP

Why useful:

- Fashion-specific image/text embedding model.
- The model card says it was trained/fine-tuned for fashion categories, style, colors, materials, keywords, and fine details.
- It can score an image against labels like `a person wearing jeans`, `a product-only clothing photo`, `a close-up of fabric`, `a dress`, `pants`, `shoes`, or `a catalog model photo`.

Best use here:

- Category sanity checks: does a `jeans` review image look more like jeans/pants than a top/dress/shoes?
- Product-only/catalog-photo checks.
- Near-duplicate image clustering by embeddings.
- Human-review prioritization for cases where CLIP and YOLO disagree.

Limitations:

- It returns similarity, not a grounded explanation.
- Needs calibration on the local approval data.
- It may inherit fashion/product bias from public datasets.

### 6. OpenAI CLIP / OpenCLIP

Download/source:

- https://github.com/openai/CLIP

License:

- MIT for OpenAI CLIP repository.

Why useful:

- Zero-shot image classification with natural-language labels.
- Good baseline for text/image similarity.
- Can be used locally without paying an API per image once installed.

Best use here:

- Baseline before FashionCLIP.
- Broad labels such as `a person wearing clothing`, `a product photo`, `a clothing tag`, `a blurry dark photo`.

Limitations:

- Less fashion-specialized than FashionCLIP.
- Prompt wording can change scores.
- Not reliable enough alone for approval.

### 7. Grounding DINO

Download/source:

- https://github.com/IDEA-Research/GroundingDINO

Why useful:

- Open-set object detection driven by text prompts.
- Can look for `person`, `pants`, `jeans`, `dress`, `skirt`, `shirt`, `shoe`, etc.
- More grounded than CLIP because it returns boxes, not just image-level similarity.

Best use here:

- Detect whether the target garment category appears in the image.
- Localize target garment boxes for crop/visibility checks.
- Produce review diagnostics like "pants detected but lower legs cropped."

Limitations:

- Heavier than YOLO.
- More complex pipeline.
- Needs careful prompt and threshold calibration.

### 8. OWLv2

Download/source:

- https://huggingface.co/docs/transformers/model_doc/owlv2

Why useful:

- Open-vocabulary object detection available through Hugging Face Transformers.
- Can use text or image-guided detection.

Best use here:

- Alternative to Grounding DINO for garment/category localization.

Limitations:

- More expensive than YOLO-style detectors.
- Needs a proper local benchmark before deployment.

### 9. YOLO-World

Download/source:

- https://github.com/AILab-CVC/YOLO-World

Why useful:

- Real-time open-vocabulary detector.
- Potential middle ground between YOLO speed and text-prompt flexibility.

Best use here:

- Fast prompted detection of garment categories.

Limitations:

- Licensing and deployment terms need review before commercial use.
- Needs local calibration against the human labels.

## Local Evaluation Findings

### YuNet Face Detection Is Accurate, But Face Is Not The Approval Target

On the 3,000-row Part 001 face ground truth:

- YuNet correctly found 445 of 451 face-present images.
- It missed only 6 face-present rows.
- It produced 78 false positives.
- Overall accuracy was 97.2%.

This makes YuNet useful as a supporting feature. It should not be a hard approval criterion because many good website images intentionally show lower body, torso, or garment crops without a visible face.

Examples from ground truth:

| Image URL | Human approval | Face GT | YuNet | What the model found | Human note |
| --- | --- | --- | --- | --- | --- |
| https://m.media-amazon.com/images/I/71Nq2MrtCvL.jpg | Approved | Face | Face | Face present, person signal present | Useful shopper image |
| https://m.media-amazon.com/images/I/711U1kbnnYL.jpg | Rejected | Face | Face | Face present | Two people; ambiguous target wearer |
| https://m.media-amazon.com/images/I/61qCAVsP6dL.jpg | Rejected | Face | No face | Face missed | Lighting too dark and grainy |
| https://m.media-amazon.com/images/I/51WH3IqlksL.jpg | Rejected | Face | Face | Face present | Background removed/white, inconsistent with catalog |

The key lesson: face detection can tell us whether a face is present, but it cannot tell us whether the image is useful for fit browsing.

### YOLO Person Detection Is Necessary But Not Sufficient

On Part 001:

| Human approval | `has_person = TRUE` | `has_person = FALSE` |
| --- | ---: | ---: |
| Approved | 1,239 | 669 |
| Rejected | 489 | 597 |

Person detection helps catch many bad rows, but it does not separate approval/rejection cleanly. A rejected image can still have a person if the person is too far away, the garment is cut off, lighting is poor, the angle is bad, or there are multiple people.

Examples from ground truth:

| Image URL | Human approval | `has_person` | Human note |
| --- | --- | --- | --- |
| https://m.media-amazon.com/images/I/716FofNwihL.jpg | Rejected | TRUE | Weird angle; cannot judge pants fit |
| https://m.media-amazon.com/images/I/71jwBqtn6FL.jpg | Rejected | TRUE | Bottom of pants is cut off |
| https://m.media-amazon.com/images/I/61sS7OFnBRL.jpg | Rejected | TRUE | Figure too far from camera |
| https://m.media-amazon.com/images/I/81ahwNzBhuL.jpg | Approved | TRUE | Two people, but the target wearer is still clear enough |

### YOLO/Pose Metrics Are Good Review Features

On 707 manually labeled Part 002 rows, all rows had `cv_decision = REVIEW`, so that prior run was conservative and did not make automatic approve/reject decisions for the reviewed subset.

Metric medians:

| Metric | Approved median | Rejected median |
| --- | ---: | ---: |
| `person_count_yolo_detect` | 1.000 | 1.000 |
| `main_person_height_pct_yolo_detect` | 0.934 | 0.875 |
| `main_person_bbox_area_pct_yolo_detect` | 0.563 | 0.503 |
| `body_coverage_score_yolo_pose` | 66.7 | 66.7 |

What this means:

- Approved images tend to have a larger main person in frame.
- Person count is usually `1` in both approved and rejected rows.
- Pose/body coverage alone is too blunt for final approval.
- These features are good inputs into a triage model, especially to prioritize manual review, but they need a garment-aware model to catch the editorial cases.

## Recommended Sorting Pipeline

### Stage 1: Hard Technical Filters

Use deterministic checks before CV:

- Image URL loads.
- Image is not tiny/corrupt.
- Required site metadata exists: size, product link, at least one measurement.

### Stage 2: Fast CV Triage

Use:

- YOLO detection for `person_count`, subject height, subject area.
- YOLO-pose or MediaPipe Pose for body coverage.
- YuNet for face presence.

Recommended decisions:

- Auto-reject if no person is detected with high confidence.
- Auto-reject if multiple people are detected and there is no clear single main subject.
- Auto-review if subject is small, pose coverage is low, or signals conflict.
- Do not auto-reject just because there is no face.

### Stage 3: Garment-Aware Checks

Use FashionCLIP first because this is a fashion site:

- Compare target category text to the image:
  - `a person wearing jeans`
  - `a person wearing pants`
  - `a person wearing a dress`
  - `a product-only photo of clothing`
  - `a close-up detail of fabric`
  - `a clothing tag or label`
- Flag mismatches for manual review.

If more precision is needed, add Grounding DINO or OWLv2:

- Prompt for the target garment category.
- Check whether the target garment box is visible and large enough.
- Combine garment box with person box and pose/crop features.

### Stage 4: Human Review Loop

Keep a review queue for:

- Borderline crops.
- Garment/category mismatch.
- Multiple people.
- Low light or clutter.
- Cases where YOLO says "pass" but FashionCLIP or Grounding DINO disagrees.

The human labels already in this workspace should be reused to tune thresholds and measure each model before wider deployment.

## Model Usefulness Ranking

| Rank | Model | Usefulness | Why |
| ---: | --- | --- | --- |
| 1 | YOLO detection + YOLO/MediaPipe pose | High | Fast core signals: person count, subject size, crop/body coverage |
| 2 | YuNet | High as support | Excellent face signal locally; cheap and permissively licensed |
| 3 | FashionCLIP | High next step | Adds fashion/category semantics missing from YOLO |
| 4 | Grounding DINO / OWLv2 | Medium-high | Adds prompted garment localization, but heavier |
| 5 | OpenAI CLIP/OpenCLIP | Medium | Good baseline, less fashion-specific |
| 6 | YOLO-World | Promising | Fast open-vocabulary detection, but needs license/deployment review |

## Final Recommendation

The best downloadable/free starting point is:

- Use the existing YOLOv8 detection and pose weights already in `FWM_Data/models`.
- Keep YuNet for face detection.
- Add Marqo FashionCLIP for category and product-photo checks.
- Evaluate Grounding DINO or OWLv2 only after FashionCLIP calibration, because they are heavier and likely only needed for garment-box localization.

The current local ground truth shows that simple CV can safely reduce manual work, but it should not be trusted to fully approve/reject website images without a human-reviewed calibration loop. The most useful version is an auditable triage pipeline: hard failures are rejected, clear passes are accepted only when multiple signals agree, and all ambiguous cases go to manual review.

## Sources

- Ultralytics YOLO11 documentation: https://docs.ultralytics.com/models/yolo11/
- Ultralytics YOLO11 Hugging Face model page: https://huggingface.co/Ultralytics/YOLO11
- OpenCV YuNet model page: https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/README.md
- MediaPipe Pose model page on Qualcomm AI Hub: https://aihub.qualcomm.com/models/mediapipe_pose
- Marqo FashionCLIP model page: https://huggingface.co/Marqo/marqo-fashionCLIP
- OpenAI CLIP repository: https://github.com/openai/CLIP
- Grounding DINO repository: https://github.com/IDEA-Research/GroundingDINO
- OWLv2 Hugging Face Transformers docs: https://huggingface.co/docs/transformers/model_doc/owlv2
- YOLO-World repository: https://github.com/AILab-CVC/YOLO-World
