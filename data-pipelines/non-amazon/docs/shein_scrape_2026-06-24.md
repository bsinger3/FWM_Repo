# SHEIN Scrape Notes - 2026-06-24

## Outcome

- Retailer: `shein_com`
- Site: `https://us.shein.com/`
- Scope requested: public women's clothing PDP review/image data only
- Scraper written: no
- Reason: public browser/static inspection found first-party review and product-list endpoints, but anonymous direct endpoint probes redirected to SHEIN's risk/limit flow. The browser-assisted playbook says to stop on this class of response unless an independently public third-party review endpoint is available.

## Run Counts

- Women's category pages manually/publicly checked: 1
- Women's PDPs discovered from public server HTML or sitemap: 0
- Women's PDPs scanned for review rows: 0
- Review/image intake rows collected: 0
- Rows with ordered size: 0
- Rows with measurements/profile/body-size text: 0
- Strict qualified rows: 0
- Product-page sidecar rows emitted for `staging.product_pages`: 0

## Public Checks

The public `robots.txt` was reachable and listed the sitemap index:

```text
https://us.shein.com/robots.txt
Sitemap: https://us.shein.com/sitemap-index.xml
```

The sitemap index and default sitemap both returned HTTP 403 from this environment:

```text
https://us.shein.com/sitemap-index.xml -> HTTP 403
https://us.shein.com/sitemap.xml -> HTTP 403
```

One women's category page fetched as static public HTML:

```text
https://us.shein.com/Women-Dresses-c-1727.html -> HTTP 200
```

That HTML did not contain usable server-rendered PDP links or product rows. It did expose public application bundles and a route/endpoint roster.

## Visible Browser Evidence

A normal visible Chrome navigation to:

```text
https://us.shein.com/Women-Clothing-c-2030.html
```

landed on a SHEIN risk/limit page:

```text
https://us.shein.com/risk/action/limit?risk-id=...
STATUS: 403
```

The risk page loaded anti-automation/risk scripts such as:

```text
https://armor.ltwebstatic.com/she_dist/armor-libs/antiin/antiin.1.9.1.min.js
https://armor.ltwebstatic.com/she_dist/armor-libs/csrandom/csrandom.1.1.0.min.js
https://sc.ltwebstatic.com/she_dist/assets/limit_action-09d1e03b05456e85.js
```

The limit-page JavaScript gathers encrypted anti-risk state and sends risk telemetry. This state was not exported, replayed, or used.

## Static Endpoint Discovery

The static category HTML referenced SHEIN first-party bundles including:

```text
product_list_v2-51db6d33db1a24a2.js
detail_main-5d6d8eb7a0a06085.js
goods-detail-reviews.5207eba0dc143695.js
goods_detail_reviews-94f2ef7409b732d0.js
```

Review bundle inspection found first-party review routes and data fields:

```text
/product/get_goods_review_detail
/product/comment/batch_translate
/product/comment/translate
/api/comment/imageCommentOffsetByAbc/get
/api/comment/abcCommentImages/query
/api/comment/abcCommentInfo/query
/api/comment/abcCommentSummary/get
```

The review code references useful fields such as `comment_info`, `comment_image`, `member_size`, `member_height`, `member_weight`, `member_bust`, `member_waist`, `member_hips`, `member_brasize`, `size`, `color`, `comment_rank`, and `comment_time`.

Detail bundle inspection found PDP/product routes and detail-data routes:

```text
/:pathMatch(.*)*-p-:goodsId(\d+)-cat-:catId(\d+).html
/:pathMatch(.*)*-p-:goodsId(\d+).html
/product/get_goods_detail_realtime_data
/products-api/get_detail_abt_info
/category-api/get_detail_rank_info
```

The static category HTML endpoint roster also included product/category routes:

```text
/category/real_category_goods_list
/category/get_select_product_list
/product/get_products_by_keywords
/product/get_goods_detail_static_data
/product/get_goods_detail_static_data_v2
```

These are first-party SHEIN endpoints, not an independently public third-party review provider such as Bazaarvoice, Loox, Okendo, Yotpo, or PowerReviews.

## Anonymous Endpoint Probes

Minimal anonymous direct probes were made without browser cookies, session headers, challenge tokens, or anti-risk headers.

```text
GET /category/real_category_goods_list?cat_id=1727&page=1&limit=20
GET /product/get_products_by_keywords?keywords=dress&page=1&limit=10
GET /api/comment/abcCommentSummary/get?goods_id=1
```

All three returned HTTP 302 redirects to:

```text
https://us.shein.com/risk/action/limit?risk-id=...
```

Because the publicly visible endpoints redirect to the risk/limit flow when called anonymously, a live scraper is not feasible under the browser-assisted scraping guardrails.

## Taxonomy/Product-Page Status

No product-page sidecar rows were emitted because no public PDP inventory or product-detail payload was safely accessible. If a future run discovers a public product feed, the scraper should preserve these product-page fields in the same pass:

- product URL and canonical URL
- title
- retailer/brand
- women's clothing category breadcrumbs and raw category IDs
- price/currency
- image URLs
- source status
- raw taxonomy signals
- `category_extractor_version=not_run_at_scrape_time`
- `needs_manual_review=true` unless shared taxonomy extraction is run during the scrape

## Affiliate Status

SHEIN remains promising from an affiliate perspective but is not ready for normal link-generation output until product URLs are available from a safe source.

- AWIN triage lists `SHEIN US`, advertiser ID `15920`, domain `us.shein.com`, 10% commission fields, and a 30-day cookie, but the scrape probe status was `http_403;http_403`.
- Sovrn tracker lists merchant group `Shein`, merchant group ID `12080`, pricing `CPA+CPC`, but scrape feasibility is `blocked_or_needs_manual_review`.
- Existing AWIN link generation expects rows with product URLs under `FWM_Data/00_raw_scraped_data`; SHEIN has no safe rows yet.
- Existing selector logic can compare AWIN/Sovrn once safe SHEIN product URLs exist, but the current blocker is scrape feasibility rather than affiliate eligibility.

## Recommended Next Step

Do not implement a SHEIN live scraper from the current evidence. Revisit only if one of these becomes available:

- a public third-party review provider endpoint with public keys/config in static assets;
- a public product/review export or affiliate product feed from AWIN/Sovrn/SHEIN that includes product URLs and, ideally, review/media metadata;
- a user-provided, non-protected dataset/export that can be converted into the existing non-Amazon intake schema and product-page sidecar contract.
