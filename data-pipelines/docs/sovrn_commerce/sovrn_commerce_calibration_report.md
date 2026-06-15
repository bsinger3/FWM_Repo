# Sovrn Commerce Calibration Report

Generated: 2026-05-27

Inputs:

- Plan: `data-pipelines/docs/sovrn_commerce/sovrn_commerce_scraping_triage_plan.md`
- Full tracker: `data-pipelines/docs/sovrn_commerce/sovrn_commerce_apparel_triage_tracker.csv`
- Calibration batch: `data-pipelines/docs/sovrn_commerce/sovrn_commerce_calibration_batch.csv`

Implementation:

- Script: `data-pipelines/scripts/02_qualify_for_supabase/sovrn/triage_sovrn_commerce_calibration.mjs`
- Output: `data-pipelines/docs/sovrn_commerce/sovrn_commerce_calibration_results.csv`

## Calibration Summary

- Merchants checked: 10
- Generic triage candidates: 2
- Blocked or needs manual/merchant-specific review: 8
- Rows with known shipping country evidence: 10
- Rows with multi-country shipping/storefront evidence: 6
- Rows with product sample URLs found: 2

## Results

| Merchant | Result | Review signal | Photo review signal | Shipping geos | Notes |
| --- | --- | --- | --- | --- | --- |
| Alo Yoga | blocked_or_needs_manual_review | unknown | unknown | US | Category evidence found; browser pass saw possible challenge/security signal. |
| Anthropologie | blocked_or_needs_manual_review | unknown | unknown | DE\|EU\|GB\|US | Homepage returned HTTP 403 in the browser pass. |
| ASOS | blocked_or_needs_manual_review | unknown | unknown | AU\|DE\|FR\|US | Homepage returned HTTP 403 in the browser pass. |
| Banana Republic | blocked_or_needs_manual_review | unknown | unknown | AU\|CA\|EU\|US | Category evidence found; browser pass saw possible challenge/security signal. |
| boohoo | triage_candidate | yes | yes | AU\|CA\|DE\|FR\|GB\|IE\|NL\|SE\|US | Category, product samples, Bazaarvoice, size signals, and review-photo signals found. |
| Chico's | triage_candidate | yes | unknown_sample_too_small | US | Category, product samples, Bazaarvoice, and size signals found; sampled pages did not prove photo reviews. |
| Everlane | blocked_or_needs_manual_review | unknown | unknown | AU\|CA\|GB\|US | Category evidence found; browser pass saw possible challenge/security signal. |
| Express Clothing | blocked_or_needs_manual_review | unknown | unknown | CA\|US | Category evidence found; browser pass saw possible challenge/security signal. |
| H&M | blocked_or_needs_manual_review | unknown | unknown | US | Homepage returned HTTP 403 in the browser pass. |
| J. Crew | blocked_or_needs_manual_review | unknown | unknown | US | Homepage returned HTTP 403 in the browser pass. |

## Calibration Takeaways

- The generic Playwright triage path is useful for sites that expose category/product links and review widgets to a normal browser session. It successfully identified boohoo and Chico's as first-pass scrape candidates.
- Large brands often need merchant-specific triage handling before review/photo feasibility can be decided. Several sites returned HTTP 403 or challenge-like signals before product samples were available.
- Shipping geo capture worked as a first-pass field. The current script combines storefront locale/domain evidence with public shipping-policy country detection when available.
- Shipping evidence should remain conservative. The tracker records `product_url_geo_inheritance` separately so product-level staging can decide whether merchant-level country evidence is enough or product-level verification is required.

## Recommended Next Implementation Step

Start scrape-feasibility work with the two confirmed generic candidates:

1. `boohoo`
2. `Chico's`

For blocked/manual-review merchants, add merchant-specific public endpoint probes only when they can be inspected without captcha, WAF bypass, login, checkout automation, or private APIs.
