# Melanie Lyne scrape probe - 2026-05-05

## Result

- Retailer: `melanielyne_com`
- Public Shopify products counted: 5,592
- Yotpo product endpoints sampled: 120
- Sampled products with public reviews: 48
- Review-image rows scraped: 0
- Status: `review_image_probe_no_public_media_rows`

## Notes

Melanie Lyne exposes a Yotpo widget on product pages with widget guid `S3ofw9erjeNtw0JGjYkRzFowWPt2xsmZfmdPNbMA`. Product review endpoints are public and return review text/counts for some products.

However, the sampled Yotpo review payloads did not expose `images_data` or `images` fields for any reviewed product. Do not prioritize a full crawl unless a Yotpo media-specific endpoint is identified.
