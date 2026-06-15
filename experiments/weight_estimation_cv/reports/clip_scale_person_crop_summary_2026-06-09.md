# Scaled CLIP Person-Crop Validation

Date: 2026-06-09

## Goal

Validate the first-pass CLIP person-crop signal on a larger held-out set. The earlier run found a strong-looking improvement for torso/partial-body images, but that subset had only 53 held-out rows. This scaled run increases the held-out crop count and keeps all artifacts isolated under `experiments/weight_estimation_cv`.

## Data

| Stage | Rows |
| --- | ---: |
| Source-balanced sample requested | 5,000 |
| Sample produced by current stratified sampler | 3,015 |
| Downloaded/cached images | 2,475 |
| Rows after dropping cross-split perceptual-hash leak | 3,013 |
| Downloaded rows after leak filter | 2,473 |
| Usable person crops | 2,237 |
| Train person crops | 1,544 |
| Test person crops | 693 |
| Full-body likely test crops | 536 |
| Torso/partial-body test crops | 155 |

One cross-split perceptual-hash duplicate group was detected and removed before tagging/evaluation: 2 rows total, 1 train and 1 test.

## Scaled CLIP Results

Same-row baseline is `baseline_ridge_height_metadata_predict_bmi`, trained only on rows available to this scaled crop run. Lower MAE is better.

| Subset | Test rows | Same-row baseline MAE | Best CLIP crop MAE | MAE delta | Best CLIP model |
| --- | ---: | ---: | ---: | ---: | --- |
| Person crop all | 693 | 29.367 | 28.728 | -0.639 | `hist_gradient_vit_base_patch16_clip_224_openai_embedding_height_predict_bmi` |
| Prior person visible | 693 | 29.367 | 28.728 | -0.639 | `hist_gradient_vit_base_patch16_clip_224_openai_embedding_height_predict_bmi` |
| Prior full body likely | 536 | 29.362 | 29.185 | -0.177 | `hist_gradient_vit_base_patch16_clip_224_openai_embedding_height_predict_bmi` |
| Prior torso or partial body | 155 | 33.608 | 33.056 | -0.552 | `random_forest_vit_base_patch16_clip_224_openai_embedding_height_predict_bmi` |

## Interpretation

1. The CLIP person-crop signal appears real but modest. It now beats the height/metadata baseline on all scaled crop subsets, but the improvement is smaller than the first-pass torso/partial result suggested.

2. The first-pass torso/partial gain was directionally correct but likely overstated by small-sample variance. It moved from a 2.716 lb MAE improvement on 53 test rows to a 0.552 lb improvement on 155 test rows.

3. The stronger scaled result is actually the overall person-crop set: 0.639 lb MAE improvement, with RMSE improving from 40.117 to 38.594 and R2 improving from 0.2950 to 0.3475.

4. CLIP is not uniformly better on every metric. For example, in the full-body subset, MAE and RMSE improve, but within-20-lb accuracy decreases versus the height/metadata baseline. This means any production use should be calibrated as a ranking signal, not trusted as a direct displayed prediction.

5. Ridge over raw embeddings performed poorly on the torso/partial subset, while tree-based models were stronger. That suggests the useful CLIP signal is nonlinear and should be validated with model selection rather than assuming a simple linear readout.

## Current Recommendation

Keep CLIP ViT-B/16 person-crop embeddings as the leading free/open candidate, but do not treat it as enough by itself to infer user weight. The right next experiment is to scale one more level and train a cleaner hybrid model:

- height/metadata baseline,
- person-crop CLIP embedding prediction,
- model confidence/error calibration,
- bucket-specific evaluation for full-body, torso/partial, and low-signal images,
- strict duplicate/group leakage controls.

If the ~0.5-0.7 lb MAE improvement persists at larger scale, CLIP embeddings may still be useful for search ranking, especially as one feature inside a broader fit-similarity model. They are not good enough to display inferred weights, which remains out of scope.

## Artifacts

Preprocessing:

- `data/clip_scale_eval_sample.csv`
- `data/clip_scale_eval_sample_with_images.csv`
- `data/clip_scale_eval_sample_hardened.csv`
- `data/clip_scale_eval_sample_hardened_no_hash_leaks.csv`
- `data/clip_scale_eval_sample_with_quality_tags.csv`
- `data/clip_scale_person_crop_attempt_rows.csv`

Reports:

- `reports/clip_scale_eval_sample_summary.json`
- `reports/clip_scale_download_eval_images_summary.json`
- `reports/clip_scale_split_hygiene_summary.json`
- `reports/clip_scale_drop_hash_leaks_summary.json`
- `reports/clip_scale_image_quality_coverage_summary.json`
- `reports/clip_scale_person_crop_attempt_summary.json`
- `reports/clip_scale_vit_base_patch16_clip_224_openai_person_crop_metrics.json`

Model outputs:

- `data/features/clip_scale_vit_base_patch16_clip_224_openai_person_crop_embeddings.npz`
- `data/clip_scale_vit_base_patch16_clip_224_openai_person_crop_embedding_rows.csv`

Scripts added for this validation:

- `scripts/make_person_crop_attempts.py`
- `scripts/drop_cross_split_duplicate_hashes.py`

