## Scripts

This folder is for local automation and data-ingestion scripts that support the Friends With Measurements project.

Recommended split:

- Repo code and automation live in `FWM_Repo`
- Generated datasets and exports live in the sibling `FWM_Data` folder

Current local parent layouts:

- Mac: `/Users/briannasinger/Projects/FWM/`
- Windows: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\`

The starter script in this folder writes to:

- `../FWM_Data/00_raw_scraped_data/amazon/apify/`

Run scripts from anywhere; they resolve paths relative to the repo automatically.

### Amazon Reviews Batch Script

`scrape_amazon_reviews_batches.py`

What it does:

- reads a CSV with an `asin` column
- chunks ASINs into sequential Apify runs
- requests `media_reviews_only`
- saves raw dataset output to `../FWM_Data/00_raw_scraped_data/amazon/apify/batch_###.json`

Expected environment variables:

- `APIFY_TOKEN`
- `APIFY_ACTOR_ID`

You can put them in a repo-local `.env` file instead of setting them in PowerShell every time.

Example `.env` at the repo root:

```dotenv
APIFY_TOKEN=your-token
APIFY_ACTOR_ID=your-actor-id
```

Example:

```powershell
python .\scripts\scrape_amazon_reviews_batches.py .\path\to\asins.csv --batch-size 50
```

Notes:

- Batch size must stay at 100 or below.
- Output is saved as raw JSON exactly as returned by the Apify dataset.
- Existing batch files are preserved; new runs continue numbering from the latest batch file found.

### Direct Amazon Reviews Smoke Scraper

`scrape_amazon_reviews_direct.mjs`

What it does:

- reads a CSV with an `asin` column, or one or more `--asin` values
- visits public Amazon `media_reviews_only` review pages with Playwright
- extracts review text, rating, date, size/color, helpful count, and customer image URLs when review cards are visible
- saves raw JSON output to `../FWM_Data/00_raw_scraped_data/amazon/direct_amazon/batch_###.json`
- stops clearly on CAPTCHA, bot checks, or Amazon sign-in/claim pages instead of attempting to bypass them

Example:

```bash
node scripts/scrape_amazon_reviews_direct.mjs path/to/fresh_asins.csv --batch-size 10 --max-pages 2
```

Single-ASIN smoke test:

```bash
node scripts/scrape_amazon_reviews_direct.mjs --asin B0F8QS88QD --max-pages 1 --debug-dir ../FWM_Data/00_raw_scraped_data/amazon/direct_amazon_debug
```

Notes:

- This is a fallback path for public review pages, not a replacement for Apify when Amazon blocks direct browser access.
- Keep `--sleep-ms` conservative; the default is intentionally slow.

### Dev Images Table Refresh

These scripts support the dev-only images-table refresh plan in
`docs/dev-images-table-refresh-plan.md`.

Safety rules:

- `SUPABASE_URL` must be the approved dev URL:
  `https://gosqgqpftqlawvnyelkt.supabase.co`
- Scripts abort when `SUPABASE_URL` is unset, points at production, or points at
  any non-approved Supabase project.
- Dev schema SQL belongs in `supabase/dev-migrations/`, not
  `supabase/migrations/`.
- Database write modes require a prior dry-run and
  `FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev`.

Dry-run commands:

```bash
npm run dev-images:migrations
npm run dev-images:reconcile-mobile
npm run dev-images:loader:dry-run -- --resolve-workbooks
npm run dev-images:attributes
npm run dev-images:taxonomy-audit -- --limit=25
npm run dev-images:orientation-audit -- --limit=100
npm run dev-images:measurement-audit:estimate -- --sample-size=100
```

The approved-images loader resolves source rows from the primary image-review
package plus current package directories under
`../FWM_Data/03_cv_annotated_pending_human_review/`. Add extra package
directories with `FWM_IMAGE_REVIEW_ADDITIONAL_PACKAGE_DIRS` when a dry-run
report shows missing source rows.

Write-mode loader apply is intentionally stricter than dry-run:

- it requires `--resolve-workbooks`
- it requires `FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev`
- it refuses unresolved mobile reconciliation, missing source rows, missing
  lookup IDs, and duplicate conflicts
- duplicate conflicts can only be skipped after report review with
  `FWM_DEV_IMAGE_LOAD_SKIP_DUPLICATE_CONFLICTS=yes-reviewed-dry-run`

Baseline manifest creation after a read-only `pg_dump --data-only` export:

```bash
npm run dev-images:baseline:export

# After reviewing the dry-run and confirming PROD_DATABASE_URL points to production:
npm run dev-images:baseline:export -- --apply
```

Or, if the export was created outside this script:

```bash
npm run dev-images:baseline:manifest -- \
  --export-file=/absolute/path/public_images.sql \
  --production-row-count=12345 \
  --pg-dump-version="$(pg_dump --version)"
```

The baseline restore script verifies the manifest checksum and dev guard first.
It does not restore unless run with `--apply`, `DEV_DATABASE_URL`, and the
explicit write flag.

After restore, verify the baseline count and sampled ID/URL preservation:

```bash
npm run dev-images:baseline:verify -- \
  --manifest=/absolute/path/baseline_public_images_export_YYYYMMDDTHHMMSSZ.json
```

After approved-image loads, verify all baseline IDs are still present while
allowing extra dev rows:

```bash
npm run dev-images:baseline:verify -- \
  --manifest=/absolute/path/baseline_public_images_export_YYYYMMDDTHHMMSSZ.json \
  --sample-limit=all \
  --allow-extra-rows
```

Baseline rows not matched to a reviewed workbook can be linked to dev-only
fallback review records with a dry-run-first workflow:

```bash
npm run dev-images:baseline:review-links

# After reviewing the report and confirming the dev target:
FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
  npm run dev-images:baseline:review-links -- --apply
```

Image attribute backfill is dev-only and conservative. It resets
loader-populated `full_body_visible = true` values back to `null` until a
head-and-feet visibility rule proves them, and it only proposes
`weeks_pregnant` updates when review text contains explicit pregnancy timing
with evidence:

```bash
npm run dev-images:attributes -- --limit=1000

# After reviewing the dry-run report:
FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
  npm run dev-images:attributes -- --limit=1000 --apply
```

The pregnancy parser has a small deterministic test suite for week/month
conversion, postpartum exclusions, and week-over-month precedence:

```bash
npm run dev-images:test:pregnancy-parser
```

Product-page availability status audit is dev-only, defaults to unchecked
product pages, respects robots.txt for the configured audit user agent, and
writes JSON plus HTML review reports before any promotion:

```bash
npm run dev-images:status-audit -- --limit=25

# Verify the report before any promotion:
npm run dev-images:report:verify -- \
  --type=status \
  --report=/absolute/path/dev_product_page_status_audit_YYYYMMDDTHHMMSSZ.json
```

Status promotions are a separate dev-only step. They take the exact verified
dry-run status report, write their own dry-run report, and produce a
human-review CSV for robots, blocked, timeout, unknown, or non-product redirect
rows:

```bash
npm run dev-images:status:promote -- \
  --status-report=/absolute/path/dev_product_page_status_audit_YYYYMMDDTHHMMSSZ.json \
  --verified-report=/absolute/path/dev_refresh_report_verify_status_YYYYMMDDTHHMMSSZ.json

# After reviewing the dry-run promotion report:
FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
  npm run dev-images:status:promote -- \
  --status-report=/absolute/path/dev_product_page_status_audit_YYYYMMDDTHHMMSSZ.json \
  --verified-report=/absolute/path/dev_refresh_report_verify_status_YYYYMMDDTHHMMSSZ.json \
  --apply
```

Browser status audit is a dry-run-only fallback for pages where direct fetch is
blocked or too shallow. It can take a previous status-audit report, opens
selected candidates with Playwright, writes screenshots plus JSON/HTML review
reports, and sends `robots_disallowed` or captcha/block pages to human review
instead of treating them as automated fixes. The default bucket list includes
`robots_disallowed`, but those URLs are not opened in the browser; they are
copied into the human-review CSV:

```bash
npm run dev-images:browser-status-audit -- \
  --status-report=/absolute/path/dev_product_page_status_audit_YYYYMMDDTHHMMSSZ.json \
  --limit=10 \
  --buckets=robots_disallowed,blocked_or_forbidden,timeout,unknown,redirected_to_non_product

npm run dev-images:report:verify -- \
  --type=browser-status \
  --report=/absolute/path/dev_product_page_browser_status_audit_YYYYMMDDTHHMMSSZ.json
```

Browser-status promotions are a separate dev-only step. They take a verified
browser-status report, skip all `human_review` rows, and only promote clear
browser statuses such as `live`, `out_of_stock`, `page_not_found`,
`product_unavailable`, and redirect buckets:

```bash
npm run dev-images:browser-status:promote -- \
  --browser-report=/absolute/path/dev_product_page_browser_status_audit_YYYYMMDDTHHMMSSZ.json \
  --verified-report=/absolute/path/dev_refresh_report_verify_browser-status_YYYYMMDDTHHMMSSZ.json

# After reviewing the dry-run promotion report:
FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
  npm run dev-images:browser-status:promote -- \
  --browser-report=/absolute/path/dev_product_page_browser_status_audit_YYYYMMDDTHHMMSSZ.json \
  --verified-report=/absolute/path/dev_refresh_report_verify_browser-status_YYYYMMDDTHHMMSSZ.json \
  --apply
```

Product-page taxonomy audit is dev-only and treats workbook clothing/category
values as hints. It fetches allowed product pages, extracts deterministic
category/tag evidence from structured data, title, breadcrumbs, description,
and URL slug, then writes JSON plus HTML review reports plus a human-review CSV
for skipped, ambiguous, or disagreement rows:

```bash
npm run dev-images:taxonomy-audit -- --limit=25

# Verify the report before any promotion:
npm run dev-images:report:verify -- \
  --type=taxonomy \
  --report=/absolute/path/dev_product_page_taxonomy_audit_YYYYMMDDTHHMMSSZ.json
```

Before applying taxonomy updates, review the promotion dry-run in the local
taxonomy dashboard. Each card shows the stored product URL, catalog image,
product title, one review image, and proposed taxonomy labels. Saving decisions
writes a `dev_taxonomy_review_decisions_*.json` approval report under
`../FWM_Data/_reports/taxonomy-review-decisions/`:

```bash
npm run taxonomy-review -- \
  --promotion-report=/absolute/path/dev_taxonomy_promotion_YYYYMMDDTHHMMSSZ.json
```

Taxonomy promotions are a separate dev-only step. They take the exact verified
dry-run report, skip ambiguous rows, skip workbook-fallback evidence, and only
promote allowed confidence levels. Apply mode requires the approval report from
the taxonomy review dashboard, and promotion dry-runs also write a skipped-rows
CSV for manual review:

```bash
npm run dev-images:taxonomy:promote -- \
  --taxonomy-report=/absolute/path/dev_product_page_taxonomy_audit_YYYYMMDDTHHMMSSZ.json \
  --verified-report=/absolute/path/dev_refresh_report_verify_taxonomy_YYYYMMDDTHHMMSSZ.json \
  --approval-report=/absolute/path/taxonomy-review-decisions/dev_taxonomy_review_decisions_YYYYMMDDTHHMMSSZ.json

# After reviewing the dry-run promotion report:
FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
  npm run dev-images:taxonomy:promote -- \
  --taxonomy-report=/absolute/path/dev_product_page_taxonomy_audit_YYYYMMDDTHHMMSSZ.json \
  --verified-report=/absolute/path/dev_refresh_report_verify_taxonomy_YYYYMMDDTHHMMSSZ.json \
  --approval-report=/absolute/path/taxonomy-review-decisions/dev_taxonomy_review_decisions_YYYYMMDDTHHMMSSZ.json \
  --apply
```

Image orientation audit is dev-only and conservative. It proposes display
rotation from EXIF/dimension evidence and stores approved corrections in
`crop_spec.rotationDeg` plus optional dev audit columns. Dry-runs write JSON,
HTML, and CSV review outputs:

```bash
npm run dev-images:orientation-audit -- --limit=100

# Verify the report before any promotion:
npm run dev-images:report:verify -- \
  --type=orientation \
  --report=/absolute/path/dev_image_orientation_audit_YYYYMMDDTHHMMSSZ.json
```

Orientation promotions are a separate dev-only step. They take the exact
verified dry-run report and only promote allowed confidence levels:

```bash
npm run dev-images:orientation:promote -- \
  --orientation-report=/absolute/path/dev_image_orientation_audit_YYYYMMDDTHHMMSSZ.json \
  --verified-report=/absolute/path/dev_refresh_report_verify_orientation_YYYYMMDDTHHMMSSZ.json

# After reviewing the dry-run promotion report:
FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
  npm run dev-images:orientation:promote -- \
  --orientation-report=/absolute/path/dev_image_orientation_audit_YYYYMMDDTHHMMSSZ.json \
  --verified-report=/absolute/path/dev_refresh_report_verify_orientation_YYYYMMDDTHHMMSSZ.json \
  --apply
```

Measurement LLM audit estimate is report-only. It samples dev rows with rich
comments and missing structured measurements, estimates token volume, and writes
the approval packet required before any LLM run. It does not call an LLM:

```bash
npm run dev-images:measurement-audit:estimate -- --sample-size=100

# Include current published pricing in the approval packet when known:
npm run dev-images:measurement-audit:estimate -- \
  --sample-size=100 \
  --model=<model-name> \
  --input-price-per-1m=<usd> \
  --output-price-per-1m=<usd> \
  --pricing-source=<url-or-doc-name> \
  --pricing-date=YYYY-MM-DD
```

Auto-crop backfill writes `crop_spec` (mode `cover-window`) into dev
`public.images` from YOLO detect+pose boxes. The crop decision is shared with the
review dashboard (`scripts/lib/detection-crop.mjs`) so what gets written equals
what was reviewed. Per the taxonomy-coverage decision, it writes only
`whole_body` / `garment_priority` / `garment_partial` modes and skips
`head_priority` (no usable garment region) plus no-person / fetch-error rows.

```bash
# 1. Detect person boxes + keypoints (CV venv) for the rows to crop:
../FWM_Data/_venv_cv/bin/python scripts/detect_person_boxes.py \
  --input /tmp/crop_sample.ndjson --output /tmp/crop_bboxes.ndjson \
  --detect-model ../FWM_Data/_models/yolov8n.pt --pose-model ../FWM_Data/_models/yolov8n-pose.pt

# 2. Visual review dashboard (original + overlays vs rendered 3:4 card):
npm run dev-images:crops:dashboard -- --input=/tmp/crop_bboxes.ndjson

# 3. Dry-run backfill (local report only, no Supabase writes):
npm run dev-images:crops:backfill -- --input=/tmp/crop_bboxes.ndjson

# 4. Verify the dry-run report:
npm run dev-images:report:verify -- \
  --type=crops --report=/absolute/path/dev_image_crop_backfill_YYYYMMDDTHHMMSSZ.json

# 5. Apply (writes crop_spec to dev only, behind all guards):
FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
  npm run dev-images:crops:backfill -- --input=/tmp/crop_bboxes.ndjson --apply \
  --verified-report=/absolute/path/dev_refresh_report_verify_crops_YYYYMMDDTHHMMSSZ.json
```

The catalog (clothing_type_id → mother_category) is built from dev
`staging.clothing_type_tags`; override with `--catalog=/path.json`. The apply step
only ever writes the small `crop_spec` JSON — it never uploads or alters image
bytes; cropping happens at render time from the window percentages.

Prettiness / photo-quality scoring (plan section 12) is dry-run only. The scorer
(`prettiness_domainfit_technical_v3`) applies deterministic rules over precomputed
YOLO/pose CV metrics and freshly decoded pixel stats — no model runs at score time
— and writes a score-distribution report, an HTML review sheet (top/middle/bottom
buckets), and a CSV. It never writes Supabase rows:

```bash
# First run rebuilds the workbook CV index cache (~395MB scan); later runs reuse it.
npm run dev-images:prettiness:dry-run -- --rebuild-cv-cache --limit=300
npm run dev-images:prettiness:dry-run -- --limit=300 --source=workbook --review-bucket=40
```

Components:

- `aspect_score`, `resolution_score` — from the fetched image header
  (JPEG/PNG/WebP dimensions).
- `body_visible_score` — how complete the body is in the source image, from the
  workbook YOLO/pose CV metrics (`scripts/lib/workbook-cv-index.mjs`, joined by
  `review_row_key`).
- `body_card_coverage_score` — crop-aware: how much of the body can survive the
  3:4 card crop and how much of the card it fills AFTER cropping
  (`scripts/lib/card-crop-geometry.mjs`). With a realized `crop_spec` it scores
  that window; without one it uses the position-independent **best-achievable**
  3:4 crop (croppability ceiling), not a naive centered crop. NOTE: under the
  no-bbox-position data we have, the ceiling equals the centered crop exactly, so
  low coverage on tall images is a true geometric limit (a person filling most of
  a very tall image cannot show head+feet in a 3:4 card at any placement), not a
  default-crop artifact. Auto-crop placement would change *which* body slice is
  shown, not this coverage ceiling, and is a separate workstream gated on
  re-running CV for bbox/keypoint positions.
- `technical_quality_score` (v3) — deterministic pixel stats from a decoded 96px
  thumbnail (`scripts/lib/pixel-stats.mjs`): `lighting_score` (exposure clipping,
  brightness, contrast, color cast) weighted 0.65 and `background_clutter_score`
  weighted 0.35. **Clutter is a COARSE whole-frame edge-busyness proxy** — with no
  person bbox position in the CV checkpoint it cannot isolate the background, so a
  busy outfit/pattern reads as clutter too. A clean subject-vs-background version
  is gated on the same CV re-run the crop work needs (person mask). On `--no-pixels`
  the technical bucket is skipped and the model reverts to `prettiness_domain_fit_v2`.
- `aesthetic_score` (CLIP, Phase 1) stays null. Smiling/composition belong here and
  ride along on that future CLIP pass.

Blend: the plan target is aesthetic 0.55 / technical 0.25 / domain-fit 0.20. While
aesthetic is null, technical's share is **clamped** to its planned 0.25 and
domain-fit absorbs the orphaned aesthetic weight (→ 0.75), i.e.
`prettiness = 0.25*technical + 0.75*domain_fit` — *not* the 0.56 technical share
that plain renormalization would hand a half-finished proxy bucket.

Flags: `--source=all|workbook|baseline` (baseline rows from the production
pg_dump have no CV match, so body components are null and the score falls back to
aspect + resolution + technical), `--no-pixels` (skip decode; v2 domain-fit only),
`--rebuild-cv-cache`, `--limit`, `--review-bucket`, `--timeout-ms`. The report also
reports the conservatively derived plan §11 `full_body_visible` boolean per row
(report only; not written).

Dry-run and estimate reports can be validated before review/apply:

```bash
npm run dev-images:report:verify -- \
  --type=taxonomy \
  --report=/absolute/path/dev_product_page_taxonomy_audit_YYYYMMDDTHHMMSSZ.json

npm run dev-images:report:verify -- \
  --type=orientation \
  --report=/absolute/path/dev_image_orientation_audit_YYYYMMDDTHHMMSSZ.json

npm run dev-images:report:verify -- \
  --type=status \
  --report=/absolute/path/dev_product_page_status_audit_YYYYMMDDTHHMMSSZ.json

npm run dev-images:report:verify -- \
  --type=browser-status \
  --report=/absolute/path/dev_product_page_browser_status_audit_YYYYMMDDTHHMMSSZ.json

npm run dev-images:report:verify -- \
  --type=measurement-estimate \
  --report=/absolute/path/dev_measurement_llm_audit_estimate_YYYYMMDDTHHMMSSZ.json

npm run dev-images:report:verify -- \
  --type=attributes \
  --report=/absolute/path/dev_image_attribute_backfill_YYYYMMDDTHHMMSSZ.json
```

Dev preview contract verification checks local config isolation and the dev
`match_by_measurements` RPC return shape:

```bash
npm run dev-images:preview:verify
```

Post-load dev database state verification checks image/review/product counts,
crop rotation validity, orientation consistency, nullable prettiness state,
taxonomy/status presence, and expected updated-at triggers:

```bash
npm run dev-images:state:verify
```
