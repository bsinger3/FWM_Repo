# Sovrn Commerce Full Merchant Triage Report

Generated: 2026-05-27

## Scope

This pass triaged every merchant in `sovrn_commerce_apparel_triage_tracker.csv` before starting any normal scraping work.

Shoes and footwear are out of scope for the current shopping workflow. Footwear-only merchants were reclassified to `P4` with `scrape_feasibility=excluded_or_low_size_importance`.

Every visited e-commerce site was checked for merchant-level shipping geography where public signals were available. Shipping evidence is stored in:

- `ships_to_country_codes`
- `shipping_geo_status`
- `shipping_geo_evidence_url`
- `shipping_geo_evidence_basis`
- `primary_market_country`
- `product_url_geo_inheritance`

## Completion

| Metric | Count |
| --- | ---: |
| Total merchants | 1,012 |
| Checked merchants | 1,012 |
| Unchecked merchants | 0 |
| Full result rows | 1,012 |
| Triage candidates | 43 |
| Rows with shipping country evidence | 477 |
| Rows with unknown shipping countries | 535 |

## Priority Counts After Cleanup

| Priority | Count |
| --- | ---: |
| P1 | 79 |
| P2 | 360 |
| P3 | 92 |
| P4 | 481 |

## Feasibility Outcomes

| Outcome | Count |
| --- | ---: |
| `excluded_or_low_size_importance` | 481 |
| `blocked_or_needs_manual_review` | 390 |
| `triage_candidate` | 43 |
| `blocked_or_unreachable` | 43 |
| `needs_manual_category_confirmation` | 35 |
| `category_confirmed_review_unknown` | 13 |
| `marketplace_requires_category_level_review` | 7 |

## Candidate Handling

The 43 `triage_candidate` rows are not a command to start scraping yet. They are the first candidate pool from the full merchant triage pass and should be reviewed/prioritized before scraper implementation.

Broad marketplaces are marked `marketplace_requires_category_level_review`; they need deliberate apparel-category selection before any product URL discovery.

Rows marked `blocked_or_needs_manual_review` or `blocked_or_unreachable` should not be worked around with bot-bypass tactics. Treat them as manual-review or lower-priority integration candidates unless there is a normal public route available.

## Files

- Full tracker: `data-pipelines/docs/sovrn_commerce/sovrn_commerce_apparel_triage_tracker.csv`
- Full checked-row snapshot: `data-pipelines/docs/sovrn_commerce/sovrn_commerce_full_tracker_triage_results.csv`
- Runner: `data-pipelines/scripts/02_qualify_for_supabase/sovrn/triage_sovrn_commerce_calibration.mjs`

## Next Step

Review the 43 `triage_candidate` rows, remove obvious false positives from the candidate pool, then rank the remaining merchants by review/photo signal quality, shipping-country coverage, and expected implementation effort.
