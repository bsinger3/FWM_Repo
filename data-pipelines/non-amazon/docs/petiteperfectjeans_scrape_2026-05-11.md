# Petite Perfect Jeans Scrape - 2026-05-11

## Result

Completed a first-time public scrape probe for `petiteperfectjeans_com` from triage rank 71.

The site is a public jeans recommendation app rather than a retailer review source. Its public Base44 app functions expose jean catalog records, affiliate/product links, and deterministic garment measurements such as inseam, rise, leg opening, size options, and brand size mappings. The public data does not expose customer review images, customer review text, customer body measurements, or catalog model image URLs.

## Outputs

- Script: `/Users/briannasinger/Projects/FWM_Repo/data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_petiteperfectjeans_reviews.py`
- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/petiteperfectjeans_com/petiteperfectjeans_com_reviews_matching_amazon_schema.csv`
- Summary: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/petiteperfectjeans_com/petiteperfectjeans_com_reviews_matching_amazon_schema_summary.json`
- Public catalog snapshot: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/petiteperfectjeans_com/petiteperfectjeans_com_public_catalog_snapshot.json`

## Coverage

- Public recommendation catalog records discovered: 168
- Brand size-mapping rows discovered: 260
- Products scanned/classified: 168
- Products excluded from Step 1 output: 168
- Review pages scanned: 0
- Exhaustive review paging: no review provider exposed
- Brands seen: Abercrombie & Fitch, American Eagle, Gap, J.Crew, Kut from the Kloth, Levi's, Madewell, Mother, Paige, Quince, Ruti

## Qualification Metrics

- Rows written: 0
- Distinct reviews: 0
- Distinct images: 0
- Rows with customer image: 0
- Rows with distinct product URL: 0
- Rows with customer ordered size: 0
- Rows with any deterministic body measurement: 0
- Supabase-qualified rows: 0

## Notes

This scrape used only public site pages and public Base44 app functions. No authentication, private endpoints, challenge handling, or workaround was attempted.

The public data is useful as a petite-jeans garment measurement reference, but it is not suitable for Step 1 image-card ingestion because there are no review/customer/model images.
