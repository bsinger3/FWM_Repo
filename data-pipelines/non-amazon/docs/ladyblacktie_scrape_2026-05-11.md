# Lady Black Tie Scrape - 2026-05-11

## Scope

- Merchant: `ladyblacktie.com`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_ladyblacktie_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/ladyblacktie_com/`
- Output CSV: `ladyblacktie_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `ladyblacktie_com_reviews_matching_amazon_schema_summary.json`

## Source And Coverage

Lady Black Tie was selected as a first-time scrape after duplicate checks across scripts, docs, claim files, active claim files, and output folders.

The scrape used only benign public sources:

- Public Shopify sitemap for product discovery:

```text
https://www.ladyblacktie.com/sitemap.xml
```

- Public Judge.me all-reviews media endpoint:

```text
https://api.judge.me/reviews/all_reviews_js_based
shop_domain=f9da5c-58.myshopify.com
sort_by=with_media
```

The public sitemap exposed 2,884 canonical product URLs. The Judge.me media feed had 9 non-empty pages and page 10 was empty. `products.json` was probed during triage and returned the first two pages, then `HTTP 500` on page 3, so the completed scraper uses sitemap discovery instead.

The run used a small delay, no login/session cookies, no auth bypass, no captcha bypass, and no WAF bypass. No 429/captcha/WAF behavior appeared.

## Result

- Products discovered: 2,884
- Products scanned: 2,884
- Review pages scanned: 9
- Rows written: 250
- Distinct product URLs in rows: 133
- Rows with customer image: 250
- Rows with catalog model image: 0
- Rows with ordered size: 0
- Rows with measurements: 64
- Supabase-qualified rows: 0
- Coverage exhaustive: yes, for the public sitemap plus public Judge.me media feed

## Notes

- Rows are `image_source_type=customer_review_image`.
- Judge.me did not expose clean structured size answers in the public review HTML for this merchant, so `size_display` is intentionally `unknown` for all rows.
- Measurement fields are populated only when the shared deterministic parser can extract explicit values from review text.
