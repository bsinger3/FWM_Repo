# Affiliate Monetization Gate Runbook

Date: 2026-06-16

## Purpose

Every new non-Amazon scrape batch should pass through an affiliate monetization
gate before image-review packaging or Supabase-ready exports. The gate decides
whether each qualified row can use an AWIN affiliate link, a Sovrn affiliate
link, or no monetized link yet, and records why.

This is a pipeline step, not a one-off cleanup. Raw scrape files stay immutable;
the gate writes durable mapping artifacts and review-package copies.

## When To Run

Run this after a scrape writes rows under:

`FWM_Data/00_raw_scraped_data/<merchant_slug>/`

and before building dashboard workbooks under:

`FWM_Data/03_cv_annotated_pending_human_review/`

The input population should usually be broad Supabase-qualified image rows:

- `original_url_display` is present.
- `product_page_url_display` or a non-affiliate `monetized_product_url_display`
  is present.
- The row is not a catalog image row.
- At least one size or measurement signal is present.

## Source Metadata

### AWIN

Use these advertiser metadata sources:

- `FWM_Data/_reports/measurement_coverage/20260609_human_labeled_approved_only/affiliate_network_leads/awin_program_review_scrape_join_recommendations.csv`
- `FWM_Data/_reports/measurement_coverage/20260609_human_labeled_approved_only/affiliate_network_leads/awin_all_clothing_advertisers_triaged_2026-06-10.csv`
- `FWM_Data/_reports/measurement_coverage/20260609_human_labeled_approved_only/affiliate_network_leads/awin_scrape_work_queue.csv`

The live Link Builder script is:

`FWM_Repo/data-pipelines/scripts/02_qualify_for_supabase/non_amazon/generate_awin_affiliate_links.py`

It must read credentials from environment variables only:

- `AWIN_PUBLISHER_ID`
- `AWIN_ACCESS_TOKEN`

Do not put AWIN tokens on the command line or in output artifacts.

### Sovrn

Use these triage sources:

- `FWM_Repo/data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv`
- `FWM_Repo/data-pipelines/docs/sovrn_commerce/sovrn_commerce_apparel_triage_tracker.csv`

Important Sovrn fields:

- `primary_domain` or `primary_domains`
- `pricing`
- `estimated_commission_per_click`
- `avg_conversion_rate_examples`
- `avg_commission_rate_examples`
- `avg_order_value_examples`
- `payout_priority_rank`
- `priority`

## Decision Rule

For each normalized product URL:

1. Match the product hostname against AWIN advertiser domains.
2. Match the product hostname against Sovrn merchant domains.
3. Estimate payout for each available network.
4. Choose the better network.
5. Generate/store the chosen monetized URL.
6. Preserve the alternate candidate metadata for audit.

Tie-break order:

1. Higher estimated commission per click.
2. If estimates are unavailable or tied, prefer a live generated AWIN tracking
   URL over an ungenerated or unresolved Sovrn option.
3. If both networks are available but payout is unknown for both, prefer the
   network with stronger known program state:
   AWIN approved/applied queue match first, then Sovrn `CPA+CPC`, then Sovrn
   `CPA`, then manually review.
4. If neither network can be linked, keep `product_page_url_display` as the raw
   product URL and leave `monetized_product_url_display` blank.

Estimated commission per click should be interpreted consistently:

- Sovrn: prefer `estimated_commission_per_click` when present.
- AWIN: prefer `epc` when present. Treat AWIN EPC as a comparable ranking value
  only after documenting its unit/source in the run summary. If EPC units are
  ambiguous for a given export, use AWIN as available-but-unknown and let the
  tie-break rule decide.

## Required Output

Every monetization gate run should write:

`FWM_Data/_reports/affiliate_links/<run_id>/`

with:

- `affiliate_link_candidates.csv`
  - one row per source image row considered
  - raw product URL
  - normalized product URL
  - source CSV
  - source row number
  - source image URL
  - Supabase qualification status
  - AWIN match fields
  - Sovrn match fields
  - selected network
  - selected reason
- `affiliate_link_map.csv`
  - one row per normalized product URL
  - selected monetized URL
  - selected network
  - selected estimated payout
  - alternate network and payout
  - generation status
  - errors
- `affiliate_link_run_summary.json`
  - input roots
  - source CSV count
  - qualified row count
  - unique product URL count
  - AWIN candidate count
  - Sovrn candidate count
  - selected network counts
  - generated URL counts
  - failure counts
  - timestamp

The image-review package should then copy the selected URL into:

`monetized_product_url_display`

while preserving:

`product_page_url_display`

## Current AWIN Command Pattern

Applied-AWIN queue, Supabase-qualified rows only:

```bash
zsh -lic 'cd /Users/briannasinger/Projects/FWM/FWM_Repo && python3 data-pipelines/scripts/02_qualify_for_supabase/non_amazon/generate_awin_affiliate_links.py --supabase-qualified-only --domains-csv /Users/briannasinger/Projects/FWM/FWM_Data/_reports/measurement_coverage/20260609_human_labeled_approved_only/affiliate_network_leads/awin_scrape_work_queue.csv --run-id awin_applied_supabase_qualified_links_YYYYMMDD'
```

Build a dashboard package from generated AWIN links:

```bash
/Users/briannasinger/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 /Users/briannasinger/Projects/FWM/FWM_Repo/data-pipelines/scripts/03_cv_annotate/non_amazon/build_awin_image_review_package.py --candidates-csv /Users/briannasinger/Projects/FWM/FWM_Data/_reports/affiliate_links/awin/<run_id>/awin_affiliate_link_candidates.csv --link-map-csv /Users/briannasinger/Projects/FWM/FWM_Data/_reports/affiliate_links/awin/<run_id>/awin_affiliate_link_map.csv --output-dir /Users/briannasinger/Projects/FWM/FWM_Data/03_cv_annotated_pending_human_review/awin_supabase_qualified_linked_YYYYMMDD
```

Start the dashboard on that package:

```bash
cd /Users/briannasinger/Projects/FWM/FWM_Repo
FWM_IMAGE_REVIEW_PACKAGE_DIR=/Users/briannasinger/Projects/FWM/FWM_Data/03_cv_annotated_pending_human_review/awin_supabase_qualified_linked_YYYYMMDD npm run image-review
```

## Selector Script

The network-vs-network selector is:

`FWM_Repo/data-pipelines/scripts/02_qualify_for_supabase/non_amazon/select_affiliate_links.py`

It:

1. Reuses the broad Supabase-qualified row filter from
   `generate_awin_affiliate_links.py`.
2. Loads AWIN and Sovrn metadata.
3. Builds one decision table for AWIN/Sovrn/no-link eligibility.
4. Selects the better network by estimated payout and tie-break rules.
5. Writes `affiliate_link_candidates.csv`, `affiliate_link_map.csv`, and
   `affiliate_link_run_summary.json`.

Example scoped run for the applied-AWIN queue:

```bash
python3 /Users/briannasinger/Projects/FWM/FWM_Repo/data-pipelines/scripts/02_qualify_for_supabase/non_amazon/select_affiliate_links.py --domains-csv /Users/briannasinger/Projects/FWM/FWM_Data/_reports/measurement_coverage/20260609_human_labeled_approved_only/affiliate_network_leads/awin_scrape_work_queue.csv --run-id affiliate_selection_awin_queue_YYYYMMDD
```

Important implementation gap: this selector currently chooses the winning
network and writes the audit table, but network-specific URL generation still
uses the dedicated generators. AWIN winners should be passed to
`generate_awin_affiliate_links.py`. Sovrn winners should be passed to the
approved Sovrn link-generation/integration path once that is pinned down.
