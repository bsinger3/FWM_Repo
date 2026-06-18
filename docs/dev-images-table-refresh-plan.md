# Dev Images Table Refresh Plan

## Summary

Update the dev Supabase image data path so manually approved review images can be loaded now, while preserving enough product, review, crop, and CV metadata for backend and frontend iteration.

This plan is dev-only. Do not run production Supabase migrations, production RPC changes, production data loads, or active website deploys as part of this work.

Migration safety rule: do not add dev-only schema changes to any migration path that CI/CD might auto-apply to production. Confirm the deployment pipeline before creating migration files. Until that is verified, keep dev-only schema SQL in `supabase/dev-migrations/` or another explicitly excluded dev-only path, not in production-applied `supabase/migrations/`. Name dev-only SQL files `YYYYMMDD_dev_<short_name>.sql`, and add or verify a CI exclusion rule that prevents `supabase/dev-migrations/` from being applied to production.

Environment safety rule: every loader, backfill, status-audit, and dev migration runner must call a shared production guard before connecting. The guard must abort if `SUPABASE_URL` is unset, matches the production Supabase project URL, or is not in the explicit dev Supabase project ref/URL allowlist. A separate deliberate override is allowed only for future production promotion work, not for this dev plan.

The repo cleanup moved generated pipeline artifacts out of repo-root `outputs/`. The implementation should treat `../FWM_Data/` as the local data root and avoid writing generated review artifacts back into `FWM_Repo`.

## Current Data Layout

Use the cleaned data locations:

- Source review workbooks:
  `../FWM_Data/03_cv_annotated_pending_human_review/partial_170000_rows_cv_gated/`
- Human-reviewed return files:
  `../FWM_Data/04_human_reviewed_ready_to_publish/human_labeled_returns/`
- Deprecated repo-root output path:
  `outputs/`

The image-review dashboard already centralizes these defaults in `tools/image-review-dashboard/paths.mjs`:

- `FWM_DATA_DIR` overrides the sibling data root.
- `defaultImageReviewPackageDir()` resolves the source workbook package.
- `defaultImageReviewReturnsDir()` resolves the human-labeled returns directory.

Any new loader or helper script should reuse those helpers or follow the same environment variable convention.

## Current Review State

Snapshot counts from the cleaned `../FWM_Data` layout. Refresh these counts with the reconciliation dry-count pass immediately before running the loader:

- Manifest decisions: `41,968`
- Manifest approvals: `28,944`
- Manifest disapprovals: `13,001`
- Manual crop adjustments: `259`
- Mobile decision files: `54`
- Mobile decisions not yet merged into manifest: `10,796`
- Unmerged mobile approvals: `6,077`
- Unmerged mobile disapprovals: `4,719`

Before loading dev Supabase, reconcile the unmerged mobile decisions so the manifest is the source of truth for this load.

## Implementation Plan

### 1. Preserve Current Website Images In Dev

The dev environment must include every image currently visible through the active website before adding newly approved images.

Baseline approach:

- Take a read-only export or snapshot of the current production website's `public.images` table.
- Use `pg_dump --data-only` for the authoritative baseline export because it preserves UUIDs, native types, timestamps, nulls, and insert order.
- Export `public.images` with explicit column inserts and restore into the dev `public.images` table without regenerating IDs.
- Existing production `public.images.id` values must be preserved exactly in dev. This is required for analytics, reports, and frontend traceability, not best-effort.
- Treat Supabase dashboard CSV exports or custom JS/PostgREST exports as fallback options only. If a fallback export is used, document that ID/type/timestamp preservation is no longer guaranteed and do not treat that load as the authoritative traceability baseline.
- Record the production export timestamp, export method, source project/ref, row count, and checksum in a versioned baseline manifest.
- Treat the baseline as an as-of snapshot. Images added to production after the export timestamp may be absent from the dev baseline until the next baseline refresh.
- Do not modify the production Supabase project during this step.
- Load that baseline into the dev Supabase `public.images` table before inserting newly approved review rows.
- Preserve existing fields currently used by the live website and `match_by_measurements`, including image URL, product URL, monetized product URL, brand, source site, size, color, body measurements, review text, and existing timestamps.
- Add the new nullable columns in dev before or during the baseline load so existing website rows can remain valid without immediate backfills.
- After baseline load, run product-page staging refresh/backfill so existing website rows also receive `product_page_id` where product URLs are available.
- Create `public.reviews` rows for existing website images. When reliable review identity cannot be computed, use the deterministic one-image fallback key `baseline:<normalized_product_url>:<image_id>`.

Baseline manifest:

- Write one versioned manifest per production export under `../FWM_Data/_reports/`, for example `baseline_public_images_export_2026-06-15T143000Z.json`.
- Include `exported_at`, `source_supabase_project_ref`, `source_table`, `production_row_count`, `export_file_path`, `export_file_sha256`, `export_method`, `pg_dump_version`, and `notes`.
- Set `source_table` to `public.images` and `export_method` to `pg_dump --data-only` for the authoritative path.
- Include a note that production remains live and rows created after `exported_at` are out of scope for the current dev baseline.
- Before restore, verify that the export file exists, its SHA-256 matches `export_file_sha256`, the source table is `public.images`, and the source project ref is the expected non-sensitive production project identifier.

Verification:

- Compare production export count to dev loaded count.
- Compare production and dev sets of `id`, `original_url_display`, and normalized product URL.
- Confirm there are no production image IDs missing, changed, regenerated, duplicated, or mapped to different image URLs in dev.
- Treat any baseline ID-preservation failure as blocking. Expected failure causes are schema incompatibility, dump from the wrong project/table, an import path that omitted or regenerated `id`, conflicting pre-existing dev rows, or a partial restore.
- Confirm baseline export format and restore logs show UUIDs, timestamps, and nullable fields were preserved exactly.
- Confirm the baseline manifest records the export timestamp and explicitly accepts any production changes after that timestamp as out of scope for the current dev baseline.
- Confirm `match_by_measurements` in dev can return known current website images before the new approved rows are layered in.
- Keep the production export manifest/checksum in `../FWM_Data/_reports/`, not in repo-root `outputs/`.

### 2. Reconcile Manual Decisions

- Import all unmerged `fwm_mobile_review*.json` files from:
  `../FWM_Data/04_human_reviewed_ready_to_publish/human_labeled_returns/`
- Use the existing importer:
  `npm run image-review:import-mobile -- <decision-file>`
- If many files need import, add a small batch wrapper that calls the existing importer and skips decisions already present in `human_labeled_returns_manifest.json`.
- Before the loader runs, write a reconciliation-state report under `../FWM_Data/_reports/` recording manifest path, manifest modified time, total manifest decisions, mobile decision files scanned, unmerged file count, and unmerged decision count.
- The loader must read that reconciliation-state report and refuse write mode unless `unmerged_file_count = 0` and `unmerged_decision_count = 0`.
- After reconciliation, run a dry-count pass that reports:
  - total manifest decisions
  - approved rows
  - disapproved rows
  - crop-adjusted approved rows
  - duplicate `review_row_key` values
  - rows missing source workbook references

Only explicit manual `APPROVE` rows should be loaded in this first dev pass. Do not include untouched CV approve candidates.

### 3. Add Review-Level Identity

Create a `public.reviews` table so Review ID means one customer review on one product, with potentially multiple approved images attached.

Dev-only migration placement:

- Put this schema change in `supabase/dev-migrations/` or an explicitly excluded dev-only SQL file unless the CI/CD migration behavior has been audited and confirmed not to apply it to production.
- Do not place this migration in production-applied `supabase/migrations/` as part of this plan.
- If the change is later promoted to production, create a separate production migration with a reviewed rollout and rollback plan.

Suggested fields:

- `id uuid primary key default gen_random_uuid()`
- `product_page_id uuid not null`
- `normalized_product_page_url text not null`
- `source_site text`
- `source_review_id text`
- `review_identity_key text not null unique`
- `reviewer_name_raw text`
- `review_date_raw text`
- `review_date_parsed date`
- `user_comment text`
- `source_file text`
- `source_row_number text`
- `created_at timestamptz default now()`
- `updated_at timestamptz default now()`

Timestamp behavior:

- Create or reuse a shared `set_updated_at()` trigger function.
- Add a `before update` trigger on `public.reviews` so `updated_at` changes on every row update.
- Make the trigger creation idempotent so rerunning dev migrations does not create duplicate triggers.
- Reuse the database's existing canonical updated-at trigger helper if one already exists; otherwise create `public.set_updated_at()`.

`review_row_key` definition:

- `review_row_key` is an existing source-workbook provenance field for manually reviewed rows.
- In the CV review workbooks, it identifies the original source row that produced the image-review row, usually derived from source file plus source row number.
- It is not the same as `public.images.id`, and it is not guaranteed to exist for current production baseline rows.
- For newly approved review-workbook rows, preserve the workbook-provided `review_row_key`.
- If a workbook row is missing `review_row_key` but has source provenance, compute it as `sha256(source_file + ":" + source_row_number)`.
- For current production baseline images that do not have `review_row_key`, compute it as `baseline:<normalized_product_url>:<image_id>`.
- If neither source `review_row_key` nor production image id is available, use `sha256(normalized_product_url + ":" + image_url + ":" + source_site + ":" + review_text + ":" + reviewer_date_size_fingerprint)`.
- Store the generated key in `images.review_row_key` and record the key source in loader logs or import metadata so baseline-generated keys are distinguishable from workbook keys.

Review grouping rules:

1. Prefer platform/source review id when present.
2. Otherwise group by normalized product URL plus stable customer/review context: reviewer, raw/parsed review date, and comment text.
3. If that context is insufficient, fall back to deterministic source identity: workbook `review_row_key`, `baseline:<normalized_product_url>:<image_id>`, or the stable hash fallback.
4. For production baseline rows with too little review context, create one-image baseline review records with `review_identity_key = 'baseline:<normalized_product_url>:<image_id>'` and mark the key source in loader metadata. This keeps baseline rows traceable while avoiding unsupported grouping assumptions.

### 4. Extend `public.images`

Add fields needed for the new app behavior and loader provenance:

Dev-only migration placement:

- Put these `public.images` extensions in `supabase/dev-migrations/` or an explicitly excluded dev-only SQL file unless the CI/CD migration behavior has been audited and confirmed safe.
- Do not place these dev-only column additions in production-applied `supabase/migrations/` as part of this plan.
- If adding a foreign key from `public.images.product_page_id` to `staging.product_pages.id`, include an explicit migration comment that this is a dev-scoped cross-schema dependency.
- The migration should check that `staging.product_pages` exists before adding the FK, or fail with a clear explanatory error. Do not assume every environment has the staging schema.
- If `public.images` has an `updated_at` column but no existing updated-at trigger, add an idempotent `before update` trigger using the same shared trigger helper as `public.reviews`.

- `review_id uuid references public.reviews(id)`
- `product_page_id uuid`
- `review_row_key text`
- `source_file text`
- `source_row_number text`
- `crop_spec jsonb`
- `full_body_visible boolean`
- `weeks_pregnant integer`
- `pregnancy_evidence text`
- `prettiness_score double precision`
- `prettiness_model_version text`
- `prettiness_components jsonb`
- `prettiness_scored_at timestamptz`

For the dev pass, link `images.product_page_id` to the existing `staging.product_pages.id`. Do not create a duplicate product-pages table as part of this plan.

This is a cross-schema relationship. It is acceptable for the dev pass, but migrations must document that `public.images.product_page_id` depends on `staging.product_pages.id` and that the migration is not portable to environments where the staging schema is absent.

Keep `prettiness_score` nullable. The schema should allow future scoring, but the first load should not depend on a prettiness model.

Treat `prettiness_score` as a photo-quality / merchandising-usefulness score, not as a rating of the person in the image. The score should reward good lighting, sharpness, composition, visible garment/body context, and cropability. It should not try to estimate facial attractiveness, body attractiveness, age, race, gender presentation, or anything similarly sensitive.

### 5. Add Product Page Status Tracking

Extend `staging.product_pages` in dev with product-page availability fields so each product URL can be audited independently of image approval.

Dev-only migration placement:

- Put these status-tracking columns in `supabase/dev-migrations/` or an explicitly excluded dev-only SQL file unless the CI/CD migration behavior has been audited and confirmed safe.
- Do not place this dev-only status migration in production-applied `supabase/migrations/` as part of this plan.

Suggested fields:

- `source_status text`
- `source_status_checked_at timestamptz`
- `source_http_status integer`
- `source_final_url text`
- `source_redirected boolean`
- `source_final_url_type text`
- `source_status_evidence text`
- `source_status_error text`
- `source_status_checker_version text`

Recommended `source_status` values:

- `live`
- `out_of_stock`
- `page_not_found`
- `product_unavailable`
- `blocked_or_forbidden`
- `robots_disallowed`
- `redirected_to_product`
- `redirected_to_non_product`
- `timeout`
- `unknown`

Status audit behavior:

- Run only against dev/staging product-page data.
- Check every `staging.product_pages.normalized_product_page_url` after baseline and approved-image loads.
- Respect robots.txt by default. Before fetching product pages for a domain, check robots.txt for the configured audit user agent and skip URLs disallowed for that user agent.
- Classify robots-disallowed URLs as `robots_disallowed`, set `source_final_url_type` to `unknown`, and record the robots.txt rule or fetch error in `source_status_evidence` / `source_status_error`.
- Do not override robots.txt for this audit unless there is explicit human approval that acknowledges the legal/ethical risk and names the affected domains.
- Use polite concurrency, retries, merchant-aware timeouts, and per-domain rate limits so the audit does not hammer retailer sites.
- Record the HTTP status, final URL, redirect state, final URL type, evidence text, checker version, and `source_status_checked_at`.
- Set `source_status_checker_version` on every audit attempt so later rule changes can distinguish rows classified by old logic from rows classified by current logic.
- Classify HTTP `404` and clear no-product pages as `page_not_found`.
- Classify explicit out-of-stock / sold-out product pages as `out_of_stock`.
- Classify product pages that load but say unavailable, discontinued, no longer available, or removed as `product_unavailable`.
- Classify `403`, bot challenge, captcha, or access-denied responses as `blocked_or_forbidden`.
- If a URL redirects to another valid product detail page for the same item or clear successor item, classify as `redirected_to_product` and keep `source_final_url` for possible canonical URL repair.
- If a URL redirects to a homepage, collection/category page, search page, login page, generic sale page, or other non-product page, classify as `redirected_to_non_product`; treat this as a soft-404-style link problem, not as a useful product redirect.
- Set `source_final_url_type` to `product`, `non_product`, `blocked`, or `unknown` using page structure and content evidence, not only the HTTP redirect flag.
- Classify network failures/timeouts separately from unavailable products.
- Preserve current category/tag data; product-page availability status should not erase taxonomy decisions.
- Use status results to filter or badge dev preview rows later, but do not hide current baseline rows until the dev behavior is reviewed.
- Apply scripts must require both the explicit dev write flag and a passed status report-verification artifact before writing status updates.

Browser fallback behavior:

- Add a dev-only, dry-run-only browser fallback audit for product pages that direct HTTP fetch classified as `blocked_or_forbidden`, `timeout`, `unknown`, or `redirected_to_non_product`.
- The browser fallback should prefer a prior status-audit report as input so the exact direct-fetch evidence remains linked to the browser result.
- Use Playwright or equivalent local browser automation with polite limits, per-domain caps, timeouts, screenshots, final URL, page title, and visible-text snippets.
- Do not use the browser fallback to bypass `robots_disallowed` results. Put those pages on a human-review list with the robots evidence.
- If the browser sees captcha, bot challenge, access denied, or similar block pages, classify as `human_review` rather than treating the page as fixed.
- Browser fallback reports should write JSON plus HTML review output with screenshot paths. They should not write Supabase rows.
- If browser fallback evidence is later promoted into status updates, that must happen through a separate reviewed promotion step using the same dev guard and report-verification requirements.
- Browser-status promotion must skip `human_review` rows and only promote clear statuses such as `live`, `out_of_stock`, `page_not_found`, `product_unavailable`, `redirected_to_product`, and `redirected_to_non_product`.
- Browser-status promotion must write its own dry-run report before apply, listing planned updates and skipped rows by reason.

Verification:

- Every product page has either a recent `source_status_checked_at` or a recorded audit error.
- Status counts are reported by `source_status`.
- Status reports include `source_status_checker_version`, and rows classified by older checker versions can be identified for re-audit.
- Browser fallback reports identify `robots_disallowed`, captcha/block pages, and unclear pages as human-review items.
- Report `robots_disallowed` counts separately by domain, including the user agent and robots.txt rule that caused the skip where available.
- Sample each status bucket manually before using the status to filter search results, especially `redirected_to_product` and `redirected_to_non_product`.
- For redirect buckets, confirm `source_final_url`, `source_final_url_type`, and `source_status_evidence` explain why the redirect remains useful or should be treated as a soft-404-style link problem.
- Known current website products remain present in dev even if their product page is now out of stock or unavailable; status is metadata first, filtering second.

### 6. Add Product Page Taxonomy Refresh

Add a dev-only product-page taxonomy enrichment pass that treats workbook fashion item types as source hints, not authoritative truth. Many source workbook rows have incorrect or overly broad item types, so product-page evidence should become the preferred taxonomy source when the page can be fetched safely.

Goals:

- Populate broad product categories that are useful for filtering and navigation, such as `tops`, `bottoms`, `dresses`, `outerwear`, `swimwear`, `activewear`, `underwear`, `shoes`, `accessories`, and `other`.
- Populate specific clothing item tags, such as `jeans`, `pants`, `shorts`, `skirt`, `leggings`, `tank`, `blouse`, `bodysuit`, `jumpsuit`, `romper`, `coat`, `blazer`, `bra`, `bikini`, and `one_piece_swimsuit`.
- Populate material, style, and detail tags, such as `denim`, `tweed`, `faux_leather`, `leather`, `linen`, `cotton`, `ribbed`, `knit`, `lace`, `satin`, `cropped`, `high_waisted`, `wide_leg`, `straight_leg`, `flare`, `mini`, `midi`, and `maxi`.
- Preserve original workbook-provided category/type values for provenance, but do not let them override stronger product-page evidence.
- Make broad categories and specific tags independently queryable so dev search can later support both high-level filters and fine-grained style/material filters.

Source priority:

1. Product structured data, including JSON-LD Product fields and merchant category fields.
2. Product title.
3. Breadcrumbs, collection/category links, and on-page category labels.
4. Product description, detail bullets, fabric/composition sections, and fit/style sections.
5. Product URL slug.
6. Workbook-provided `clothing_type_id` and `product_category_raw` as fallback evidence only.

Dev-only schema:

- Use existing `staging.product_pages` page-level fields for the primary broad category:
  - `mother_category_id`
  - `category_confidence`
  - `category_evidence`
  - `raw_metadata`
- Use existing `staging.product_page_clothing_type_tags` for specific item tags that map to the controlled clothing type taxonomy.
- Add a dev-only table if richer tags do not fit cleanly in the existing type-tag table:
  - `staging.product_page_attribute_tags`
  - Suggested fields: `product_page_id`, `tag_type`, `tag_id`, `label`, `confidence`, `evidence`, `source_field`, `extractor_version`, `created_at`, `updated_at`
  - Suggested `tag_type` values: `item_type`, `material`, `style`, `fit`, `length`, `rise`, `pattern`, `occasion`, `detail`

Extraction behavior:

- Run only against dev/staging product-page data.
- Reuse the same shared production guard as the loader, status audit, and dev migration runner.
- Respect robots.txt by default, using the same policy as the product-page status audit.
- Use polite concurrency, merchant-aware rate limits, retries, and timeouts.
- Use deterministic extraction first: normalized dictionaries, aliases, and phrase matching against structured data, title, breadcrumbs, description, and URL slug.
- Require evidence text for every assigned broad category and every assigned specific tag.
- Allow multiple specific tags per product page.
- Allow one primary broad category per product page when confidence is high or medium.
- Mark ambiguous pages as `category_confidence = 'low'` and include competing evidence in the dry-run report rather than guessing.
- Do not infer sensitive body/person attributes from product copy.
- Do not infer pregnancy/postpartum from product category or words like `maternity`, `bump friendly`, or `postpartum`; pregnancy remains review-text-only as described in the attribute backfill section.
- Do not modify image approval, review identity, crop specs, or measurement fields.

Dry-run workflow:

1. Select a sample of product pages that includes pages with known workbook clothing types, pages with missing workbook types, and pages where workbook values look suspicious.
2. Fetch only product pages allowed by robots.txt.
3. Extract candidate broad categories, specific item tags, and material/style/detail tags.
4. Compare extracted values against workbook `clothing_type_id`, `product_category_raw`, and current staging fields.
5. Write a report to `../FWM_Data/_reports/` with:
   - product page URL
   - current workbook clothing type/category hints
   - extracted broad category
   - extracted item tags
   - extracted material/style/detail tags
   - confidence
   - exact evidence snippets
   - source field used, such as `json_ld`, `title`, `breadcrumb`, `description`, `url_slug`, or `workbook_fallback`
   - extractor version
   - proposed database writes
6. Manually review a sample of high-confidence matches, low-confidence matches, and workbook-disagreement cases before applying broadly.

Apply workflow:

- Apply only after reviewing the dry-run report.
- Apply scripts must require both the explicit dev write flag and a passed report-verification artifact for the exact report type before writing.
- Write page-level category fields to `staging.product_pages`.
- Write controlled item tags to `staging.product_page_clothing_type_tags`.
- Write material/style/detail tags to `staging.product_page_attribute_tags` if that table is added.
- Store extractor version and evidence for auditability and reruns.
- Preserve workbook-provided values in existing raw/provenance fields.
- Never overwrite stronger existing human-reviewed taxonomy evidence without a dry-run diff and explicit approval.

Acceptance criteria:

- Workbook clothing type is no longer treated as authoritative when product-page evidence disagrees.
- Every generated category/tag has evidence, confidence, source field, and extractor version.
- Broad category filters and specific tags can be queried independently.
- Product-page taxonomy writes are dev-only and guarded by the approved dev Supabase URL.
- No production Supabase writes, production migrations, or production website deploys run as part of this taxonomy refresh.
- Dev preview can later filter or badge by broad category and specific tags only after manual review.

### 7. Build The Loader

Create a loader that first validates the current website baseline in dev, then reads the manual approval manifest and rehydrates approved rows from source workbooks.

Inputs:

- `FWM_DATA_DIR`, defaulting to `../FWM_Data`
- source package dir from `defaultImageReviewPackageDir(repoRoot)`
- returns dir from `defaultImageReviewReturnsDir(repoRoot)`
- `human_labeled_returns_manifest.json`

Behavior:

- Abort immediately if `SUPABASE_URL` is unset, points to the production Supabase URL, or is not in the approved dev Supabase allowlist.
- Use the same shared production guard as every backfill, status-audit, and dev migration runner so the production-safety check cannot drift between scripts.
- Print the resolved Supabase project ref/URL and require it to be dev before any write-mode action.
- Verify the current website baseline has already been loaded into dev.
- Verify the human-labeled returns manifest is fully reconciled before loading approved rows.
- Refuse to run the write-mode loader if any `fwm_mobile_review*.json` decision file contains decisions not represented in `human_labeled_returns_manifest.json`.
- Refuse to run write mode unless the latest reconciliation-state report exists and shows zero unmerged mobile decision files and zero unmerged mobile decisions.
- Print the unmerged mobile decision file names and counts when this guard fails, then require the existing import/reconcile step to run first.
- Read approved manifest decisions.
- Load corresponding source workbook rows by `bucket`, `part_file`, and `review_row_key`.
- For production baseline rows, generate `review_row_key = 'baseline:<normalized_product_url>:<image_id>'` before review grouping so baseline rows do not depend on workbook provenance.
- Normalize product URLs using the existing staging normalization logic.
- Upsert product records into `staging.product_pages`.
- Create or find review records in `public.reviews`.
- Upsert approved image rows into `public.images`.
- Preserve row-level provenance: `review_row_key`, `source_file`, `source_row_number`, decision export metadata, and relevant CV metrics.
- Create deterministic one-image `public.reviews` fallback records for current website baseline rows that lack reliable review identity, using `review_identity_key = 'baseline:<normalized_product_url>:<image_id>'`.
- Store existing manual crop fields as `crop_spec`.
- Leave `crop_spec` null for rows without manual crop; automatic crop specs will be populated in a later backfill.
- Parse `weeks_pregnant` conservatively from `user_comment`; store the matched phrase in `pregnancy_evidence`.

Duplicate policy:

- Treat normalized image URL as the first duplicate key. Normalize by trimming whitespace and removing clearly transient query parameters only when safe for that host.
- Treat existing production baseline rows as canonical over newly approved rows when the normalized image URL already exists in dev.
- When a newly approved row duplicates a baseline image URL, do not insert a second `public.images` row. Instead, update only nullable enrichment fields on the existing dev row when the new row has better provenance or metadata, such as `review_row_key`, `product_page_id`, `review_id`, `crop_spec`, `full_body_visible`, or measurement fields. Never overwrite non-null baseline display fields without a dry-run diff and explicit approval.
- When two newly approved rows duplicate the same image URL before insert, keep one canonical image row and merge non-conflicting metadata from the others. Prefer the row with a reliable product URL, size, measurements, review identity, manual crop, and richer `user_comment`.
- If duplicate rows have conflicting product URLs or incompatible review identity, do not guess. Quarantine the duplicate set into a review report under `../FWM_Data/_reports/` and skip inserting those duplicate rows until reviewed.
- Record duplicate decisions in the loader report: inserted, merged into baseline, merged into approved canonical row, quarantined, or skipped.
- The write-mode loader should fail if there are any unreviewed duplicate conflicts unless it is run with an explicit `ALLOW_QUARANTINED_DUPLICATES=true`-style dev override that records the skipped duplicate sets in the loader report.

### 8. Crop Spec

Use the current dashboard crop export fields as the initial frontend contract. Treat crop and orientation as display metadata only: do not rewrite source image URLs or source image bytes during this dev pass.

```json
{
  "mode": "object-position",
  "aspectRatio": "3:4",
  "objectPositionXPct": 50,
  "objectPositionYPct": 50,
  "zoom": 1,
  "rotationDeg": 0,
  "source": "manual|auto|default"
}
```

`crop_spec.rotationDeg` is the canonical frontend display rotation field for this pass. It should be interpreted clockwise and should use only `0`, `90`, `180`, or `270` unless a later reviewed design explicitly supports arbitrary angles. Initial load should preserve manual dashboard rotation exports when present and otherwise use `0` or leave the field absent.

Optional dev-only audit fields may be added to `public.images` if the orientation backfill needs a clearer audit trail than `crop_spec` alone:

- `image_orientation_degrees integer`
- `image_orientation_confidence text`
- `image_orientation_evidence jsonb`
- `image_orientation_checked_at timestamptz`
- `image_orientation_model_version text`

If these fields are added, `image_orientation_degrees` must mirror the display rotation written into `crop_spec.rotationDeg` for applied corrections. Keep them null for images that have not been checked or do not need correction.

Manual crop exports map directly from:

- `crop_has_adjustment`
- `crop_mode`
- `crop_aspect_ratio`
- `crop_object_position_x_pct`
- `crop_object_position_y_pct`
- `crop_zoom`
- `crop_rotation_deg`

Automatic crop backfill should be conservative:

- Use existing person-size/body-position CV metrics where available.
- Keep the output compatible with `object-fit: cover` and `object-position`.
- Fall back to centered 3:4 cover if CV data is missing or ambiguous.

### 9. Image Orientation Correction

Add a dev-only image-orientation audit and backfill that detects approved images whose displayed orientation is likely wrong and proposes a rotation correction.

Goals:

- Detect approved images that should be rotated, especially `90`, `180`, or `270` degrees.
- Store approved display corrections in `public.images.crop_spec.rotationDeg`.
- Preserve source image URLs and source image bytes; do not rewrite hosted images during this pass.
- Keep corrections nullable and evidence-backed so ambiguous cases can be manually reviewed.

Inputs:

- Approved dev `public.images` rows only.
- Existing `crop_spec` values, including any manual rotation already present.
- Image dimensions and EXIF orientation when available.
- Optional local CV/layout signals from the image itself.

Detection strategy:

1. Read EXIF orientation when available.
2. Compare image width/height/aspect ratio against the expected garment-photo display layout.
3. Use local deterministic or CV checks for likely sideways images, such as person/body pose orientation, face/body keypoint orientation, text/logo orientation from local OCR, or a large garment/object vertical axis.
4. Prefer high precision over high recall. A false positive rotation is worse than leaving an ambiguous image unchanged.
5. Do not use a hosted/paid CV endpoint or upload images to a third party without explicit human approval.

Dry-run workflow:

1. Scan approved dev images.
2. Download or inspect image metadata locally with conservative timeouts and per-domain rate limits.
3. Produce a report in `../FWM_Data/_reports/` containing:
   - image id
   - image URL
   - current `crop_spec`
   - image dimensions
   - EXIF orientation if present
   - proposed rotation
   - confidence
   - evidence
   - proposed database write
   - thumbnail or contact-sheet path for manual review when practical
4. Do not write Supabase rows during dry-run.

Manual review:

- Review every proposed non-zero rotation before broad apply, or at minimum every medium-confidence case plus a representative high-confidence sample.
- Include side-by-side before/after thumbnails when practical.
- Reject corrections where the image may be intentionally landscape, flat-lay, collage, mirror selfie with unusual framing, or merchant layout.
- Do not overwrite an existing manual non-zero `crop_spec.rotationDeg` without a dry-run diff and explicit approval.

Apply workflow:

- Apply only reviewed or high-confidence corrections in dev.
- Apply scripts must require both the explicit dev write flag and a passed report-verification artifact before writing orientation corrections.
- Update `crop_spec.rotationDeg` without changing the other crop fields unless the dry-run explicitly proposes and explains a coupled crop adjustment.
- If orientation audit fields exist, write `image_orientation_degrees`, `image_orientation_confidence`, `image_orientation_evidence`, `image_orientation_checked_at`, and `image_orientation_model_version`.
- Preserve manual crop fields.
- Keep production unchanged.

Frontend interpretation:

- The frontend should read `crop_spec.rotationDeg` and apply it as clockwise CSS rotation inside the image crop frame.
- Rotation must be composed with existing zoom and object-position behavior so the visible frame remains the same 3:4 card area.
- Cards with no `crop_spec` or no `rotationDeg` should behave exactly like current production cards.
- Cards with `rotationDeg = 0` should render the same as unrotated cards.
- Cards with `90` or `270` degrees may need the rendered image element to swap its effective width/height or use a larger transform scale so the rotated image continues to cover the frame without empty corners.
- The frontend should tolerate malformed or unsupported rotation values by ignoring rotation and falling back to `0`.

Acceptance criteria:

- No production Supabase writes.
- No source image files are modified.
- Ambiguous images remain unchanged.
- Every non-zero rotation has evidence and reviewability.
- Dev preview renders rotated images correctly without empty corners or layout shift.
- Baseline production image IDs and URLs remain unchanged.

### 10. Measurement Extraction Audit And Backfill

Improve missing structured measurements by using an LLM to audit a random sample of approved rows, then converting any confirmed missed patterns into deterministic parser updates.

Goal:

- Find cases where `user_comment` contains explicit measurements that are missing from structured fields such as height, weight, waist, hips, bust, bra band, cup size, and inseam.
- Use the LLM for discovery and labeling only.
- Do not let LLM output directly update Supabase measurement fields.
- Promote only reviewed, deterministic regex/parser improvements into the backfill pipeline.
- Require explicit human permission before every LLM audit run because the loop can be token-expensive.

Workflow:

1. Propose the audit run first, including sample size, row-selection criteria, model choice, pricing source, token estimate, cost estimate, and output location.
2. Get explicit human approval before sending any rows to the LLM.
3. Draw the approved random sample of dev image rows, biased toward rows with rich `user_comment` text and missing one or more measurement fields, but stratified by `source_site` so Amazon and non-Amazon review formats are represented separately.
4. Ask the LLM to extract only explicit self-reported measurements from the freeform text and cite the exact supporting phrase for each candidate.
5. Compare LLM candidates against the existing structured fields.
6. Classify each miss into a pattern bucket, such as height format, weight phrase, waist/hips pair, bust phrase, bra size, inseam phrase, metric units, range values, or false positive.
7. Manually review the pattern buckets and select only high-confidence deterministic patterns.
8. Update the existing deterministic parsers, especially:
   - `data-pipelines/scripts/00_raw_scrape/non_amazon/step1_intake_utils.py`
   - `data-pipelines/scripts/00_raw_scrape/non_amazon/backfill_review_measurements.py`
   - Amazon-specific measurement backfill scripts when the missed pattern applies to Amazon rows.
9. Assign a deterministic parser version for the backfill run, including git commit SHA, dirty-worktree flag, parser file paths, and a short config/ruleset version string.
10. Run deterministic backfill in dry mode and report newly populated fields by measurement type.
11. Apply backfill to dev image rows only after dry-run review and after the script confirms `SUPABASE_URL` is an approved dev Supabase URL.
12. Keep a report in `../FWM_Data/_reports/` showing sample size, LLM-found candidates, accepted parser updates, false positives, parser version metadata, and final deterministic backfill counts.

LLM audit cost estimate requirements:

- Before asking for approval, sample enough candidate `user_comment` values to estimate the average and p90 input token length for the target row population. Use at least 50 rows when available, or the whole candidate set if smaller.
- Include the proposed `source_site` strata and per-stratum row counts in the approval request. At minimum, separate Amazon from non-Amazon rows; when volume allows, include the largest non-Amazon retailers as their own strata.
- Estimate prompt overhead separately from review text tokens, including system/developer instructions, JSON schema or output-format instructions, and per-row metadata.
- Estimate expected response tokens per row from a small local/template calculation or prior dry-run output shape, including exact evidence phrases and null/no-finding rows.
- Use the current published model pricing for input and output tokens, recording the pricing source and date in the approval request.
- Calculate: `estimated_input_tokens = sample_size * (avg_comment_tokens + per_row_prompt_overhead_tokens) + fixed_prompt_tokens`.
- Calculate: `estimated_output_tokens = sample_size * expected_output_tokens_per_row`.
- Calculate estimated cost from input/output token pricing, then add a conservative contingency buffer, for example 25%.
- The approval request must show sample size, avg/p90 comment tokens, fixed prompt tokens, per-row overhead, expected output tokens per row, model pricing, estimated input/output tokens, estimated total cost, and output path.

Parser safety rules:

- Extract only explicit measurements from review/customer text.
- Do not infer measurements from product names, size charts, model photos, product descriptions, or image appearance.
- Preserve raw matched text where possible.
- Avoid weight-change false positives such as `lost 20 pounds`, `down 10 lb`, `pre-pregnancy weight`, or product/fabric weight.
- Keep exact values and ranges distinct; do not collapse a range into a false exact value.
- Prefer null over low-confidence extraction.

Acceptance criteria:

- The deterministic parser update improves recall on reviewed samples without introducing unacceptable false positives.
- Dry-run backfill reports before/after coverage by field.
- Dry-run and write-mode reports include parser version metadata: git commit SHA, dirty-worktree flag, parser file paths, config/ruleset version, run timestamp, and source dataset/manifest identifier.
- A spot-check sample of newly populated fields confirms the exact review-text evidence.
- Dev search results improve for measurement filters without changing production data.

### 11. Attribute Backfills

Backfill `full_body_visible` and `weeks_pregnant` conservatively after the initial dev load. Both fields should be nullable in practice: use `null` when the signal is missing or ambiguous rather than guessing.

`full_body_visible` backfill:

- Use existing CV columns first: `person_count_yolo_detect`, `main_person_height_pct_yolo_detect`, `main_person_bbox_area_pct_yolo_detect`, `body_coverage_score_yolo_pose`, and `has_face_yunet`.
- Set `true` only when the person's head and feet are both visible in the image.
- Set `false` when the image clearly cuts off the head, feet, or both, or when it is torso-only, legs-only, close-up, garment detail, or otherwise partial body.
- Leave `null` when CV is missing, contradictory, or cannot confidently establish whether both head and feet are visible.
- Treat "near full body" and "useful fit image" as separate concepts; they are not enough for `full_body_visible = true` unless head and feet are both visible.
- Store the rule version and raw CV metrics used for the decision in loader/backfill logs so thresholds can be audited later.
- Validate the rule on a sampled review sheet before applying broadly; approved images can still be non-full-body and useful, so this should not become an approval filter.

`weeks_pregnant` backfill:

- Parse only explicit pregnancy timing in `user_comment` and related review text.
- Accept direct week phrases such as `20 weeks pregnant`, `20 wks pregnant`, `20 weeks along`, `20 weeks postpartum` should not populate `weeks_pregnant`.
- Accept month phrases only when clearly pregnancy-related, then convert using `weeks = floor(months * 4.345 + 0.5)`, which is round half-up to the nearest integer.
- Direct week phrases win over month phrases when both appear.
- Store the original matched phrase in `pregnancy_evidence`.
- Do not infer pregnancy from body shape, product category, maternity clothing, or vague phrases like `bump friendly`, `maternity`, `postpartum`, `after baby`, or `pre-pregnancy`.
- Leave `weeks_pregnant` null unless the text explicitly supports a week estimate.
- Add `pregnancy_evidence` for the matched phrase and, if useful, a future `pregnancy_parse_version` field or loader log entry for auditability.

### 12. Prettiness / Photo Quality Score

Populate `prettiness_score` with a computer-vision backfill after the initial dev load. Do not use an LLM for the first scoring pass. The first version should be deterministic, reproducible, and cheap enough to rerun locally or in a controlled batch job.

Recommended first implementation:

1. Use a CLIP/OpenCLIP aesthetic predictor as the primary aesthetic model. A good starting point is the LAION aesthetic predictor style of model: CLIP image embeddings plus a small learned linear/MLP scoring head that outputs an aesthetic score. This gives a practical 0-10-ish "does this look like a good photo" signal.
2. Add a no-reference image-quality model as a technical quality component. Prefer MUSIQ if implementation/dependency cost is reasonable because it is designed to handle native image sizes and varying aspect ratios; otherwise use NIMA as the simpler fallback.
3. Add domain-specific CV components from our existing pipeline and/or lightweight reruns:
   - person count / single primary person
   - head-and-feet visibility from `full_body_visible`
   - main-person bounding-box coverage and cropability
   - face present, but not face attractiveness
   - image resolution and aspect ratio suitability
   - blur/low-light flags when available
4. Store all component scores and model versions in `prettiness_components`, then store one calibrated blended score in `prettiness_score`.

Proposed v1 blend:

```text
prettiness_score_v1 =
  0.55 * normalized_aesthetic_score
+ 0.25 * normalized_technical_quality_score
+ 0.20 * normalized_domain_fit_score
```

`domain_fit_score` should reward a useful fit-photo composition, not a model's body shape. Suggested positive signals are one clear person, garment visible, enough body context for fit, head and feet visible when applicable, and a crop that can fill a card without cutting off important content. Suggested negative signals are screenshots, collages, product-only photos, extreme closeups, heavy occlusion, tiny person area, multiple ambiguous people, bad blur, bad exposure, or watermarked/overlaid content.

Calibration workflow:

1. Run the scorer in dry mode on a stratified sample of approved dev images.
2. Export a review sheet with thumbnail, existing manual decision, `prettiness_score`, and component scores.
3. Human-review the top, middle, and bottom score buckets to check whether the ordering matches our merchandising taste.
4. Adjust weights/thresholds before writing broad scores to dev.
5. Record the scoring run id, model names, model checkpoints, source image URL/hash, component scores, and `prettiness_scored_at`.
6. Use the score as a sorting/boosting input only after review. Do not hide approved rows solely because v1 scored them low.

Safety and bias notes:

- Avoid naming this user-facing field "prettiness" in the UI; internally it can remain `prettiness_score` for now, but product copy should describe it as photo quality or presentation quality.
- Because generic aesthetic predictors can encode cultural and demographic preferences, validate the score across body sizes, skin tones, merchant sources, image types, and pregnancy/postpartum examples before using it for ranking.
- If we use a paid hosted CV endpoint or any model that uploads images to a third party, get explicit human approval first and document the expected cost and data-sharing implications. Local open-source inference is preferred for the first pass.
- Keep the field nullable for rows where images cannot be fetched, model inference fails, or the components disagree too strongly.

Acceptance criteria:

- A dry-run report shows score distributions and component distributions.
- Human spot checks confirm high-scoring images are usually clearer and more useful for fit-shopping than low-scoring images.
- The scorer is reproducible from a recorded model version and config.
- No production Supabase project is touched.
- Dev search behavior does not depend on `prettiness_score` until after review.

### 13. Frontend And RPC Updates

Update `public.match_by_measurements` in the dev Supabase environment only, without changing the production Supabase project or active website behavior.

Keep current returned fields and add:

- `crop_spec`
- `review_id`
- `product_page_id`
- `full_body_visible`
- `weeks_pregnant`
- `prettiness_score`

Update frontend card rendering:

- Apply `crop_spec` when present.
- Interpret `crop_spec.rotationDeg` as clockwise display rotation and compose it with crop zoom/object-position.
- Fall back to current `object-fit: cover` behavior when `crop_spec` is null.
- Ignore malformed or unsupported `rotationDeg` values and render as `0`.
- Keep product links and existing measurement display behavior unchanged for the first pass.
- Do not expose `prettiness_score` in the UI at first; only use it in dev sorting experiments after the scoring calibration review.

### 14. Dev Website Preview

Create a dev-only website preview that looks and behaves like the current live website, but reads from the updated dev Supabase tables and RPCs.

Requirements:

- Preserve the current `index.html` UI, layout, search controls, card styling, image proxy behavior, and product-link behavior.
- Do not point the preview at production Supabase.
- Do not deploy the preview over the active production website.
- Use a dev-specific config file and local preview entrypoint so `window.SUPABASE_URL` and `window.SUPABASE_ANON_KEY` point to the dev Supabase project.
- Keep production `config.js` unchanged unless there is a separate production release plan.
- Serve the preview locally first, then optionally deploy to a clearly separate dev/staging URL.
- Make the preview visually comparable to production by using the same static frontend files wherever possible and only swapping data config plus any dev-only crop rendering support.

Concrete config mechanism:

- Keep production `config.js` as the production-only config loaded by the active website.
- Add a local-only `config.dev.js` containing dev Supabase URL/key and `window.FWM_ENV = "dev"`.
- Add `index.dev.html` as the dev preview entrypoint. It should mirror `index.html` but load `config.dev.js` instead of `config.js`.
- Do not edit production `index.html` to conditionally choose configs based on hostname for this first dev pass; use a separate local entrypoint to avoid accidental production config swaps.
- Exclude `config.dev.js` and `index.dev.html` from production deploys unless there is an intentional separate staging deployment target.
- Add a preview runtime banner or console assertion that confirms the page is using dev Supabase before any search runs.

Preview verification:

- Search with the same measurement inputs on production and dev preview.
- Confirm dev preview returns rows from the updated dev tables.
- Confirm the production website still points to production Supabase.
- Confirm production deploy artifacts do not include or reference `config.dev.js` or `index.dev.html`.
- Confirm cards without `crop_spec` look like the current production cards.
- Confirm cards with `crop_spec` apply the updated crop behavior.
- Confirm cards with `crop_spec.rotationDeg` apply rotation correctly in dev preview.
- Confirm no production analytics, reports, or writes are accidentally used for dev testing unless intentionally configured.

## Test Plan

### Current Website Baseline

- Export current production `public.images` in read-only mode with `pg_dump --data-only`.
- Record the export timestamp and treat the dev baseline as complete only as of that timestamp.
- Write and verify the versioned baseline manifest before restore, including row count, source project ref, export path, SHA-256 checksum, export method, and `pg_dump` version.
- Load the export into dev.
- Compare production export count against dev baseline count.
- Compare every exported production image ID against dev; missing, changed, regenerated, duplicated, or URL-mismatched IDs are blocking errors.
- Confirm no baseline rows are overwritten or dropped when newly approved rows are added.

### Loader Dry Run

Run a dry mode before database writes and verify:

- approved row count matches reconciled manifest expectations
- no unmerged mobile decision files remain outside `human_labeled_returns_manifest.json`
- the latest reconciliation-state report exists and records zero unmerged mobile files and decisions
- all source workbook paths resolve under `../FWM_Data`
- every loadable row has image URL and product URL
- duplicate image URLs are reported
- duplicate image URLs have deterministic planned actions: insert, merge into baseline, merge into approved canonical row, quarantine, or skip
- multi-image reviews are grouped under one planned `review_id`
- baseline rows without source-workbook `review_row_key` receive deterministic `baseline:<normalized_product_url>:<image_id>` keys
- rows skipped for missing source data are listed with reasons

### Measurement Backfill Verification

- Sample approved rows with missing structured measurements.
- Compare LLM-audited candidates against existing deterministic extraction.
- Update deterministic regex/parser rules only after reviewing evidence.
- Require explicit human approval before each LLM audit run, with sample size and cost estimate.
- Run dry backfill and report new values by field.
- Spot-check newly filled values against exact review text before writing to dev.
- Include deterministic pregnancy parser tests for month conversion: `1 month pregnant` -> `4`, `2 months pregnant` -> `9`, `3 months pregnant` -> `13`, and `7 months pregnant` -> `30`.
- Include a precedence test where an explicit week phrase and month phrase both appear; the direct week value must win.

### Prettiness Score Verification

- Run the CV scorer in dry mode first; do not write scores on the first pass.
- Report score distribution, component distributions, model versions, failures, and skipped image counts.
- Review sampled thumbnails from high, middle, and low score buckets before approving broad writes to dev.
- Confirm low scores are driven by image quality, composition, cropability, or technical issues, not by body/face attractiveness.
- Confirm scoring is nullable and does not block approved image rows from appearing in dev.
- Confirm no hosted/paid model or third-party image upload is used without explicit human approval.

### Database Verification

After dev load:

- Newly approved workbook-loaded images have `review_id`.
- Current website baseline images have either a reliably grouped `review_id` or a deterministic one-image fallback `review_id`.
- Every loaded image with a product URL has `product_page_id`; rows without product URLs are reported separately with reasons.
- Every loaded image has `original_url_display`.
- Every loaded image has either `product_page_url_display` or `monetized_product_url_display`.
- Multi-image reviews with reliable review identity share the same `review_id`.
- `crop_spec` is either null or valid JSON matching the frontend contract.
- `crop_spec.rotationDeg` is absent or one of `0`, `90`, `180`, or `270`.
- If orientation audit columns are added, applied non-zero orientation corrections have matching `crop_spec.rotationDeg`, `image_orientation_degrees`, evidence, checked timestamp, and model/version metadata.
- `weeks_pregnant` is null unless review text explicitly supports it.
- `prettiness_score` is null before scoring, or populated only by an approved dev CV scoring run with `prettiness_model_version`, `prettiness_components`, and `prettiness_scored_at`.
- Updating one dev `public.reviews` row changes its `updated_at` value without changing `created_at`.
- Updating one dev `public.images` row changes its `updated_at` value if the column exists, without changing `created_at`.

### Image Orientation Verification

- Orientation audit dry-run reports include image id, URL, current `crop_spec`, dimensions, EXIF orientation if available, proposed rotation, confidence, evidence, and proposed database write.
- Every proposed non-zero rotation is reviewable with a thumbnail/contact sheet or equivalent visual evidence.
- Existing manual non-zero `crop_spec.rotationDeg` values are not overwritten without an explicit dry-run diff and approval.
- Applied orientation corrections update `crop_spec.rotationDeg` and do not rewrite source image URLs or source image bytes.
- Dev preview cards with `90` and `270` degree rotations still cover the card frame without empty corners.
- Cards with no rotation metadata and cards with `rotationDeg = 0` match current production rendering.
- Malformed rotation metadata falls back to `0` rather than breaking card rendering.

### Product Page Taxonomy Verification

- Product-page taxonomy dry-run reports include workbook hints, proposed broad categories, proposed specific tags, confidence, evidence snippets, source fields, extractor version, and proposed database writes.
- Workbook clothing type disagreements are reported separately from matches.
- Every proposed broad category and specific tag has an evidence snippet from product structured data, title, breadcrumb/category text, description, URL slug, or workbook fallback.
- No product-page taxonomy apply runs against robots-disallowed URLs unless explicitly approved for named domains.
- Applied page-level categories are visible in `staging.product_pages`.
- Applied controlled item tags are visible in `staging.product_page_clothing_type_tags`.
- Applied material/style/detail tags are visible in `staging.product_page_attribute_tags` if that table is added.
- Broad category filters and specific tag filters can be tested independently in dev before any frontend behavior depends on them.
- Product-page taxonomy does not overwrite image approval decisions, review identity, crop specs, measurement fields, or production baseline IDs.

### Migration Safety Verification

- Repo-documented deployment facts: the live site is Cloudflare Pages connected to GitHub `main`; it serves raw HTML, JavaScript, and CSS with no build step. No GitHub Actions workflows are configured in this checkout.
- Because Cloudflare Pages is serving the static frontend without a build step, the production deploy path does not run `supabase db push`, `supabase migration up`, `psql`, or package scripts that apply SQL migrations.
- Confirm Cloudflare Pages production settings still match the repo docs before adding schema files: project is connected to `bsinger3/FWM_Repo`, production branch is `main`, build command is empty or static-only, and no deploy hook/command runs Supabase migration commands.
- Confirm dev-only schema changes are outside production-applied migration paths.
- Confirm dev-only migration files follow the `YYYYMMDD_dev_<short_name>.sql` naming convention.
- Confirm CI excludes `supabase/dev-migrations/` from any production migration application job, or that dev schema changes are isolated on a separate dev Supabase branch/project.
- Confirm no new dev-only migration in this plan is placed in `supabase/migrations/` unless production deployment has been explicitly approved through a separate promotion plan.
- Confirm every loader, backfill, status-audit, and dev migration runner has a production URL guard that aborts if `SUPABASE_URL` matches production.
- Confirm scripts use an explicit dev Supabase allowlist before write-mode operations.
- Confirm write-capable scripts use the shared production guard rather than duplicating slightly different checks.
- Confirm production Supabase schema remains unchanged after dev testing.

### Frontend Verification

- Existing search tests still pass.
- `match_by_measurements` still returns the current required fields.
- Cards with `crop_spec` render with the intended crop.
- Cards without `crop_spec` render with the existing fallback.
- Product-page status can be displayed or filtered in dev only after status buckets are manually sampled.
- Product links and report-image behavior still work.
- A local or staging dev preview renders the current website experience while using only dev Supabase data.

## Assumptions

- The first dev load includes explicit manual approvals only.
- Dev starts from a complete baseline copy/export of the current website `public.images` table before newly approved rows are added.
- Review ID means one customer's review on one product, not one image. Baseline rows without reliable review identity use explicit one-image fallback review records with `review_identity_key = 'baseline:<normalized_product_url>:<image_id>'`.
- `staging.product_pages` remains the product table for this dev pass.
- Workbook-provided clothing type and product category values are source hints only; product-page evidence is preferred for taxonomy when the page can be fetched safely.
- Product-page availability status is recorded as metadata in dev first; it should not automatically remove current website rows from search until reviewed.
- Product-page taxonomy is recorded as metadata in dev first; it should not automatically change search filters, ranking, or UI labels until sampled and reviewed.
- A future public product-table promotion can happen separately when product-level frontend reads require it.
- Prettiness scoring should be schema-only for the initial dev load, then populated by a separate approved CV backfill after dry-run review.
- `crop_spec` is nullable on initial load; automatic crop specs will be backfilled later.
- `crop_spec.rotationDeg` is the first-pass display rotation contract; any separate orientation audit fields are dev-only traceability fields and must stay consistent with `crop_spec.rotationDeg` when populated.
- Every LLM measurement-audit run requires explicit human permission before rows are sent to the model.
- No production Supabase migrations, RPC changes, data loads, or website deploys should run as part of this plan. Production promotion requires a separate reviewed migration, verification, and rollback plan.
- Dev-only schema changes must not be placed in any migration path that CI/CD auto-applies to production.
- Write-capable scripts must refuse to run when pointed at the production Supabase URL.
- Dev website preview must use dev Supabase credentials and must not overwrite the active production website.
- Generated review outputs and loader artifacts stay in `../FWM_Data`, not repo-root `outputs/`.
