# DINOv2 full-image embedding benchmark summary

Date: 2026-06-09

Model: `timm/vit_small_patch14_dinov2`

Local artifacts:

- Evaluator: `scripts/evaluate_dinov2_full_image_embeddings.py`
- Embeddings: `data/features/dinov2_small_full_image_embeddings.npz`
- Row map: `data/dinov2_small_full_image_embedding_rows.csv`
- Metrics: `reports/dinov2_small_full_image_metrics.json`

## What was tested

DINOv2-small full-image embeddings were extracted for all downloaded FWM eval images. FWM train-split regressors were then trained to predict BMI, converted to pounds using self-reported height.

Subsets evaluated:

- all downloaded images
- person-visible images
- full-body-likely images
- torso/partial-body images

## Coverage and runtime

- Rows embedded: `971 / 971`
- Extraction runtime: about `5m 02s`
- Embedding dimension: `384`
- Input size: `518x518`

## Results

| Subset | Best DINOv2 model | DINOv2 MAE | Same-subset baseline MAE | Delta |
| --- | --- | ---: | ---: | ---: |
| all downloaded | `random_forest_dinov2_embedding_height_predict_bmi` | `34.887 lb` | `32.038 lb` | `+2.849 lb` |
| person visible | `random_forest_dinov2_embedding_height_predict_bmi` | `34.054 lb` | `31.310 lb` | `+2.744 lb` |
| full body likely | `hist_gradient_dinov2_embedding_height_predict_bmi` | `32.528 lb` | `32.017 lb` | `+0.511 lb` |
| torso/partial body | `random_forest_dinov2_embedding_height_predict_bmi` | `37.729 lb` | `34.129 lb` | `+3.600 lb` |

## Interpretation

DINOv2 full-image embeddings do not beat the same-subset height/metadata baselines.

The closest result is on full-body-likely images, where the gap is only about `0.5 lb`, but it is still not an improvement. Full-image embeddings are likely diluted by background, clothing, product framing, mirror/selfie composition, and non-body pixels.

## Decision

Do not use full-image DINOv2 embeddings as a standalone candidate.

Next visual embedding step, if continued:

- test DINOv2 or CLIP on YOLO person crops rather than full images;
- include geometry + metadata + crop embeddings in one stacked model.
