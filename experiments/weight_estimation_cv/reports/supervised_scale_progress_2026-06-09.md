# Supervised Scale Experiment Progress

Date: 2026-06-09

## Status

Started the supervised weight-model experiment plan, completed the medium-scale data preparation, extracted CLIP person-crop embeddings, and ran the first guarded supervised model comparison.

All artifacts are contained under `experiments/weight_estimation_cv`. The repo-level `outputs/` folder was not touched.

## Completed Steps

### 1. Larger Supervised Sample

Created a new sampler that can produce a larger source/weight-aware sample:

- `scripts/make_supervised_scale_sample.py`

Created the medium sample:

- `data/supervised_scale_sample.csv`
- `reports/supervised_scale_sample_summary.json`

Summary:

| Metric | Count |
| --- | ---: |
| Sample rows | 20,000 |
| Train rows | 15,409 |
| Test rows | 4,591 |
| Source files | 130 |
| Source groups | 83 |

### 2. Image Download

Downloaded images into an isolated cache:

- `cache/supervised_scale_images/`
- `data/supervised_scale_with_images.csv`
- `reports/supervised_scale_download_summary.json`

Summary:

| Status | Count |
| --- | ---: |
| Downloaded | 18,624 |
| Failed | 1,376 |

Most failures were HTTP 403 or connection errors.

### 3. Split Hardening

Computed exact file hashes and perceptual hashes:

- `data/supervised_scale_hardened.csv`
- `reports/supervised_scale_split_hygiene_summary.json`

Result:

| Leak Type | Cross-Split Groups |
| --- | ---: |
| Image URL | 0 |
| Exact file SHA1 | 0 |
| Perceptual average hash | 12 |
| Row ID | 0 |

Dropped cross-split perceptual-hash duplicate groups:

- `data/supervised_scale_no_hash_leaks.csv`
- `reports/supervised_scale_drop_hash_leaks_summary.json`

Rows removed:

| Metric | Count |
| --- | ---: |
| Dropped rows | 54 |
| Dropped hash groups | 12 |
| Output rows | 19,946 |

### 4. Image Quality and Person Tags

Tagged downloaded rows with face/person detection and quality buckets:

- `data/supervised_scale_with_quality_tags.csv`
- `reports/supervised_scale_quality_summary.json`

Summary:

| Metric | Count |
| --- | ---: |
| Rows | 19,946 |
| Downloaded rows after leak cleanup | 18,570 |
| Person-visible rows | 16,489 |
| Full-body likely rows | 12,740 |
| Torso/partial-body rows | 3,679 |
| Multiple-people rows | 2,733 |
| Low-signal rows | 3,162 |

### 5. Training Eligibility Filter

Created a training-eligible subset that excludes multi-person images and keeps only useful body-visibility buckets:

- `scripts/make_training_eligible_rows.py`
- `data/supervised_scale_training_eligible_rows.csv`
- `reports/supervised_scale_training_eligibility_summary.json`

Eligibility criteria:

- downloaded image exists,
- person visible,
- not multiple people,
- image bucket is `full_body_likely` or `torso_or_partial_body`.

Summary:

| Metric | Count |
| --- | ---: |
| Eligible rows | 13,712 |
| Eligible train rows | 10,584 |
| Eligible test rows | 3,128 |
| Eligible full-body likely rows | 10,695 |
| Eligible torso/partial-body rows | 3,017 |

### 6. Reusable Person Crop Boxes

Generated YOLO person crop boxes for the eligible rows:

- `data/supervised_scale_person_crop_attempt_rows.csv`
- `reports/supervised_scale_person_crop_attempt_summary.json`

Summary:

| Metric | Count |
| --- | ---: |
| Attempted rows | 13,712 |
| Successful crops | 13,712 |
| Failed/no-person crops | 0 |
| Train crops | 10,584 |
| Test crops | 3,128 |

### 7. CLIP Person-Crop Embeddings

Extracted CLIP ViT-B/16 embeddings from the saved person crops:

- `data/features/supervised_scale_vit_base_patch16_clip_224_openai_person_crop_embeddings.npz`
- `data/supervised_scale_vit_base_patch16_clip_224_openai_person_crop_embedding_rows.csv`

Summary:

| Metric | Count |
| --- | ---: |
| Embedded rows | 13,712 |
| Embedding dimensions | 768 |
| Train embeddings | 10,584 |
| Test embeddings | 3,128 |
| Failed embeddings | 0 |

The older embedding script's built-in evaluator was intentionally not used as the main result because it includes feature families we decided to exclude.

### 8. Guarded Supervised Weight Model

Created and ran a dedicated supervised trainer:

- `scripts/train_supervised_hybrid_weight_models.py`
- `reports/supervised_scale_hybrid_model_metrics.json`
- `reports/supervised_scale_hybrid_model_summary_2026-06-09.md`

Feature guardrails:

- allowed: CLIP embedding PCA components, `height_in`, optional `size_display`, optional `source_site_display`,
- excluded: `clothing_type_id`, image quality as a feature, multi-person images, crop/framing geometry, image dimensions, detector geometry, and low-signal operational labels,
- used for slicing only: `image_quality_bucket`, `weight_bin`, `height_bin`.

Best held-out result:

| Metric | Value |
| --- | ---: |
| Model | `ridge_clip_pca_height_size_predict_weight` |
| Train rows | 10,584 |
| Test rows | 3,128 |
| MAE | 24.814 lbs |
| Median absolute error | 15.738 lbs |
| RMSE | 37.938 lbs |
| R2 | 0.3309 |
| Within 20 lbs | 0.5994 |
| Within 30 lbs | 0.7602 |

Top comparison points:

| Model | Target | MAE | Median AE | Within 30 |
| --- | --- | ---: | ---: | ---: |
| `ridge_clip_pca_height_size_predict_weight` | `weight_lbs` | 24.814 | 15.738 | 0.7602 |
| `ridge_clip_pca_height_size_predict_bmi` | `bmi` | 24.900 | 15.650 | 0.7561 |
| `ridge_clip_pca_height_predict_weight` | `weight_lbs` | 26.361 | 18.063 | 0.7062 |
| `ridge_height_size_predict_bmi` | `bmi` | 28.205 | 15.945 | 0.7155 |
| `ridge_height_only_predict_weight` | `weight_lbs` | 32.557 | 22.442 | 0.6365 |

Best-model slices:

| Slice | Rows | MAE | Median AE | Within 30 |
| --- | ---: | ---: | ---: | ---: |
| Full-body likely | 2,570 | 24.073 | 15.557 | 0.7716 |
| Torso/partial-body | 558 | 28.230 | 16.677 | 0.7079 |
| 121-140 lbs | 862 | 12.610 | 10.253 | 0.9304 |
| 141-160 lbs | 641 | 11.063 | 9.226 | 0.9657 |
| 181-210 lbs | 325 | 28.628 | 27.401 | 0.5662 |
| 211-250 lbs | 222 | 61.190 | 61.554 | 0.0676 |
| 251-350 lbs | 199 | 107.220 | 102.198 | 0.0000 |

### 9. Bin-Balanced and Sample-Weighted Models

Created and ran a follow-up trainer focused on the high-weight failure mode:

- `scripts/train_balanced_supervised_weight_models.py`
- `reports/supervised_scale_balanced_model_metrics.json`
- `reports/supervised_scale_balanced_model_summary_2026-06-09.md`

This pass tested:

- sample weighting schemes: none, square-root inverse bin frequency, capped inverse bin frequency, inverse bin frequency,
- targets: direct `weight_lbs`, `bmi` converted back to pounds, and `log(weight_lbs)` converted back to pounds,
- feature sets: height+size, CLIP PCA+height, CLIP PCA+height+size, and CLIP PCA+height+size+source.

Weight bins were used only for sample weighting and evaluation slices, not as prediction features.

Best overall weighted result:

| Metric | Value |
| --- | ---: |
| Model | `ridge_clip_pca_height_size_sqrt_inverse_bin_predict_weight` |
| Overall MAE | 24.773 lbs |
| Median absolute error | 17.268 lbs |
| Within 30 lbs | 0.7251 |
| 211+ lb MAE | 70.647 lbs |
| 211+ lb mean signed error | -70.456 lbs |

Best 211+ lb result:

| Metric | Value |
| --- | ---: |
| Model | `ridge_clip_pca_height_inverse_bin_predict_weight` |
| Overall MAE | 29.437 lbs |
| Median absolute error | 24.034 lbs |
| Within 30 lbs | 0.6017 |
| 181+ lb MAE | 41.929 lbs |
| 211+ lb MAE | 54.909 lbs |
| 251+ lb MAE | 74.211 lbs |
| 211+ lb mean signed error | -52.563 lbs |

The weighted pass improved the high-weight failure mode but did not solve it. Compared with the unweighted top CLIP+height+size model, the best 211+ model reduced the 211+ aggregate MAE from about 82.9 lbs to 54.9 lbs, but it still substantially underpredicts higher-weight users.

### 10. Two-Stage High-Weight-Aware Models

Created and ran a two-stage trainer:

- `scripts/train_two_stage_weight_models.py`
- `reports/supervised_scale_two_stage_model_metrics.json`
- `reports/supervised_scale_two_stage_model_summary_2026-06-09.md`

This pass trained:

- high-weight classifiers for 181+, 211+, and 251+ lbs,
- high-weight specialist regressors trained only on rows above each threshold,
- routed predictions that switch from a global model to a specialist model when classifier confidence crosses a cutoff,
- blended predictions that mix the global and specialist predictions by classifier probability.

Classifier summary:

| Classifier | Threshold | Test positives | ROC AUC | Average precision | Precision @ 0.5 | Recall @ 0.5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Logistic | 181+ | 746 | 0.8734 | 0.6546 | 0.6010 | 0.6381 |
| Hist-gradient | 181+ | 746 | 0.8580 | 0.6403 | 0.7628 | 0.2587 |
| Logistic | 211+ | 421 | 0.8711 | 0.4492 | 0.4361 | 0.6485 |
| Hist-gradient | 211+ | 421 | 0.8551 | 0.4625 | 0.7101 | 0.1164 |
| Logistic | 251+ | 199 | 0.8528 | 0.2679 | 0.3060 | 0.3568 |
| Hist-gradient | 251+ | 199 | 0.7666 | 0.2297 | 0.8000 | 0.0201 |

Best overall two-stage result:

| Metric | Value |
| --- | ---: |
| Model | `blend_gte_211_hist_gradient_power_1.0` |
| Overall MAE | 24.004 lbs |
| Median absolute error | 15.840 lbs |
| Within 30 lbs | 0.7551 |
| 211+ lb MAE | 72.337 lbs |
| 211+ lb mean signed error | -71.900 lbs |

Best 211+ specialist result:

| Metric | Value |
| --- | ---: |
| Model | `specialist_ridge_clip_pca_height_train_gte_211` |
| Overall MAE | 83.365 lbs |
| 211+ lb MAE | 26.080 lbs |
| 211+ lb median absolute error | 20.525 lbs |
| 211+ lb mean signed error | -7.124 lbs |
| 251+ lb MAE | 33.273 lbs |

Best routed high-weight tradeoff:

| Metric | Value |
| --- | ---: |
| Model | `route_gte_211_logistic_cutoff_0.15` |
| Overall MAE | 36.695 lbs |
| Within 30 lbs | 0.6119 |
| Routed rows | 1,355 |
| 211+ lb MAE | 30.917 lbs |
| 211+ lb mean signed error | -13.704 lbs |

The key result is that the high-weight specialist regressor works much better on 211+ users, but routing to it without hurting everyone else is still difficult. The logistic classifier has useful rank signal, but low-threshold routing sends too many non-high-weight rows to the specialist; high-threshold routing protects overall MAE but misses too many high-weight rows.

### 11. Search-Style Retrieval Evaluation

Created and ran an offline search-retrieval evaluator:

- `scripts/evaluate_weight_search_retrieval.py`
- `reports/supervised_scale_search_retrieval_metrics.json`
- `reports/supervised_scale_search_retrieval_summary_2026-06-09.md`

This pass treats each held-out test row as a simulated image query with hidden weight. That is not how the product works, because website users input measurements rather than submitting images. The results below are therefore superseded by the catalog measurement-search evaluation in Step 12.

This does not use production search logs. It is an offline ground-truth evaluation over the labeled test split.

Compared strategies:

- `height_size_only`: height proximity plus a small exact-size tie-break,
- `global_point`: rank by distance to the global predicted weight,
- `weighted_global_point`: rank by distance to the inverse-bin weighted global prediction,
- `two_stage_blend_point`: rank by distance to a logistic 211+ probability blend of global and specialist predictions,
- `global_range_pm30`: rank candidates inside the global predicted +/-30 lb range first,
- `candidate_expansion_211`: global range plus 211+ specialist range when classifier probability is at least 0.15,
- `oracle_true_weight`: upper bound that ranks by true held-out query weight.

Overall retrieval:

| Strategy | P@50 +/-30 lbs | Mean weight delta @50 | Has match @50 +/-30 |
| --- | ---: | ---: | ---: |
| `oracle_true_weight` | 0.9968 | 0.7538 | 1.0000 |
| `global_point` | 0.7672 | 24.8016 | 0.7711 |
| `two_stage_blend_point` | 0.6981 | 26.1734 | 0.7078 |
| `global_range_pm30` | 0.6897 | 30.9130 | 0.8024 |
| `candidate_expansion_211` | 0.6869 | 31.1719 | 0.8107 |
| `weighted_global_point` | 0.6168 | 29.3733 | 0.6301 |
| `height_size_only` | 0.6027 | 40.1706 | 0.7708 |

211+ retrieval:

| Strategy | P@50 +/-30 lbs | Mean weight delta @50 | Has match @50 +/-30 |
| --- | ---: | ---: | ---: |
| `oracle_true_weight` | 0.9765 | 4.7304 | 1.0000 |
| `two_stage_blend_point` | 0.4024 | 46.0289 | 0.4299 |
| `weighted_global_point` | 0.2866 | 54.9680 | 0.3040 |
| `global_point` | 0.0392 | 82.9667 | 0.0428 |
| `candidate_expansion_211` | 0.0225 | 102.6738 | 0.1306 |
| `height_size_only` | 0.0198 | 130.0289 | 0.1306 |
| `global_range_pm30` | 0.0148 | 103.2760 | 0.0689 |

The search-shaped takeaway is different from the point-estimate takeaway: the global model is best overall, but it nearly fails 211+ retrieval. The two-stage blend is meaningfully better for 211+ retrieval while preserving decent overall retrieval quality. The naive range-expansion implementation did not work well for 211+ precision, likely because it creates broad candidate ties and still relies too much on the underpredicting global range.

### 12. Catalog Measurement-Search Evaluation

Created and ran the corrected product-shaped retrieval evaluator:

- `scripts/evaluate_catalog_measurement_search.py`
- `reports/supervised_scale_catalog_measurement_search_metrics.json`
- `reports/supervised_scale_catalog_measurement_search_summary_2026-06-09.md`

This pass treats held-out catalog images as if their weights were missing, assigns inferred weights to those catalog images, then simulates users searching by measurements. It measures whether inferred catalog weights help the right images and nearby measurement matches rank well.

Compared strategies:

- `height_size_only`: current-style search without inferred catalog weight,
- `global_point`: inferred catalog weight as a primary ranking distance,
- `weighted_global_point`: weighted global inferred catalog weight as a primary ranking distance,
- `two_stage_blend_point`: two-stage blended inferred catalog weight as a primary ranking distance,
- `two_stage_candidate_boost`: use blended catalog weight for likely 211+ catalog images when it improves query distance,
- `height_size_global_weight_boost`: keep height/size primary and use global inferred catalog weight as a light boost,
- `height_size_two_stage_weight_boost`: keep height/size primary and use two-stage blended inferred catalog weight as a light boost,
- `height_size_weighted_global_boost`: keep height/size primary and use weighted global inferred catalog weight as a light boost,
- `oracle_true_weight`: upper bound using true held-out catalog weight.

Overall catalog search:

| Strategy | Target in Top 50 | P@50 | Mean Weight Delta@50 | Mean Height Delta@50 |
| --- | ---: | ---: | ---: | ---: |
| `oracle_true_weight` | 1.0000 | 0.9577 | 1.6808 | 0.9623 |
| `height_size_two_stage_weight_boost` | 0.6915 | 0.7619 | 22.8350 | 0.3646 |
| `height_size_global_weight_boost` | 0.8232 | 0.7449 | 24.9178 | 0.3609 |
| `two_stage_blend_point` | 0.1973 | 0.7387 | 23.4710 | 0.9860 |
| `two_stage_candidate_boost` | 0.2369 | 0.7138 | 26.1759 | 0.8676 |
| `global_point` | 0.2184 | 0.7045 | 26.1691 | 1.1422 |
| `height_size_weighted_global_boost` | 0.6138 | 0.7042 | 25.7654 | 0.3667 |
| `weighted_global_point` | 0.1602 | 0.6613 | 27.0376 | 1.0471 |
| `height_size_only` | 0.9869 | 0.6484 | 32.2305 | 0.3420 |

211+ catalog search:

| Strategy | Target in Top 50 | P@50 | Mean Weight Delta@50 | Mean Height Delta@50 |
| --- | ---: | ---: | ---: | ---: |
| `oracle_true_weight` | 1.0000 | 0.8266 | 4.9995 | 1.9332 |
| `height_size_global_weight_boost` | 0.6983 | 0.3596 | 50.7947 | 0.6792 |
| `height_size_weighted_global_boost` | 0.5867 | 0.3535 | 51.4323 | 0.7820 |
| `height_size_two_stage_weight_boost` | 0.5914 | 0.3474 | 52.7878 | 0.6588 |
| `height_size_only` | 0.9952 | 0.2907 | 79.6251 | 0.3599 |
| `two_stage_candidate_boost` | 0.1900 | 0.2726 | 54.4797 | 1.9313 |
| `two_stage_blend_point` | 0.1829 | 0.2689 | 54.6325 | 1.9470 |
| `weighted_global_point` | 0.1639 | 0.2466 | 53.1847 | 2.3656 |
| `global_point` | 0.1235 | 0.2064 | 50.1901 | 3.2031 |

The corrected product takeaway is stronger: do not replace measurement search with predicted weight distance. Use inferred catalog weight as a light ranking boost on top of height and size. That improves overall P@50 from 0.6484 to 0.7619, and improves 211+ P@50 from 0.2907 to 0.3596 while preserving height closeness.

## What We Learned

1. A medium-scale supervised dataset is feasible: 18,624 of 20,000 sampled rows downloaded successfully.
2. Duplicate controls matter: perceptual hashing found 12 near-duplicate groups crossing train/test.
3. Excluding multi-person and low-signal images still leaves a strong training set: 13,712 eligible rows.
4. The eligible set is large enough to test supervised CLIP models much more seriously than the prior 2,237-row CLIP validation.
5. The dataset is still weight-distribution-skewed toward mid-range weights, so later error slicing by weight band is essential.
6. CLIP image embeddings do add signal: the best CLIP+height+size model improved MAE by about 3.4 lbs over height+size and about 7.7 lbs over height alone.
7. Direct `weight_lbs` training slightly beat BMI-target training in this first guarded run.
8. The model is not yet acceptable for higher-weight users: errors above 211 lbs are very large, likely because the training distribution is skewed and the regressor collapses toward midweight predictions.
9. Sample weighting helps the high-weight bins but creates a tradeoff: the best high-weight model has worse overall MAE, lower within-30-lbs coverage, and still underpredicts the 211+ group by about 52.6 lbs on average.
10. For this dataset, direct `weight_lbs` remains the best target in both the overall and high-weight weighted comparisons.
11. Two-stage modeling confirms that the visual embeddings contain much stronger high-weight signal than the global regressors use: a 211+ specialist gets 211+ MAE down to 26.1 lbs.
12. The routing problem is now the main blocker. The high-weight classifier can find many 211+ rows, but a low threshold routes too many midweight users into the specialist and damages overall accuracy.
13. The best overall two-stage blend slightly improves overall MAE to 24.0 lbs, but it does not solve high-weight underprediction.
14. In retrieval terms, the global point model is best overall, but it is nearly useless for 211+ users: only 3.92% of the top 50 candidates are within +/-30 lbs for 211+ test queries.
15. The two-stage blend is the strongest current retrieval strategy for 211+ users: 40.24% of top 50 candidates are within +/-30 lbs, with mean top-50 weight delta 46.0 lbs.
16. Search evaluation is the better framing for product use. A model can be too risky for displaying or trusting as a point estimate while still being useful for candidate ranking.
17. The first search-retrieval framing was backwards for the product. Users input measurements; they do not submit query images. The corrected catalog measurement-search evaluation is the relevant one.
18. Inferred weights work best as a light boost on top of height/size search, not as a replacement ranking key.
19. For all held-out catalog items, height+size plus two-stage weight boost improved P@50 from 0.6484 to 0.7619.
20. For 211+ held-out catalog items, height+size plus global weight boost improved P@50 from 0.2907 to 0.3596 and cut mean top-50 weight delta from 79.6 lbs to 50.8 lbs.

## Next Step

Run the next retrieval-focused passes:

- tune the light boost weight instead of using the first fixed 0.08 multiplier,
- compare inferred weight boost only for catalog images missing self-reported weight versus all catalog images,
- add source-group/product de-duplication so top-K results are not inflated by near-duplicate review contexts,
- evaluate with the actual website search scoring formula if available,
- evaluate real search-log replay separately if production logs include enough outcome signal,
- try stronger high-weight oversampling beyond sample weighting,
- inspect high-weight test examples for label/data artifacts and crop quality,
- try larger or alternate free image embeddings now that the data pipeline is reusable.
