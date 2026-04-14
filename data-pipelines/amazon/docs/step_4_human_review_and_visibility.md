# Step 4 Human Review And Visibility

Step 4 is the human review layer on top of the Step 3 machine-annotated image
review sheets.

Required approval column:

- Step 4 review sheets must contain a column named `Approved for publishing`

Human action:

- a human reviewer manually enters `1` in `Approved for publishing` for rows
  approved for publishing on the web

Working-sheet rule:

- the `Approved for publishing` column should appear immediately after the
  machine-generated review columns

Current state:

- some Step 4 material is still incomplete
- incomplete review comparison files belong in
  `data/step_4_human_review_and_visibility_decisions/incomplete_human_review_samples/`
- incomplete review samples should not be treated as final approval outputs

## Canonical Step 4 Review Sheet Format

The full Step 4 review-sheet set should be generated from the Step 3
machine-annotated outputs.

Canonical Step 4 review sheets should:

- preserve the row set from Step 3
- remove the blank unnamed column seen in the old partial sample file
- rename the machine-generated review columns into human-readable working names
- add the required `Approved for publishing` column immediately after the
  machine-generated review columns
- optionally keep a `Flag_errors` helper column for reviewer QA notes
- add an `exceeds_cap` column for search-visibility gating
- not use `Manual_keep? (1=keep,2=don'tkeep)` as the canonical approval field

## Step 3 To Step 4 Column Mapping

Step 3 machine-review columns should map like this:

- `has_person_REVIEWONLY` -> `has_person`
- `has_face_yunet_REVIEWONLY` -> `has_face_yunet`
- `lighting_ok_REVIEWONLY` -> `lighting_ok`
- `full_lower_body_visible_REVIEWONLY` -> `full_lower_body_visible`

Other columns should remain unchanged unless a later workflow change explicitly
requires a rename.

## Canonical Leading Column Order

The beginning of each generated Step 4 review sheet should be:

1. `created_at_display`
2. `id`
3. `original_url_display`
4. `has_person`
5. `has_face_yunet`
6. `lighting_ok`
7. `full_lower_body_visible`
8. `Approved for publishing`
9. `Flag_errors`
10. `exceeds_cap`
11. `product_page_url_display`
12. `monetized_product_url_display`
13. `height_raw`
14. `weight_raw`
15. `user_comment`
16. `date_review_submitted_raw`

After that point, preserve the remaining Step 3 columns in their existing order.

## Reviewer-Product Cap Rule

Step 4 should also decide whether an image row is eligible to appear in search
results.

The cap rule is:

- all rows should remain stored in the dataset
- cap search eligibility at 3 image rows per synthetic reviewer per product
- identify the reviewer conservatively from `reviewer_profile_url` plus
  normalized `comment_text`
- use `product_page_url_display` as the product grouping field
- mark rows outside the cap with `exceeds_cap = 1`
- rows marked `exceeds_cap = 1` should still be retained, but should not be
  returned in search results

## Reviewer Identity Heuristic

Because reviewer name fields and reviewer profile fields are often blank,
reviewer identity should be approximated rather than taken from a single source.

Suggested logic:

- normalize `reviewer_profile_url` into a stable profile key when present
- normalize `comment_text` into a stable text key when present
- if both exist, combine them into one synthetic reviewer identity
- if only one exists, use the available value
- if neither exists, do not auto-cap the row unless a later rule is added

The reviewer identity helper is primarily an internal calculation. It does not
need to become a human-facing Step 4 review column unless debugging later proves
that useful.

## Cap Selection Preference

When a reviewer-product group has more than 3 candidate image rows, the rows
inside the cap should be selected with this preference order:

1. rows with `has_face_yunet = true`
2. rows with `has_person = true`
3. rows with `lighting_ok = true`
4. rows with `full_lower_body_visible = true`
5. stable original row order as the final tie-breaker

This keeps the cap deterministic while favoring the most useful search-facing
images.

## Canonical Rule

For the full generated Step 4 review sheets:

- `Approved for publishing` is the one true approval column
- `Flag_errors` is allowed as a reviewer helper field
- `exceeds_cap` records search-result overflow rows that should still be stored
- the old sample-only manual keep field should not be part of the canonical
  generated Step 4 format
