# prAna scrape notes - 2026-05-11

## Triage

- Retailer: `prana_com`
- Domain: `prana.com`
- Triage rank: 58
- Triage bucket: `build adapter / API inspect`
- Provider hint: Bazaarvoice
- Fast-probe signal: structured size signals, no review-media hint

## Outcome

Built a public product-page scraper for prAna using the product sitemap and individual product pages only. The site exposes Bazaarvoice review widgets, but the public product HTML did not expose customer review bodies, customer review media, or deterministic reviewer measurements. Product pages did expose catalog model images plus deterministic variant-size tokens in `data-onmodel`; those rows were captured as catalog model rows with product URL, product title/category/color, ordered size, and source image dimensions.

Important access note: plain public `curl` requests returned full product HTML. Browser-like request headers returned stripped product HTML without `_digitalData` or `js-model-image` elements, so the scraper intentionally uses the simpler public request form. No disallowed Demandware endpoints, Bazaarvoice endpoint guessing, captcha handling, WAF bypass, or S3 sync was used.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_prana_reviews.py`
- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/prana_com/prana_com_reviews_matching_amazon_schema.csv`
- Summary: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/prana_com/prana_com_reviews_matching_amazon_schema_summary.json`

## Metrics

- Products discovered: 355
- Products scanned: 355
- Products excluded from output: 189
- Review pages scanned: 0
- Exhaustive review paging: true
- Product review count hint: 26,664
- Rows written: 166
- Distinct reviews: 166 synthetic catalog-model IDs
- Distinct images: 166
- Rows with distinct product URL: 166
- Rows with any measurement: 0
- Rows with customer image: 0
- Rows with catalog model image: 166
- Rows with customer ordered size: 166
- Supabase-qualified rows: 0
- Coverage exhaustive: true
- Errors: none

## Qualification

Rows are useful as deterministic product-size/catalog-model rows, but they do not qualify for the stricter customer-review measurement target because no public review text, customer media, or reviewer measurements were available in product HTML.
