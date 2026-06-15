# Two-Stage Weight Model Experiment

## Dataset

- Train rows: 10,584
- Test rows: 3,128
- PCA dimensions: 96

## Best Overall MAE

- Model: `blend_gte_211_hist_gradient_power_1.0`
- Overall MAE: 24.004 lbs
- Median absolute error: 15.84 lbs
- Within 30 lbs: 0.7551
- 211+ MAE: 72.337 lbs

## Best 211+ lb MAE

- Model: `specialist_ridge_clip_pca_height_train_gte_211`
- Overall MAE: 83.365 lbs
- 211+ MAE: 26.08 lbs
- 211+ signed error: -7.124 lbs

## Classifier Metrics

| Classifier | Threshold | Positives | ROC AUC | Avg Precision | P@0.5 | R@0.5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `logistic` | 181.0 | 746 | 0.8734 | 0.6546 | 0.601 | 0.6381 |
| `hist_gradient` | 181.0 | 746 | 0.858 | 0.6403 | 0.7628 | 0.2587 |
| `logistic` | 211.0 | 421 | 0.8711 | 0.4492 | 0.4361 | 0.6485 |
| `hist_gradient` | 211.0 | 421 | 0.8551 | 0.4625 | 0.7101 | 0.1164 |
| `logistic` | 251.0 | 199 | 0.8528 | 0.2679 | 0.306 | 0.3568 |
| `hist_gradient` | 251.0 | 199 | 0.7666 | 0.2297 | 0.8 | 0.0201 |

## Top Overall Models

| Rank | Model | MAE | Median AE | Within 30 | 211+ MAE | 211+ Signed Error |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `blend_gte_211_hist_gradient_power_1.0` | 24.004 | 15.84 | 0.7551 | 72.337 | -71.9 |
| 2 | `blend_gte_181_hist_gradient_power_1.0` | 24.028 | 16.019 | 0.7366 | 64.663 | -63.57 |
| 3 | `blend_gte_181_hist_gradient_power_1.5` | 24.043 | 15.803 | 0.7516 | 70.139 | -69.465 |
| 4 | `blend_gte_211_logistic_power_2.0` | 24.176 | 16.081 | 0.7321 | 56.639 | -53.055 |
| 5 | `blend_gte_181_hist_gradient_power_2.0` | 24.184 | 15.715 | 0.7542 | 73.284 | -72.828 |
| 6 | `blend_gte_211_hist_gradient_power_1.5` | 24.28 | 15.706 | 0.7615 | 76.585 | -76.334 |
| 7 | `blend_gte_181_logistic_power_2.0` | 24.379 | 16.386 | 0.7308 | 59.535 | -57.765 |
| 8 | `blend_gte_211_hist_gradient_power_2.0` | 24.437 | 15.783 | 0.7609 | 78.564 | -78.383 |
| 9 | `route_gte_211_hist_gradient_cutoff_0.5` | 24.495 | 15.627 | 0.7625 | 77.989 | -76.086 |
| 10 | `blend_gte_251_hist_gradient_power_1.0` | 24.638 | 15.801 | 0.7567 | 80.982 | -80.88 |
| 11 | `blend_gte_211_logistic_power_1.5` | 24.649 | 16.603 | 0.7206 | 52.231 | -47.839 |
| 12 | `route_gte_211_hist_gradient_cutoff_0.25` | 24.661 | 15.738 | 0.7574 | 72.8 | -68.656 |
| 13 | `blend_gte_181_logistic_power_1.5` | 24.675 | 16.965 | 0.7196 | 55.262 | -53.096 |
| 14 | `route_gte_251_hist_gradient_cutoff_0.35` | 24.7 | 15.71 | 0.7615 | 82.1 | -81.989 |
| 15 | `route_gte_211_hist_gradient_cutoff_0.35` | 24.707 | 15.71 | 0.7577 | 76.104 | -73.599 |

## Top 211+ lb Models

| Rank | Model | Overall MAE | Within 30 | 211+ MAE | 211+ Median AE | 211+ Signed Error |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `specialist_ridge_clip_pca_height_train_gte_211` | 83.365 | 0.1103 | 26.08 | 20.525 | -7.124 |
| 2 | `specialist_ridge_clip_pca_height_train_gte_181` | 58.22 | 0.1937 | 29.818 | 23.46 | -21.995 |
| 3 | `route_gte_211_logistic_cutoff_0.15` | 36.695 | 0.6119 | 30.917 | 23.234 | -13.704 |
| 4 | `route_gte_181_logistic_cutoff_0.15` | 33.613 | 0.593 | 31.299 | 24.313 | -23.733 |
| 5 | `route_gte_181_logistic_cutoff_0.25` | 30.121 | 0.6512 | 35.47 | 25.127 | -28.079 |
| 6 | `specialist_ridge_clip_pca_height_train_gte_251` | 119.35 | 0.0595 | 36.71 | 34.149 | 24.84 |
| 7 | `route_gte_211_logistic_cutoff_0.25` | 31.945 | 0.6714 | 37.263 | 25.843 | -21.412 |
| 8 | `route_gte_181_logistic_cutoff_0.35` | 28.218 | 0.6848 | 40.124 | 28.376 | -32.931 |
| 9 | `route_gte_211_logistic_cutoff_0.35` | 29.271 | 0.6998 | 42.313 | 29.303 | -27.8 |
| 10 | `blend_gte_211_logistic_power_1.0` | 26.163 | 0.6899 | 45.884 | 40.144 | -40.311 |
| 11 | `blend_gte_181_logistic_power_1.0` | 25.729 | 0.6886 | 49.383 | 44.581 | -46.592 |
| 12 | `route_gte_211_logistic_cutoff_0.5` | 26.635 | 0.7267 | 50.29 | 40.641 | -38.268 |
| 13 | `route_gte_181_logistic_cutoff_0.5` | 26.4 | 0.7177 | 50.318 | 41.188 | -44.256 |
| 14 | `route_gte_181_hist_gradient_cutoff_0.15` | 26.687 | 0.7107 | 50.778 | 42.102 | -44.895 |
| 15 | `blend_gte_211_logistic_power_1.5` | 24.649 | 0.7206 | 52.231 | 48.267 | -47.839 |

## Feature Guardrails

The two-stage pass uses CLIP PCA components plus height and size for classification, and CLIP PCA plus height for high-weight specialist regressors.
Weight thresholds are used only for classifier labels, specialist training subsets, routing, and evaluation slices.
