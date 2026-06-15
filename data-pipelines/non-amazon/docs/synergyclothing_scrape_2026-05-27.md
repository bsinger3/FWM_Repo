# Synergy Clothing scrape notes - 2026-05-27

## Triage

- Retailer: `synergyclothing_com`
- Domain: `synergyclothing.com`
- Source: `data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv`
- Triage bucket: `sovrn_first_pass_scrape_candidate`
- Triage facts: CPC, CPC amount not populated, reviews present, photo reviews present, shipping `US`, provider unknown.
- Evidence URL: `https://www.synergyclothing.com/category/shop-organic/womens-collection/`

## Outcome

The public seed URL returned normal HTTP 200 HTML and no captcha/WAF/auth block, but the live site no longer exposes a product/review surface matching the triage facts.

Observed public surface:

- The seed category is a WordPress/Elementor content category, not a product listing.
- WordPress REST for category `28` returned zero posts.
- Public WordPress search returned only posts/pages, not products.
- No review provider markers were found on the seed page (`Yotpo`, `Judge.me`, `Loox`, `Stamped`, `Okendo`, `Bazaarvoice`, `PowerReviews`, `reviews.io`, `Trustpilot`, or native WooCommerce review markup).
- Common commerce paths returned 404:
  - `https://www.synergyclothing.com/shop/`
  - `https://www.synergyclothing.com/products.json`
  - `https://www.synergyclothing.com/product-category/womens-collection/`

Because there were no public PDPs, review widgets, customer-photo sources, catalog product cards, or fit/variant data on the current live public site, no intake rows were emitted.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_synergyclothing_reviews.py`
- CSV: `C:/Users/bsing/OneDrive/Documents/Projects/FWM/FWM_Data/non-amazon/data/step_1_raw_scraping_data/synergyclothing_com/synergyclothing_com_reviews_matching_intake_schema.csv`
- Summary: `C:/Users/bsing/OneDrive/Documents/Projects/FWM/FWM_Data/non-amazon/data/step_1_raw_scraping_data/synergyclothing_com/synergyclothing_com_reviews_matching_intake_schema_summary.json`

## Metrics

- Products discovered: 0
- Products scanned: 0
- Review pages scanned: 0
- Rows written: 0
- Rows with customer review image: 0
- Rows with catalog model image: 0
- Errors: 0

## Revisit Notes

Revisit only if a current public product/category URL or public review media endpoint is documented. Continue to avoid auth flows, private endpoints, captcha solving, WAF bypass, or pressure retries.
