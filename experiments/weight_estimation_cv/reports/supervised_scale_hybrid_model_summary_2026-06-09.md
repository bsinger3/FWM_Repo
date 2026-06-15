# Supervised Weight Model Experiment Checkpoint

## Dataset

- Train rows: 10,584
- Test rows: 3,128
- Original embedding dimension: 768
- PCA dimensions used for supervised models: 96
- PCA explained variance ratio: 0.7444

## Best Result

- Model: `ridge_clip_pca_height_size_predict_weight`
- MAE: 24.814 lbs
- Median absolute error: 15.738 lbs
- RMSE: 37.938 lbs
- Within 20 lbs: 0.5994
- Within 30 lbs: 0.7602

## Top Models

| Rank | Model | Target | MAE | Median AE | RMSE | Within 20 | Within 30 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `ridge_clip_pca_height_size_predict_weight` | `weight_lbs` | 24.814 | 15.738 | 37.938 | 0.5994 | 0.7602 |
| 2 | `ridge_clip_pca_height_size_predict_bmi` | `bmi` | 24.9 | 15.65 | 38.138 | 0.5985 | 0.7561 |
| 3 | `ridge_clip_pca_height_size_source_predict_weight` | `weight_lbs` | 25.114 | 16.059 | 38.264 | 0.5985 | 0.758 |
| 4 | `ridge_clip_pca_height_size_source_predict_bmi` | `bmi` | 25.218 | 15.586 | 38.466 | 0.5937 | 0.7535 |
| 5 | `hist_gradient_clip_pca_height_size_predict_bmi` | `bmi` | 25.409 | 14.72 | 39.328 | 0.6125 | 0.7458 |
| 6 | `hist_gradient_clip_pca_height_size_predict_weight` | `weight_lbs` | 25.669 | 14.878 | 39.976 | 0.6145 | 0.7465 |
| 7 | `hist_gradient_clip_pca_height_size_source_predict_bmi` | `bmi` | 25.822 | 14.771 | 40.066 | 0.6049 | 0.7455 |
| 8 | `hist_gradient_clip_pca_height_size_source_predict_weight` | `weight_lbs` | 26.204 | 15.004 | 40.883 | 0.6106 | 0.742 |
| 9 | `ridge_clip_pca_height_predict_weight` | `weight_lbs` | 26.361 | 18.063 | 38.455 | 0.5448 | 0.7062 |
| 10 | `ridge_clip_pca_height_predict_bmi` | `bmi` | 26.454 | 17.971 | 38.521 | 0.5403 | 0.7075 |
| 11 | `hist_gradient_clip_pca_height_predict_bmi` | `bmi` | 27.157 | 18.208 | 39.51 | 0.5371 | 0.7008 |
| 12 | `hist_gradient_clip_pca_height_predict_weight` | `weight_lbs` | 27.288 | 17.866 | 39.784 | 0.5412 | 0.6937 |

## Feature Guardrails

The supervised pass uses image embeddings plus height, optional size text, and optional source-site text.
It excludes clothing type, image quality as a feature, all crop/framing geometry, image dimensions, detector geometry, low-signal labels, and multi-person images.
Image-quality bucket is retained only for evaluation slices.
