# Spinnaker Boutique scrape notes - 2026-05-27

## Triage

- Retailer: `spinnakerboutique_com`
- Domain: `spinnakerboutique.com`
- Source: `data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv`
- Triage bucket: `sovrn_first_pass_scrape_candidate`
- Provider hint: Loox
- Reviews/photo reviews present: yes
- Shipping geos: `US`
- Conversion signal: `3.17%`
- Commission/AOV: not populated in triage

## Outcome

The public seed category and PDPs were accessible with normal HTTP 200 HTML and no captcha/WAF/auth block. The scrape checked the triage seed category, the two sample PDPs, the wishlist evidence URL, and 20 product pages linked from the seed jeans category.

No public Loox review source was exposed in those pages:

- No `loox.io/widget/...` app ID
- No `Loox.shop` setting
- No `images.loox.io` media
- No `loox-review` or `loox-photo` widget markup

Because the public pages exposed product metadata/catalog imagery but no customer review-photo source, no intake rows were emitted.

## Public Probes

- `https://www.spinnakerboutique.com/it-IT/donna/abbigliamento/jeans`
- `https://www.spinnakerboutique.com/it-IT/products/guestwishlist`
- `https://www.spinnakerboutique.com/it-IT/product/62317/miu_miu/jeans/jeans`
- `https://www.spinnakerboutique.com/it-IT/product/62293/versace/jeans/jeans`

The category page exposed 36 product links; the run checked 20 category product pages including the sample PDPs.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_spinnakerboutique_reviews.py`
- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\spinnakerboutique_com\spinnakerboutique_com_reviews_matching_intake_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\spinnakerboutique_com\spinnakerboutique_com_reviews_matching_intake_schema_summary.json`

## Metrics

- Category product links found: 36
- Product pages checked: 20
- Products scanned: 20
- Review pages scanned: 0
- Exhaustive review paging: false
- Rows written: 0
- Distinct reviews: 0
- Distinct images: 0
- Rows with distinct product URL: 0
- Rows with any measurement: 0
- Rows with customer image: 0
- Rows with customer ordered size: 0
- Supabase-qualified rows: 0

## Revisit Notes

Revisit only if a documented public Loox/widget endpoint or another public customer-review media endpoint is found. Do not use auth flow, private endpoints, captcha solving, WAF bypass, or pressure retries.
