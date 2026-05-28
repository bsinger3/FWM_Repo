# Luxefashion Clothing Scrape - 2026-05-27

Source: payout-prioritized Sovrn triage candidate from `sovrn_commerce_scrape_triage_candidates.csv`.

- Merchant: `luxefashionclothing_com`
- Triage facts: first-pass candidate, CPA, `photo_reviews=yes`, reviews present, shipping `US`, provider unknown.
- Payout note: Sovrn payout fields were not populated.
- Category evidence URL: `https://luxefashionclothing.com/product-category/women/womens-lingerie/bathing-suits-beachwear-swimwear/beach-dresses-cover-ups-pareos/`
- Sample PDPs:
  - `https://luxefashionclothing.com/product/beach-dress-model-164140-marko/`
  - `https://luxefashionclothing.com/product/beach-dress-model-164141-marko/`
  - `https://luxefashionclothing.com/product/beach-dress-model-179491-madora/`

## Pre-Scrape Checks

- Checked repo scripts/docs and data-root `_active_scrape_claims`, `_claims`, and output directories for `luxefashion`, `luxe fashion`, `luxefashionclothing`, and `luxefashionclothing_com`.
- No prior Luxe Fashion Clothing scrape script, output directory, active claim, completed claim, or scrape doc was found.
- Added active claim at `FWM_Data/non-amazon/data/step_1_raw_scraping_data/_active_scrape_claims/luxefashionclothing_com.claim` before probing/scraping.

## Public Implementation Finding

- Platform: WordPress + WooCommerce.
- Review implementation: native WooCommerce reviews/comments.
- The sample PDPs expose native review tabs, but each sampled public tab/comment feed had zero reviews.
- No Yotpo, Loox, Judge.me, Stamped, Okendo, CusRev, or other third-party review provider was found in the sampled public pages.
- Usable media source: public WordPress product media attachments for the triage category.

The scrape used public pages/endpoints only. No auth, captcha, WAF bypass, or non-public endpoint was used.

## Output

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_luxefashionclothing_reviews.py`
- CSV: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/luxefashionclothing_com/luxefashionclothing_com_reviews_matching_intake_schema.csv`
- Summary: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/luxefashionclothing_com/luxefashionclothing_com_reviews_matching_intake_schema_summary.json`

## Results

- Products discovered: 107 from public WordPress product category `189`.
- Products scanned: 107.
- Public native comment endpoints sampled: 3 products, 0 comments.
- Review pages scanned: 0 third-party/native review-media pages; native comments were sampled and empty.
- Rows written: 16 catalog product/gallery image rows.
- Distinct product URLs with rows: 8.
- Rows with customer image: 0.
- Rows with catalog model/product image: 16.
- Rows with ordered size: 0.
- Rows with at least one measurement: 0.
- Strict customer-review Supabase-qualified rows: 0.
- Catalog image rows with image + product URL: 16.
- Errors: none.

Validation notes:

- CSV row count matches `rows_written` in the summary.
- Sampled product image URL returned HTTP 200 with `image/jpeg`.
- Sampled Luxe Fashion Clothing product URL returned HTTP 200 with `text/html`.
- Normalized numeric measurement fields in the summary validator reported zero invalid values.

Follow-up note: this appears to be a catalog-media scrape, not a customer-review-photo scrape, despite the Sovrn triage flag. The public WooCommerce review implementation did not expose customer photo reviews in the sampled evidence pages.
