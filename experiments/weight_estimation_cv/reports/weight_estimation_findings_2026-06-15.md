# Weight Estimation CV Findings

Date: 2026-06-15

## Recommendation

Do not display inferred weights and do not use inferred weights as hard filters.

The useful product path is to use inferred catalog weights as a light ranking boost for database images that are missing self-reported weight, layered on top of the existing measurement search signals such as height and size.

## Why

The image models are not accurate enough to trust as point estimates. The best supervised CLIP person-crop model reached roughly 24.8 lbs MAE overall, but it badly underpredicted higher-weight users. Sample weighting and two-stage high-weight specialists improved the high-weight bins, but routing those specialist predictions as a single inferred weight was still too fragile.

The corrected product-shaped evaluation was more promising. Users search by measurements; they do not submit image queries. In that setup, inferred weights are assigned to catalog images whose weight is hidden, then used to influence measurement-based ranking.

## Best Product-Shaped Result

Catalog measurement-search evaluation over the held-out test split:

| Strategy | Overall P@50 | 211+ P@50 | Overall Mean Weight Delta@50 | 211+ Mean Weight Delta@50 |
| --- | ---: | ---: | ---: | ---: |
| Height/size only | 0.6484 | 0.2907 | 32.2305 lbs | 79.6251 lbs |
| Height/size + two-stage inferred-weight boost | 0.7619 | 0.3474 | 22.8350 lbs | 52.7878 lbs |
| Height/size + global inferred-weight boost | 0.7449 | 0.3596 | 24.9178 lbs | 50.7947 lbs |
| Oracle true weight upper bound | 0.9577 | 0.8266 | 1.6808 lbs | 4.9995 lbs |

P@50 means the share of the top 50 returned catalog images within +/-30 lbs and +/-3 inches of the measurement query.

## Experimental Path

1. Public/pretrained CV models were not sufficient out of the box.
2. A supervised dataset was built from 20,000 labeled rows.
3. After download, duplicate cleanup, and quality filtering, the training-eligible set had 13,712 single-person rows.
4. CLIP ViT-B/16 person-crop embeddings were extracted for all eligible rows.
5. The best global supervised regressor improved over height-only and height+size baselines, but still underpredicted high-weight users.
6. Sample weighting improved high-weight error but made overall ranking worse.
7. Two-stage high-weight specialist regressors showed that the embeddings contain useful high-weight signal, but classifier routing is too risky as a hard switch.
8. Measurement-search evaluation showed the right usage pattern: keep height/size primary, then use inferred catalog weight as a light ranking boost.

## Important Numbers

Best direct supervised point-estimate model:

- Model: `ridge_clip_pca_height_size_predict_weight`
- MAE: 24.814 lbs
- Median absolute error: 15.738 lbs
- Within 30 lbs: 0.7602

Best 211+ specialist point-estimate model:

- Model: `specialist_ridge_clip_pca_height_train_gte_211`
- 211+ MAE: 26.080 lbs
- 211+ mean signed error: -7.124 lbs
- Overall MAE: 83.365 lbs

The specialist is useful as evidence that high-weight signal exists, but it is not suitable as a global model.

## Guardrails

The supervised training/evaluation intentionally excluded:

- `clothing_type_id`,
- image quality as a model feature,
- multi-person images,
- crop/framing geometry,
- image dimensions,
- person/face detector geometry,
- low-signal operational labels.

Image quality was used only for filtering or slicing.

## Next Steps

1. Tune the inferred-weight boost strength against the actual website search scoring formula.
2. Apply inferred-weight boosting only to catalog images missing self-reported weight, not to rows with real user-provided weights.
3. Add source-group/product de-duplication to retrieval metrics.
4. Inspect high-weight failures for label/crop artifacts.
5. Try stronger embeddings or a custom fine-tuned model only after search-score tuning establishes the value of the signal.

## Key Artifacts

- `reports/supervised_scale_progress_2026-06-09.md`
- `reports/supervised_scale_catalog_measurement_search_summary_2026-06-09.md`
- `reports/supervised_scale_catalog_measurement_search_metrics.json`
- `scripts/evaluate_catalog_measurement_search.py`
- `scripts/train_supervised_hybrid_weight_models.py`
- `scripts/train_balanced_supervised_weight_models.py`
- `scripts/train_two_stage_weight_models.py`
