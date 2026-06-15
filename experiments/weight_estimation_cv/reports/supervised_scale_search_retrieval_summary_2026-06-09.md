# Search Retrieval Evaluation

## Dataset

- Train candidate rows: 10,584
- Test query rows: 3,128
- PCA dimensions: 96

## Best Strategies

- Best non-oracle overall `precision_at_50_within_30`: `global_point`
- Best non-oracle 211+ `precision_at_50_within_30`: `two_stage_blend_point`

## Overall Retrieval

| Rank | Strategy | P@20 +/-30 | P@50 +/-30 | P@100 +/-30 | Mean Delta@50 | Has Match@50 +/-30 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `oracle_true_weight` | 0.9995 | 0.9968 | 0.9899 | 0.7538 | 1.0 |
| 2 | `global_point` | 0.7661 | 0.7672 | 0.7687 | 24.8016 | 0.7711 |
| 3 | `two_stage_blend_point` | 0.6948 | 0.6981 | 0.7005 | 26.1734 | 0.7078 |
| 4 | `global_range_pm30` | 0.694 | 0.6897 | 0.6882 | 30.913 | 0.8024 |
| 5 | `candidate_expansion_211` | 0.6934 | 0.6869 | 0.6852 | 31.1719 | 0.8107 |
| 6 | `weighted_global_point` | 0.6123 | 0.6168 | 0.6212 | 29.3733 | 0.6301 |
| 7 | `height_size_only` | 0.6144 | 0.6027 | 0.5894 | 40.1706 | 0.7708 |

## 211+ Retrieval

| Rank | Strategy | P@20 +/-30 | P@50 +/-30 | P@100 +/-30 | Mean Delta@50 | Has Match@50 +/-30 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `oracle_true_weight` | 0.9966 | 0.9765 | 0.925 | 4.7304 | 1.0 |
| 2 | `two_stage_blend_point` | 0.3968 | 0.4024 | 0.4008 | 46.0289 | 0.4299 |
| 3 | `weighted_global_point` | 0.2885 | 0.2866 | 0.2866 | 54.968 | 0.304 |
| 4 | `global_point` | 0.0369 | 0.0392 | 0.0407 | 82.9667 | 0.0428 |
| 5 | `candidate_expansion_211` | 0.0209 | 0.0225 | 0.0257 | 102.6738 | 0.1306 |
| 6 | `height_size_only` | 0.017 | 0.0198 | 0.0141 | 130.0289 | 0.1306 |
| 7 | `global_range_pm30` | 0.0152 | 0.0148 | 0.0182 | 103.276 | 0.0689 |

## Notes

This evaluates search-style retrieval, not displayable weight estimates.
The oracle strategy ranks candidates by the query's true weight and is included only as an upper bound.
Candidate expansion uses the global predicted range and, when the 211+ classifier probability is at least 0.15, also considers a 211+ specialist range.
