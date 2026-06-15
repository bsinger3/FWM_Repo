# abhaymise face height/weight/BMI model probe

Date: 2026-06-09

Repo: https://github.com/abhaymise/Face-to-height-weight-BMI-estimation-

Local clone:

`/Users/briannasinger/Projects/FWM/FWM_Repo/experiments/weight_estimation_cv/models/abhaymise_face_height_weight_bmi`

## What was checked

- The repo was cloned into the isolated experiment `models/` directory.
- The README and notebook were inspected.
- The serialized files were checked:
  - `height_predictor.model`
  - `weight_predictor.model`
  - `bmi_predictor.model`
- Current experiment venv dependencies were checked.
- A compatibility shim for old `sklearn.externals.joblib` references was attempted.
- The bundled Codex Python runtime was also checked as a possible fallback.

## Findings

The repo is not an end-to-end image model. It expects:

1. `face_recognition` / dlib to extract a 128-dimensional face embedding.
2. Old scikit-learn regressors to predict height, weight, and BMI from that embedding.

The current experiment venv does not include:

- `face_recognition`
- `dlib`

The serialized model files also do not load under the current scikit-learn/joblib stack:

- Initial failure: `ModuleNotFoundError: No module named 'sklearn.externals.joblib'`
- Narrow compatibility shim failure: internal scikit-learn `KeyError`s while loading the old pickles.

The Codex bundled Python runtime is Python 3.12 and has pandas, but not scikit-learn/joblib/dlib/face_recognition. There is no obvious older local Python runtime suitable for scikit-learn 0.19 / TensorFlow-era dependencies.

## Decision

Do not spend more time on this model in the current pass.

Reasons:

- It was trained on a small manually collected Bollywood celebrity dataset.
- It requires old dlib/face_recognition embeddings.
- Its pickled regressors are not compatible with the current runtime.
- Installing/forcing old sklearn and dlib would likely cost more time than this low-confidence model is worth.

## Status

Blocked / deprioritized.

This candidate should only be revisited if:

- we create an old Python compatibility environment specifically for archaeology, or
- someone rewrites/extracts the old regressors into a current format, or
- other stronger candidates fail and we still want to exhaust every face-model option.

