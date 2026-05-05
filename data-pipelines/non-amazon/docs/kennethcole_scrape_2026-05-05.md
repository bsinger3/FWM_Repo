# Kenneth Cole Scrape Notes - 2026-05-05

## Status

- Retailer: `kennethcole_com`
- Site: `https://kennethcole.com`
- Claim: `_active_scrape_claims/kennethcole_com.claim`
- Current status: `completed_no_public_review_images`

## Findings

- Product pages expose Yotpo with app key `2J604wtjmJrwlaN4BhAmaQW5NCK2vdiehl3uoScl`.
- Product-level Yotpo endpoints are public.
- Aggregate Yotpo endpoint is public and reports about 3,006 reviews:
  - `https://api-cdn.yotpo.com/v1/widget/{app_key}/reviews.json?per_page=100&page=1`
- Sparse page checks across pages 1, 5, 10, 15, 20, 25, and 31 found zero review `images_data` attachments.

## Outcome

- No intake CSV rewrite was performed because the public feed appears to expose text reviews only, not customer image rows.
- This site is not a good candidate for Step 1 image-based intake unless another public media source is discovered.

## Revisit Plan

- Revisit only if a new product/page shows visible customer review photos or a different review provider appears.
- If revisited, check Yotpo `images_data` first before catalog scanning.
- Keep public pages/endpoints only; no auth bypass, captcha bypass, WAF bypass, or aggressive retries.
