# Andie Swim Scrape Notes - 2026-05-05

## Status

- Retailer: `andieswim_com`
- Site: `https://andieswim.com`
- Claim: `_active_scrape_claims/andieswim_com.claim`
- Current status: `blocked_rate_limited`

## What Worked

- Public Shopify catalog page 1 was reachable.
- Public Okendo widget settings exposed subscriber/store id `d47c3b09-1c8d-4b29-b158-9f2d9489623e`.
- Public Okendo product-level review endpoints returned customer review media, ordered size, and reviewer attributes such as height, bra size, and pant size.
- A 60-product smoke run wrote 110 image rows and 106 qualified rows.
- A lower-traffic store-level Okendo adapter was added after confirming `https://api.okendo.io/v1/stores/{store_id}/reviews?limit=100` is public and paginated.

## Problem Encountered

- The follow-up store-level smoke still needed Shopify catalog context and hit `HTTP 429 Too Many Requests` on `https://andieswim.com/products.json?limit=250&page=2`.
- The run was stopped immediately to avoid increasing request pressure or looking like suspicious traffic.

## Revisit Plan

- Wait for a later scrape window before retrying catalog discovery.
- Prefer a store-feed-only mode that does not require full Shopify catalog pagination; use review `productUrl`, `productName`, `productHandle`, and `productVariantName` for product context.
- If catalog context is needed, retry with a much slower catalog delay, at least `--request-delay-seconds 2.0`, and checkpoint after each catalog page.
- Keep public pages/endpoints only; no auth bypass, captcha bypass, WAF bypass, or aggressive retries.
