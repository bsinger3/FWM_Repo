# Wild Secrets Lingerie NZ scrape - 2026-05-27

## Source and scope

- Triage source: `data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv`
- Target: `wildsecretslingerie_co_nz` / `www.wildsecretslingerie.co.nz`
- Sovrn triage facts: first-pass candidate, CPA, reviews present, photo review status `unknown_sample_too_small`, shipping `AU|NZ|US`, provider unknown, payout fields not populated.
- Access policy: public SearchSpring product API and public PDP HTML only. The scraper stops on 429/captcha/WAF/auth-like responses.

## Implementation

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_wildsecretslingerie_co_nz_reviews.py`
- Discovery: public SearchSpring endpoint `vua081.a.searchspring.io/api/search/search.json` sorted by `ratingavg`.
- Provider identified: native PHE/Excite `ProductReview` markup embedded in public PDP HTML. No Bazaarvoice/Yotpo/Loox/Judge/Stampled/reviews.io customer-photo provider was found in sampled PDPs.
- Image policy: review text is native customer review text, but no customer-uploaded review media was exposed in sampled public review markup. Rows therefore use `image_source_type=catalog_model_image`, pairing native review text with public product gallery/model images and variant size/color data.

## Output

- CSV: `C:/Users/bsing/OneDrive/Documents/Projects/FWM/FWM_Data/non-amazon/data/step_1_raw_scraping_data/wildsecretslingerie_co_nz/wildsecretslingerie_co_nz_reviews_matching_intake_schema.csv`
- Summary: `C:/Users/bsing/OneDrive/Documents/Projects/FWM/FWM_Data/non-amazon/data/step_1_raw_scraping_data/wildsecretslingerie_co_nz/wildsecretslingerie_co_nz_reviews_matching_intake_schema_summary.json`
- Rows written: 35
- Distinct products: 16
- Rows with native review text: 35
- Rows with catalog model image: 35
- Rows with customer review image: 0
- Errors: 0

## Notes

- Some SearchSpring results have `ratingcount=0`; those are recorded as skipped in the summary and were not output.
- The public PDP review block exposes reviewer nickname, date, comment, verification marker, and optional demographic questions. It did not expose customer photo URLs in the sampled products.
