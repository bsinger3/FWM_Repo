# Yoga Democracy Scrape - 2026-05-27

Source: payout-prioritized Sovrn triage candidate from `sovrn_commerce_scrape_triage_candidates.csv`.

- Merchant: `yogademocracy_com`
- Triage facts: first-pass candidate, Yotpo, `photo_reviews=yes`, reviews present, shipping `US`.
- Payout note: Sovrn payout fields were not populated, so this was a focused safe scrape/probe before any broad crawling.
- Category evidence URL: `https://www.yogademocracy.com/shop/tops/`

## Pre-Scrape Checks

- Checked repo scripts/docs and data-root `_active_scrape_claims`, `_claims`, and output directories for `yogademocracy`, `yoga democracy`, and `yogademocracy_com`.
- No prior Yoga Democracy scrape script, output directory, active claim, completed claim, or scrape doc was found.
- Added active claim at `FWM_Data/non-amazon/data/step_1_raw_scraping_data/_active_scrape_claims/yogademocracy_com.claim` before probing/scraping.

## Public Sources Used

- Public category evidence page: `https://www.yogademocracy.com/shop/tops/`
- Adjacent public category pages exposed from the category nav: bottoms, shorts, tanks, sports bras, and inseam update.
- Public Demandware category pagination endpoint: `Search-UpdateGrid`.
- Public product pages for product metadata.
- Public Yotpo aggregate review JSON with app key exposed on category/PDP HTML: `YVXTEHoqp4n0JhHEBNigfesPIxNLjbyOSszJl7nI`.

The scrape used public pages/endpoints only. No auth, captcha, WAF bypass, or non-public endpoint was used.

## Output

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_yogademocracy_reviews.py`
- CSV: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/yogademocracy_com/yogademocracy_com_reviews_matching_intake_schema.csv`
- Summary: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/yogademocracy_com/yogademocracy_com_reviews_matching_intake_schema_summary.json`

## Results

- Category products discovered: 472.
- Yotpo products scanned/mapped: 84.
- Public Yotpo review pages scanned: 7.
- Exhaustive review paging: yes, for the small public aggregate feed.
- Rows written: 6 customer review image rows.
- Distinct product URLs with rows: 6.
- Rows with customer image: 6.
- Rows with ordered size: 2.
- Rows with at least one measurement: 4.
- Supabase-qualified rows: 2.
- Missing product URL reviews: 0.
- Errors: none.

Validation notes:

- CSV row count matches `rows_written` in the summary.
- Sampled customer image URL returned HTTP 200 with `image/jpeg`.
- Sampled Yoga Democracy product URL returned HTTP 200 with `text/html`.
- Normalized numeric measurement fields in the summary validator reported zero invalid values.

Follow-up note: the public Yotpo aggregate feed reports 644 reviews, but only six reviews expose customer media. The focused pass found all six media reviews on page 1; pages 2-7 had no image reviews.
