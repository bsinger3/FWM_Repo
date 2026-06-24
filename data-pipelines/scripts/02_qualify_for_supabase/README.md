# 02 Qualify For Supabase

Scripts that select rows with image, product URL, and at least one measurement
belong here.

- `non_amazon/`: measurement coverage, gap prioritization, lead-yield analysis,
  and AWIN advertiser qualification reports.
- `non_amazon/generate_awin_affiliate_links.py`: scans image/review CSV product
  URLs, matches AWIN advertiser domains, and creates dry-run or live AWIN
  Link Builder mapping artifacts for `monetized_product_url_display` backfills.
