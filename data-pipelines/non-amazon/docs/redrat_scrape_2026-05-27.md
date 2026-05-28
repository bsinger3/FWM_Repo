# Red Rat scrape notes - 2026-05-27

## Triage

- Retailer: `redrat_co_nz`
- Domain: `redrat.co.nz`
- Source: `sovrn_commerce_scrape_triage_candidates.csv`
- Sovrn status: first-pass scrape candidate
- Commercial terms: CPA+CPC; payout fields not populated
- Provider hint: unknown
- Review signal: reviews present; photo review status `unknown_sample_too_small`
- Starting points: public women's category `/c/womens` and sample PDPs from the Sovrn candidate row

## Implementation

Built `scrape_redrat_reviews.py` for Red Rat's public storefront. The site is a custom first-party storefront, not Shopify/Yotpo/Loox/Judge.me/Bazaarvoice. Public category and PDP HTML embed JSON in `window.category` and `window.product`.

The product review implementation is native Red Rat/Vue. The review UI submits through `/productapi/submitreview`, and the public product JSON has `reviews` / `reviewsaverage` fields. The review template exposes rating, fit, size purchased/worn, recommendation, name, title, and comment fields, but no public review-photo/media field was found. The final women's-category scrape found no populated native review records in the scanned PDPs.

Because public customer review photos were not exposed, the adapter writes public product/gallery images as `image_source_type=catalog_model_image`, preserving product title, brand, category, color, available-size detail, and PDP URL. Footwear/accessories and non-women's/unisex products from the broad women's category listing are excluded.

Access stayed within public category and product pages. No authentication, browser bypass, captcha handling, WAF bypass, private endpoint use, or cart/account actions were attempted. The run completed without 429, captcha, WAF, auth-wall, or challenge-marker behavior.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_redrat_reviews.py`
- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\redrat_co_nz\redrat_co_nz_reviews_matching_intake_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\redrat_co_nz\redrat_co_nz_reviews_matching_intake_schema_summary.json`

## Metrics

- Women's category pages scanned: 17
- Products discovered: 385
- Products scanned: 385
- Products excluded from output: 313
- Native reviews found: 0
- Native reviews with photos: 0
- Catalog images found: 627
- Rows written: 627
- Distinct images: 413
- Rows with distinct product URL: 72
- Rows with customer image: 0
- Rows with catalog model image: 627
- Rows with any measurement: 0
- Rows with customer ordered size: 0
- Supabase-qualified rows: 0
- Coverage exhaustive: true for the public women's category pages
- Errors: none

## Qualification

This is a low-value scrape for strict customer-photo/measurement intake because no public review media, populated review text, or model measurements were exposed in the current women's-category pass. It still provides a clean catalog-image dataset for 72 in-scope women's apparel PDPs, with useful product/category/color/available-size context for later fallback workflows.
