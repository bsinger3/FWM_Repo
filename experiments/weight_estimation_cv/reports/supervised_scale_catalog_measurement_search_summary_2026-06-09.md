# Catalog Measurement Search Evaluation

## Dataset

- Train rows used to fit inference models: 10,584
- Held-out catalog/query rows: 3,128
- PCA dimensions: 96

## What This Simulates

Users input measurements to search the image database. This evaluation treats held-out catalog images as if their weights were missing, assigns inferred catalog weights, then checks whether those images and nearby measurement matches rank well for measurement-based searches.

## Overall Catalog Search

| Rank | Strategy | Target in Top 50 | P@50 | Mean Weight Delta@50 | Mean Height Delta@50 |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | `oracle_true_weight` | 1.0 | 0.9577 | 1.6808 | 0.9623 |
| 2 | `height_size_two_stage_weight_boost` | 0.6915 | 0.7619 | 22.835 | 0.3646 |
| 3 | `height_size_global_weight_boost` | 0.8232 | 0.7449 | 24.9178 | 0.3609 |
| 4 | `two_stage_blend_point` | 0.1973 | 0.7387 | 23.471 | 0.986 |
| 5 | `two_stage_candidate_boost` | 0.2369 | 0.7138 | 26.1759 | 0.8676 |
| 6 | `global_point` | 0.2184 | 0.7045 | 26.1691 | 1.1422 |
| 7 | `height_size_weighted_global_boost` | 0.6138 | 0.7042 | 25.7654 | 0.3667 |
| 8 | `weighted_global_point` | 0.1602 | 0.6613 | 27.0376 | 1.0471 |
| 9 | `height_size_only` | 0.9869 | 0.6484 | 32.2305 | 0.342 |

## 211+ Catalog Search

| Rank | Strategy | Target in Top 50 | P@50 | Mean Weight Delta@50 | Mean Height Delta@50 |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | `oracle_true_weight` | 1.0 | 0.8266 | 4.9995 | 1.9332 |
| 2 | `height_size_global_weight_boost` | 0.6983 | 0.3596 | 50.7947 | 0.6792 |
| 3 | `height_size_weighted_global_boost` | 0.5867 | 0.3535 | 51.4323 | 0.782 |
| 4 | `height_size_two_stage_weight_boost` | 0.5914 | 0.3474 | 52.7878 | 0.6588 |
| 5 | `height_size_only` | 0.9952 | 0.2907 | 79.6251 | 0.3599 |
| 6 | `two_stage_candidate_boost` | 0.19 | 0.2726 | 54.4797 | 1.9313 |
| 7 | `two_stage_blend_point` | 0.1829 | 0.2689 | 54.6325 | 1.947 |
| 8 | `weighted_global_point` | 0.1639 | 0.2466 | 53.1847 | 2.3656 |
| 9 | `global_point` | 0.1235 | 0.2064 | 50.1901 | 3.2031 |

## Notes

The oracle strategy uses the held-out catalog image's true weight and is only an upper bound.
Precision@K means the share of top-K returned catalog images within +/-30 lbs and +/-3 inches of the measurement query.
Target-in-top-K asks whether the exact held-out catalog image that generated the synthetic query appears in the top K.
