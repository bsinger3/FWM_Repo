# AWIN Affiliate Link Generation Plan

Date: 2026-06-16

## Goal

Create a reusable pipeline script that scans FWM image/review CSV data, finds product-page URLs that belong to AWIN advertiser domains, and generates AWIN tracking links for those products. The script should produce a durable mapping artifact that can be used to backfill `monetized_product_url_display` without mutating source scrape files by default.

Important: AWIN generation is now one network-specific substep of the broader
affiliate monetization gate. Before packaging new scraped rows for image review
or Supabase publish, compare AWIN eligibility against Sovrn eligibility and pick
the better payout where both are available. See:

`FWM_Repo/data-pipelines/docs/affiliate_monetization_gate_runbook.md`

## API Contract

Use AWIN's publisher Link Builder API:

- Base URL: `https://api.awin.com`
- Endpoint: `POST /publishers/{publisherId}/linkbuilder/generate`
- Auth: `Authorization: Bearer <token>`
- Body fields:
  - `advertiserId`: required AWIN advertiser ID
  - `destinationUrl`: product page URL
  - `parameters`: optional click parameters such as `campaign`, `clickref`, `clickref2`, etc.
  - `shorten`: optional boolean
- Response fields:
  - `url`: generated AWIN tracking URL
  - `shortUrl`: optional shortened URL when `shorten` is true
- Limits:
  - AWIN documents a 20 API calls/minute throttle.
  - The link builder can create one tracking link or batches of up to 100 tracking links.

## Existing FWM Inputs

Use the current lifecycle layout and existing AWIN lead artifacts:

- Image/review source data:
  - `FWM_Data/00_raw_scraped_data/**/**/*_reviews_matching_*schema.csv`
  - Potentially later: approved/human-reviewed publish artifacts under `FWM_Data/04_human_reviewed_ready_to_publish/`
- Product URL columns:
  - `product_page_url_display`
  - `monetized_product_url_display`
- AWIN advertiser metadata:
  - `FWM_Data/_reports/measurement_coverage/20260609_human_labeled_approved_only/affiliate_network_leads/awin_program_review_scrape_join_recommendations.csv`
  - `FWM_Data/_reports/measurement_coverage/20260609_human_labeled_approved_only/affiliate_network_leads/awin_all_clothing_advertisers_triaged_2026-06-10.csv`
  - `FWM_Data/_reports/measurement_coverage/20260609_human_labeled_approved_only/affiliate_network_leads/awin_scrape_work_queue.csv`

The script should prefer metadata rows that include `advertiserId`, `normalized_domain`, `programmeName`, and `displayUrl`.

## Proposed Script

Add:

`FWM_Repo/data-pipelines/scripts/02_qualify_for_supabase/non_amazon/generate_awin_affiliate_links.py`

Responsibilities:

1. Load AWIN advertiser metadata and build a `normalized_domain -> advertiserId` lookup.
2. Scan bounded input CSVs for valid product URLs.
3. Normalize product URLs for dedupe while preserving the original destination URL sent to AWIN.
4. Match each product URL to an AWIN advertiser by hostname, including `www.` and subdomain variants.
5. Skip rows that already have an AWIN-looking `monetized_product_url_display` unless `--include-existing` is passed.
6. Generate affiliate links through the AWIN Link Builder API unless `--dry-run` is passed.
7. Write output mapping CSV plus a JSON run summary.

## CLI Shape

Required:

- `--publisher-id`: AWIN publisher ID, or `AWIN_PUBLISHER_ID`
- `--access-token`: AWIN API token, or `AWIN_ACCESS_TOKEN`

Useful options:

- `--input-root`: default `FWM_Data/00_raw_scraped_data`
- `--advertisers-csv`: repeatable, default the AWIN recommendation/triage CSVs above
- `--output-dir`: default `FWM_Data/_reports/affiliate_links/awin`
- `--limit`: cap products for smoke tests
- `--domain`: repeatable domain filter
- `--campaign`: optional AWIN campaign parameter, default `fwm_product_links`
- `--clickref-prefix`: optional deterministic clickref prefix
- `--shorten`: request AWIN `shortUrl`
- `--include-existing`: include rows with existing monetized URLs
- `--dry-run`: build the candidate set and output preview without API calls
- `--write-back`: optional later phase to produce updated copies of input CSVs, not in-place mutation

## Output Artifacts

Default output directory:

`FWM_Data/_reports/affiliate_links/awin/<run_id>/`

Files:

- `awin_affiliate_link_candidates.csv`
  - Candidate product URLs, source CSV path, advertiser match, and skip reason when not eligible.
- `awin_affiliate_link_map.csv`
  - One row per unique product URL sent to AWIN.
  - Columns: `normalized_product_url`, `destination_url`, `advertiserId`, `normalized_domain`, `programmeName`, `tracking_url`, `short_url`, `status`, `error`, `source_row_count`, `source_files`.
- `awin_affiliate_link_run_summary.json`
  - Counts, API status summary, unmatched domains, failures, and command/config metadata.

## Safety Rules

- Do not overwrite raw scrape files by default.
- Never print API tokens.
- Treat AWIN failures per product as row-level errors and continue the run.
- Sleep between API calls to stay under 20 calls/minute.
- Keep enough source-file provenance to update downstream Supabase-ready data later.
- Use `pipeline_paths.py` so the script respects `FWM_DATA_DIR`.

## Implementation Steps

1. Implement helper functions for URL/domain normalization, advertiser lookup loading, input CSV discovery, and candidate extraction.
2. Implement dry-run candidate generation first and verify it against a small domain such as `shopbrabar.com` or `baleaf.com`.
3. Implement AWIN API client with Bearer auth, JSON body, retry/backoff for 429/5xx, and safe error capture.
4. Add output writers for candidates, link map, and run summary.
5. Run a dry-run smoke test with `--limit 10` and one AWIN domain.
6. Compile the script with `python3 -m py_compile`.
7. Leave live API execution for when `AWIN_ACCESS_TOKEN` and `AWIN_PUBLISHER_ID` are available in the environment.

## Open Questions

- Whether FWM wants all raw scraped AWIN product links monetized first, or only rows that survive human review.
- Whether clickrefs should include source-row identity, normalized product identity, or only a campaign-level marker.
- Whether downstream write-back should update Supabase staging CSVs or generate a separate join table for the app import.
