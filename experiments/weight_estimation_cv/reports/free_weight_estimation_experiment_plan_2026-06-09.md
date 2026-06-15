# Free weight-estimation CV experiment plan

Date: 2026-06-09

Goal: determine whether free/open computer-vision approaches can infer useful hidden weight/BMI signals from FWM user-submitted apparel/review photos when a user did not self-report weight.

Product constraint: inferred weights must never be displayed on Friends With Measurements. They are only candidate internal ranking/search features.

Cost constraint: do not pay for APIs, vendors, datasets, or commercial tools in this phase.

Explicitly out of scope: body-fat percentage, fat distribution, lean mass, muscle mass, health-risk scores, or body-composition modeling. We only care about signals that help estimate weight/BMI or improve clothing-fit search/ranking.

## Current baseline

Existing isolated experiment directory:

`/Users/briannasinger/Projects/FWM/FWM_Repo/experiments/weight_estimation_cv`

Current ground-truth data:

- `77,770` rows with usable image URL, exact-ish self-reported height, and exact-ish self-reported weight.
- Current eval sample: `1,200` rows.
- Downloaded image subset: `971` images.
- Downloaded-only split used in earlier experiments: `698` train / `273` test.

Current best baseline from prior run:

- Best tabular baseline: `ridge_height_size_category_predict_bmi`
- MAE: `31.958 lb`
- RMSE: `42.290 lb`
- R2: `0.2962`
- Within 20 lb: `0.4249`

Current image baseline:

- Generic ImageNet CNN embeddings did not beat the best height+metadata baseline.
- Best tested image model: EfficientNet-B0 + image + height + metadata
- MAE: `32.452 lb`

Implication: future models must be compared against the height+metadata baseline on the same rows/subsets. A model is not useful just because it is "visual"; it must improve accuracy, coverage, or ranking utility.

## Primary metrics

Report all model results in pounds after converting BMI predictions where needed:

- `MAE`: mean absolute error in pounds.
- `RMSE`: root mean squared error in pounds.
- `R2`: explained variance.
- `within_10_lb`: percent of predictions within 10 lb.
- `within_20_lb`: percent of predictions within 20 lb.
- `within_30_lb`: percent of predictions within 30 lb.
- `coverage`: percent of eligible images where the model produced a prediction.
- `accepted_coverage`: percent of all eval images where the model both accepted the image and predicted.
- `median_abs_error`: robust middle error.
- Bias slices:
  - self-reported weight bucket,
  - height bucket,
  - clothing size bucket where available,
  - product/category where available,
  - image type/quality bucket.

Minimum reporting rule:

- Always report performance on the full downloaded test set where possible.
- Always report performance on model-eligible subsets separately.
- Always compare against a baseline refit/evaluated on the same subset.

## Experiment principles

1. Predict BMI when height exists.
   - BMI prediction plus known height is usually better structured than direct weight prediction.
   - Convert BMI to pounds with:
     - `weight_lb = bmi * height_in^2 / 703`

2. Track eligibility before accuracy.
   - Face models should only be evaluated on face-visible images.
   - Full-body/person-geometry models should only be evaluated on person-visible images.
   - A model with good MAE on tiny coverage may still be useful, but it is not a universal solution.

3. Keep train/test leakage out.
   - Do not train and evaluate on different images from the same underlying review/person if a stable grouping key exists.
   - If no person/review grouping exists, at least keep exact duplicate URLs and near-duplicate images in the same split.

4. Prefer simple models first.
   - Ridge/ElasticNet, random forest, gradient boosting, and calibrated regressors are enough for feature benchmarks.
   - Only train neural heads after embeddings/features prove signal.

5. Store every new artifact under this experiment directory.
   - Do not write to the active `outputs/` folder.
   - Keep large downloads/checkpoints under ignored `cache/` or `models/`.

## Phase 0: dataset hygiene and split hardening

Purpose: make later model comparisons trustworthy.

Tasks:

1. Confirm columns in `data/ground_truth_manifest.csv` and `data/eval_sample_with_images.csv`.
2. Add stable row identifiers:
   - image URL hash,
   - source/review/product key if available,
   - local image path,
   - ground-truth height/weight fields.
3. Deduplicate:
   - exact image URLs,
   - exact local image bytes if cheap,
   - near-duplicate perceptual hashes if cheap.
4. Create or validate a hardened train/test split:
   - same person/review/product grouping kept together where possible,
   - deterministic random seed,
   - stratified by weight bucket and height bucket.
5. Save:
   - `data/eval_sample_hardened.csv`
   - `reports/split_hygiene_summary.json`

Success criteria:

- We can explain exactly what rows are in train/test.
- No obvious duplicate leakage across train/test.
- Baseline metrics are reproduced or intentionally superseded on the hardened split.

Stop condition:

- If leakage is found, all later experiments must use the hardened split, not prior reported metrics.

## Phase 1: image eligibility and quality tagging

Purpose: create subsets that match the actual requirements of each model family.

Tasks:

1. Run face detection on downloaded images.
   - Candidate tools: MediaPipe Face Detection, RetinaFace, OpenCV/InsightFace if easy.
   - Save:
     - number of faces,
     - largest face bbox,
     - face area ratio,
     - face confidence,
     - face-visible flag.

2. Run person detection on downloaded images.
   - Candidate tools: YOLOv8/YOLO11 person class.
   - Save:
     - person bbox,
     - person confidence,
     - person area ratio,
     - full-body-ish flag,
     - torso-only/cropped flag,
     - multiple-person flag.

3. Run pose/keypoint detection where feasible.
   - Candidate tools: MediaPipe Pose, YOLO pose, OpenPose if already convenient.
   - Save:
     - shoulder/hip/knee/ankle visibility,
     - full-body keypoint coverage,
     - approximate pose quality.

4. Create image-type buckets:
   - `face_visible`
   - `person_visible`
   - `full_body_likely`
   - `torso_or_partial_body`
   - `multiple_people`
   - `low_signal`

5. Save:
   - `data/eval_sample_with_quality_tags.csv`
   - `reports/image_quality_coverage_summary.json`

Success criteria:

- We know how many of the 971 downloaded images are eligible for:
  - face models,
  - full-body/person-crop models,
  - geometry/pose models.

Decision gate:

- If face-visible coverage is below ~10%, deprioritize face-only models after one quick benchmark.
- If person-visible coverage is high, person-crop/foundation-feature experiments become the main path.

## Phase 2: reproduce baselines on each eligible subset

Purpose: avoid fooling ourselves by comparing a face model on easy face-visible rows against a baseline measured on all rows.

Tasks:

1. Refit/evaluate baseline models on:
   - all hardened test rows,
   - face-visible subset,
   - person-visible subset,
   - full-body-likely subset,
   - torso/partial subset.

2. Baselines to include:
   - mean train weight,
   - mean train BMI + height,
   - height-only ridge,
   - height + available size/category/source metadata,
   - current best tabular baseline.

3. Save:
   - `reports/subset_baseline_metrics.json`

Success criteria:

- Every later model has a fair same-subset baseline.

## Phase 3: free face-visible model benchmarks

Purpose: test free/off-the-shelf face-based models only where faces are visible.

Priority order:

1. `abhaymise/Face-to-height-weight-BMI-estimation-`
2. `face-to-bmi-vit`
3. MeFEm embeddings + FWM-trained regressor

### 3A. abhaymise face-to-height/weight/BMI repo

Link: https://github.com/abhaymise/Face-to-height-weight-BMI-estimation-

Why first:

- It has actual serialized model artifacts.
- Apache-2.0 license.
- Cheap to test.

Tasks:

1. Clone/download into `models/abhaymise_face_height_weight_bmi/`.
2. Inspect model format and dependencies.
3. Identify expected face crop preprocessing.
4. Run on `face_visible` subset.
5. Evaluate:
   - direct weight predictor,
   - BMI predictor converted to weight using FWM height,
   - height predictor only as a sanity check, not as a replacement for known height.

Expected weakness:

- Trained on a tiny celebrity dataset, likely biased and noisy.

Success criteria:

- It beats same-subset height+metadata baseline by at least 3 lb MAE, or gives a useful calibrated feature when stacked with metadata.

Stop condition:

- If MAE is worse than baseline by >5 lb and residuals show obvious bias, do not spend more time adapting it.

### 3B. face-to-bmi-vit

Link: https://github.com/liujie-zheng/face-to-bmi-vit

Tasks:

1. Clone/download into `models/face_to_bmi_vit/`.
2. Confirm whether usable checkpoints are included or downloadable for free.
3. Run on face crops from `face_visible` subset.
4. Convert predicted BMI to weight using self-reported height.
5. Evaluate against same-subset baselines.

Success criteria:

- Better than same-subset height+metadata baseline.
- Or useful in an ensemble/stacked model.

Stop condition:

- If no free checkpoint is available and training requires unavailable data, move to MeFEm.

### 3C. MeFEm embeddings + FWM regressor

Links:

- https://arxiv.org/abs/2602.14672
- https://huggingface.co/boretsyury/MeFEm

Tasks:

1. Download public MeFEm weights into experiment cache.
2. Extract embeddings for face crops.
3. Train simple regressors on FWM train split:
   - ridge,
   - elastic net,
   - random forest or gradient boosting if useful.
4. Targets:
   - BMI, then convert to weight with height,
   - direct weight as a secondary target.
5. Feature combinations:
   - MeFEm only,
   - MeFEm + height,
   - MeFEm + height + metadata.

Success criteria:

- Improves same-subset baseline enough to justify keeping face-visible model track.

Decision gate after Phase 3:

- If no face model improves same-subset baseline, face models should only be used as weak optional ensemble features or dropped.
- If a face model improves same-subset baseline but face coverage is low, use only as a conditional ranking boost for eligible rows.

## Phase 4: free person-crop and geometry feature benchmarks

Purpose: test visual features that are more directly relevant to clothing fit and review photos than face-only BMI.

Tasks:

1. Generate person crops from person detector bboxes.
2. Generate simple geometry features:
   - person bbox width,
   - person bbox height,
   - bbox aspect ratio,
   - person area ratio,
   - crop fills image ratio,
   - full-body keypoint coverage,
   - shoulder width proxy,
   - hip width proxy,
   - shoulder/hip ratio where reliable,
   - torso height proxy,
   - visible leg/ankle flag,
   - multiple-person flag,
   - face-visible flag.

3. Train/evaluate regressors:
   - geometry only,
   - geometry + height,
   - geometry + height + metadata.

4. Save:
   - `data/geometry_features.csv`
   - `reports/geometry_feature_metrics.json`

Success criteria:

- Geometry + height + metadata beats height + metadata baseline on person-visible subset.
- Geometry features remain useful in feature importance/permutation tests.

Stop condition:

- If pose/keypoint extraction is too noisy, keep only robust bbox/person-area features and move on.

## Phase 5: stronger free foundation embeddings on person crops

Purpose: replace generic ImageNet CNN features with models more likely to encode visual similarity, body shape, clothing, and silhouette.

Priority order:

1. DINOv2
2. OpenCLIP / CLIP
3. FashionCLIP, if setup is straightforward and free

Inputs:

- full image,
- YOLO person crop,
- optional torso/full-body crop bucket separately.

Targets:

- BMI first, converted to weight using height,
- direct weight second.

Feature combinations:

- embedding only,
- embedding + height,
- embedding + height + metadata,
- embedding + geometry + height + metadata.

Models:

- ridge regression,
- elastic net,
- random forest,
- gradient boosting / hist gradient boosting,
- optional simple stacking of best models.

Save:

- `data/features/dinov2_*.npz`
- `data/features/openclip_*.npz`
- `data/features/fashionclip_*.npz`
- `reports/foundation_embedding_metrics.json`

Success criteria:

- Meaningful improvement over height+metadata baseline on person-visible or full-body-likely subsets.
- Prefer at least 3-5 lb MAE improvement or a strong within-20-lb lift.

Stop condition:

- If embeddings are no better than geometry/metadata and extraction is expensive, do not scale them before trying Digital Scale weights.

## Phase 6: Digital Scale benchmark if weights arrive

Purpose: test the best direct BMI-from-photo model if the authors/team share weights for free.

Tasks:

1. Store weights under:
   - `models/digital_scale/`
2. Follow repo quick-start inference.
3. Run on:
   - all downloaded images,
   - person-visible subset,
   - full-body-likely subset.
4. Preserve Digital Scale quality/rejection outputs.
5. Convert predicted BMI to weight using FWM height.
6. Evaluate:
   - all attempted rows,
   - accepted-only rows,
   - rejected rows separately by image type.

Save:

- `data/digital_scale_predictions.csv`
- `reports/digital_scale_metrics.json`

Success criteria:

- Better than same-subset height+metadata baseline.
- Coverage high enough to affect search/ranking meaningfully.

Decision gate:

- If Digital Scale works well, prioritize calibration/uncertainty and integration planning.
- If it fails on FWM-style images, use its outputs only as features or move toward FWM-trained models.

## Phase 7: BodyM / silhouette dataset investigation

Purpose: decide whether free external body-measurement data can help a custom model.

Links:

- https://adversarialbodysim.github.io/
- https://arxiv.org/abs/2210.05667

Tasks:

1. Confirm data access terms and whether BodyM is downloadable for free.
2. Confirm labels include height and weight in usable format.
3. Compare domain:
   - BodyM silhouettes vs FWM apparel/review crops.
4. If accessible:
   - train a simple silhouette/person-crop model on BodyM,
   - fine-tune/evaluate on FWM.

Success criteria:

- Demonstrable transfer benefit over FWM-only training.

Stop condition:

- If access is not free/easy or labels are restricted, defer.

## Phase 8: model comparison and recommendation

Purpose: decide whether any free external model is good enough, or whether FWM should train its own.

Final report should include:

- Coverage table by model.
- Metrics table by same-subset evaluation.
- Best model by:
  - all downloaded images,
  - face-visible images,
  - person-visible images,
  - full-body-likely images.
- Calibration plot or error buckets.
- Error examples:
  - best predictions,
  - worst overestimates,
  - worst underestimates,
  - rejected images.
- Bias/slice analysis:
  - low/mid/high weight buckets,
  - height buckets,
  - size buckets,
  - category buckets.
- Recommended production direction:
  - no image signal worth using,
  - conditional face/person signal only,
  - Digital Scale-like model,
  - FWM-specific model.

## Prioritized execution order

1. Harden split and reproduce baselines.
2. Add image eligibility/quality tags.
3. Run same-subset baselines.
4. Benchmark `abhaymise` face model.
5. Benchmark `face-to-bmi-vit` if free checkpoint is usable.
6. Benchmark MeFEm embeddings + FWM regressor.
7. Build person geometry features.
8. Run DINOv2 embeddings on full images and person crops.
9. Run OpenCLIP/FashionCLIP if DINOv2 shows promise or setup is cheap.
10. Benchmark Digital Scale when/if weights arrive.
11. Investigate BodyM only if custom training looks necessary.
12. Produce final recommendation.

## What we are not doing

- No paid APIs.
- No 3DLOOK or Bodygram trial unless it is free and terms are acceptable.
- No body-fat/body-composition modeling.
- No displaying inferred weights.
- No writing into active `outputs/`.
- No production integration until model quality, coverage, and bias are understood.

## Expected outcomes

Most likely:

- Face models have limited coverage but may help on face-visible photos.
- Person-crop geometry and DINOv2/OpenCLIP features are more relevant to FWM than generic ImageNet CNN embeddings.
- Digital Scale is still the strongest direct external model if weights arrive.
- If free external models do not beat the metadata baseline, train a FWM-specific model using height, metadata, person-crop embeddings, and geometry features.

Best case:

- Digital Scale or a person-crop/foundation embedding model improves MAE by 5+ lb on a meaningful subset and can be used as a hidden search-ranking feature.

Worst case:

- Visual models do not beat height+metadata baseline. In that case, we should avoid inferred weight for now and use the ground-truth dataset to train a purpose-built FWM model later.

