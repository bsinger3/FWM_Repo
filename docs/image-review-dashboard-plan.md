# Image Review Dashboard Plan

## Goal

Replace the slow Google Sheets image-approval workflow with a focused web dashboard for rapidly reviewing CV-routed image rows while preserving the visual judgment context from the public Friends With Measurements cards.

The dashboard should let a reviewer:

- Open one tab for `approve_candidates` and quickly mark false positives with a red outline.
- Open one tab for `needs_human_review` and make explicit approve or disapprove calls.
- Open one tab for `disapprove_candidates` and quickly mark false negatives with a green outline.
- Choose a rejection reason once, then click or box-select many images to apply that reason.
- See the same image ratio, card scale, size, and measurement metadata used on the live Friends With Measurements cards.
- Export decisions back into the current spreadsheet-compatible review fields.

## Current Inputs

Primary current output folder:

`../FWM_Data/03_cv_annotated_pending_human_review/partial_170000_rows_cv_gated/`

Current package summary:

- `approve_candidates`: 72,113 rows across 73 workbooks.
- `needs_human_review`: 40,170 rows across 41 workbooks.
- `disapprove_candidates`: 211,918 rows across 212 workbooks.
- Total routed rows: 324,201.
- Workbooks are chunked at about 1,000 rows each.

Workbook families:

- `supabase_image_review_approve_candidates_part_NNN.xlsx`
- `supabase_image_review_needs_human_review_part_NNN.xlsx`
- `supabase_image_review_disapprove_candidates_part_NNN.xlsx`

Important columns already present:

- Decision fields: `production_decision`, `rejection_reason`, `review_notes`.
- Recommendation fields: `sorter_recommendation`, `sorter_reason_codes`, `cv_decision`, `cv_reason_code`, `cv_reason_summary`.
- CV metrics: `person_count_yolo_detect`, `main_person_height_pct_yolo_detect`, `main_person_bbox_area_pct_yolo_detect`, `body_coverage_score_yolo_pose`, `has_face_yunet`.
- Image fields: `image_preview`, `image_url_to_use`, `raw_scraped_image_url`, `needs_url_update`.
- Product/link fields: `product_page_url_display`, `monetized_product_url_display`, `brand`, `product_title_raw`, `product_category_raw`, `product_variant_raw`, `clothing_type_id`.
- Measurement fields: `size_display`, `height_in_display`, `weight_lbs_display`, `waist_in`, `hips_in_display`, `bust_in_display`, `bra_band_in_display`, `cupsize_display`, `inseam_inches_display`.
- Context and provenance: `user_comment`, `source_family`, `source_site_display`, `review_row_key`, `source_file`, `source_row_number`.

Current rejection-reason list:

- `LOW_RESOLUTION_AFTER_URL_REPAIR`
- `TOO_DARK`
- `TOO_BRIGHT_OR_WASHED_OUT`
- `BLURRY_OR_MOTION_BLUR`
- `GRAINY_OR_NOISY`
- `GARMENT_CUT_OFF`
- `GARMENT_TOP_COVERED`
- `GARMENT_BOTTOM_CUT_OFF`
- `GARMENT_OBSCURED`
- `PERSON_TOO_FAR`
- `TARGET_WEARER_AMBIGUOUS`
- `BAD_ANGLE_TOP_DOWN`
- `BAD_ANGLE_SIDE_OR_TWISTED`
- `BACKGROUND_TOO_CLUTTERED`
- `DISTRACTING_OBJECTS`
- `NOT_WORN_BY_PERSON`
- `NO_PERSON_VISIBLE`
- `WRONG_PRODUCT_CONTEXT`
- `DUPLICATE_OR_NEAR_DUPLICATE`
- `IMAGE_FETCH_FAILED`
- `OTHER`

## Existing Card Pattern To Reuse

The public site card style in `index.html` should be treated as the dashboard baseline:

- Grid uses `repeat(auto-fill, minmax(180px, 1fr))`.
- Card border radius is `8px`.
- Image uses `width: 100%`, `aspect-ratio: 3/4`, and `object-fit: cover`.
- Metadata is compact, with a primary row for size/color and a summary row for measurements.
- Existing displayed metrics include size, color, height, weight, bra/bust, hips, and waist.
- Existing image loading uses the configured image proxy first, then falls back to the original URL.

Dashboard cards should not become bigger spreadsheet cells. They should feel like reviewable versions of the live cards: same image geometry, same compact measurement pills, plus review-only overlays.

## Information Architecture

Use one reviewer-focused route, for example `/admin/image-review`, with three top-level tabs:

- `Approve Candidates`
  - Default recommendation: approve.
  - Reviewer action: move any card to approved, rejected, or neutral.
  - Visual state: green outline for explicit approve, red outline for explicit reject, neutral for no explicit human decision.
  - Requires a rejection reason before export unless the reason is inherited from an active bulk reason mode.

- `Needs Human Review`
  - Default recommendation: undecided.
  - Reviewer action: move any card to approved, rejected, or neutral.
  - Visual state: green outline for approve, red outline for disapprove, neutral for untouched.
  - Disapprove requires a reason.

- `Disapprove Candidates`
  - Default recommendation: disapprove.
  - Reviewer action: move any card to approved, rejected, or neutral.
  - Visual state: green outline for explicit approve, red outline for explicit reject, neutral for no explicit human decision.
  - Existing `cv_reason_code` remains visible so the reviewer can see why the image landed here.

The workbook bucket should be treated as the machine recommendation, not as a constraint. A reviewer must always be able to override or clear the decision regardless of whether the row came from an approve, needs-review, or disapprove workbook.

Add a persistent review toolbar:

- Bucket tabs with counts and changed counts.
- Current part selector, plus search by part number or source row key.
- Rejection reason dropdown.
- Selection mode toggle: `Click`, `Box Select`.
- Click mode segmented control: inspect, approve-on-click, reject-on-click.
- Action buttons: approve selected, disapprove selected, clear selected, clear decision.
- Bulk visible actions: approve all visible unmarked cards, reject all visible unmarked cards with the active reason.
- Per-card state controls: approve, reject, neutral, and open details/comment.
- Filters: changed only, untouched only, current human decision, rejection reason, reason for needing human review, CV reason, source family, clothing type, payout priority.
- Reason visibility toggle: show or hide reason chips on every card.
- Reason legend toggle: open or collapse a color-coded legend for the visible reason categories.
- Save/export status: unsaved changes count, last saved timestamp, output workbook count, export button.

## Reason Filters And Legend

Reason filtering should be a core workflow, especially for the `needs_human_review` tab.

Add a filter group that lets the reviewer narrow cards by:

- `cv_reason_code`, such as `BORDERLINE_BODY_COVERAGE`, `MULTIPLE_PEOPLE`, `BORDERLINE_SUBJECT_SIZE`, `SUBJECT_TOO_SMALL`, `BORDERLINE_COMPOSITION`, or `IMAGE_FETCH_FAILED`.
- `sorter_reason_codes`, when it gives additional non-CV context.
- Any existing `rejection_reason` already applied in a previous saved review session.
- Human decision state: unreviewed, approved, rejected, changed this session, saved previously.

Add a `Show reasons on cards` toggle:

- Off: cards keep the clean Friends With Measurements visual style and only show decision outlines.
- On: each card shows a small color-coded reason chip near the lower image edge or top of the metadata area.
- The chip should prefer the human-applied `rejection_reason` when present, then fall back to `cv_reason_code`, then fall back to the bucket label.
- Long reason labels should be shortened on-card, with the full reason available in a tooltip or expanded detail view.

Add a color-coded legend:

- The legend should list visible reason categories, the count currently shown for each, and the color used on cards.
- Clicking a legend row should toggle that reason as a filter.
- The legend should make multi-select filtering easy, so the reviewer can show, for example, both `BORDERLINE_BODY_COVERAGE` and `BORDERLINE_SUBJECT_SIZE`.
- Keep decision outlines semantically separate from reason colors: green/red outlines mean human approve/reject, while reason-chip color explains why the row is in the review queue or why it was rejected.

Initial color grouping:

- Body/framing issues: blue.
- Multiple or ambiguous people: purple.
- No person / not worn: gray.
- Image quality or fetch problems: amber.
- Product/context mismatch: red-orange.
- Duplicate/near duplicate: teal.
- Other: neutral.

## Card Content

Each card should show:

- Image from `image_url_to_use`, with fallback to `raw_scraped_image_url` if needed.
- Size and variant/color if available.
- Height in feet/inches, weight in pounds, bra/bust, waist, hips, inseam.
- Clothing type and source family as small secondary metadata.
- CV reason and compact metric chips:
  - person count
  - body coverage score
  - main person height percent
  - main person box area percent
- Optional expandable details:
  - user comment
  - product title/category/variant
  - product URL
  - monetized URL
  - source file and source row number
  - review row key

Card visual states:

- Explicit approve: green 3px outline.
- Explicit reject: red 3px outline plus reason chip when available.
- Neutral / no human decision: neutral border, regardless of source bucket.
- Untouched approve candidate: neutral border with approve-candidate recommendation available in the reason/recommendation chip when reason visibility is enabled.
- Untouched needs-review candidate: neutral border with "Needs review" chip.
- Untouched disapprove candidate: neutral border with `cv_reason_code` chip.
- Selected for bulk operation: blue focus outline or overlay, separate from final decision color.
- Image failed to load: muted card state with URL and `IMAGE_FETCH_FAILED` action available.
- Reason chip hidden or visible according to the `Show reasons on cards` toggle.
- Previously saved decision: same green/red decision outline, plus a subtle saved marker so reopened sessions clearly distinguish old saved work from new unsaved work.
- Comment present: small note marker on the card, visible even when the details panel is closed.

## Review Interaction Model

### Universal Card States

Every card can have exactly one human state:

- Neutral: no explicit human decision; keep the machine recommendation visible but do not treat it as a saved human decision.
- Approved: `production_decision = APPROVE`.
- Rejected: `production_decision = DISAPPROVE`, with `rejection_reason` required before export.

This state model must work the same way in all tabs and for all workbook types. The tab can change the default quick-action emphasis, but not which states are available.

Recommended controls:

- Small approve, reject, and neutral icon buttons on each card.
- Toolbar actions for selected cards: approve selected, reject selected, neutral selected.
- Toolbar click modes:
  - Inspect mode opens details or selects cards.
  - Approve mode marks any clicked card as approved.
  - Reject mode marks any clicked card as rejected with the active rejection reason.
- Toolbar bulk actions:
  - Approve every visible card that is still neutral.
  - Reject every visible card that is still neutral, using the active rejection reason.
- Keyboard shortcuts for the focused or selected card set.
- Optional single-click mode that applies the most common action for the active tab, while still exposing the other two states beside it.

### Card Details And Comments

Clicking into a card should open a detail drawer or modal without losing the reviewer position in the grid.

The detail view should include:

- Larger image preview using the same `image_url_to_use` fallback behavior.
- All visible card metadata plus product title/category/variant and user comment.
- CV recommendation, reason codes, and metrics.
- Source provenance fields.
- Approve, reject, and neutral controls.
- Rejection reason dropdown.
- Free-form comment box mapped to `review_notes`.
- Save/apply button and close button.

The free-form comment should support both approval and rejection notes. Examples:

- Rejection: "Looks like a product listing image, not a review photo."
- Rejection: "Good person detection, but the garment is mostly hidden by the coat."
- Approval: "Borderline crop, but enough of the jeans fit is visible."
- Approval: "Multiple people, but the reviewed wearer is clearly identifiable."

Cards with a free-form comment should show a small note marker so they are easy to find later. The `review_notes` field should be exported with the generated return workbook.

### Reason-First Bulk Review

When a rejection reason is selected, the reviewer can:

- Click cards in bulk-reason mode to apply `DISAPPROVE` with that reason.
- Drag a rectangle to box-select visible cards.
- Press "Disapprove selected" to apply the active reason.
- Change the active reason without changing already-marked cards.

This supports the workflow: "Everything in this visible cluster is `NO_PERSON_VISIBLE`" or "These are all `GARMENT_CUT_OFF`."

### Keyboard Shortcuts

Use keyboard support for speed, but mirror every shortcut with visible controls:

- `A`: mark selected as approve.
- `D`: mark selected as disapprove with active reason.
- `N`: return selected to neutral.
- `C`: open comment/details for the focused card.
- `R`: focus reason dropdown.
- `U`: clear decision on selected.
- `Shift` plus drag: box-select.
- Arrow keys: move focus through cards.
- Space: toggle current card according to active tab behavior.

## Data Model

Create a normalized review row shape in the dashboard layer:

```ts
type ImageReviewRow = {
  bucket: "approve_candidates" | "needs_human_review" | "disapprove_candidates";
  packageId: string;
  partNumber: number;
  partFile: string;
  rowKey: string;
  imageUrl: string;
  rawImageUrl?: string;
  productUrl?: string;
  monetizedProductUrl?: string;
  defaultDecision: "APPROVE" | "DISAPPROVE" | "NEEDS_HUMAN_REVIEW";
  humanState: "APPROVE" | "DISAPPROVE" | "NEUTRAL";
  productionDecision?: "APPROVE" | "DISAPPROVE" | "";
  rejectionReason?: string;
  reviewNotes?: string;
  savedDecisionState?: "unsaved" | "saved" | "exported";
  reviewedAt?: string;
  cvDecision?: string;
  cvReasonCode?: string;
  cvReasonSummary?: string;
  sorterRecommendation?: string;
  sorterReasonCodes?: string;
  cvMetrics: Record<string, string | number | null>;
  display: {
    size?: string;
    colorOrVariant?: string;
    clothingType?: string;
    heightIn?: number;
    weightLbs?: number;
    waistIn?: number;
    hipsIn?: number;
    bustIn?: number;
    braBandIn?: number;
    cupSize?: string;
    inseamIn?: number;
    userComment?: string;
  };
  source: {
    sourceFamily?: string;
    sourceSite?: string;
    sourceFile?: string;
    sourceRowNumber?: number;
  };
};
```

Decision export should preserve the current workbook semantics:

- Approve means `production_decision = APPROVE`, blank `rejection_reason`.
- Disapprove means `production_decision = DISAPPROVE`, populated `rejection_reason`.
- Neutral means blank `production_decision`, blank `rejection_reason`, and no saved human approval/rejection state.
- Notes remain optional in `review_notes`, and comments should be allowed for approved, rejected, and neutral cards.
- Untouched rows should remain untouched in generated output unless the reviewer explicitly asks to export a full reviewed copy.

## Persistence And Export

The original review workbooks are immutable inputs. The dashboard should never edit the files in `partial_170000_rows_cv_gated/` in place.

Use a four-stage persistence plan:

1. Local dashboard session state for fast review:
   - Store in browser local storage or IndexedDB by package ID, bucket, part, and `review_row_key`.
   - Autosave every few seconds.
   - Warn before leaving with unsaved changes.
   - On startup, load local decisions first so already-reviewed cards appear with their saved approve/reject state.

2. Durable return workbooks:
   - Add a `Save progress / Export decisions` button in the toolbar.
   - Clicking it writes new workbook files under `../FWM_Data/04_human_reviewed_ready_to_publish/human_labeled_returns/`.
   - The generated files should contain only reviewed or changed rows by default, grouped by source bucket and part.
   - Generated file names should include package ID or date, bucket, source part number, and timestamp, for example `human_labeled_approve_candidates_part_001_2026-06-02T153000.xlsx`.
   - The source workbook should be copied into the return workbook shape with updated `production_decision`, `rejection_reason`, and `review_notes`, while preserving provenance columns.
   - The export process should also write a compact manifest/index file that records which `review_row_key` values have been saved.

3. Resume from saved returns:
   - On dashboard load, scan `human_labeled_returns/` for prior return workbooks and manifests.
   - Merge saved decisions over the immutable source package by `review_row_key`, `bucket`, and `part_file`.
   - Cards already marked approve or reject should render as reviewed immediately, so the reviewer does not review them again.
   - Filters should include `saved previously` and `unreviewed only` states.
   - If a local unsaved decision conflicts with a saved return workbook, show the local newer decision as unsaved and include it in the next export.

4. Undo last export:
   - Add an `Undo last export` toolbar button next to save/export.
   - The button should use the manifest's latest `export_stamp` as the rollback unit.
   - Before undoing, show a confirmation with the export timestamp, generated workbook count, and affected decision count.
   - On confirm, delete only the generated files listed for that export from `human_labeled_returns/`.
   - Remove only decisions whose `export_stamp` matches the latest export from `human_labeled_returns_manifest.json`.
   - Remove the latest export entry from the manifest.
   - Leave original workbooks in `partial_170000_rows_cv_gated/` untouched.
   - Reload the current dashboard part so those cards are no longer shown as previously saved.
   - Prefer returning the undone decisions to local unsaved state if the user wants immediate revision without re-clicking, but never require this for correctness.

The first implementation may export both a compact machine-readable delta and workbook returns. The workbook return is the human workflow artifact; the delta is useful for reconciliation and testing.

Recommended return folder:

`../FWM_Data/04_human_reviewed_ready_to_publish/human_labeled_returns/`

Recommended generated artifacts:

- One or more `.xlsx` return workbooks containing saved reviewed rows.
- A `human_labeled_returns_manifest.json` file with package ID, export timestamp, source folder, source workbook names, row keys, decisions, reasons, and output workbook names.
- Optional CSV delta for easy diffing and quick pipeline ingestion.
- Undo metadata in the manifest: each export entry should list generated filenames and enough row keys to remove only that export's saved decisions.

Recommended first export shape:

```csv
bucket,part_file,review_row_key,source_file,source_row_number,default_decision,production_decision,rejection_reason,review_notes,reviewed_at
```

Do not make the first dashboard write directly into production tables. The first version should produce auditable generated return workbooks and a decision delta that can be reconciled against the existing pipeline.

## Loading Strategy

The dashboard should avoid loading all 324k rows at once.

Recommended path:

- Add a build step that converts the XLSX package into normalized JSONL or partitioned JSON files.
- Partition by bucket and part number, matching the existing workbook chunks.
- Load one part at a time in the browser, with next/previous part navigation.
- Add optional infinite scroll inside a part after the core review actions are stable.
- Use image lazy loading and keep the existing image proxy behavior.
- Cache only normalized metadata and decisions; do not copy image files locally.

Longer-term path:

- Store rows and reviewer decisions in Supabase staging tables.
- Page rows through an admin API with filters.
- Use row-level locks or assignment batches if more than one reviewer may work simultaneously.

## Suggested Implementation Phases

### Phase 1: Static Prototype

Build a local-only prototype from one approve part, one needs-review part, and one disapprove part.

Deliverables:

- Dashboard route or standalone HTML page.
- Three tabs.
- Existing card layout recreated with real output rows.
- Universal card state controls for approved, rejected, and neutral in every tab.
- Card detail drawer/modal with free-form `review_notes`.
- Reason dropdown.
- Reason filters for `needs_human_review` and CV reason codes.
- `Show reasons on cards` toggle.
- Color-coded reason legend with counts.
- Box-select interaction.
- Changed-count toolbar.
- Save progress / export button.
- Undo last export button.
- Generated return workbook or workbook-shaped export under `human_labeled_returns/`.
- Reload behavior that remembers previously saved approve/reject decisions.

Success check:

- A reviewer can process a visible page of images without opening Google Sheets.
- Export clearly maps back to `production_decision`, `rejection_reason`, and `review_notes`.

### Phase 2: Full Package Browser

Expand from sample parts to all generated part files.

Deliverables:

- XLSX-to-JSON conversion script.
- Part index with bucket counts.
- Part navigation and filters.
- Autosaved decisions.
- Resume where left off from local state and generated return workbooks.
- Export changed rows across all reviewed parts to `human_labeled_returns/`.
- Manifest merge logic so saved rows are not presented as unreviewed again.
- Undo-last-export flow that deletes the latest generated return files and removes only the latest export's manifest decisions.

Success check:

- The dashboard can review rows from the full `partial_170000_rows_cv_gated` package without browser slowdown.

### Phase 3: Pipeline Reconciliation

Make dashboard exports first-class pipeline inputs.

Deliverables:

- Importer for dashboard decision deltas.
- Importer for dashboard-generated return workbooks.
- Validation that disapproved rows have a reason.
- Validation that row keys still exist in the package.
- Summary report: approved rescues, disapproved removals, untouched rows, reason-code totals.
- Human-approved output package compatible with the current publish-ready flow.

Success check:

- Dashboard decisions can replace manual Google Sheets edits for one batch end to end.

### Phase 4: Admin-Grade Workflow

Move from local review artifact to durable admin tool.

Deliverables:

- Admin authentication.
- Reviewer identity on each decision.
- Assignment queues or batch claiming.
- Supabase staging tables for rows and decisions.
- Audit history per image/review row.
- Reopen and revise decisions.

Success check:

- Multiple review sessions can happen safely without losing or overwriting decisions.

## Open Design Decisions

- Whether the first version should live as a standalone local page under `tools/` or as an admin route in the existing static site.
- Whether to use CSV/JSON exports first or write directly to a Supabase staging table.
- Whether the default card click should open the detail drawer, select the card, or apply the active quick action.
- Whether the review unit should be individual image rows only, or optionally grouped by `review_row_key` / future canonical review group.
- Whether the dashboard should hide already-reviewed cards immediately or keep them visible with outlines until export.
- Whether the active rejection reason should be required before selecting cards, or only before applying disapprove.
- Whether return workbooks should contain only changed rows or full part copies with reviewed decisions overlaid.
- Whether `human_labeled_returns_manifest.json` should be the source of truth for resume state, or whether the dashboard should derive state from the workbooks each time.
- Exact reason color palette and grouping for CV reasons versus human rejection reasons.

## Recommended First Build Choice

Start with a local static prototype inside the repo, backed by normalized JSON generated from three workbook parts. This is the fastest way to validate the human-review interaction without changing production code or database behavior.

The prototype should deliberately reuse the live card CSS rules for image ratio and metadata density, then add only the review dashboard controls needed for speed: tabs, reason dropdown, reason filters, reason visibility toggle, legend, red/green outlines, click toggles, box selection, changed counts, save progress, generated return workbooks, and resume-from-saved decisions.
