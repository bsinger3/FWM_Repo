# Image Approval Context

This document summarizes the repo context for deciding whether an image is okay
to show on Friends With Measurements, especially for computer vision work.

## Product Purpose

Friends With Measurements helps shoppers find clothing that fits by showing
real product photos from people with similar body measurements.

The site is built around photos of shoppers wearing clothing, paired with sizing
and measurement context such as height, weight, bust, waist, hips, cup size, and
ordered size.

Relevant repo sources:

- `README.md`: The project explores clothing fit, sizing, and measurements.
- `about.html`: The site shows real product photos from people with similar
  body measurements.
- `about.html`: Images and measurements come from publicly available product
  review pages on retailer websites.
- `privacy.html`: The site shows product photos and sizing details collected
  from public retailer pages.
- `terms.html`: Product images and pages belong to their respective retailers.

## Hard Data Requirements

An image card should not be shown unless the record has the minimum data needed
to be useful and clickable.

The frontend skips a result unless it has:

- A non-empty image URL: `original_url_display`
- A valid size: `size_display`, not blank and not `unknown`
- At least one body measurement:
  - `height_in_display`
  - `weight_display_display`
  - `bust_in_number_display`
  - `hips_in_display`
  - `waist_in`
- A product link:
  - `monetized_product_url_display`, or
  - `product_page_url_display`

The database also enforces:

- `original_url_display` must not be blank.
- At least one product URL must be present.
- `size_display` is required.

Relevant repo sources:

- `index.html`: `render()` skips cards without size, image, body measurement,
  or product link.
- `supabase/migrations/20260413141641_remote_schema.sql`: constraints require
  an original image URL and at least one product URL.
- `database.types.ts`: documents the current `images` table shape.

## Link And Loading Behavior

Images are loaded through the configured image proxy first:

- `window.IMAGE_PROXY = "https://fwm-proxy.bsinger3.workers.dev/?url="`

If the proxied image fails, the frontend retries the original image URL. If that
also fails, the image is hidden.

Relevant repo sources:

- `config.js`
- `index.html`
- `privacy.html`

## User Report Signals

The site lets users report image cards. These report reasons are the clearest
repo-backed signals for what can make an image unacceptable after ingestion:

- `duplicate_image`
- `incorrect_data`
- `image_not_helpful`
- `dead_link`
- `sold_out`
- `other_link_problem`

The visible UI labels are:

- Duplicate image
- Incorrect measurements/category/size
- Image not helpful
- Dead link
- Sold out
- Other link problem

Relevant repo sources:

- `index.html`
- `supabase/migrations/20260419010000_add_image_reports.sql`

## Computer Vision Decision Boundary

The repo does not contain an active CV approval pipeline script, but it does
contain CV-related assets and local review samples:

- `yolov8n.pt`
- `yolov8n-pose.pt`
- `archive.image_vectors` schema with a 768-dimension embedding column
- `data-pipelines/amazon/data/step_4_human_review_and_visibility_decisions/review_queue/part_002_only_optimized_combined_review_queue_ANNOTATED.xlsx`
- `.codex_tmp/sample_sheets/approved_sample.jpg`
- `.codex_tmp/sample_sheets/not_approved_sample.jpg`
- `.codex_tmp/disagreement_sheets/*`

Based on the site purpose, report reasons, and local sample sheets, the practical
approval boundary appears to be:

### Approve

Approve an image when it is useful for judging how clothing fits on a real body.

Good approval candidates usually have:

- One main person or shopper.
- The person is wearing the reviewed clothing.
- The full product being reviewed is visible enough to judge fit.
- The product being reviewed is identified from the product link and its
  descriptive words, not from anything the user can infer from the image alone.
- The image is not just a tag, label, flat-lay, product catalog image, or tiny
  detail.

Low body coverage can still be acceptable when the visible crop is useful for
fit. For example, a waist/hip crop of jeans can be useful if it clearly shows
how the reviewed product fits.

### Reject

Reject an image when it is not useful or creates ambiguity for fit matching.

Common rejection cases:

- No person visible.
- Product-only image, flat-lay, tag, label, packaging, measuring tape, or fabric
  close-up.
- Uploaded product catalog image, such as a professional product listing image
  that appears to show the catalog item rather than a shopper's review photo.
- Crop is too tight or too unrelated to understand fit.
- The product being reviewed is not visible enough.
- Image is duplicate of another accepted image.
- Image has bad or mismatched metadata, such as wrong measurements, wrong
  category, or wrong size.
- Link is dead, sold out, or otherwise unusable.

## Annotated Review Queue

The annotated Amazon review workbook is a useful human-label source:

`data-pipelines/amazon/data/step_4_human_review_and_visibility_decisions/review_queue/part_002_only_optimized_combined_review_queue_ANNOTATED.xlsx`

It has one sheet, `part_002_only_optimized_combine`, with 999 data rows.

Important columns:

- `original_url_display`: image URL.
- `image_preview`: Excel `IMAGE()` formula previewing the image.
- `FacePresent?_GroundTruth (1=FacePresent,2=NoFace)`: sparse face label.
- `Manul_approval(1=approved,2=reject, 3=ApprovedANDLabel'Pretty")`: main
  human approval label.
- `Rejection Reason`: free-text human rejection reason.
- `cv_reason_summary`: CV reason summary.
- `cv_decision`: CV decision.
- `cv_reason_code`: CV reason code.
- `has_face_yunet`: face detector output.
- `person_count_yolo_detect`: YOLO person count.
- `main_person_height_pct_yolo_detect`: main person height as percent of image.
- `main_person_bbox_area_pct_yolo_detect`: main person box area as percent of
  image.
- `body_coverage_score_yolo_pose`: pose/body coverage score.

Manual label counts in this workbook:

- `1`: approved, 260 rows.
- `2`: rejected, 419 rows.
- `3`: approved and label as "Pretty", 28 rows.
- blank: unlabeled, 292 rows.

CV status in this workbook:

- `cv_decision` is mostly `REVIEW`, not a final approve/reject label.
- Common CV reason summaries are:
  - `Body visibility is borderline`: 804 rows.
  - `Person size is borderline`: 68 rows.
  - `Required CV data missing`: 12 rows.
  - `Composition is borderline`: 8 rows.
  - `Borderline framing and no face detected`: 2 rows.

Common human rejection reasons include:

- Figure/person too far away from the camera.
- Image too dark.
- Image URL is not valid.
- Bad angle.
- Too cluttered.
- Top of jeans or relevant garment is covered.
- Needs crop.
- Figure too small.
- No human.
- Rotation is incorrect.
- Garment cut off or not fully visible.

Metric patterns from the labeled rows:

- Approved rows all had `person_count_yolo_detect = 1`.
- Rejected rows mostly also had `person_count_yolo_detect = 1`, so person count
  alone is not enough.
- Approved rows had median `main_person_height_pct_yolo_detect` around `0.943`.
- Rejected rows had median `main_person_height_pct_yolo_detect` around `0.875`.
- Approved "Pretty" rows had lower person height and bbox-area medians, but all
  had face detected and strong pose/body coverage.
- Many accepted rows did not have a detected face, so face detection should not
  be required for normal approval.
- Rejection is often driven by human-visible usefulness issues that CV metrics
  only partially capture: darkness, angle, clutter, crop, and whether the
  garment itself is visible.

## Part 001 Rejection Reasons

Part 001 includes a backup CSV with explicit rejection reasons:

`data-pipelines/amazon/data/step_4_human_review_and_visibility_decisions/manual_chunks/backup/images_to_approve_part_001_SORTED_FacialDetectionGT_RejectionReasons1.csv`

It has 3,000 rows:

- Approved: 1,908 rows.
- Rejected: 1,092 rows.
- Rows with nonblank rejection reason text: 27.
- Exact unique rejection reason strings: 16.

Exact unique rejection reasons:

- `Too many people in the shot`
- `Too many people on the shot`
- `Figure is too far away from the camera`
- `The black bar at the top and bottom makes this picture look odd, and it won't fit in with the catalog`
- `The lighting is too dark and grainy for us to see the garment`
- `This is a man wearing men's clothing, and so far the website only supports women's clothing`
- `This is at a weird angle, and we can't really see how the pants fit`
- `There are two people in this shot, and we don't know which one is wearing the clothing item we're interested in`
- `Too many people in this shot; we don't know who is wearing the garment of interest`
- `The bottom of the pants is cut off`
- `Two people in this shot. We don't know who is wearing the garment of interest`
- `We can't see the entire garment`
- `The bottom of the pants is cut off, and since this review is for pants, that won't work. This image would work if the review is for a top because the entire top is visible`
- `This is a review for pants, and the bottom of the pants is cut off, so we can't see how they fit`
- `This has two people in the shot, but since one of them is a man, we can assume that it's the woman wearing the garment of interest, so this one is actually okay`
- `Background removed or turned white, which would look odd with the rest of the catalog`

Canonical rejection categories represented by those reasons:

- Too many people if the reviewed product cannot be assessed clearly.
- Person/figure too far away.
- Product/body cropped or reviewed product not fully visible.
- Too dark or grainy to see the garment.
- Bad angle for judging fit.
- Visual formatting inconsistent with catalog, such as black bars or removed
  white background.
- Uploaded catalog-style product image rather than a shopper review photo.
- Unsupported clothing/audience category, specifically men's clothing when the
  site only supports women's clothing.

One note: one exact reason says the image is "actually okay" despite two people.
Treat that as an exception case: multiple people are not automatically a reject
if the reviewed product is still fully visible and useful for judging fit.

## Practical CV Checks

A computer vision classifier or review pipeline should likely check:

- Person detection: is there a person in the image?
- Person count/composition: do multiple people prevent assessing the reviewed
  product clearly?
- Clothing-on-body: is clothing being worn, not merely photographed?
- Product-link grounding: use the product link's descriptive words to determine
  which product is being reviewed.
- Reviewed-product visibility: is the full reviewed product visible enough?
- Catalog-image detection: does the image look like an uploaded product catalog
  item instead of a shopper review photo?
- Fit usefulness: can a shopper infer fit from the crop?
- Duplicate detection: compare `hash_md5` and/or embeddings.
- Image fetch health: status code, content type, bytes, dimensions, and load
  success.
- Link health: product URL exists and resolves.
- Metadata completeness: size plus at least one body measurement.

## Upstream Product URL Clothing Type Assignment

An upstream product-metadata enrichment step should assign `clothing_type_id`
from the product URL before image approval or CV review begins. This gives later
image review steps a grounded answer to "what product is being reviewed?"

Current clothing type IDs seen in the Amazon review chunks:

- `jeans`
- `pants`
- `dress`
- `top`
- `other`
- `overalls`
- `swimsuit`
- `jumpsuit`
- `shorts`
- `skirt`
- `shirt`
- `bra`
- `bikini`
- `coverup`
- `capris`
- `jacket`
- `tank`
- `romper`
- `sweater`
- `bodysuit`

Use this procedure:

1. Choose the source URL.

Use `product_page_url_display` first. If it is blank and only
`monetized_product_url_display` is present, decode the redirect URL and use its
embedded retailer URL parameter.

2. Extract descriptor text from the URL.

For Amazon URLs, use the readable slug before `/dp/` when present:

`https://www.amazon.com/Levis-Womens-Original-Medium-Regular/dp/B09Z22WPMG/...`

Descriptor text:

`Levis Womens Original Medium Regular`

If the URL is only `/dp/<ASIN>` with no readable product slug, do not invent a
type from the URL. Keep the existing `clothing_type_id` if present; otherwise
route to manual/product metadata enrichment.

3. Normalize descriptor text.

- URL-decode percent encoding.
- Lowercase.
- Replace punctuation, hyphens, underscores, and plus signs with spaces.
- Collapse repeated whitespace.
- Split into word tokens.
- Remove color, size, brand, and generic commerce words when they are not useful
  for category assignment, such as `women`, `womens`, `ladies`, `plus`, `size`,
  `pack`, `amazon`, `essentials`, `original`, `medium`, `regular`.

4. Apply high-precision keyword rules in priority order.

Priority matters because some product names contain multiple clothing words.
Assign the first matching category:

| clothing_type_id | Match descriptors |
| --- | --- |
| `overalls` | `overall`, `overalls`, `bib overall`, `shortall` |
| `jumpsuit` | `jumpsuit`, `jumpsuits` |
| `romper` | `romper`, `rompers` |
| `bikini` | `bikini`, `two piece swimsuit`, `2 piece swimsuit`, `two piece bathing suit` |
| `swimsuit` | `swimsuit`, `swim suit`, `one piece swimsuit`, `bathing suit`, `monokini` |
| `coverup` | `cover up`, `coverup`, `swim cover`, `beach cover` |
| `dress` | `dress`, `dresses`, `gown`, `maxi dress`, `mini dress`, `midi dress`, `sundress` |
| `skirt` | `skirt`, `skirts`, `skort` |
| `shorts` | `shorts`, `bermuda`, `bike shorts`, `biker shorts` |
| `capris` | `capri`, `capris`, `cropped pants`, `cropped leggings` |
| `jeans` | `jean`, `jeans`, `denim jean`, `skinny jeans`, `straight jeans`, `bootcut jeans`, `wide leg jeans` |
| `pants` | `pant`, `pants`, `trouser`, `trousers`, `slacks`, `legging`, `leggings`, `jogger`, `joggers`, `sweatpants`, `palazzo`, `cargo pants` |
| `bodysuit` | `bodysuit`, `body suit` |
| `bra` | `bra`, `bralette`, `sports bra` |
| `tank` | `tank`, `tanktop`, `tank top`, `camisole`, `cami` |
| `sweater` | `sweater`, `cardigan`, `pullover` |
| `jacket` | `jacket`, `coat`, `blazer`, `shacket` |
| `shirt` | `shirt`, `tee`, `t shirt`, `tshirt`, `blouse`, `button down`, `button up` |
| `top` | `top`, `crop top`, `halter`, `tunic` |

5. Resolve ambiguous matches.

- If `jeans` and `pants` both match, assign `jeans`.
- If `bikini` and `swimsuit` both match, assign `bikini`.
- If `coverup` and `dress` both match, assign `coverup` when swim/beach words
  are present.
- If `jumpsuit` or `romper` matches, do not assign `top` or `pants` even if the
  descriptor includes those words.
- If only broad/generic words match, such as `clothing`, `apparel`, `outfit`, or
  `set`, assign `other` or route to manual review.

6. Validate the output.

The assigned value must match an existing `public.clothing_types.id`. If no
high-confidence rule matches, leave `clothing_type_id` blank or set `other`,
depending on downstream requirements, and mark the row for product metadata
review.

7. Store provenance for auditability.

When possible, store or log:

- source URL used
- normalized descriptor text
- matched keyword
- assigned `clothing_type_id`
- confidence level, such as `high`, `medium`, or `manual_needed`

### Procedure Update Plan From Annotated Review

The annotated product-link review showed that the first-pass URL keyword rules
were too literal. Many Amazon product slugs identify jeans with style words
instead of the word `jeans`, for example `totally shaping`, `high rise`,
`straight`, `bootcut`, `skinny`, `barrel`, `boyfriend`, and `sculpting`.

Update plan:

1. Decide the category taxonomy before changing the automated assignment.

The annotated file used categories that are not currently in the known site list:

- `jeggings`
- `jegging`
- `leggings`
- `belt`
- `belt buckle`

Before implementation, decide whether these should become real
`public.clothing_types.id` values or be mapped into existing IDs such as
`pants`, `jeans`, or `other`.

2. Normalize singular/plural category variants.

If `jeggings` becomes a supported ID, normalize `jegging` to `jeggings`.
If it does not become supported, map both `jegging` and `jeggings` to the chosen
fallback category.

3. Add jeans-specific style descriptors.

Add high-confidence jeans rules for product slugs that include combinations of
denim/jeans brand or style terms, including:

- `skinny`
- `straight`
- `bootcut`
- `barrel`
- `boyfriend`
- `high rise`
- `mid rise`
- `ribcage`
- `marilyn`
- `aero rise`
- `totally shaping`
- `sculpting`
- `legendary stretch`

These should assign `jeans` when the URL/source context indicates denim bottoms
and no stronger category, such as `pants`, `leggings`, or `jeggings`, applies.

4. Add explicit legging/jegging rules.

If supported by taxonomy:

- `jegging`, `jeggings`, `pull on skinny`, and `denim legging` should map to
  `jeggings`.
- `legging`, `leggings`, and non-denim `pull on` bottomwear should map to
  `leggings` or `pants`, depending on the taxonomy decision.

5. Add accessory detection.

If the product slug clearly describes `belt` or `belt buckle`, either assign the
new accessory category or route to manual review/rejection if accessories are out
of scope for the website.

6. Use ASIN-level enrichment.

The Step 4 review rows often contain only `/dp/<ASIN>` URLs. The enrichment step
should join those ASINs back to richer Step 1 URLs or product metadata before
classification. If no richer slug/title is available, keep the row as
`manual_needed` rather than guessing from review text.

7. Capture product name and description during scraping.

When scraping retailer pages, store the product name/title and, when available,
the product description or bullet-style product details. URLs are not guaranteed
to contain descriptive category words. Some Amazon review links collapse to
`/dp/<ASIN>`, and even richer slugs can omit the actual clothing noun.

The upstream category assignment should prefer sources in this order:

1. Explicit product metadata from the retailer page:
   - product name/title
   - product subtitle, if present
   - product description
   - product detail bullets
2. Rich product URL slug.
3. Existing trusted `clothing_type_id`, if already populated.
4. Manual metadata review.

Do not rely on review text to infer the product category unless the workflow is
explicitly marked as low-confidence/manual-assisted. Review text often mentions
other garments, styling ideas, or comparisons that are not the reviewed product.

8. Keep an audit trail.

For each assigned category, write the source URL, ASIN, descriptor text, matched
rule, assigned category, and confidence. This makes it easy to create another
review workbook and refine the rules without losing why a category was chosen.

## Key Principle

An acceptable image is not merely an image of clothing. It should be a useful
visual reference for how clothing fits on a real shopper with known measurement
context.
