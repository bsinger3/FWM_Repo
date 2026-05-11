# Ever-Pretty Scrape - 2026-05-11

## Scope

- Merchant: `ever-pretty.com`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_ever_pretty_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/ever_pretty_com/`
- Output CSV: `ever_pretty_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `ever_pretty_com_reviews_matching_amazon_schema_summary.json`

## Source And Coverage

Ever-Pretty was selected as a first-time scrape after duplicate checks across scripts, docs, claim files, active claim files, and output folders.

Product discovery used the public Shopify product sitemap because the public `products.json` endpoints returned `HTTP 500`:

```text
https://www.ever-pretty.com/sitemap.xml
https://www.ever-pretty.com/sitemap_products_1.xml?from=3737074565194&to=8199652606026
```

The product sitemap exposed 749 product URLs. Customer review media came from the public Judge.me all-reviews endpoint for the Shopify shop domain:

```text
https://api.judge.me/reviews/all_reviews_js_based
shop_domain=ever-pretty-usa.myshopify.com
sort_by=with_media
```

The scraper paged the media-sorted public Judge.me feed through 63 non-empty pages and confirmed page 64 was empty. It used a small delay and stopped-on-pressure behavior; no 429/captcha/WAF signal appeared.

## Result

- Products discovered: 749
- Products scanned: 749
- Review pages scanned: 63
- Rows written: 1,444
- Distinct product URLs in rows: 251
- Rows with customer image: 1,444
- Rows with catalog model image: 0
- Rows with ordered size: 442
- Rows with measurements: 833
- Supabase-qualified rows: 430
- Coverage exhaustive: yes, for the public sitemap plus public Judge.me media feed

## Notes

- Rows are `image_source_type=customer_review_image`.
- Product URLs in review rows come from Judge.me review product links and are canonicalized.
- Ordered size parsing uses structured Judge.me `Size` custom answers only. Non-clean values are written as `unknown` to avoid prose-derived size guesses.
- Measurements are extracted deterministically by the shared Step 1 intake parser from review text and custom answers.
