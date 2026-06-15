# MeFEm-S face embedding benchmark summary

Date: 2026-06-09

Model: https://huggingface.co/boretsyury/MeFEm

Local artifacts:

- Evaluator: `scripts/evaluate_mefem_face_embeddings.py`
- Weights: `models/mefem/MeFEm-S.pth.tar`
- Embeddings: `data/features/mefem_s_face_embeddings.npz`
- Row map: `data/mefem_s_face_embedding_rows.csv`
- Metrics: `reports/mefem_s_face_embedding_metrics.json`

## What was tested

MeFEm-S face embeddings were extracted for FWM face-visible images, then FWM train-split regressors were trained to predict BMI or direct weight.

The evaluator:

1. Detects and loosely crops the largest face.
2. Runs MeFEm-S (`vit_small_patch16_224`) to produce 384-dimensional CLS embeddings.
3. Trains regressors on FWM train rows.
4. Evaluates on FWM face-visible test rows.
5. Compares against the same-subset height+metadata baseline.

## Coverage and runtime

- Original face-visible rows: `279`
- Rows with successful second-pass face crops and embeddings: `274`
- Train rows: `200`
- Test rows: `74`
- Extraction runtime: about `2m 18s`
- Checkpoint size: about `43 MB`

## Same-row baseline

On the exact MeFEm-eligible rows:

- Best baseline: `ridge_height_metadata_predict_bmi`
- Rows: `200 train / 74 test`
- MAE: `37.774 lb`
- RMSE: `50.219 lb`
- R2: `0.2128`
- Within 20 lb: `0.3784`

## Best MeFEm result

Best model:

`random_forest_mefem_s_embedding_height_predict_bmi`

Metrics:

- MAE: `38.316 lb`
- RMSE: `48.287 lb`
- R2: `0.2722`
- Within 20 lb: `0.3514`

## Interpretation

MeFEm-S does not beat the metadata baseline on MAE, which is the primary metric.

It does improve RMSE and R2 slightly, suggesting the embeddings may reduce some larger errors. But the MAE and within-20-lb metrics are worse, so this is not enough to justify keeping face embeddings as a main path right now.

## Decision

Deprioritize face-only models after this pass.

Reasons:

- Face-visible coverage is limited: `279 / 971` downloaded images.
- The raw face-to-bmi-vit checkpoint underperformed by a clear margin.
- MeFEm-S plus FWM training came close but still missed the metadata baseline on MAE.

Possible future use:

- Revisit as an ensemble feature only if later person-crop/foundation models need stacking experiments.
- Do not spend more time on face-only models before testing person/body-visible approaches.
