# Supervised Weight Model Experiment Plan

Date: 2026-06-09

## Purpose

The pretrained CV models we tested did not produce a strong out-of-the-box weight estimator. The best result so far is CLIP ViT-B/16 on YOLO person crops, which produced a modest improvement over the height/metadata baseline after scaling:

| Subset | Baseline MAE | Best CLIP crop MAE | Improvement |
| --- | ---: | ---: | ---: |
| All person crops | 29.367 lb | 28.728 lb | 0.639 lb |
| Full-body likely | 29.362 lb | 29.185 lb | 0.177 lb |
| Torso/partial body | 33.608 lb | 33.056 lb | 0.552 lb |

That is not good enough as a standalone inferred-weight model, but it does suggest there is weak visual signal in the images. The next experiment should test whether FWM's own ground-truth dataset can learn that signal better than generic pretrained models alone.

The goal is not to display inferred weights. The goal is to determine whether inferred visual/height features can improve search ranking and fit-similarity matching.

## Hypothesis

FWM can train a better task-specific model by combining:

- self-reported height,
- pretrained image embeddings,
- and supervised labels from self-reported weight.

The first model should not be trained from raw pixels. It should train on top of pretrained image embeddings and metadata first. Raw image fine-tuning only becomes worthwhile if the supervised embedding model clearly beats baseline.

## Success Criteria

Primary metric:

- Weight MAE in pounds on a held-out test set.

Secondary metrics:

- RMSE in pounds.
- R2.
- Within 10/20/30 lb accuracy.
- Error by image quality bucket.
- Error by weight band.
- Error by height band.
- Error by source site.
- Ranking usefulness for search.

Minimum bar for continuing:

- At least 1.5-2.0 lb MAE improvement over the same-row height/metadata baseline on a large held-out test set, or
- a measurable improvement in search/ranking relevance even if pound-error gains are smaller.

Strong bar:

- 3+ lb MAE improvement over baseline on person-visible images without obvious leakage or source artifacts.

Stop condition:

- If supervised models improve MAE by less than 1 lb and do not improve ranking metrics, do not train deeper CV models yet.

## Data Scope

Start from:

- `data/ground_truth_manifest.csv`

Current available ground-truth rows:

- 77,770 usable rows with image URL, height, weight, and BMI fields.

Use a larger sample than the prior runs:

| Phase | Target rows | Purpose |
| --- | ---: | --- |
| Smoke | 500-1,000 | Confirm pipeline correctness |
| Medium | 10,000-20,000 | Fast model comparison |
| Large | All downloadable usable rows | Final validation |

Do not use the active repo-level `outputs/` folder. All derived data, images, embeddings, metrics, and reports should stay under:

- `experiments/weight_estimation_cv/`

## Leakage Controls

This experiment only matters if the held-out set is genuinely held out.

Required controls:

1. Drop exact duplicate rows by image URL, height, and weight.
2. Hash downloaded image files and prevent exact image hash from crossing train/test.
3. Compute perceptual hashes and prevent near-duplicate image groups from crossing train/test.
4. Group split by source/product/review family when possible.
5. Keep source-site distribution visible in every report.
6. Compare against same-row baselines only.
7. Never compare a model on an easier row subset to a baseline trained/tested on a harder subset.

Potential leakage risks to watch:

- same review image duplicated under different resized CDN URLs,
- same reviewer/product rows appearing in both train and test,
- source sites with distinctive image styles that correlate with body-size distributions,
- product sizes that leak weight indirectly,
- duplicated captions/review metadata if text features are added later.

## Features

### Eligibility Filters

Some fields should be used to decide whether an image belongs in the training/evaluation set, not as trainable model features.

Use these as filters:

- exclude images with multiple detected people,
- exclude low-signal images where no usable person crop is available,
- optionally exclude images below a minimum person-crop confidence,
- optionally run separate experiments for full-body versus torso/partial images.

Do not train directly on:

- `image_quality_bucket`,
- multiple-people flags,
- low-signal flags,
- arbitrary image-quality labels.

Those labels are useful for filtering and reporting slices. They should not become shortcuts the model learns.

### Baseline Features

Use these to define the minimum benchmark:

- `height_in`
- `size_display`
- `source_site_display`

Do not include `clothing_type_id` in the main model. It is unlikely to be meaningfully related to body weight, and it risks teaching the model source/catalog quirks instead of body-shape signal.

`source_site_display` should be tested cautiously. It may help diagnose source distribution effects, but if it improves results too much, that may mean the model is learning source-specific artifacts rather than visual body information. Report metrics both with and without source-site features.

### Target Options

The business target is weight in pounds. All primary metrics should be reported as weight error.

For model training, compare two target formulations:

1. Directly predict `weight_lbs`.
2. Predict `bmi`, then convert back to weight using height:

```text
predicted_weight_lbs = predicted_bmi * height_in^2 / 703
```

Why test BMI at all:

- weight is heavily driven by height,
- BMI normalizes weight by height,
- predicting BMI may force the model to learn visual body-size signal rather than mostly relearning that taller people tend to weigh more,
- converted weight error still tells us whether the model is useful for the actual product need.

Why direct weight may still win:

- self-reported height may be noisy or missing for some rows,
- the website ultimately needs weight-like similarity, not BMI itself,
- direct weight prediction may better match user/search behavior.

Decision rule:

- evaluate both targets,
- choose whichever has better held-out weight MAE and better ranking metrics,
- never report BMI as the user-facing goal.

### Geometry Diagnostics

Use YOLO/person crop geometry for filtering, diagnostics, and ablation tests only. Do not include these fields in the primary model.

Do not train the primary model on:

- image dimensions,
- main person area percentage,
- crop area percentage,
- crop aspect ratio,
- crop width/height percentages,
- person width/height percentages,
- person aspect ratio.

These fields mostly describe camera framing, crop coverage, pose, and composition. They may correlate with source-site style or photo type, but they are not reliable evidence of body weight.

Do not include person count after filtering, because training should only use single-person images. Detection confidence should primarily be used as a filter/slice, not as a core predictive feature.

Permitted uses:

- remove images with no usable person crop,
- remove images with multiple people,
- slice evaluation by crop coverage/full-body/partial-body,
- verify whether the embedding model fails on low-coverage crops,
- run a clearly labeled ablation to confirm geometry does or does not help.

### Embedding Features

Prioritized embedding sources:

1. CLIP ViT-B/16 person crop embeddings.
2. CLIP ViT-B/16 full-image embeddings.
3. DINOv2 person crop embeddings only as a comparison, since it was weak in earlier tests.
4. Optional later: larger CLIP/OpenCLIP variants if they are available locally/free and computationally reasonable.

The leading candidate from prior experiments is:

- `vit_base_patch16_clip_224.openai` via `timm`

### Image Quality Slices

Keep separate metrics for:

- full-body likely,
- torso or partial body,
- person visible low coverage,
- face only or small person,
- low signal.

Low-signal images should probably either:

- fall back to baseline, or
- receive lower confidence in search ranking.

Multiple-person images should be excluded from this experiment rather than modeled.

## Model Families

### Phase 1: Non-Deep Supervised Models

Train regressors over tabular features plus embeddings.

Recommended first models:

- Ridge regression over embeddings and allowed metadata.
- Random forest.
- Histogram gradient boosting.
- LightGBM or XGBoost if installation is feasible.
- CatBoost if categorical handling is helpful and installation is feasible.

Train and compare both target formulations:

- direct `weight_lbs`,
- `bmi` converted back to `weight_lbs` for evaluation.

Why start here:

- Much cheaper than fine-tuning.
- Easier to debug.
- Works with cached embeddings.
- Better for learning whether the dataset has enough signal.

### Phase 2: Calibration and Model Gating

Train or evaluate separate models/gates for:

- all person-visible images,
- full-body likely images,
- torso/partial images.

The final system may not use one model everywhere. It may use:

- baseline/fallback for low-signal images excluded from CV training,
- CLIP hybrid model for person-visible images,
- bucket-specific calibration for full-body versus partial-body crops.

Required comparison:

| Gate | Question |
| --- | --- |
| Always baseline | What happens if we ignore vision? |
| Always hybrid | Does CLIP help globally? |
| Bucket-gated hybrid | Does CLIP only help certain image types? |
| Confidence-gated hybrid | Can we use CLIP only when predicted error/confidence is favorable? |

### Phase 3: Fine-Tuning

Only do this if Phases 1-2 show meaningful signal.

Fine-tuning options:

- fine-tune a lightweight vision head on frozen CLIP features,
- unfreeze last transformer block of CLIP/ViT,
- train a small MLP over embeddings plus height/metadata,
- use pairwise/ranking loss instead of direct weight loss.

Avoid training a full vision model from scratch unless:

- the supervised embedding models strongly outperform baseline,
- there are enough downloaded images,
- and the ranking product need justifies the extra complexity.

## Search-Ranking Evaluation

Weight MAE is not the only useful metric for FWM.

The product need is closer to:

> Given a user or image, rank photos/reviews from people with similar bodies and fit-relevant measurements.

Add ranking metrics after the first supervised model works:

1. For each held-out row, retrieve nearest neighbors by:
   - baseline height/metadata,
   - CLIP embedding similarity,
   - supervised predicted weight,
   - hybrid score.
2. Measure average absolute difference in:
   - weight,
   - BMI,
   - height,
   - size,
   - known garment fit outcome if available later.
3. Report top-k metrics:
   - mean top-5 weight difference,
   - mean top-10 weight difference,
   - percentage of top-10 within 20 lb,
   - percentage of top-10 within same size bucket.

This may reveal value even if direct point predictions remain noisy.

## Experiment Order

### Step 1: Prepare A Larger Clean Dataset

Create a new scale dataset under `data/supervised_scale_*`.

Outputs:

- `data/supervised_scale_sample.csv`
- `data/supervised_scale_with_images.csv`
- `data/supervised_scale_hardened.csv`
- `data/supervised_scale_no_hash_leaks.csv`
- `reports/supervised_scale_data_summary.json`

What to learn:

- How many rows can be downloaded/cached?
- How many survive duplicate/leak controls?
- How balanced are height/weight/source distributions?

### Step 2: Tag Image Quality and Person Geometry

Run face/person detection and quality buckets. Use quality/person labels to decide eligibility and to create evaluation slices, not as trainable features.

Outputs:

- `data/supervised_scale_with_quality_tags.csv`
- `data/supervised_scale_training_eligible_rows.csv`
- `reports/supervised_scale_quality_summary.json`

What to learn:

- How many rows are full-body versus partial-body versus low-signal?
- How many rows remain after excluding low-signal and multiple-person images?
- Is the large dataset skewed toward certain image hosts or source sites?

### Step 3: Generate Person Crops

Generate reusable YOLO crop boxes for eligible single-person images.

Outputs:

- `data/supervised_scale_person_crop_attempt_rows.csv`
- `reports/supervised_scale_person_crop_attempt_summary.json`

What to learn:

- How many usable person crops exist?
- Does YOLO fail systematically on certain source sites/image types?

### Step 4: Extract CLIP Embeddings

Extract CLIP ViT-B/16 embeddings for eligible single-person crops.

Outputs:

- `data/features/supervised_scale_clip_person_crop_embeddings.npz`
- `data/supervised_scale_clip_person_crop_embedding_rows.csv`
- `reports/supervised_scale_clip_embedding_summary.json`

What to learn:

- Whether the embedding pipeline scales cleanly.
- Whether cache size/runtime are manageable.

### Step 5: Train Supervised Hybrid Models

Train baseline and hybrid models on identical eligible rows. Do not include `clothing_type_id` or `image_quality_bucket` as model inputs.

Model specs:

- baseline height/allowed-metadata model,
- CLIP embedding + height,
- CLIP embedding + height + allowed metadata,
- bucket-gated variants.

Optional ablation only:

- add geometry diagnostics to confirm whether they help or just overfit to framing/source artifacts.

Train each model twice where feasible:

- target = direct `weight_lbs`,
- target = `bmi`, evaluated after conversion back to `weight_lbs`.

Outputs:

- `reports/supervised_scale_model_metrics.json`
- `reports/supervised_scale_model_summary.md`
- optional `models/supervised_scale/*.joblib`

What to learn:

- Does supervised learning over CLIP embeddings beat baseline?
- Which model family works best?
- Which subsets benefit?
- Is the improvement big enough to justify more work?

### Step 6: Error Analysis

Create sliced metrics by:

- weight band,
- BMI band,
- height band,
- image-quality bucket,
- source site,
- crop area/coverage.

Multiple-person images should not appear in the training/evaluation set. If any remain, count them as a data-cleaning issue, not a model slice.

Outputs:

- `reports/supervised_scale_error_slices.csv`
- `reports/supervised_scale_error_analysis.md`

What to learn:

- Where does the model help?
- Where does it harm?
- Are errors biased against specific body sizes?
- Does model performance degrade at high/low weights?

### Step 7: Ranking Evaluation

Evaluate whether predictions/embeddings improve search results even if direct MAE gains are modest.

Outputs:

- `reports/supervised_scale_ranking_metrics.json`
- `reports/supervised_scale_ranking_summary.md`

What to learn:

- Does the model retrieve more body-similar examples?
- Does it improve top-k similarity compared with height/metadata alone?
- Is it useful enough for search ranking?

### Step 8: Decision Point

Decide among:

1. Stop: visual model does not help enough.
2. Use as a weak ranking feature: modest improvement, low engineering risk.
3. Train a custom head/MLP over embeddings: useful signal, but tree models plateau.
4. Fine-tune CLIP/DINO/ViT: strong enough supervised signal to justify deeper CV training.

## Expected Outcomes

Likely outcome:

- Supervised CLIP hybrid improves modestly over baseline, probably enough to consider as a ranking feature but not enough for displayed weight inference.

Good outcome:

- Hybrid model improves MAE by 2+ lb and improves top-k body-similarity ranking.

Excellent outcome:

- Hybrid or bucket-gated model improves MAE by 3+ lb and materially improves search relevance across body-size ranges.

Bad outcome:

- No stable improvement after leakage controls. In that case, do not train deeper image models. Focus on explicit user-provided measurements and non-weight fit signals.

## Implementation Notes

Reuse existing scripts where possible:

- `scripts/make_eval_sample.py`
- `scripts/download_eval_images.py`
- `scripts/harden_eval_split.py`
- `scripts/drop_cross_split_duplicate_hashes.py`
- `scripts/tag_image_quality.py`
- `scripts/make_person_crop_attempts.py`
- `scripts/evaluate_timm_person_crop_embeddings.py`

New scripts likely needed:

- `scripts/train_supervised_hybrid_weight_models.py`
- `scripts/evaluate_weight_model_error_slices.py`
- `scripts/evaluate_weight_ranking_metrics.py`

Avoid changing production code during this experiment.

## Privacy and Product Constraints

- Do not display inferred weights.
- Treat inferred weight/BMI as an internal ranking signal only.
- Keep reports focused on aggregate model quality, not individual user examples.
- Be careful about bias: error analysis must include body-size bands.
- If the model is ever used in production search, store confidence and provenance so inferred fields are clearly separated from self-reported measurements.
