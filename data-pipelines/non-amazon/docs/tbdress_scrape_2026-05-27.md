# TB Dress scrape notes - 2026-05-27

## Scope

- Retailer: `tbdress_com`
- Source of truth: `sovrn_commerce_scrape_triage_candidates.csv`
- Triage fields: first-pass candidate, CPC, reviews present, photo reviews present, shipping `US`, provider unknown, CPC amount not populated.
- Sovrn merchant/domain field: `cart.tbdress.com`
- Public category evidence: `https://www.tbdress.com/factory/132`

## Public domain findings

- `cart.tbdress.com` did not resolve during the public preflight.
- `m.tbdress.com` did not resolve during the public preflight.
- `tbdress.com` resolves and redirects to `https://www.tbdress.com/`.
- `www.tbdress.com` is currently a small WordPress factory directory, not an apparel storefront.
- The public sitemap lists only the homepage, policy/about pages, and one default post.
- WordPress REST endpoints returned 401 in manual preflight and were not used by the scraper.

## Product/review findings

- No public apparel PDP/review implementation was found.
- The triage category evidence URL is a factory detail page.
- Public pages scanned were the homepage, the triage factory page, and linked factory pages from the homepage.
- Public images are factory/company logos, not customer review photos or catalog model/variant images.
- No customer photo review source, review provider, catalog model image source, size/fit data, or apparel product URL was exposed on the public pages checked.
- No 429, captcha, WAF, or auth-wall behavior was observed on the public pages used.

## Scraper

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_tbdress_reviews.py`
- Adapter: `public_domain_preflight_no_product_review_surface`
- Access policy: public TB Dress domain/category/factory pages only; unauthorized WordPress REST endpoints were not used.

## Output

- CSV: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/tbdress_com/tbdress_com_reviews_matching_intake_schema.csv`
- Summary: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/tbdress_com/tbdress_com_reviews_matching_intake_schema_summary.json`

Final summary:

- Products discovered: 0
- Products scanned: 0
- Review pages scanned: 0
- Factory pages scanned: 9
- Rows written: 0
- Customer review image rows: 0
- Catalog/model image rows: 0
- Stop reason: `no_public_product_or_review_surface`
- Errors: 0

Notes:

- The summary preserves the Sovrn triage values, but the current public site did not reproduce the `reviews_present=yes` or `photo_reviews=yes` signal.
- No logo/factory image rows were emitted because they are not useful apparel fit/media evidence.
