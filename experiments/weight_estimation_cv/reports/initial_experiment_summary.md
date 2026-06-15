# Initial Weight Estimation CV Experiment

Date: 2026-06-09

## Scope

All experiment files are isolated under `experiments/weight_estimation_cv/`.
No active `outputs/` package was modified.

## Dataset

- Raw manifest: `data/ground_truth_manifest.csv`
- Rows with usable image URL, exact-ish height, and exact-ish self-reported weight: 77,770
- First evaluation sample: `data/eval_sample.csv`
- Sample rows: 1,200
- Downloaded/cached usable images: 971
- Download failures: 229, mostly HTTP 403 from blocked image hosts

## Baselines On Downloaded Sample

Input: `data/eval_sample_with_images.csv`
Train/test split: 698 train, 273 test

| Model | MAE lbs | RMSE lbs | R2 | Within 20 lbs |
| --- | ---: | ---: | ---: | ---: |
| height + size/category/source ridge predicting BMI | 31.958 | 42.290 | 0.2962 | 0.4249 |
| height + existing-CV/image-size fields ridge predicting BMI | 32.185 | 42.412 | 0.2922 | 0.4066 |
| random forest height + size/category/source predicting BMI | 32.251 | 42.820 | 0.2785 | 0.4103 |
| mean BMI x height | 36.310 | 45.139 | 0.1982 | 0.3187 |
| height-only ridge predicting BMI | 36.391 | 45.243 | 0.1945 | 0.3260 |
| mean weight | 41.385 | 50.543 | -0.0053 | 0.2564 |

## Pretrained Image Encoder Results

Pretrained ImageNet encoders were downloaded through torchvision and cached under `cache/torch`.
Features were extracted for all 971 cached images.

| Model/scenario | MAE lbs | RMSE lbs | R2 | Within 20 lbs |
| --- | ---: | ---: | ---: | ---: |
| EfficientNet-B0 + image + height + size/category/source | 32.452 | 43.393 | 0.2590 | 0.4286 |
| MobileNetV3-small + image + height + size/category/source | 33.482 | 42.932 | 0.2747 | 0.3810 |
| ResNet18 + image + height + size/category/source | 33.579 | 43.441 | 0.2574 | 0.3626 |
| EfficientNet-B0 image + height | 34.170 | 45.187 | 0.1965 | 0.3956 |
| EfficientNet-B0 image only | 34.207 | 45.234 | 0.1949 | 0.3919 |

## Interpretation

Generic pretrained ImageNet encoders did not beat the non-image tabular baseline on this first split.
The strongest result so far is still height plus scraped structured context, not raw generic image features.

This does not rule out computer vision. It suggests that if visual signal is going to help, the next useful tests are:

1. A purpose-built BMI/weight model such as Digital Scale, if model weights can be obtained.
2. Fashion/person-specific embeddings such as FashionCLIP or CLIP, not only ImageNet classifiers.
3. A domain-trained FWM model using the 77,770-row ground truth manifest.
4. A smaller, progress-logged YOLO pose/framing feature pass to check whether body visibility metrics improve calibration or abstention.

The first attempted full YOLO metric pass over 971 images was stopped because CPU-only inference was too slow for this checkpoint.
