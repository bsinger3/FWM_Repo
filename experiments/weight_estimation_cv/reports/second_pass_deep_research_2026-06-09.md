# Second-pass deep research: overlooked weight/BMI/body-composition CV leads

Date: 2026-06-09

This is a second, broader internet research pass after the initial Digital Scale / face-to-BMI / commercial body-scan sweep. I searched less-obvious areas: anthropometric estimation, body-composition models, virtual fitting and body-measurement APIs, insurance/wellness use cases, 3D body-shape models, and GitHub repos that predict height/weight/BMI as side features.

## Executive summary

New useful leads from this pass:

1. `abhaymise/Face-to-height-weight-BMI-estimation-`: an older Apache-licensed GitHub repo with actual serialized `height_predictor.model`, `weight_predictor.model`, and `bmi_predictor.model` files. It is probably weak because it is trained on manually collected Bollywood celebrity face images, but it is concrete and easy to benchmark.
2. `Human-Attributes-Estimation`: a small selfie-based height/weight/age/gender repo using MobileNetV2. It does not appear to include trained weights, but confirms the selfie/portrait direction and could supply architecture ideas.
3. BodyM / Adversarial BodySim: a serious dataset/paper for estimating body measurements from frontal/lateral silhouettes, with height and weight included. This is more useful for training/fine-tuning our own model than for off-the-shelf inference.
4. Photo/body-fat literature: body-fat/body-composition from front images or smartphone photos is adjacent and may be useful as a proxy-feature direction, especially where people report body fat or body shape, but most papers do not provide runnable weight models.
5. Insurance/adversarial BMI papers: visual BMI is considered realistic enough in insurance/wellness contexts that adversarial-attack papers discuss it, which is useful evidence that the signal exists but also that it can be fragile/manipulable.
6. Commercial products: 3DLOOK remains the only clearly advertised weight-prediction vendor; Bodygram is the next most relevant because it has API/SDK positioning and body-composition claims, though it may rely on user-provided height/weight in some flows.

No newly found source displaces Digital Scale as the top target. The main update is that we should add one quick benchmark track for old/small face-to-height/weight/BMI repos, and one dataset/modeling track for BodyM/silhouette/body-measurement methods.

## Newly found actionable GitHub candidates

### 1. Face-to-height-weight-BMI-estimation

Link: https://github.com/abhaymise/Face-to-height-weight-BMI-estimation-

Why it matters:

- It directly tries to predict height, weight, and BMI from a face image.
- It includes actual serialized model files:
  - `height_predictor.model`
  - `weight_predictor.model`
  - `bmi_predictor.model`
- Apache-2.0 license.
- 21 stars / 19 forks by GitHub API metadata.

Important caveats:

- README says the author manually collected 5-20 images of Bollywood celebrities and labels from public forums.
- That is a tiny, celebrity-biased, likely noisy dataset.
- It is face-only, so it will only apply to FWM images with visible faces.
- The model files are small, suggesting a classic face embedding + shallow regressor workflow, not a robust modern visual model.

Suggested experiment:

- Download the repo into the isolated experiment directory.
- Run face detection on our eval sample.
- Try its weight predictor only on face-visible images.
- Compare to:
  - height/metadata baseline on the same subset,
  - `face-to-bmi-vit`,
  - MeFEm embeddings + FWM-trained regressor.

Expected value:

- Low production confidence, but very cheap to test. If it performs badly, that is still useful evidence against small public face-weight demos.

### 2. Human-Attributes-Estimation

Link: https://github.com/akashkanumetta/Human-Attributes-Estimation

Why it matters:

- Selfie/portrait model predicting height, weight, age, and gender from one image.
- Uses MobileNetV2 feature extraction and multi-output prediction.
- The use case overlaps with "we have a user-submitted photo but not weight."

Important caveats:

- Tiny repo, zero stars.
- I did not see trained model weights in the repository contents.
- It may train from filenames that encode labels; likely not immediately usable.
- Includes gender prediction; avoid using sensitive/demographic attributes unless there is a clear policy reason and measured benefit.

Suggested experiment:

- Not worth prioritizing as-is.
- Mine for architecture/preprocessing ideas only if we train our own selfie/face-visible model.

### 3. metha-shankar/Weight-Estimation

Link: https://github.com/metha-shankar/Weight-Estimation

Why it matters:

- Claims human body weight estimation from images using segmentation, object detection, feature extraction, and regression.
- Has a notebook and report PDF.

Important caveats:

- No obvious reusable weights or polished package.
- Zero stars at discovery.
- Likely student/project prototype.

Suggested experiment:

- Low priority. Inspect notebook only if we want feature-engineering ideas after testing stronger candidates.

## Academic / dataset leads that were easy to overlook

### 1. BodyM / Adversarial BodySim

Links:

- Paper: https://arxiv.org/abs/2210.05667
- Project/data page: https://adversarialbodysim.github.io/
- Amazon Science page: https://www.amazon.science/publications/human-body-measurement-estimation-with-adversarial-augmentation

What it is:

- Human body measurement estimation with adversarial augmentation.
- BodyM dataset contains 8,978 frontal and lateral silhouette images of 2,505 identities.
- Labels include height, weight, gender, and 14 body measurements.
- Built around estimating measurements from silhouette pairs, then using synthetic/adversarial augmentation to handle body-shape diversity.

Why it matters for FWM:

- This is probably the most relevant overlooked dataset for training our own model.
- It is not arbitrary apparel review photos, but it does include height and weight labels paired with frontal/lateral body silhouettes.
- The silhouette framing may transfer better than face-only BMI models if we can segment the person from FWM images.

Limitations:

- Not a ready public "weight predictor" model for arbitrary images.
- Requires a pipeline: person segmentation, silhouette/crop extraction, then train/fine-tune a model.
- Dataset domain is controlled silhouettes, not messy review photos.

Suggested experiment:

- If the data is accessible, use BodyM as pretraining or auxiliary data for person-crop/silhouette weight estimation.
- Compare a FWM-only model vs BodyM-pretrained/FWM-finetuned model.

### 2. Estimation of BMI from photographs using semantic segmentation

Link: https://arxiv.org/abs/1908.11694

What it is:

- Uses photographs of 161 people to estimate BMI using semantic segmentation.
- Reports high correlation between BMI and estimates based on segmented body geometry.

Why it matters:

- Supports a non-face route: segmentation/silhouette features can contain BMI/weight signal.
- Useful architectural clue for FWM because apparel review photos often show body outline/clothing silhouette even when faces are hidden.

Limitations:

- Small dataset.
- No obvious public model weights found.

Suggested experiment:

- Add segmentation-derived features: person mask area, width/height ratio, body-part ratios, visible-body coverage, pose/keypoint-derived shape metrics.
- Feed those into a regressor along with height and category/size metadata.

### 3. Digital Scale, revisited through arXiv API

Link: https://arxiv.org/abs/2508.20534

Why it still matters:

- ArXiv query for `"BMI estimation" AND "image"` returned Digital Scale and MeFEm as the only two direct recent arXiv hits.
- The Digital Scale abstract itself says prior CV approaches were limited to datasets of up to 14,500 images, while Digital Scale used 84,963 smartphone images from 25,353 individuals.

Status:

- We already emailed the authors/team for model weights.
- Still the top direct target.

### 4. MeFEm, revisited

Links:

- Paper: https://arxiv.org/abs/2602.14672
- Hugging Face: https://huggingface.co/boretsyury/MeFEm

Why it still matters:

- ArXiv API confirms it is one of the only direct recent BMI/image papers surfaced by query.
- Public weights exist.
- It is face embedding rather than plug-and-play full-body BMI.

Suggested experiment:

- Use it as a face embedding model, not as the only estimator.
- Train a regressor on FWM ground truth for face-visible images.

### 5. Multimodal AI for Body Fat Estimation

Link: https://arxiv.org/abs/2511.17576

What it is:

- Estimates body fat percentage from frontal body images and anthropometric data.
- Dataset includes 535 samples, including Reddit images with self-reported body-fat percentages and some DEXA-derived claims.
- Image model reportedly achieved RMSE 4.44 percentage points and R2 0.807.

Why it matters:

- It is not weight prediction, but it shows that front-body images can support body composition inference.
- Useful as a proxy path: estimate body fat/body shape features, then combine with height and metadata to infer weight/BMI.

Limitations:

- Not a weight model.
- Very small dataset.
- No obvious public code/weights found in this pass.

### 6. PhotoScan / smartphone body-composition phenotyping

Link: https://arxiv.org/abs/2603.27017

Why it matters:

- Smartphone-image body composition model evaluated against DXA-style targets.
- Strong adjacent evidence that camera images can estimate body composition, not just rough BMI.

Limitations:

- No public implementation found.
- More health/clinical than fashion/search.

### 7. Fooling Computer Vision into Inferring the Wrong BMI

Link: https://arxiv.org/abs/1905.06916

Why it matters:

- This is not a model to use, but it shows BMI-from-face models were considered plausible enough for insurance use cases and adversarial-risk analysis.
- It warns that visual BMI estimates can be manipulated and should not be treated as authoritative.

FWM implication:

- If inferred weights become ranking signals, keep them low-confidence and internal.
- Add safeguards against over-reliance and track uncertainty/calibration.

### 8. MassNet / pressure image weight estimation

Link: https://arxiv.org/abs/2303.10136

What it is:

- Deep learning body-weight extraction from pressure images from a pressure mattress.

Why it matters:

- Not useful for FWM photos directly.
- Useful methodologically: pose-aware features + contrastive learning for body-weight regression.

Suggested value:

- Keep as a modeling idea only.

### 9. 3D depth/volume weight estimation

Link: https://arxiv.org/abs/2410.02800

What it is:

- Uses RealSense D415 depth maps, 3D model reconstruction, body volume, and height to estimate body weight.

Why it matters:

- Reinforces that volume + height is the core geometric route to weight.
- Not directly applicable to 2D review photos, but a useful conceptual target if we ever estimate 3D shape or body volume from monocular images.

## Commercial/product leads

### 1. 3DLOOK

Link: https://3dlook.ai/

Status:

- Still the strongest commercial candidate.
- Explicitly advertises weight prediction, BMI verification, body composition, pose validation, clothing detection, SDK/API integration, and 2-photo capture.

FWM fit:

- Worth contacting if we want a commercial API benchmark.
- Key question: can they process existing arbitrary apparel/review photos, or only guided front/side capture?

### 2. Bodygram

Link: https://www.bodygram.com/en

Why it matters:

- Offers body measurements, body composition, API/SDK positioning, insurance/wellness use cases, and AI body scanning.
- This is closer to FWM than pure fitness apps because it intersects apparel sizing and health/body composition.

Caveat:

- Some Bodygram flows appear to generate scans from four data points including height and weight, or from two photos. If weight is required as input in a given mode, it cannot solve our missing-weight problem.

Suggested action:

- Contact Bodygram only after clarifying whether their API can infer weight/body composition from images when weight is missing.

### 3. MyBVI / Body Volume Index products

Example source: https://www.the-sun.com/health/12627454/phone-app-mybvi-body-scan-risk-stroke-diabetes/

Why it matters:

- Consumer app uses front/side photos to estimate body volume/body-fat style risk measures.
- Strong evidence that body-shape-from-photo products exist outside academic CV.

Caveat:

- Not a downloadable model.
- Not clearly an API for batch use.
- Consumer-health framing; terms/privacy likely restrictive.

### 4. Fit3D, Size Stream, Sizer, MySize, TrueToForm, Nettelo

General finding:

- These are relevant for body scans, body measurements, virtual fitting, avatars, and size recommendation.
- In this pass, I did not find clear public claims that they provide downloadable or API-accessible weight prediction from existing arbitrary photos.

FWM fit:

- Useful for measurement/shape inference ideas.
- Lower priority than 3DLOOK and Bodygram for weight/BMI specifically.

## Lower-priority / not directly useful buckets

### Commercial insurance / underwriting

Searches around insurance and BMI surfaced that weight/BMI is important for underwriting, and that visual BMI has been discussed as an adversarial-risk target. But I did not find a clear commercial API that lets us upload user photos to predict weight/BMI for our use case.

### Hugging Face

Second-pass Hugging Face searches for:

- `weight estimation image`
- `body composition`
- `face BMI`
- `anthropometric`

returned no additional credible public models beyond MeFEm and the low-signal Keras BMI model found earlier.

### Animal/livestock weight estimation

There is a rich literature and GitHub ecosystem for cattle/pig/fish weight estimation from RGB/depth images. These methods use segmentation, body-length/area/volume proxies, and regression. I would not prioritize them for direct transfer, but they support the same modeling principle: segment the body, estimate geometry, regress mass.

If we train our own FWM model, livestock methods are a useful mental model for feature engineering:

- mask area and dimensions,
- body length/width ratios,
- multi-view if available,
- depth/volume if available,
- uncertainty by pose and occlusion.

## Updated candidate ranking after second pass

### Benchmark now / soon

1. Digital Scale, pending weights.
2. `face-to-bmi-vit` on face-visible subset.
3. MeFEm embeddings + FWM regressor on face-visible subset.
4. `abhaymise/Face-to-height-weight-BMI-estimation-`, because it has actual weight/BMI model artifacts and is cheap to test.
5. Stronger FWM-trained embeddings on person crops: DINOv2, OpenCLIP, FashionCLIP, YOLO/person crop features.

### Investigate for custom model training

1. BodyM / Adversarial BodySim dataset and silhouette estimation.
2. Segmentation-based BMI papers and silhouette geometry.
3. Body-composition papers as proxy-feature inspiration.
4. SHAPY/3D body-shape models as heavy second-wave feature extractors.

### Contact commercially if open-source options stall

1. 3DLOOK.
2. Bodygram.
3. MyBVI / Select Research if an API or research access exists.

## Concrete next experimental plan

1. Add a face-visible eval split:
   - Detect face presence/size on the current downloaded FWM images.
   - Report number and percent of images where face models are eligible.

2. Benchmark public face models:
   - `face-to-bmi-vit`.
   - MeFEm embeddings + simple FWM-trained regressor.
   - `abhaymise` direct weight/BMI predictors.

3. Add silhouette/person-crop features:
   - YOLO/SAM/person mask area ratio.
   - crop aspect ratio.
   - pose keypoint visibility.
   - rough body-width proxies at torso/hip/leg regions if keypoints are usable.

4. Re-rank against the same test split:
   - height-only baseline,
   - height + metadata baseline,
   - image features only,
   - image + height,
   - image + height + metadata,
   - face-only subset separately,
   - full/person-visible subset separately.

5. Decide whether to train:
   - If no external model beats metadata baseline on meaningful coverage, train FWM-specific models.
   - BodyM is the best discovered external dataset candidate for pretraining a silhouette/person-shape model.

## Conclusion

The second pass did uncover overlooked runnable and training-relevant options, but it did not uncover a hidden mature full-body open-source model better positioned than Digital Scale.

The biggest practical additions are:

- test the Apache-licensed `abhaymise` face-to-height/weight/BMI repo because it has weights,
- treat BodyM as a serious pretraining/auxiliary dataset candidate,
- view segmentation/silhouette geometry as the strongest non-face path,
- consider Bodygram alongside 3DLOOK if we want commercial evaluation,
- keep all visual weight estimates internal, probabilistic, and coverage-aware.

