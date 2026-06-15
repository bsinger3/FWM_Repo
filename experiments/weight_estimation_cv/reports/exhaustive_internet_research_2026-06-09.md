# Exhaustive internet research: photo-based weight/BMI estimation

Date: 2026-06-09

Scope: Find public or commercial computer-vision systems that could estimate user weight, BMI, or body-composition proxies from user-submitted photos. Prioritize models that can be downloaded or benchmarked against the FWM self-reported height/weight ground truth set. Height is available for many FWM photos, so BMI-predicting models are relevant because predicted weight can be derived from BMI and height:

`weight_lb = predicted_bmi * height_in^2 / 703`

## Bottom line

The public landscape is thinner than it first appears.

The best direct match is Digital Scale, an ETH Zurich / WayBetter project for BMI estimation from smartphone camera images. It has a public GitHub repo with training, filtering, Android/on-device deployment, and inference scaffolding, but the trained BMI model weights and sample data are not included in the repository; the README says to request them from the authors. If we can obtain those weights, this should be the first serious model to benchmark.

The second strongest public direction is face-to-BMI. There are several papers and repos, with `liujie-zheng/face-to-bmi-vit` being the most polished runnable repo I found. This is only useful for FWM photos where a face is visible and large enough. It should not be treated as a general solution for review/apparel photos.

The third direction is 3D body shape / body-measurement estimation. These models can estimate shape, measurements, or body composition from images, but most do not directly output weight. They may provide useful features if we train our own downstream weight regressor. They are also more brittle for casual apparel photos because they usually expect front/side/full-body capture, visible pose, or constrained clothing.

Commercial vendors such as 3DLOOK and Bodygram are quite relevant, but they are API/SDK products, not downloadable models. 3DLOOK is especially relevant because it explicitly advertises weight prediction and BMI verification from two photos, with a claimed average weight prediction error of 3.5%. It would need a vendor/API evaluation rather than a local open-source benchmark.

I did not find a credible off-the-shelf Hugging Face full-body "predict weight from arbitrary image" model. Hugging Face has MeFEm, a 2026 face embedding model with BMI evaluation and downloadable weights, plus one low-signal Keras gender/age/BMI model. MeFEm is worth testing only on face-visible images.

Given our first FWM experiment, where generic ImageNet features did not beat the height+metadata baseline, the next practical pass should test purpose-built BMI models first, then stronger foundation embeddings such as DINOv2/CLIP/FashionCLIP/OpenCLIP on person crops. If purpose-built weights are unavailable or weak on FWM photos, training a FWM-specific model is probably the right path.

## Search methodology

Sources checked:

- Web search for academic papers: full-body BMI estimation, body weight estimation, smartphone BMI estimation, face-to-BMI, body composition from smartphone imagery, body shape under clothing.
- GitHub search/API for downloadable repos: `DigitalScale`, `Face-to-BMI`, `body weight estimation image`, `BMI estimation image`, `BMI prediction image pytorch`.
- Hugging Face API/search for `BMI`, `Face-to-BMI`, and related image models.
- Commercial/vendor websites for body scanning, weight/BMI verification, and body measurement APIs.
- Existing FWM experiment results in this directory for context.

## Highest-priority candidates to benchmark

### 1. Digital Scale

Links:

- Paper: https://arxiv.org/abs/2508.20534
- Repo: https://github.com/im-ethz/DigitalScale

What it is:

- Deep learning BMI estimation from smartphone camera images.
- Trained on WayBED, a proprietary dataset of 84,963 smartphone images from 25,353 people.
- Uses filtering/posture/person-detection quality controls to reject bad inputs.
- Supports full-body and torso-oriented BMI estimation workflows.
- Converts directly to our target if height is known, because it predicts BMI rather than pounds.

Reported performance:

- MAPE 7.9% on WayBED holdout using full-body images.
- MAPE 13% on unseen VisualBodyToBMI.
- MAPE 8.56% after fine-tuning on VisualBodyToBMI.

Availability:

- Code is public.
- Repo includes training/evaluation scripts, VisualBodyToBMI parsing, person/face boxes, keypoints, posture filtering, and Android/CLAID app code.
- Trained BMI model weights are not committed. README says to contact the authors for "Digital Scale model weights and sample data."
- No GitHub release package as of this research pass.

Fit for FWM:

- Best open-source-aligned target.
- Strong because FWM often has full-body or outfit mirror photos, and we often have height.
- Risk: Digital Scale appears trained on controlled smartphone health/weight-loss-style capture. FWM photos have apparel, mirrors, crops, poses, occlusions, and product/review context. Its own filtering may reject many images.

Recommended next action:

1. Request the model weights from the authors.
2. Run the quick-start inference on the current downloaded FWM evaluation sample.
3. Convert predicted BMI to pounds using self-reported height.
4. Report coverage separately from accuracy: MAE on all attempted images, MAE on model-accepted images, rejection rate, and bias by height/size/category/source.

### 2. 3DLOOK FitXpress

Link: https://3dlook.ai/

What it is:

- Commercial body scanning platform.
- Explicitly advertises weight prediction, BMI verification, fat ratio, body composition, oversized-clothing detection, real-time pose validation, and 80+ body measurements from mobile camera capture.
- Claims "only 2 photos needed" and "45 sec measuring process."

Reported performance:

- 3DLOOK claims BMI calculations based on predicted weight have 89% accuracy, 76% of users have deviation of 5% or less, average weight prediction error is 3.5%, and body measurements have 96-97% accuracy.

Availability:

- Commercial API/SDK, not a downloadable model.
- Integration appears to require business/vendor access.

Fit for FWM:

- Very relevant if the company will allow batch API evaluation or trial access.
- Risk: likely optimized for guided front/side scans, not arbitrary apparel review images. Their own product uses pose validation and clothing detection, which suggests unconstrained images may perform worse.

Recommended next action:

- If vendor evaluation is acceptable, ask for an API trial and run a small, privacy-reviewed benchmark on images where user consent/data terms allow it. Keep guessed weights internal only.

### 3. BodyWeightEstimationbyFacialImages

Link: https://github.com/73510/BodyWeightEstimationbyFacialImages

What it is:

- GitHub repo for estimating body weight from front/side images plus structured inputs.
- Repo description says it estimates bodyweight based on front and side image, height, race, and gender, with MAE 5.05 kg.

Availability:

- MIT license.
- Mostly notebooks: preprocessing, front model, side model, structured model, hybrid model, transfer, model test.
- Includes an `edge_model` directory.

Fit for FWM:

- Interesting because it predicts weight directly and uses height.
- But likely built around structured front/side image capture, and it includes race/gender inputs that we likely should avoid unless already validly available and needed. It is also a small one-star repo, so treat it as experimental, not production-grade.

Recommended next action:

- Inspect whether pretrained weights are present in `edge_model`. If yes, test it on a manually filtered subset where both front-ish full-body image and height are available. Do not add race/gender features unless there is a clear policy/product reason.

### 4. face-to-bmi-vit

Link: https://github.com/liujie-zheng/face-to-bmi-vit

What it is:

- Vision Transformer model predicting BMI from one human face image.
- MIT license, 36 stars, updated through 2026 GitHub metadata, Python.
- README says the model outperforms a referenced state-of-the-art VisualBMI benchmark by 39.5%.

Reported performance:

- README reports MAE 3.45 BMI points on the original test dataset after 10 epochs.
- README reports MAE 3.02 BMI points on augmented data after 7 epochs.

Availability:

- Public code and demo script.
- Dataset/checkpoint details need local inspection; repo is large (~964 MB by GitHub API), so it may include significant assets.

Fit for FWM:

- Useful only when a face is visible and occupies enough of the image.
- FWM images often crop faces, hide faces, use mirror poses, or show bodies/outfits more than faces. So this should be benchmarked as a conditional model: "if face-visible, does it help?"

Recommended next action:

- Add a face-detection gate on the existing eval sample, then benchmark face-to-bmi-vit only on the face-present subset. Convert BMI to weight using height.

### 5. MeFEm

Links:

- Paper: https://arxiv.org/abs/2602.14672
- Hugging Face: https://huggingface.co/boretsyury/MeFEm

What it is:

- 2026 medical/anthropometric face embedding model based on a modified JEPA.
- Paper says it performs well on anthropometric tasks and has promising BMI estimation results on a closed-source consolidated dataset.

Availability:

- Hugging Face model is public, ungated, with `MeFEm-B.pth.tar` and `MeFEm-S.pth.tar`.
- No downloads/likes at the time of the API check, so it is new and unproven in practice.

Fit for FWM:

- A strong face-feature candidate, not a full-body weight estimator.
- We would probably use it as an embedding model plus a FWM-trained regressor rather than expecting a plug-and-play BMI prediction head.

Recommended next action:

- Benchmark MeFEm embeddings on face-present FWM images, with height included downstream. Compare to face-to-bmi-vit and to non-image baseline.

## Other relevant academic work

### Face-to-BMI: Using Computer Vision to Infer Body Mass Index on Social Media

Link: https://arxiv.org/abs/1703.03156

What it is:

- Older social-media face-to-BMI work.
- Important historically because many face-BMI repos trace back to this line of work.

Fit for FWM:

- Conceptually relevant, but face-only and old.
- Useful mainly as background, not a top implementation target.

### Region-aware face-BMI pooling

Link: https://arxiv.org/abs/2104.04733

What it is:

- BMI estimation from facial images using semantic face segmentation and region-aware pooling.
- Evaluated on VisualBMI, Bollywood, and VIP attributes datasets.

Fit for FWM:

- Better method family than plain whole-face embeddings, but I did not find an immediately polished runnable repo during this pass.
- If we build our own face-visible pipeline, this informs architecture choices.

### PatchBMI-Net

Link: https://arxiv.org/abs/2311.18102

What it is:

- Lightweight facial patch-based BMI ensemble for mobile deployment.
- Reports BMI MAE in the range 3.58 to 6.51 across BMI-annotated facial datasets, with about 3.3M parameters.

Fit for FWM:

- Relevant only for face-visible photos.
- No clear public weights found in this pass.

### PhotoScan / smartphone body composition phenotyping

Link: https://arxiv.org/abs/2603.27017

What it is:

- Smartphone imagery method for body composition rather than weight.
- Estimates body fat percentage and fat distribution proxies against DXA.
- Uses UK Biobank and clinical cohorts.

Reported performance:

- BF% MAE around 2.15% in the paper abstract.

Availability:

- I did not find public code/model weights in this pass.

Fit for FWM:

- Scientifically relevant, but not immediately usable.
- Could be useful if code appears later or if commercial access exists.

### Celeb-FBI

Link: https://arxiv.org/abs/2407.03486

What it is:

- Full-body celebrity image dataset with age, gender, height, and weight.
- 7,211 full-body images.
- Paper reports classification-style accuracy for age/gender/height/weight using CNN, ResNet-50, and VGG-16.

Fit for FWM:

- Relevant as a dataset/paper, not a plug-and-play model.
- It uses celebrity images and likely binned targets, so it may not transfer well to FWM review-photo regression.

### SHAPY

Links:

- Paper: https://arxiv.org/abs/2206.07036
- Project noted in abstract: https://shapy.is.tue.mpg.de

What it is:

- 3D body shape regression from a single RGB image using metric and semantic attributes.
- Focuses on estimating body shape under clothing/fashion imagery.

Fit for FWM:

- Potentially relevant for extracting shape features, not direct weight.
- More complex setup and likely heavier dependencies.
- Could be a second-wave experiment if direct BMI/weight models are insufficient.

### Shape of You

Link: https://arxiv.org/abs/2304.07389

What it is:

- Improves 3D body shape estimation for diverse body types and clothing recommendation use cases.

Fit for FWM:

- Relevant to body-shape features and fashion use cases.
- Not a direct weight estimator.

### Two-view body measurements from frontal/side images

Link: https://arxiv.org/abs/2205.14347

What it is:

- Estimates 3D body shape and clothing measurements from frontal and side-view images using silhouettes.

Fit for FWM:

- Good conceptual match for guided scans; weaker match for arbitrary review photos.
- Could inform a future feature pipeline if we can detect front/side-ish full-body images.

## Lower-priority GitHub finds

### metha-shankar/Weight-Estimation

Link: https://github.com/metha-shankar/Weight-Estimation

What it is:

- Small 2026 GitHub repo describing a human body weight estimation system using segmentation, object detection, feature extraction, and regression.
- Contains a notebook and PDF report.

Fit for FWM:

- Too small/unclear to be a top candidate, but worth quick inspection if we want ideas for handcrafted/segmentation features.

### jankit311/Face_to_BMI

Link: https://github.com/jankit311/Face_to_BMI

What it is:

- Older notebook repo: "Show me your face and I will tell your height, weight and body mass index."

Fit for FWM:

- Low priority. Face-only, older, no obvious production-quality model.

### tonyzzzzz/FaceToBMI and other small Face-to-BMI repos

Examples:

- https://github.com/tonyzzzzz/FaceToBMI
- https://github.com/tocodeat/Face2BMI
- https://github.com/shuklkj/BMI-prediction-using-VGG-Face

Fit for FWM:

- Mostly small demos, old notebooks, Flask apps, or low-star repos.
- Useful as references, not as primary benchmark candidates.

## Hugging Face findings

Hugging Face search for `BMI` was noisy because many unrelated model IDs contain the substring `bmi`.

Useful/possibly useful:

- `boretsyury/MeFEm`: real anthropometric face embedding model with public `.pth.tar` weights.
- `DriveMyScream/Gender_Age_BMI_Prediction`: Keras model with zero downloads; low confidence.

Not found:

- No credible public full-body, arbitrary-photo, weight/BMI predictor with a standard Hugging Face pipeline.
- No obvious hosted Digital Scale checkpoint.

## Commercial/API landscape

### 3DLOOK

Link: https://3dlook.ai/

Most directly relevant commercial option. Explicitly advertises weight prediction, BMI verification, body composition, clothing detector, pose validation, SDK/API integration, and health/fitness use cases.

### Bodygram

Link: https://www.bodygram.com/en

Advertises smartphone scanning, 35 body measurements, body composition such as body fat and muscle mass, and posture analysis. Strong for body measurement/body composition; less explicit than 3DLOOK about weight prediction.

### Sizer

Link: https://sizer.me/

AI body measurement and fashion sizing product. Relevant for measurements/sizing, but not obviously a weight estimator.

### MySize

Link: https://mysizeid.com/

AI-driven apparel sizing/digital experience platform. Relevant for sizing but not obviously a weight estimator.

### MyBVI / BVI

Search result/source: https://www.the-sun.com/health/12627454/phone-app-mybvi-body-scan-risk-stroke-diabetes/

Relevant body-volume/body-composition concept using front/side smartphone images. Appears consumer/commercial, not a downloadable model. Useful as market/tech context, not a local benchmark.

## Product/privacy constraints for FWM

1. Guessed weights should remain internal ranking features only. They should not be displayed as user facts.
2. If using commercial APIs, we need to review vendor terms, image retention, and whether sending user-submitted images is allowed.
3. Face-based models raise extra sensitivity: faces may identify users, face visibility is inconsistent, and face-to-BMI has documented bias concerns in the literature. Treat face-derived weight signals as optional, quality-gated features, not universal predictions.
4. Evaluate by subgroup where possible: height range, self-reported size, product category, image source, crop/full-body quality, face-visible vs face-hidden, and likely gender category only if already present and allowed.
5. Report coverage separately from error. A model with 20 lb MAE on 15% of high-quality full-body photos may still be useful for ranking, but it is not a complete inference system.

## Recommended experimental plan

### Phase 1: benchmark direct/purpose-built models

1. Digital Scale:
   - Request weights/sample package.
   - Run inference on the current FWM eval sample.
   - Convert BMI to weight using self-reported height.
   - Track rejection/coverage from its person/posture filters.

2. face-to-bmi-vit:
   - Run face detector over current eval sample.
   - Benchmark only images where a face is large enough.
   - Convert BMI to weight using height.

3. MeFEm:
   - Use as face embedding model.
   - Train a simple ridge/gradient-boosting regressor on FWM train split with height and metadata.
   - Compare to face-to-bmi-vit and non-image baseline on the same face-visible subset.

### Phase 2: benchmark stronger generic/full-body features

The first experiment used ImageNet CNN features and did not beat the best tabular baseline. Next feature candidates should be more aligned to apparel/person/body imagery:

- DINOv2 embeddings on full image and person crop.
- CLIP/OpenCLIP embeddings on full image and person crop.
- FashionCLIP if easy to run.
- YOLO/person segmentation features: bounding box height/width ratio, person area ratio, pose/keypoint visibility, crop quality.

Evaluate each model against:

- height-only baseline,
- height + self-reported size/category/source baseline,
- image-only,
- image + height,
- image + height + metadata.

### Phase 3: train our own model if needed

Training our own starts to make sense if:

- Digital Scale weights are unavailable,
- Digital Scale rejects too many FWM images,
- Digital Scale/face models do not beat the metadata baseline,
- generic foundation embeddings plus height improve meaningfully but remain underfit,
- enough labeled images remain after quality filtering.

Likely custom model path:

1. Build person/face/full-body quality labels automatically using YOLO/keypoints/face detection.
2. Train separate regressors for:
   - full-body/person-crop images,
   - torso/mirror images,
   - face-visible images,
   - no-useful-person-signal images.
3. Predict BMI instead of pounds where height exists; predict weight directly only when height is missing.
4. Calibrate uncertainty and use only high-confidence estimates as search-ranking features.

## Ranking of candidates

1. Digital Scale: best open/research fit if weights can be obtained.
2. 3DLOOK: best commercial fit if API evaluation is acceptable.
3. face-to-bmi-vit: best public face-BMI repo.
4. MeFEm: promising face embedding baseline, especially for training our own downstream regressor.
5. DINOv2/OpenCLIP/FashionCLIP on person crops: best generic feature direction after purpose-built models.
6. SHAPY/3D body shape models: potentially useful but heavier and indirect.
7. Small GitHub demos: inspect only if they contain usable checkpoints or simple feature ideas.

## Decision implication

We have done enough research now to say there is no abundant market of mature, downloadable, general-purpose "weight from arbitrary user photo" models. There are credible BMI/weight-adjacent systems, but each has a caveat:

- Digital Scale: best match, but weights must be requested.
- 3DLOOK: relevant and likely good, but commercial/API.
- Face-to-BMI: runnable, but only face-visible subset.
- SHAPY/body-shape models: useful features, not direct weight.
- Hugging Face: no strong full-body plug-and-play model found.

So the most evidence-driven next step is not to keep hunting indefinitely. It is to benchmark Digital Scale if weights are obtainable, benchmark face-BMI on face-visible photos, and then decide whether a FWM-specific model trained on our self-reported weight/height data is justified.
