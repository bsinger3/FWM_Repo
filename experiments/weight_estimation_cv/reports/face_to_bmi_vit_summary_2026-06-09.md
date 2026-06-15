# face-to-bmi-vit benchmark summary

Date: 2026-06-09

Repo: https://github.com/liujie-zheng/face-to-bmi-vit

Weights URL:

`https://face-to-bmi-weights.s3.us-east.cloud-object-storage.appdomain.cloud/aug_epoch_7.pt`

Local artifacts:

- Evaluator: `scripts/evaluate_face_to_bmi_vit.py`
- Weights: `models/face_to_bmi_vit/weights/aug_epoch_7.pt`
- Predictions: `data/face_to_bmi_vit_predictions.csv`
- Metrics: `reports/face_to_bmi_vit_metrics.json`

## What was tested

The pretrained checkpoint was downloaded and evaluated on the FWM face-visible test subset.

The evaluator:

1. Detects and crops the largest face with OpenCV Haar cascade.
2. Runs the `vit_h_14` model with the repo's 518px preprocessing.
3. Predicts BMI.
4. Converts predicted BMI to pounds using FWM self-reported height.
5. Compares predictions to self-reported weight.

## Runtime notes

The checkpoint is large: about `2.4 GB`.

This machine did not expose MPS acceleration through the experiment venv, so inference ran on CPU. The 74-row face-visible test subset took about `14m 24s`, or `11.7s/image` on average.

## Metrics

Same-subset baseline:

- Model: `ridge_height_metadata_predict_bmi`
- Rows: `74`
- MAE: `37.785 lb`
- RMSE: `50.219 lb`
- R2: `0.2128`
- Within 20 lb: `0.3919`

face-to-bmi-vit:

- Rows attempted: `74`
- Rows predicted: `74`
- MAE: `43.261 lb`
- RMSE: `58.583 lb`
- R2: `-0.0712`
- Within 20 lb: `0.3108`

## Error pattern

Prediction bias by true weight quartile:

| True weight quartile | Rows | MAE | Mean bias |
| --- | ---: | ---: | ---: |
| 75-120 lb | 20 | 41.167 lb | +25.050 lb |
| 120-153 lb | 18 | 22.603 lb | +6.544 lb |
| 153-199.5 lb | 17 | 37.608 lb | -20.838 lb |
| 199.5-330 lb | 19 | 70.092 lb | -56.751 lb |

This looks like strong regression toward middle-BMI predictions. That is especially bad for FWM because the highest-weight users are exactly where fit/ranking mistakes can become most harmful.

## Decision

Reject this checkpoint as a raw off-the-shelf FWM weight signal.

Reasons:

- It is worse than the same-subset height+metadata baseline by `5.476 lb` MAE.
- It has negative R2 on FWM face-visible test rows.
- It has poor high-weight performance and a large underestimation bias in the heaviest quartile.
- It is computationally heavy for broad use without batching/acceleration.

Possible future use:

- Revisit only as a calibrated feature if we later decide to run train-split predictions and stack it with metadata.
- Do not use raw predictions directly for search/ranking.
