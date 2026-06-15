# Person Crop Embedding Comparison

Date: 2026-06-09

## Goal

Test whether person-only crops improve weight estimation versus the same-row height/metadata baseline. This isolates the person from background clutter and checks whether general-purpose vision embeddings carry useful body-size signal.

All outputs are contained under `experiments/weight_estimation_cv`; the main `outputs/` tree was not touched.

## Models Tested

| Model | Source path | Crop rows | Embedding dim | Result |
| --- | --- | ---: | ---: | --- |
| DINOv2 small | `facebook/dinov2-small` via local evaluator | 867 | 384 | Worse than baseline across all crop subsets |
| CLIP ViT-B/16 | `vit_base_patch16_clip_224.openai` via `timm` | 867 | 768 | Best positive signal so far, mostly on torso/partial subset |
| SigLIP ViT-B/16 | `vit_base_patch16_siglip_224.webli` via `timm` | 867 | 768 | Worse than baseline across all crop subsets |
| CLIP ResNet-50 | `resnet50_clip.openai` via `timm` | 867 | 2048 | Slight partial-body/full-body signal, weaker than CLIP ViT-B/16 |

## Main Comparison

Same-row baseline is `baseline_ridge_height_metadata_predict_bmi`, trained on the exact rows available for each crop embedding run. Lower MAE is better.

| Subset | Test rows | Same-row baseline MAE | Best CLIP ViT-B/16 MAE | Best CLIP ResNet-50 MAE | Best SigLIP MAE | Best DINOv2 crop MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Person crop all | 237 | 31.186 | 31.342 | 32.394 | 32.213 | 33.924 |
| Prior person visible | 234 | 31.184 | 31.513 | 32.984 | 32.197 | 33.631 |
| Prior full body likely | 180 | 31.843 | 31.637 | 31.793 | 32.106 | 33.379 |
| Prior torso or partial body | 53 | 34.160 | 31.444 | 32.279 | 34.939 | 37.417 |

## What We Learned

1. Person crops are not automatically better than full images. DINOv2 full-image and DINOv2 crop embeddings both underperformed the height/metadata baseline.

2. CLIP ViT-B/16 is the first open/free model with a meaningful positive signal. It improved the torso/partial subset by 2.716 lb MAE and improved within-20-lb accuracy from 43.4% to 52.8%.

3. The CLIP signal is not broad yet. On all person crops and on the person-visible subset, CLIP ViT-B/16 had slightly worse MAE than the baseline, though RMSE and R2 improved a bit.

4. CLIP ResNet-50 partially confirms the direction, but it is weaker than CLIP ViT-B/16. It improved torso/partial MAE by 1.881 lb and full-body MAE by only 0.050 lb.

5. SigLIP did not reproduce the CLIP gain. That makes this look less like “any language-image model works” and more like “specific CLIP representations may contain useful signal.”

## Caveat

The strongest CLIP ViT-B/16 win is on only 53 held-out test rows. That is enough to justify scaling the experiment, but not enough to treat as a production-quality result.

## Recommendation

Next step: scale CLIP ViT-B/16 person-crop embeddings to a larger sample from the 77,770-row ground-truth manifest, prioritizing rows where:

- a person crop is confidently available,
- height and weight are both present,
- duplicate leakage is blocked by image URL/hash/group,
- torso/partial and full-body subsets are both large enough to compare.

If the torso/partial improvement survives a larger held-out test, then the best practical path is likely a hybrid rank feature:

- use height/metadata as the stable base,
- add CLIP crop predictions only where they beat calibrated baseline confidence,
- never display inferred weights to users.

## Artifacts

Scripts:

- `scripts/evaluate_dinov2_person_crop_embeddings.py`
- `scripts/evaluate_timm_person_crop_embeddings.py`

Metric files:

- `reports/dinov2_small_person_crop_metrics.json`
- `reports/vit_base_patch16_clip_224_openai_person_crop_metrics.json`
- `reports/vit_base_patch16_siglip_224_webli_person_crop_metrics.json`
- `reports/resnet50_clip_openai_person_crop_metrics.json`

Embedding rows:

- `data/dinov2_small_person_crop_embedding_rows.csv`
- `data/vit_base_patch16_clip_224_openai_person_crop_embedding_rows.csv`
- `data/vit_base_patch16_siglip_224_webli_person_crop_embedding_rows.csv`
- `data/resnet50_clip_openai_person_crop_embedding_rows.csv`

