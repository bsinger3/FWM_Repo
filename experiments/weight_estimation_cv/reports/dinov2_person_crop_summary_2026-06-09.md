# DINOv2 person-crop embedding benchmark summary

Date: 2026-06-09

Model: `timm/vit_small_patch14_dinov2`

Cropper: YOLOv8n person detector

Local artifacts:

- Evaluator: `scripts/evaluate_dinov2_person_crop_embeddings.py`
- Attempt rows: `data/dinov2_small_person_crop_attempt_rows.csv`
- Successful crop rows: `data/dinov2_small_person_crop_embedding_rows.csv`
- Embeddings: `data/features/dinov2_small_person_crop_embeddings.npz`
- Metrics: `reports/dinov2_small_person_crop_metrics.json`

## What was tested

For every downloaded image in the eval sample, the evaluator reran YOLO, selected the largest detected person, cropped that region with light padding, extracted DINOv2-small embeddings, and trained FWM regressors to predict BMI. Predicted BMI was converted to pounds using self-reported height.

The report includes exact same-row baselines so crop-eligible rows are compared fairly.

## Coverage and runtime

- Attempted rows: `971`
- Successful person crops: `867`
- No-person rows: `104`

Subset coverage:

- Person crop all: `630 train / 237 test`
- Prior person-visible: `623 train / 234 test`
- Prior full-body-likely: `465 train / 180 test`
- Prior torso/partial-body: `156 train / 53 test`

## Results

| Subset | Best crop model | Crop MAE | Same-row baseline MAE | Delta |
| --- | --- | ---: | ---: | ---: |
| person crop all | `random_forest_crop_dinov2_embedding_height_predict_bmi` | `33.924 lb` | `31.186 lb` | `+2.738 lb` |
| prior person-visible | `random_forest_crop_dinov2_embedding_geometry_predict_bmi` | `33.631 lb` | `31.184 lb` | `+2.447 lb` |
| prior full-body-likely | `random_forest_crop_dinov2_embedding_geometry_predict_bmi` | `33.379 lb` | `31.843 lb` | `+1.536 lb` |
| prior torso/partial-body | `random_forest_crop_dinov2_embedding_height_predict_bmi` | `37.417 lb` | `34.160 lb` | `+3.257 lb` |

## Interpretation

Cropping to the main person did not make DINOv2 useful enough for weight/BMI estimation.

This is an important negative result because it removes the most obvious explanation for the full-image failure. The issue is not just that full images contain background noise; DINOv2 person-crop embeddings still do not outperform height and existing metadata on this sample.

The best crop models are tree models using embeddings plus height, but they are consistently worse than the same-row metadata baseline and have lower within-20-lb accuracy.

## Decision

Do not keep DINOv2 person-crop embeddings as a primary candidate.

Next possible crop-embedding check:

- OpenCLIP/CLIP person-crop embeddings, if setup is cheap.

If CLIP also misses, the free generic-embedding route should be deprioritized. At that point the strongest remaining options are:

- wait for Digital Scale weights;
- train a FWM-specific model with more data;
- improve metadata/search features rather than relying on visual weight inference.
