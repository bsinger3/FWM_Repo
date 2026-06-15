# Net-New Measurement Gap Okendo Scrape - 2026-06-09

## Scope

Source queue: `outputs/measurement_coverage/20260609_human_labeled_approved_only/net_new_site_research_candidates.csv`

Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_net_new_okendo_gap_reviews.py`

The run targeted net-new, API-ready Okendo candidates from the measurement-gap research queue:

- `glamorise.com`
- `knix.com`
- `honeylove.com`
- `skims.com`

Access policy: public product pages and public Okendo review JSON only; stop on auth, captcha, WAF, or rate-limit pressure.

## Outcome

The seed Okendo review endpoints worked for all four domains. Product/catalog discovery was limited by 429s or missing `products.json`, so the scraper follows related product IDs exposed inside public Okendo review payloads instead of repeatedly crawling retailer PDPs.

| Retailer | Products scanned | Review pages scanned | Rows | Measurement rows | Supabase-qualified rows | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `glamorise_com` | 50 | 68 | 31 | 29 | 29 | Best yield; bra/full-bust rows with customer bra-size measurements. Catalog discovery hit HTTP 429, but Okendo related-product expansion worked. |
| `knix_com` | 12 | 15 | 10 | 4 | 4 | Useful but sparser; related-product expansion found additional rows, with 3 bra-size rows. Catalog discovery hit HTTP 429. |
| `honeylove_com` | 3 | 6 | 3 | 0 | 0 | Customer images found, but no measurement-qualified rows from tested related products. |
| `skims_com` | 12 | 23 | 6 | 4 | 4 | Useful rows, but related product IDs mostly repeated grouped reviews. `products.json` returned 404. |

## Outputs

- `FWM_Data/non-amazon/data/step_1_raw_scraping_data/glamorise_com/glamorise_com_reviews_matching_intake_schema.csv`
- `FWM_Data/non-amazon/data/step_1_raw_scraping_data/glamorise_com/glamorise_com_reviews_matching_intake_schema_summary.json`
- `FWM_Data/non-amazon/data/step_1_raw_scraping_data/knix_com/knix_com_reviews_matching_intake_schema.csv`
- `FWM_Data/non-amazon/data/step_1_raw_scraping_data/knix_com/knix_com_reviews_matching_intake_schema_summary.json`
- `FWM_Data/non-amazon/data/step_1_raw_scraping_data/honeylove_com/honeylove_com_reviews_matching_intake_schema.csv`
- `FWM_Data/non-amazon/data/step_1_raw_scraping_data/honeylove_com/honeylove_com_reviews_matching_intake_schema_summary.json`
- `FWM_Data/non-amazon/data/step_1_raw_scraping_data/skims_com/skims_com_reviews_matching_intake_schema.csv`
- `FWM_Data/non-amazon/data/step_1_raw_scraping_data/skims_com/skims_com_reviews_matching_intake_schema_summary.json`

## Follow-Up

These sites are useful enough to keep, but broader volume requires product ID discovery that avoids direct PDP/catalog pressure:

- Glamorise: promote to the next gap-fill batch. The current public Okendo path produced the best bra/full-bust measurement yield.
- Knix: keep as second-tier; useful rows exist, but density is lower.
- Honeylove: deprioritize unless additional product IDs show measurement attributes.
- SKIMS: keep as second-tier; useful rows exist, but grouped reviews heavily overlap across product IDs.
