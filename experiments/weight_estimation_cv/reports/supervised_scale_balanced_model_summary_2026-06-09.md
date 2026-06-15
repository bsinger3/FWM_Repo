# Balanced Supervised Weight Model Experiment

## Dataset

- Train rows: 10,584
- Test rows: 3,128
- PCA dimensions: 96

## Best Overall MAE

- Model: `ridge_clip_pca_height_size_sqrt_inverse_bin_predict_weight`
- MAE: 24.773 lbs
- Median absolute error: 17.268 lbs
- Within 30 lbs: 0.7251

## Best 211+ lb MAE

- Model: `ridge_clip_pca_height_inverse_bin_predict_weight`
- Overall MAE: 29.437 lbs
- 211+ lb MAE: 54.909 lbs
- 211+ lb mean signed error: -52.563 lbs

## Top Overall Models

| Rank | Model | Target | Weighting | MAE | Median AE | Within 30 | 211+ MAE | 211+ Signed Error |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `ridge_clip_pca_height_size_sqrt_inverse_bin_predict_weight` | `weight_lbs` | `sqrt_inverse_bin` | 24.773 | 17.268 | 0.7251 | 70.647 | -70.456 |
| 2 | `ridge_clip_pca_height_size_sqrt_inverse_bin_predict_bmi` | `bmi` | `sqrt_inverse_bin` | 24.776 | 17.271 | 0.7305 | 71.294 | -70.859 |
| 3 | `ridge_clip_pca_height_size_sqrt_inverse_bin_predict_log_weight` | `log_weight` | `sqrt_inverse_bin` | 24.813 | 16.046 | 0.7484 | 78.185 | -77.869 |
| 4 | `ridge_clip_pca_height_size_none_predict_weight` | `weight_lbs` | `none` | 24.814 | 15.738 | 0.7602 | 82.947 | -82.915 |
| 5 | `ridge_clip_pca_height_size_none_predict_bmi` | `bmi` | `none` | 24.9 | 15.65 | 0.7561 | 83.225 | -83.121 |
| 6 | `ridge_clip_pca_height_size_source_sqrt_inverse_bin_predict_log_weight` | `log_weight` | `sqrt_inverse_bin` | 24.947 | 15.977 | 0.7478 | 79.921 | -79.74 |
| 7 | `ridge_clip_pca_height_size_capped_inverse_bin_predict_log_weight` | `log_weight` | `capped_inverse_bin` | 25.0 | 16.46 | 0.7366 | 75.236 | -74.73 |
| 8 | `ridge_clip_pca_height_size_source_capped_inverse_bin_predict_log_weight` | `log_weight` | `capped_inverse_bin` | 25.068 | 16.429 | 0.7379 | 77.052 | -76.753 |
| 9 | `ridge_clip_pca_height_size_source_sqrt_inverse_bin_predict_weight` | `weight_lbs` | `sqrt_inverse_bin` | 25.104 | 17.539 | 0.7199 | 72.429 | -72.335 |
| 10 | `ridge_clip_pca_height_size_source_none_predict_weight` | `weight_lbs` | `none` | 25.114 | 16.059 | 0.758 | 84.182 | -84.172 |
| 11 | `ridge_clip_pca_height_size_source_sqrt_inverse_bin_predict_bmi` | `bmi` | `sqrt_inverse_bin` | 25.12 | 17.171 | 0.7276 | 73.055 | -72.859 |
| 12 | `ridge_clip_pca_height_size_capped_inverse_bin_predict_weight` | `weight_lbs` | `capped_inverse_bin` | 25.195 | 17.943 | 0.7094 | 67.553 | -67.232 |
| 13 | `ridge_clip_pca_height_size_inverse_bin_predict_log_weight` | `log_weight` | `inverse_bin` | 25.198 | 17.367 | 0.718 | 67.869 | -66.548 |
| 14 | `ridge_clip_pca_height_size_capped_inverse_bin_predict_bmi` | `bmi` | `capped_inverse_bin` | 25.201 | 17.887 | 0.7142 | 68.238 | -67.616 |
| 15 | `ridge_clip_pca_height_size_source_none_predict_bmi` | `bmi` | `none` | 25.218 | 15.586 | 0.7535 | 84.598 | -84.528 |

## Top 211+ lb Models

| Rank | Model | Target | Weighting | Overall MAE | 211+ MAE | 211+ Median AE | 211+ Signed Error |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| 1 | `ridge_clip_pca_height_inverse_bin_predict_weight` | `weight_lbs` | `inverse_bin` | 29.437 | 54.909 | 48.884 | -52.563 |
| 2 | `ridge_clip_pca_height_inverse_bin_predict_bmi` | `bmi` | `inverse_bin` | 29.369 | 55.849 | 50.502 | -52.821 |
| 3 | `ridge_clip_pca_height_size_inverse_bin_predict_weight` | `weight_lbs` | `inverse_bin` | 26.329 | 58.333 | 54.576 | -57.287 |
| 4 | `ridge_clip_pca_height_size_inverse_bin_predict_bmi` | `bmi` | `inverse_bin` | 26.231 | 59.745 | 55.991 | -58.171 |
| 5 | `ridge_clip_pca_height_size_source_inverse_bin_predict_weight` | `weight_lbs` | `inverse_bin` | 26.68 | 60.484 | 57.253 | -59.81 |
| 6 | `ridge_clip_pca_height_size_source_inverse_bin_predict_bmi` | `bmi` | `inverse_bin` | 26.576 | 61.768 | 59.243 | -60.778 |
| 7 | `ridge_clip_pca_height_inverse_bin_predict_log_weight` | `log_weight` | `inverse_bin` | 27.881 | 61.81 | 57.497 | -59.093 |
| 8 | `hist_gradient_height_size_inverse_bin_predict_bmi` | `bmi` | `inverse_bin` | 27.521 | 62.862 | 58.327 | -62.378 |
| 9 | `hist_gradient_height_size_inverse_bin_predict_weight` | `weight_lbs` | `inverse_bin` | 27.689 | 63.273 | 60.098 | -62.835 |
| 10 | `ridge_clip_pca_height_capped_inverse_bin_predict_weight` | `weight_lbs` | `capped_inverse_bin` | 27.599 | 63.353 | 58.391 | -62.723 |
| 11 | `ridge_clip_pca_height_capped_inverse_bin_predict_bmi` | `bmi` | `capped_inverse_bin` | 27.679 | 63.616 | 58.357 | -62.417 |
| 12 | `ridge_clip_pca_height_sqrt_inverse_bin_predict_weight` | `weight_lbs` | `sqrt_inverse_bin` | 26.879 | 67.303 | 62.929 | -66.93 |
| 13 | `ridge_clip_pca_height_sqrt_inverse_bin_predict_bmi` | `bmi` | `sqrt_inverse_bin` | 26.933 | 67.39 | 62.612 | -66.655 |
| 14 | `ridge_clip_pca_height_size_capped_inverse_bin_predict_weight` | `weight_lbs` | `capped_inverse_bin` | 25.195 | 67.553 | 63.463 | -67.232 |
| 15 | `ridge_clip_pca_height_size_inverse_bin_predict_log_weight` | `log_weight` | `inverse_bin` | 25.198 | 67.869 | 65.046 | -66.548 |

## Feature Guardrails

This pass uses the same approved features as the first supervised experiment: CLIP PCA components, height, optional size text, and optional source-site text.
Weight bins are used only to compute sample weights and evaluation slices, not as prediction features.
